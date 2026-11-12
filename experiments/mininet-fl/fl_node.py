# SPDX-License-Identifier: AGPL-3.0-or-later
"""One node of a simulated federated-learning round (E1). Synthetic numpy arrays only, no real data.

Roles:
  server  --listen PORT --clients N --rounds R --size BYTES [--upstream HOST:PORT]
          Each round: send the global model to its N children, receive N updates, average them.
          With --upstream it is an edge aggregator: after averaging it sends one update to the root
          and receives the next global model from it.
  client  --server HOST:PORT --rounds R --scheme none|q8|topk
          Each round: receive the model, perturb it ("training"), send the update encoded by scheme.

Wire format per message: 1-byte scheme, 8-byte length, payload. Encodings of a float32 vector:
  none  raw float32 (4 bytes/value)
  q8    8-bit linear quantisation: float32 min and scale + 1 byte/value
  topk  the 1% largest-magnitude values: uint32 index + float32 value (8 bytes per kept value)
"""
import argparse
import json
import socket
import struct
import sys
import threading
import time

import numpy as np

SCHEMES = {"none": 0, "q8": 1, "topk": 2}
TOPK_FRACTION = 0.01


def encode(vec, scheme):
    if scheme == "none":
        return vec.astype(np.float32).tobytes()
    if scheme == "q8":
        lo, hi = float(vec.min()), float(vec.max())
        scale = (hi - lo) / 255 or 1.0
        q = np.round((vec - lo) / scale).astype(np.uint8)
        return struct.pack("<ff", lo, scale) + q.tobytes()
    k = max(1, int(len(vec) * TOPK_FRACTION))
    idx = np.argpartition(np.abs(vec), -k)[-k:].astype(np.uint32)
    return idx.tobytes() + vec[idx].astype(np.float32).tobytes()


def decode(payload, scheme, n):
    if scheme == "none":
        return np.frombuffer(payload, dtype=np.float32).copy()
    if scheme == "q8":
        lo, scale = struct.unpack("<ff", payload[:8])
        return np.frombuffer(payload[8:], dtype=np.uint8).astype(np.float32) * scale + lo
    k = len(payload) // 8
    idx = np.frombuffer(payload[:4 * k], dtype=np.uint32)
    out = np.zeros(n, dtype=np.float32)
    out[idx] = np.frombuffer(payload[4 * k:], dtype=np.float32)
    return out


def send(sock, scheme, payload):
    sock.sendall(struct.pack("<BQ", SCHEMES[scheme], len(payload)) + payload)


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(1 << 20, n - len(buf)))
        if not chunk:
            raise ConnectionError("peer closed")
        buf += chunk
    return bytes(buf)


def recv(sock):
    code, length = struct.unpack("<BQ", recv_exact(sock, 9))
    name = {v: k for k, v in SCHEMES.items()}[code]
    return name, recv_exact(sock, length)


def run_server(a):
    n = a.size // 4
    model = np.zeros(n, dtype=np.float32)
    lst = socket.socket()
    lst.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lst.bind(("0.0.0.0", a.listen))
    lst.listen(a.clients)
    up = None
    if a.upstream:
        host, port = a.upstream.split(":")
        for _ in range(200):
            try:
                up = socket.create_connection((host, int(port)))
                break
            except OSError:
                time.sleep(0.1)
    children = [lst.accept()[0] for _ in range(a.clients)]
    times = []
    for _ in range(a.rounds):
        if up is not None:  # the edge gets the global model from the root first
            scheme, payload = recv(up)
            model = decode(payload, scheme, n)
        t0 = time.time()
        threads = [threading.Thread(target=send, args=(c, "none", model.tobytes())) for c in children]
        [t.start() for t in threads]
        [t.join() for t in threads]
        updates = [None] * len(children)

        def get(i, c):
            scheme, payload = recv(c)
            updates[i] = decode(payload, scheme, n)
        threads = [threading.Thread(target=get, args=(i, c)) for i, c in enumerate(children)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        model = np.mean(updates, axis=0).astype(np.float32)
        if up is not None:
            send(up, a.scheme, encode(model, a.scheme))
        times.append(time.time() - t0)
    for c in children:
        c.close()
    print(json.dumps({"role": "edge" if up else "server", "round_seconds": times}))


def run_client(a):
    host, port = a.server.split(":")
    for _ in range(200):
        try:
            sock = socket.create_connection((host, int(port)))
            break
        except OSError:
            time.sleep(0.1)
    else:
        sys.exit("client: cannot connect")
    rng = np.random.default_rng(a.seed)
    for _ in range(a.rounds):
        scheme, payload = recv(sock)
        model = decode(payload, scheme, len(payload) // 4)
        update = model + rng.standard_normal(len(model)).astype(np.float32) * 0.01  # "training"
        send(sock, a.scheme, encode(update, a.scheme))
    sock.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("role", choices=["server", "client"])
    p.add_argument("--listen", type=int, default=9000)
    p.add_argument("--clients", type=int, default=1)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--size", type=int, default=1_000_000)
    p.add_argument("--upstream")
    p.add_argument("--server")
    p.add_argument("--scheme", choices=list(SCHEMES), default="none")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    (run_server if a.role == "server" else run_client)(a)


if __name__ == "__main__":
    main()

# E1: network overhead of federated-learning update patterns

Owner direction 024. A separate Compose project, not part of the app or its gate. Synthetic numpy
arrays only; no real data.

## Run

```powershell
docker compose -f experiments/mininet-fl/compose.yaml build
docker compose -f experiments/mininet-fl/compose.yaml run --rm lab --clients 4,16 --rounds 3   # appends to results/e1.csv
docker compose exec -T web python experiments/mininet-fl/summarize.py                          # results/summary.md
```

Options: `--clients 4,16,32`, `--patterns star,edge,star-q8,star-topk`, `--bw 10,50,100` (Mbit/s),
`--latency 20,100` (ms, one way client to server), `--size 1000000` (model bytes), `--rounds 3`.

## Setup

- Image: official `ubuntu:24.04` with `mininet`, `openvswitch-switch`, `bridge-utils`, `python3-numpy`
  from Ubuntu's packages. The container runs `--privileged` (Mininet needs network namespaces, tc and
  bridges): the one allowed exception, with no mounts but `results/`, no secrets, removed after each
  run (`--rm`).
- **Switch: Linux bridges.** The Docker Desktop kernel has no Open vSwitch module (`modprobe
  openvswitch` fails), so `fl_lab.py` falls back to Mininet's `LinuxBridge` (STP off). The column
  `switch` in the CSV records it.
- Links: `TCLink` (tc htb + netem) on every link with the given bandwidth; the one-way latency is
  split evenly over the links of a client-to-server path (2 links star, 3 links edge).
- One round: the server sends the model (float32, uncompressed) to every client in parallel, each
  client adds noise ("training") and sends its update, the server averages. Edge: clients talk to
  an aggregator per group of 4, the aggregators to the server.
- Update encodings: `none` (4 bytes/value), `q8` (8-bit linear quantisation, 1 byte/value + 8 bytes),
  `topk` (top 1% by magnitude, 8 bytes per kept value). Only updates are compressed, not the model.
- Measured per run: bytes sent by all hosts (on the wire, counted once at the sender), bytes in and
  out of the server's link, and the server's round time.

## Results (1 MB model, 4 and 16 clients)

See `results/summary.md` (table and text charts) and `results/e1.csv`. Main points:

- **Bytes:** star moves 2 x clients x model per round. 8-bit updates cut the total by about 38%,
  top-1% updates by about 49%; the uncompressed download then dominates.
- **Two-level edge:** about 25% more bytes in total (one more hop) but 4x fewer through the server's
  link. With 16 clients at 10 Mbit/s a round takes 12 s instead of 24 s (the server link is the
  bottleneck); with 4 clients (one group) the extra hop only adds time.
- **Latency:** 100 ms instead of 20 ms adds about 1-4 s per round at 100 Mbit/s (TCP needs several
  round trips per transfer); at 10 Mbit/s bandwidth dominates.
- One run (16 clients, star, 100 Mbit/s, 20 ms) first gave 0.05 s/round for 33 MB, i.e. the shaping
  was not applied; it was re-run (2.44 s) and the first row kept in `results/rejected.csv`.

Not done yet: 32 clients, 50 Mbit/s, 10 MB models.

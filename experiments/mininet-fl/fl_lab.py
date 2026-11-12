# SPDX-License-Identifier: AGPL-3.0-or-later
"""E1 driver: Mininet topologies, one run per configuration, CSV out (024).

Patterns:  star      all clients -> one server (FedAvg)
           edge      clients -> edge aggregator per group of 4 -> server (two-level)
           star-q8   star, updates 8-bit quantised
           star-topk star, updates top-1% sparsified
Links: every link gets the bandwidth; the one-way client-to-server latency is split evenly over the
links on that path (star: 2 links; edge: 3 links).
Measured: bytes sent by all hosts (bytes on the wire, counted once at the sender), bytes through the
server's link, and the mean round time seen by the server (model out, all updates in, averaged).
"""
import argparse
import csv
import json
import os
import subprocess
import time

from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.nodelib import LinuxBridge
from mininet.topo import Topo

HERE = os.path.dirname(os.path.abspath(__file__))
NODE = os.path.join(HERE, "fl_node.py")
GROUP = 4


class FLTopo(Topo):
    def build(self, clients, pattern, bw, latency_ms):
        hops = 3 if pattern == "edge" else 2
        link = {"bw": bw, "delay": f"{latency_ms / hops:.1f}ms"}
        core = self.addSwitch("s0")
        self.addLink(self.addHost("root"), core, **link)
        if pattern != "edge":
            for i in range(clients):
                self.addLink(self.addHost(f"c{i}"), core, **link)
            return
        for g in range(clients // GROUP):
            sw = self.addSwitch(f"s{g + 1}")
            self.addLink(sw, core, **link)
            self.addLink(self.addHost(f"e{g}"), sw, **link)  # edge aggregator next to its clients
            for i in range(GROUP):
                self.addLink(self.addHost(f"c{g * GROUP + i}"), sw, **link)


def tx_bytes(host):
    return sum(int(host.cmd(f"cat /sys/class/net/{i}/statistics/tx_bytes").strip() or 0)
               for i in host.intfNames() if i != "lo")


def run_one(switch, clients, pattern, bw, latency_ms, size, rounds):
    net = Mininet(topo=FLTopo(clients, pattern, bw, latency_ms), link=TCLink, switch=switch, controller=None,
                  autoSetMacs=True)
    net.start()
    try:
        root, scheme = net.get("root"), {"star-q8": "q8", "star-topk": "topk"}.get(pattern, "none")
        hosts = [h for h in net.hosts]
        before = {h.name: tx_bytes(h) for h in hosts}
        root_before = tx_bytes(root) + int(root.cmd(
            f"cat /sys/class/net/{root.intfNames()[0]}/statistics/rx_bytes").strip())
        procs = []
        if pattern == "edge":
            groups = clients // GROUP
            server = root.popen(["python3", NODE, "server", "--listen", "9000", "--clients", str(groups),
                                 "--rounds", str(rounds), "--size", str(size)])
            for g in range(groups):
                e = net.get(f"e{g}")
                procs.append(e.popen(["python3", NODE, "server", "--listen", "9001", "--clients", str(GROUP),
                                      "--rounds", str(rounds), "--size", str(size), "--scheme", scheme,
                                      "--upstream", f"{root.IP()}:9000"]))
                for i in range(GROUP):
                    c = net.get(f"c{g * GROUP + i}")
                    procs.append(c.popen(["python3", NODE, "client", "--server", f"{e.IP()}:9001", "--rounds",
                                          str(rounds), "--scheme", scheme, "--seed", str(g * GROUP + i)]))
        else:
            server = root.popen(["python3", NODE, "server", "--listen", "9000", "--clients", str(clients),
                                 "--rounds", str(rounds), "--size", str(size)])
            for i in range(clients):
                procs.append(net.get(f"c{i}").popen(["python3", NODE, "client", "--server", f"{root.IP()}:9000",
                                                     "--rounds", str(rounds), "--scheme", scheme, "--seed", str(i)]))
        out, _ = server.communicate(timeout=3600)
        for p in procs:
            p.wait(timeout=600)
        result = json.loads(out.decode().strip().splitlines()[-1])
        wire = sum(tx_bytes(h) - before[h.name] for h in hosts)
        root_after = tx_bytes(root) + int(root.cmd(
            f"cat /sys/class/net/{root.intfNames()[0]}/statistics/rx_bytes").strip())
        times = result["round_seconds"]
        return {"bytes_on_wire": wire, "server_link_bytes": root_after - root_before,
                "round_s_mean": sum(times) / len(times), "round_s_max": max(times)}
    finally:
        net.stop()


def pick_switch():
    """Kernel Open vSwitch if the Docker Desktop kernel has the module, else Linux bridges."""
    ok = subprocess.run(["modprobe", "openvswitch"], capture_output=True).returncode == 0 or \
        os.path.isdir("/sys/module/openvswitch")
    if ok:
        return (lambda name, **kw: OVSSwitch(name, failMode="standalone", **kw)), "ovs-kernel"
    return (lambda name, **kw: LinuxBridge(name, stp=False, **kw)), "linux-bridge"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--clients", default="4,16")
    p.add_argument("--patterns", default="star,edge,star-q8,star-topk")
    p.add_argument("--bw", default="10,100")
    p.add_argument("--latency", default="20,100")
    p.add_argument("--size", type=int, default=1_000_000)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--out", default="/results/e1.csv")
    a = p.parse_args()
    setLogLevel("warning")
    switch, switch_name = pick_switch()
    fields = ["switch", "clients", "pattern", "bw_mbit", "latency_ms", "model_bytes", "rounds", "bytes_on_wire",
              "server_link_bytes", "round_s_mean", "round_s_max"]
    new = not os.path.exists(a.out)
    with open(a.out, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        if new:
            w.writeheader()
        for clients in map(int, a.clients.split(",")):
            for pattern in a.patterns.split(","):
                for bw in map(int, a.bw.split(",")):
                    for latency in map(int, a.latency.split(",")):
                        t0 = time.time()
                        r = run_one(switch, clients, pattern, bw, latency, a.size, a.rounds)
                        row = {"switch": switch_name, "clients": clients, "pattern": pattern, "bw_mbit": bw,
                               "latency_ms": latency, "model_bytes": a.size, "rounds": a.rounds, **r}
                        w.writerow(row)
                        fh.flush()
                        print(f"{clients:>3} {pattern:<9} {bw:>3} Mbit {latency:>3} ms: "
                              f"{r['round_s_mean']:.2f} s/round, {r['bytes_on_wire'] / 1e6:.1f} MB "
                              f"({time.time() - t0:.0f} s)", flush=True)


if __name__ == "__main__":
    main()

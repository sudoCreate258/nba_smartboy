#!/bin/sh
# E1 entry point inside the lab container. Arguments are passed to fl_lab.py.
set -eu
service openvswitch-switch start >/dev/null 2>&1 || true
mn -c >/dev/null 2>&1 || true
python3 /lab/fl_lab.py "$@"

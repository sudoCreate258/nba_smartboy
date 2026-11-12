# SPDX-License-Identifier: AGPL-3.0-or-later
# Experiment E1 (024): Mininet lab for federated-learning traffic. Official ubuntu:24.04 image with
# Mininet, Open vSwitch and NumPy from Ubuntu's own packages. Not part of the app or its gate.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends mininet openvswitch-switch python3 python3-numpy \
       iproute2 iputils-ping procps kmod bridge-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /lab
COPY fl_node.py fl_lab.py run.sh ./
ENTRYPOINT ["sh", "/lab/run.sh"]

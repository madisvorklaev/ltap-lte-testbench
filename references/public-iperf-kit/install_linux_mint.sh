#!/usr/bin/env bash
set -euo pipefail

# Linux Mint / Ubuntu-family dependencies for the public iPerf3 collector.
# Safe to run repeatedly.

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  iperf3 openssh-client iputils-ping iproute2 jq curl git python3

echo
echo "Versions:"
python3 --version
iperf3 --version | head -n 2
ssh -V 2>&1 | head -n 1
ip -Version

echo
echo "Dependencies installed."

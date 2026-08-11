#!/bin/bash
# Blocks until outbound DNS resolves, so a timer that fires immediately after
# boot doesn't run against a dead network.
#
# Why this is needed: these are *user* units, and systemd starts the user
# manager slightly BEFORE the network is up. Measured on this box at the
# 2026-08-11 boot: user@1000.service was up at boot+6.3s, but
# network-online.target was only reached at boot+11.1s. A user unit cannot
# order itself against a system target, so `Persistent=true` catch-up runs
# fire into that ~5s hole.
#
# That matters because the refresh scripts catch their own exceptions per
# source and still exit 0 (see step() in refresh_crypto_live.py). A run with
# no network would therefore be recorded by systemd as a SUCCESS and consume
# the catch-up, leaving the data stale until the next scheduled tick — a full
# day, in refresh_market_data's case, whose output feeds the 09:20 digest.
#
# Exits 0 even on timeout: a hard failure here would leave the job never run
# at all, which is strictly worse than attempting it. The warning lands in the
# job's own log.
set -u

HOST=${1:-api.binance.com}
TIMEOUT=${2:-180}

deadline=$(( $(date +%s) + TIMEOUT ))
until getent hosts "$HOST" >/dev/null 2>&1; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "wait_online: '$HOST' still unresolvable after ${TIMEOUT}s — running anyway" >&2
    exit 0
  fi
  sleep 3
done

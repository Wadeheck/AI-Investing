#!/usr/bin/env bash
# Pull the ProDesk's state snapshots to whatever machine you run this from.
#
# WHY PULL AND NOT PUSH: the ProDesk is the machine that is exposed 24/7 and the
# one that would be compromised first. If it held credentials to write to the
# backup location, whatever got onto it could delete the backups too — which is
# the failure mode that makes a backup worthless exactly when it is needed. A
# pull means the archive host needs no trust from the ProDesk, and the ProDesk
# needs no reach into the archive.
#
# WHY MANUAL: the SSH key is passphrase-protected, so an unattended timer cannot
# use it without either stripping the passphrase or leaving an agent running.
# Both are worse than a copy you take when you happen to be at the keyboard.
# Run this whenever you SSH in. It is idempotent and cheap (~4 MB/day, skips
# what it already has).
#
# The engine keeps writing while this runs. The snapshots in data/backups/ are
# already-sealed tarballs so they are safe to copy live; the live data/ tree is
# NOT copied here for exactly that reason — use backup.py's snapshot, not a
# hot copy of a database being written to.
set -euo pipefail

HOST="${PRODESK_HOST:-eugene@100.64.113.103}"
KEY="${PRODESK_KEY:-$HOME/.ssh/prodesk_ed25519}"
DEST="${BACKUP_DEST:-$HOME/AI-Investing-archive}"

mkdir -p "$DEST"

echo "pulling snapshots from $HOST -> $DEST"
rsync -av --ignore-existing --chmod=F600 \
      -e "ssh -i $KEY -o BatchMode=yes" \
      "$HOST:Projects/AI-Investing/data/backups/state-*.tar.gz" "$DEST/"

# A backup you have never opened is a hypothesis. Prove the newest one is a
# readable archive, not 4 MB of truncated garbage — this is the whole point of
# taking it, and it costs a second.
newest="$(ls -1t "$DEST"/state-*.tar.gz 2>/dev/null | head -1)"
if [ -z "$newest" ]; then
    echo "NOTHING PULLED — no snapshots found. Check backup.timer on the ProDesk." >&2
    exit 1
fi

if tar -tzf "$newest" >/dev/null 2>&1; then
    n=$(tar -tzf "$newest" | wc -l)
    echo "verified $(basename "$newest") — $n entries, $(du -h "$newest" | cut -f1)"
else
    echo "CORRUPT: $newest does not read as a gzip tar." >&2
    exit 1
fi

echo "$(ls -1 "$DEST"/state-*.tar.gz | wc -l) snapshots held locally"

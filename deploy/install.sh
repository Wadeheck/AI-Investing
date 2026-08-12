#!/usr/bin/env bash
# Installs AI-Investing as **user** systemd units (systemd --user), which is how
# the live box has actually run since 2026-08-04.
#
# This script used to install four *system* units into /etc/systemd/system with
# sudo, under different names (ai-investing-engine.service). Nothing had used
# that path in months, and running it on the live host would have started a
# SECOND engine against the same data/ directory and the same live book. The
# system-unit templates are gone; deploy/systemd/ is now the single source of
# truth and mirrors the installed units one-for-one.
#
# Why user units: everything here is one person's always-on workload, needs no
# root, and wants the login session's keyring and environment. Lingering (below)
# is what keeps them running with nobody logged in.
#
# Safe to re-run. `enable --now` does not restart a unit that is already active,
# so a re-run will not bounce the engine — which matters, because repeated
# restarts throttle the yfinance feed.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
REPO="$(pwd)"
UNIT_SRC="$REPO/deploy/systemd"
UNIT_DST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
# The units carry absolute paths rather than %h so they read unambiguously in
# `systemctl cat`. This is the prefix they were written with; if the repo lives
# somewhere else, every occurrence is rewritten on the way in.
CANONICAL_REPO="/home/eugene/Projects/AI-Investing"

say()  { printf "\033[1;34m▸ %s\033[0m\n" "$1"; }
warn() { printf "\033[1;33m!  %s\033[0m\n" "$1"; }

# -- preconditions -----------------------------------------------------------
if [ ! -f "$REPO/.env" ]; then
  echo "No .env found — run 'make setup' first." >&2
  exit 1
fi
if [ ! -x "$REPO/.venv/bin/python" ]; then
  echo "No .venv found — run 'make setup' first (it creates the venv and installs" >&2
  echo "engine/requirements.txt so live market data actually works under systemd)." >&2
  exit 1
fi
if [ ! -d "$UNIT_SRC" ]; then
  echo "Missing $UNIT_SRC — the unit files are not where this script expects." >&2
  exit 1
fi

say "Installing user units from deploy/systemd/ for repo at $REPO"

# -- lingering ---------------------------------------------------------------
# Without this the user manager stops at logout and every timer dies with it.
# This is the whole reason the engine survives a headless reboot.
if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || echo no)" != "yes" ]; then
  say "Enabling lingering for $USER (keeps units running with nobody logged in)"
  loginctl enable-linger "$USER" || warn "could not enable lingering — units will stop at logout"
fi

# -- dashboard credentials ---------------------------------------------------
# Deliberately its own 0600 file rather than the repo-root .env: the dashboard
# needs exactly two values, and handing a Node process every broker and LLM
# credential would be a gift to anyone who finds an RCE in it. See the long
# comment in ai-investing-dashboard.service.
DASH_ENV="${XDG_CONFIG_HOME:-$HOME/.config}/ai-investing/dashboard.env"
if [ ! -f "$DASH_ENV" ]; then
  DASHBOARD_USER="$(sed -nE 's/^DASHBOARD_USER=(.*)$/\1/p' "$REPO/.env" | tail -1)"
  DASHBOARD_PASSWORD="$(sed -nE 's/^DASHBOARD_PASSWORD=(.*)$/\1/p' "$REPO/.env" | tail -1)"
  if [ -n "$DASHBOARD_USER" ] && [ -n "$DASHBOARD_PASSWORD" ]; then
    say "Creating $DASH_ENV (0600) from the DASHBOARD_* values in .env"
    mkdir -p "$(dirname "$DASH_ENV")"
    ( umask 077; printf 'DASHBOARD_USER=%s\nDASHBOARD_PASSWORD=%s\n' \
        "$DASHBOARD_USER" "$DASHBOARD_PASSWORD" > "$DASH_ENV" )
  else
    warn "No DASHBOARD_USER/DASHBOARD_PASSWORD — the dashboard will have NO auth."
    warn "Set both in .env and re-run, or write $DASH_ENV by hand (0600),"
    warn "before exposing this host beyond the tailnet."
  fi
fi

# -- units -------------------------------------------------------------------
mkdir -p "$UNIT_DST"
installed=0
for src in "$UNIT_SRC"/*.service "$UNIT_SRC"/*.timer; do
  [ -e "$src" ] || continue
  unit="$(basename "$src")"
  if [ "$REPO" = "$CANONICAL_REPO" ]; then
    cp "$src" "$UNIT_DST/$unit"
  else
    sed "s|$CANONICAL_REPO|$REPO|g" "$src" > "$UNIT_DST/$unit"
  fi
  installed=$((installed + 1))
done
say "Installed $installed unit files into $UNIT_DST"
[ "$REPO" = "$CANONICAL_REPO" ] || say "Rewrote the repo path from $CANONICAL_REPO to $REPO"

systemctl --user daemon-reload

# -- enable ------------------------------------------------------------------
# Exactly the units that declare [Install]: the three long-running services and
# the twelve timers. The remaining services are `static` on purpose — their
# timer is what pulls them in, and enabling them directly would run them at boot.
mapfile -t ENABLE < <(grep -l '^\[Install\]' "$UNIT_SRC"/*.service "$UNIT_SRC"/*.timer | xargs -n1 basename | sort)
say "Enabling ${#ENABLE[@]} units; the rest are timer-activated"
systemctl --user enable --now "${ENABLE[@]}"

# -- dashboard build ---------------------------------------------------------
# The unit runs `npm run start`, which serves a previous production build.
if [ -d "$REPO/dashboard" ]; then
  say "Building the dashboard for production"
  ( cd "$REPO/dashboard" && npm run build )
  systemctl --user try-restart ai-investing-dashboard.service
fi

echo
say "Done. Current state:"
systemctl --user list-units 'ai-investing*' --no-pager --no-legend | sed 's/^/   /'
echo
say "Useful commands:"
echo "   systemctl --user status ai-investing ai-investing-chat ai-investing-dashboard"
echo "   systemctl --user list-timers 'ai-investing*'"
echo "   journalctl --user -u ai-investing -f        # or: tail -f data/engine.log"
echo "   systemctl --user disable --now ai-investing ai-investing-chat ai-investing-dashboard"

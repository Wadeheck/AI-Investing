#!/usr/bin/env bash
# Installs AI-Investing as systemd services: the engine loop (always-on),
# the dashboard (production build), and a watchdog timer (dead-man's switch).
# Requires sudo. Review the generated unit files before running if unsure.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
REPO="$(pwd)"
RUN_AS="${1:-$USER}"
say() { printf "\033[1;34m▸ %s\033[0m\n" "$1"; }

if [ ! -f .env ]; then
  echo "No .env found — run 'make setup' first." >&2
  exit 1
fi

if [ ! -x "$REPO/.venv/bin/python" ]; then
  echo "No .venv found — run 'make setup' first (it creates the venv and installs" >&2
  echo "engine/requirements.txt so live market data actually works under systemd)." >&2
  exit 1
fi
PYTHON="$REPO/.venv/bin/python"

# .env isn't valid shell (some values have unescaped spaces/parens), so pull
# out just the two dashboard-auth vars by pattern instead of sourcing it.
DASHBOARD_USER="$(sed -nE 's/^DASHBOARD_USER=(.*)$/\1/p' .env | tail -1)"
DASHBOARD_PASSWORD="$(sed -nE 's/^DASHBOARD_PASSWORD=(.*)$/\1/p' .env | tail -1)"
if [ -z "$DASHBOARD_USER" ] || [ -z "$DASHBOARD_PASSWORD" ]; then
  say "DASHBOARD_USER/DASHBOARD_PASSWORD not set in .env — dashboard will have NO auth."
  say "Set both in .env before installing if this host is reachable off localhost."
fi

say "Installing systemd units for user '$RUN_AS', repo at $REPO"
for unit in ai-investing-engine.service ai-investing-dashboard.service \
            ai-investing-watchdog.service ai-investing-watchdog.timer; do
  sed -e "s|@@REPO@@|$REPO|g" -e "s|@@USER@@|$RUN_AS|g" \
      -e "s|@@PYTHON@@|$PYTHON|g" \
      -e "s|@@DASHBOARD_USER@@|$DASHBOARD_USER|g" \
      -e "s|@@DASHBOARD_PASSWORD@@|$DASHBOARD_PASSWORD|g" \
    "deploy/$unit" | sudo tee "/etc/systemd/system/$unit" >/dev/null
done
sudo chmod 600 /etc/systemd/system/ai-investing-dashboard.service

say "Building the dashboard for production"
( cd dashboard && npm run build )

say "Reloading systemd and enabling services"
sudo systemctl daemon-reload
sudo systemctl enable --now ai-investing-engine.service
sudo systemctl enable --now ai-investing-dashboard.service
sudo systemctl enable --now ai-investing-watchdog.timer

echo
say "Done. Useful commands:"
echo "   systemctl status ai-investing-engine ai-investing-dashboard ai-investing-watchdog.timer"
echo "   journalctl -u ai-investing-engine -f"
echo "   sudo systemctl disable --now ai-investing-engine ai-investing-dashboard ai-investing-watchdog.timer"

#!/usr/bin/env bash
# Deploy the server to shnr.org. Run from Git Bash:  bash deploy/deploy.sh
# First time only: also run root_setup.sh (see that file) — this script tells you if it's missing.
set -euo pipefail
HOST=sshaner@10.0.0.187
REMOTE=/projects/kalshi-arb
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"

# Stage deploy files in ~ so root_setup.sh can be run from there.
tar -C "$HERE" -czf - kalshi-arb.service arb.shnr.org.conf root_setup.sh | ssh $HOST 'mkdir -p ~/kalshi-arb-deploy && tar -C ~/kalshi-arb-deploy -xzf -'

if ! ssh $HOST "test -w $REMOTE && test -f /etc/systemd/system/kalshi-arb.service"; then
  echo "Root setup not done yet. Run once:"
  echo "  ssh -t $HOST 'sudo bash ~/kalshi-arb-deploy/root_setup.sh'"
  exit 1
fi

echo "== copying server code"
tar -C "$ROOT/server" --exclude=__pycache__ --exclude='*.db*' --exclude=.env --exclude=venv -czf - . | ssh $HOST "tar -C $REMOTE -xzf -"

echo "== venv + tests"
# Tests gate the restart: a failure stops the deploy before the running service is touched.
ssh $HOST "cd $REMOTE && (test -d venv || python3 -m venv venv) && venv/bin/pip install -q -r requirements.txt &&   (venv/bin/python -m pytest -q > /tmp/kalshi-arb-pytest.log 2>&1; rc=\$?; tail -3 /tmp/kalshi-arb-pytest.log; exit \$rc)"   || { echo "!! tests failed; NOT restarting (full log: /tmp/kalshi-arb-pytest.log on the server)"; exit 1; }

if ! ssh $HOST "test -f $REMOTE/.env"; then
  echo "!! $REMOTE/.env missing — create it (see server/.env.example) before starting"; exit 1
fi

echo "== restart"
ssh $HOST "sudo -n systemctl restart kalshi-arb && sleep 3 && sudo -n systemctl is-active kalshi-arb"
ssh $HOST "curl -s -o /dev/null -w 'local API (no token, expect 401): %{http_code}\n' http://127.0.0.1:8095/api/status"

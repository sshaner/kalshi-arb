#!/usr/bin/env bash
# One-time root setup on shnr.org. Run as:  ssh -t sshaner@10.0.0.187 'sudo bash ~/kalshi-arb-deploy/root_setup.sh'
# Creates /projects/kalshi-arb, installs the systemd unit + nginx vhost, and lets sshaner
# restart/inspect this one service without a password so deploy.sh can run unattended.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"

mkdir -p /projects/kalshi-arb
chown sshaner:sshaner /projects/kalshi-arb

install -m 644 "$SRC/kalshi-arb.service" /etc/systemd/system/kalshi-arb.service
install -m 644 "$SRC/arb.shnr.org.conf" /etc/nginx/sites-available/arb.shnr.org.conf
ln -sf /etc/nginx/sites-available/arb.shnr.org.conf /etc/nginx/sites-enabled/arb.shnr.org.conf

cat > /etc/sudoers.d/kalshi-arb <<'SUDO'
sshaner ALL=(root) NOPASSWD: /usr/bin/systemctl restart kalshi-arb, /usr/bin/systemctl start kalshi-arb, /usr/bin/systemctl stop kalshi-arb, /usr/bin/systemctl status kalshi-arb, /usr/bin/systemctl is-active kalshi-arb, /usr/bin/journalctl -u kalshi-arb *
SUDO
chmod 440 /etc/sudoers.d/kalshi-arb
visudo -cf /etc/sudoers.d/kalshi-arb

systemctl daemon-reload
systemctl enable kalshi-arb
nginx -t
systemctl reload nginx
echo "root setup done"

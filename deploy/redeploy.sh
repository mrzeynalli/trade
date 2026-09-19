#!/usr/bin/env bash
# Rebuild the frontend and refresh the deployed copy without touching Nginx,
# systemd unit files or the data directory.
set -euo pipefail
REPO="${REPO:-/root/analytics/trade}"
TARGET="${TARGET:-/opt/analytics-trade}"

( cd "$REPO/frontend" && npm run build )

rm -rf "$TARGET/backend/trade_api" "$TARGET/frontend/dist"
cp -a "$REPO/backend/trade_api" "$TARGET/backend/"
find "$TARGET/backend" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp -a "$REPO/frontend/dist" "$TARGET/frontend/dist"
chown -R root:root "$TARGET/backend" "$TARGET/frontend"
chmod -R go-w "$TARGET/backend" "$TARGET/frontend"

# An admin command accidentally run as root leaves files the service account
# cannot rewrite, which fails silently inside a background job. Normalise.
chown -R tradeapp:tradeapp "${DATA_DIR:-/var/lib/analytics-trade}" 2>/dev/null || true

systemctl restart analytics-trade-api analytics-trade-worker
for i in $(seq 1 20); do
    curl -fsS http://127.0.0.1:8092/trade/api/health >/dev/null 2>&1 && { echo "healthy"; exit 0; }
    sleep 1
done
echo "ERROR: service did not become healthy" >&2
journalctl -u analytics-trade-api -n 30 --no-pager >&2
exit 1

#!/usr/bin/env bash
#
# Deploy Global Trade Intelligence to /opt/analytics-trade and wire it into the
# existing analytics.mrzeynalli.xyz virtual host.
#
# Safe to re-run. It makes the smallest possible change to Nginx: one include
# line inside the existing server block, and it refuses to reload if the
# configuration does not validate.

set -euo pipefail

REPO="${REPO:-/root/analytics/trade}"
TARGET="${TARGET:-/opt/analytics-trade}"
DATA_DIR="${DATA_DIR:-/var/lib/analytics-trade}"
ENV_DIR="${ENV_DIR:-/etc/analytics-trade}"
SERVICE_USER="${SERVICE_USER:-tradeapp}"
VHOST="${VHOST:-/etc/nginx/sites-available/analytics.mrzeynalli.xyz}"
SNIPPET="${SNIPPET:-/etc/nginx/snippets/trade.location.conf}"
BACKUP_DIR="${BACKUP_DIR:-/root/analytics/trade/backups}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "Service account"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
    echo "created $SERVICE_USER"
else
    echo "$SERVICE_USER already exists"
fi

say "Application directory"
mkdir -p "$TARGET"
rm -rf "$TARGET/backend" "$TARGET/frontend"
mkdir -p "$TARGET/backend" "$TARGET/frontend"
cp -a "$REPO/backend/trade_api" "$TARGET/backend/"
cp -a "$REPO/backend/requirements.txt" "$TARGET/backend/"
find "$TARGET/backend" -name '__pycache__' -type d -prune -exec rm -rf {} +

if [ ! -d "$REPO/frontend/dist" ]; then
    echo "ERROR: frontend/dist is missing. Run 'npm run build' in $REPO/frontend first." >&2
    exit 1
fi
cp -a "$REPO/frontend/dist" "$TARGET/frontend/dist"

say "Python environment"
if [ ! -x "$TARGET/.venv/bin/python" ]; then
    python3 -m venv "$TARGET/.venv"
fi
"$TARGET/.venv/bin/python" -m pip install --quiet --upgrade pip wheel
"$TARGET/.venv/bin/python" -m pip install --quiet -r "$TARGET/backend/requirements.txt"

say "Data directory"
mkdir -p "$DATA_DIR"/{state,refs,raw,parquet,manifests,tmp}
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
chmod 750 "$DATA_DIR"

say "Environment file"
mkdir -p "$ENV_DIR"
if [ ! -f "$ENV_DIR/trade.env" ]; then
    if [ -f "$REPO/.env" ]; then
        install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 600 "$REPO/.env" "$ENV_DIR/trade.env"
        echo "installed from $REPO/.env"
    else
        install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 600 "$REPO/.env.example" "$ENV_DIR/trade.env"
        echo "WARNING: installed the example file. Set COMTRADE_API_KEY in $ENV_DIR/trade.env." >&2
    fi
fi
# The service must not read a stray .env from its working directory.
grep -q '^TRADE_ENV_FILE=' "$ENV_DIR/trade.env" || echo "TRADE_ENV_FILE=$ENV_DIR/trade.env" >> "$ENV_DIR/trade.env"
grep -q '^TRADE_STATIC_DIR=' "$ENV_DIR/trade.env" || echo "TRADE_STATIC_DIR=$TARGET/frontend/dist" >> "$ENV_DIR/trade.env"
chown "$SERVICE_USER:$SERVICE_USER" "$ENV_DIR/trade.env"
chmod 600 "$ENV_DIR/trade.env"
chmod 755 "$ENV_DIR"

# The application directory is read-only to the service.
chown -R root:root "$TARGET"
chmod -R go-w "$TARGET"

say "systemd units"
install -m 644 "$REPO/deploy"/analytics-trade-*.service /etc/systemd/system/
install -m 644 "$REPO/deploy"/analytics-trade-*.timer /etc/systemd/system/
systemctl daemon-reload

say "Nginx"
mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
cp -a "$VHOST" "$BACKUP_DIR/analytics.mrzeynalli.xyz.$STAMP.conf"
echo "backed up vhost to $BACKUP_DIR/analytics.mrzeynalli.xyz.$STAMP.conf"

install -m 644 "$REPO/deploy/trade.location.conf" "$SNIPPET"

if ! grep -q 'snippets/trade.location.conf' "$VHOST"; then
    # Insert the include immediately before the catch-all "location / {" of the
    # TLS server block, leaving every other directive untouched.
    python3 - "$VHOST" <<'PY'
import re
import sys

path = sys.argv[1]
text = open(path).read()
marker = "    location / {"
index = text.rindex(marker)
include = "    include snippets/trade.location.conf;\n\n"
open(path, "w").write(text[:index] + include + text[index:])
print("added include to", path)
PY
else
    echo "include already present"
fi

say "Validating Nginx"
nginx -t

say "Starting services"
systemctl enable --now analytics-trade-api.service
systemctl enable --now analytics-trade-worker.service
systemctl enable --now analytics-trade-sync.timer
systemctl enable --now analytics-trade-refs.timer
systemctl enable --now analytics-trade-sources.timer
systemctl restart analytics-trade-api.service analytics-trade-worker.service

say "Health check"
for attempt in $(seq 1 20); do
    if curl -fsS http://127.0.0.1:8092/trade/api/health >/dev/null 2>&1; then
        echo "backend healthy"
        break
    fi
    sleep 1
    [ "$attempt" = 20 ] && { echo "ERROR: backend did not become healthy" >&2; \
        journalctl -u analytics-trade-api -n 40 --no-pager >&2; exit 1; }
done

say "Reloading Nginx"
systemctl reload nginx

say "Verifying routes"
curl -fsS -o /dev/null -w 'existing site /        -> HTTP %{http_code}\n' https://analytics.mrzeynalli.xyz/
curl -fsS -o /dev/null -w 'existing site /gdelt   -> HTTP %{http_code}\n' https://analytics.mrzeynalli.xyz/gdelt
curl -fsS -o /dev/null -w 'new route    /trade    -> HTTP %{http_code}\n' https://analytics.mrzeynalli.xyz/trade
curl -fsS -o /dev/null -w 'new route    /trade/api-> HTTP %{http_code}\n' https://analytics.mrzeynalli.xyz/trade/api/meta/countries

say "Done. https://analytics.mrzeynalli.xyz/trade"

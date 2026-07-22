#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 sudo 运行此脚本。" >&2
  exit 1
fi

DOMAIN="${DOMAIN:-}"
AUTH_USER="${AUTH_USER:-owner}"
APP_DIR="/opt/prompt-rag"

if [[ -z "$DOMAIN" ]]; then
  echo "请先设置域名，例如：DOMAIN=rag.example.com sudo -E bash deploy/install-ubuntu.sh" >&2
  exit 1
fi

if [[ ! -f "$APP_DIR/pyproject.toml" || ! -f "$APP_DIR/data/prompt_rag.db" ]]; then
  echo "请先把发布包解压到 $APP_DIR。" >&2
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 python3-venv python3-pip nginx apache2-utils sqlite3 certbot python3-certbot-nginx

if ! id prompt-rag >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin prompt-rag
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -e "$APP_DIR"

install -d -o prompt-rag -g prompt-rag -m 750 "$APP_DIR/data" "$APP_DIR/logs" "$APP_DIR/backups"
chown -R root:root "$APP_DIR/src" "$APP_DIR/web" "$APP_DIR/web-v2" "$APP_DIR/deploy" "$APP_DIR/pyproject.toml"
chown -R prompt-rag:prompt-rag "$APP_DIR/data" "$APP_DIR/logs" "$APP_DIR/backups"
chmod +x "$APP_DIR/deploy/backup.sh"

install -d -o root -g prompt-rag -m 750 /etc/prompt-rag
if [[ ! -f /etc/prompt-rag/prompt-rag.env ]]; then
  install -o root -g prompt-rag -m 640 "$APP_DIR/deploy/env.production.example" /etc/prompt-rag/prompt-rag.env
fi

install -o root -g root -m 644 "$APP_DIR/deploy/systemd/prompt-rag.service" /etc/systemd/system/prompt-rag.service
install -o root -g root -m 644 "$APP_DIR/deploy/systemd/prompt-rag-backup.service" /etc/systemd/system/prompt-rag-backup.service
install -o root -g root -m 644 "$APP_DIR/deploy/systemd/prompt-rag-backup.timer" /etc/systemd/system/prompt-rag-backup.timer

sed "s/__DOMAIN__/$DOMAIN/g" "$APP_DIR/deploy/nginx/prompt-rag.conf" > /etc/nginx/sites-available/prompt-rag
ln -sfn /etc/nginx/sites-available/prompt-rag /etc/nginx/sites-enabled/prompt-rag
rm -f /etc/nginx/sites-enabled/default

echo "请为私有工作台设置访问密码："
htpasswd -c /etc/nginx/prompt-rag.htpasswd "$AUTH_USER"
chmod 640 /etc/nginx/prompt-rag.htpasswd
chown root:www-data /etc/nginx/prompt-rag.htpasswd

nginx -t
systemctl daemon-reload
systemctl enable prompt-rag.service
systemctl enable --now prompt-rag-backup.timer
systemctl reload nginx

cat <<EOF

基础设施安装完成，应用尚未启动。
下一步：
  1. sudoedit /etc/prompt-rag/prompt-rag.env
  2. 填写新的 DashScope 与 MiMo API Key，并把 CORS 域名改为 https://$DOMAIN
  3. sudo systemctl start prompt-rag
  4. curl http://127.0.0.1:8010/api/health
  5. sudo certbot --nginx -d $DOMAIN
EOF

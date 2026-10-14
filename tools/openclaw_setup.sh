#!/bin/sh
# Một lần trên VM: token gateway, thư mục key provider, openclaw.json ban đầu, bật gateway + CLI.
# Chạy lại an toàn (không ghi đè token/key/config đã có).
set -e
cd "$(dirname "$0")/.."
IMG=ghcr.io/openclaw/openclaw:2026.9.8
umask 077
if [ ! -f .env.openclaw ]; then
  printf 'OPENCLAW_GATEWAY_TOKEN=%s\n' "$(head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | cut -c1-48)" > .env.openclaw
  echo "đã tạo .env.openclaw (600)"
fi
chmod 600 .env.openclaw
# Key provider: file thuộc uid 1000 (user node trong container), quyền 600 — OpenClaw từ chối file
# không riêng tư. Dùng docker (không cần sudo) để đặt chủ sở hữu.
mkdir -p secrets
docker run --rm --user 0 -v "$PWD/secrets:/s" --entrypoint sh "$IMG" -c \
  'touch /s/provider_key; chown 1000:1000 /s /s/provider_key; chmod 700 /s; chmod 600 /s/provider_key'
# openclaw.json ban đầu (chỉ khi volume chưa có) rồi provider mặc định CometAPI.
if ! tools/oc_compose.sh run --rm --no-deps -T openclaw sh -c 'test -s /home/node/.openclaw/openclaw.json'; then
  tools/oc_compose.sh run --rm --no-deps -T openclaw sh -c \
    'umask 077; mkdir -p /home/node/.openclaw && cat > /home/node/.openclaw/openclaw.json' < infra/openclaw/openclaw.base.json
  echo "đã ghi openclaw.json ban đầu"
  PROVIDER_ONLY_CONFIG=1 tools/set_provider.sh "${1:-https://api.cometapi.com/v1}" "${2:-gpt-4.1-mini}" </dev/null
fi
tools/oc_compose.sh up -d
if [ ! -x /usr/local/bin/openclaw ] || ! cmp -s tools/openclaw /usr/local/bin/openclaw; then
  sudo install -m 755 tools/openclaw /usr/local/bin/openclaw && echo "đã cài /usr/local/bin/openclaw"
fi

#!/bin/sh
# docker compose cho stack VM + gateway OpenClaw thật. Dùng: tools/oc_compose.sh <lệnh compose...>
#   tools/oc_compose.sh up -d --build      tools/oc_compose.sh logs -f openclaw
# Nạp CẢ .env (bí mật app) lẫn .env.openclaw (token gateway) — chỉ --env-file .env.openclaw thì compose bỏ .env.
cd "$(dirname "$0")/.." || exit 1
exec docker compose --env-file .env --env-file .env.openclaw \
  -f docker-compose.yml -f docker-compose.prized.yml -f docker-compose.vm.yml -f docker-compose.openclaw.yml \
  --profile tunnel "$@"

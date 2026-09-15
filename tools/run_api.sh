#!/usr/bin/env bash
# Khởi động API ClawCompany trên devstack cục bộ (Postgres + Redis nhúng).
#
# Dùng: tools/run_api.sh [port]
# Log:  /tmp/clawcompany-api.log
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PORT="${1:-8000}"

# shellcheck disable=SC1090
eval "$("$ROOT/.venv/bin/python" tools/devstack.py env)"

# Dừng tiến trình cũ trên cùng cổng, không dùng pkill theo mẫu chuỗi vì nó
# dễ bắn trúng cả shell đang gọi script này.
if PID=$(pgrep -f "uvicorn app.main:app --host 127.0.0.1 --port ${PORT}" | head -1); then
  [ -n "${PID}" ] && kill "${PID}" 2>/dev/null || true
  sleep 2
fi

cd backend
nohup env \
  DATABASE_URL="$DATABASE_URL" \
  REDIS_URL="$REDIS_URL" \
  CELERY_BROKER_URL="$CELERY_BROKER_URL" \
  CELERY_RESULT_BACKEND="$CELERY_RESULT_BACKEND" \
  JWT_SECRET="$JWT_SECRET" \
  VECTOR_BACKEND="$VECTOR_BACKEND" \
  EMBEDDING_PROVIDER="$EMBEDDING_PROVIDER" \
  OPENCLAW_MODE="$OPENCLAW_MODE" \
  OPENCLAW_GATEWAY_WS="$OPENCLAW_GATEWAY_WS" \
  CORS_ORIGINS="$CORS_ORIGINS" \
  "$ROOT/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
  > /tmp/clawcompany-api.log 2>&1 &

for _ in $(seq 1 40); do
  if curl -fsS -m 3 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "API lên ở http://127.0.0.1:${PORT}"
    curl -s "http://127.0.0.1:${PORT}/health"
    echo
    exit 0
  fi
  sleep 1
done

echo "API không lên; 40 dòng cuối của log:" >&2
tail -40 /tmp/clawcompany-api.log >&2
exit 1

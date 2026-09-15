#!/usr/bin/env bash
# Khởi động Next dev server cho ClawCompany.
#
# Luôn xoá .next trước: chạy `next build` trong khi dev server đang chạy sẽ
# ghi đè thư mục đó, và dev server sau đó trả 404 cho mọi chunk tĩnh (đã gặp
# hai lần, triệu chứng là trang trắng kèm 404 /_next/static/...).
set -uo pipefail
cd "$(dirname "$0")/.."
PORT="${1:-3000}"

PID=$(pgrep -f "next-server|next dev" | head -1 || true)
[ -n "${PID}" ] && kill "${PID}" 2>/dev/null || true
sleep 2
rm -rf .next

nohup env NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api NEXT_PUBLIC_AUTH_REQUIRED=true \
  npx next dev -H 127.0.0.1 -p "${PORT}" > /tmp/clawcompany-web.log 2>&1 &

for _ in $(seq 1 60); do
  if curl -fsS -m 3 "http://127.0.0.1:${PORT}/app/os" >/dev/null 2>&1; then
    echo "web lên ở http://127.0.0.1:${PORT}"
    exit 0
  fi
  sleep 1
done
echo "web không lên:" >&2; tail -20 /tmp/clawcompany-web.log >&2; exit 1

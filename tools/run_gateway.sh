#!/usr/bin/env bash
# Khởi động gateway OpenClaw cho môi trường phát triển.
#
# Không dùng pgrep theo chuỗi "openclaw gateway" để tìm tiến trình cũ: chuỗi đó
# khớp cả shell đang chạy script, và kill nó là tự cắt chân mình (đã bị đúng
# hai lần). Dùng `openclaw gateway stop` — chính chủ nó biết PID của nó.
set -uo pipefail
export PATH="/tmp/nodejs/bin:$PATH"
OC=/tmp/oc/node_modules/.bin/openclaw

"$OC" gateway stop >/dev/null 2>&1 || true
sleep 3

cd /tmp/oc
nohup "$OC" gateway --auth none --bind loopback --port 18789 --allow-unconfigured \
  > /tmp/clawcompany-gateway.log 2>&1 &

for _ in $(seq 1 40); do
  if curl -fsS -m 3 http://127.0.0.1:18789/ >/dev/null 2>&1; then
    echo "gateway lên ở ws://127.0.0.1:18789"
    grep -E "agent model" /tmp/clawcompany-gateway.log | tail -1
    exit 0
  fi
  sleep 1
done
echo "gateway không lên; 30 dòng cuối:" >&2
tail -30 /tmp/clawcompany-gateway.log >&2
exit 1

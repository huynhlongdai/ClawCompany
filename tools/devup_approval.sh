#!/bin/bash
# D1.1 — dựng lại môi trường phép thử approval (gateway thật + model giả + API).
# usage: tools/devup_approval.sh [framelog] ; ADMIN=true để xin operator.admin
set -u
export PATH=/data/oc/node-v24.21.0-linux-x64/bin:$PATH
if ! pgrep -f openclaw-gateway >/dev/null; then
  (cd /data/oc && HOME=/data/oc/home setsid nohup ./node_modules/.bin/openclaw gateway --dev --auth none --bind loopback --port 18789 --allow-unconfigured > /tmp/ocgw.log 2>&1 < /dev/null &)
fi
if ! pgrep -f "tools/scripted_llm.py" >/dev/null; then
  (cd /data/cc && setsid nohup .venv/bin/python tools/scripted_llm.py > /tmp/scripted_llm.out 2>&1 < /dev/null &)
fi
P=$(pgrep -f "m uvicorn app.main:app" | head -1); [ -n "$P" ] && kill $P && sleep 2
(cd /data/cc/backend && DATABASE_URL=sqlite:////data/cc/backend/dev.db JWT_SECRET=dev OPENCLAW_MODE=native \
  OPENCLAW_GATEWAY_WS=ws://127.0.0.1:18789 OPENCLAW_REQUEST_APPROVALS_SCOPE=true \
  OPENCLAW_REQUEST_ADMIN_SCOPE=${ADMIN:-false} OPENCLAW_FRAME_LOG=${1:-} WAKEUP_DRAIN_SECONDS=${DRAIN:-0} \
  CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000" \
  setsid nohup ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 < /dev/null &)
for i in $(seq 1 40); do
  curl -s -o /dev/null localhost:8000/api/v19/openclaw/protocol && curl -s -o /dev/null localhost:18789/ && break; sleep 1
done
echo "api $(curl -s -o /dev/null -w '%{http_code}' localhost:8000/api/v19/openclaw/protocol) llm $(curl -s -o /dev/null -w '%{http_code}' localhost:18800/v1/models)"

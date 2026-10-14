#!/bin/sh
# Đặt provider model OpenAI-compatible cho gateway OpenClaw. Key đọc từ STDIN (không qua tham số/lịch sử shell).
#   read -rs K && printf %s "$K" | ~/clawcompany/tools/set_provider.sh https://api.cometapi.com/v1 gpt-4.1-mini; unset K
# Mặc định: https://api.cometapi.com/v1 + gpt-4.1-mini. Provider id cố định "custom" → model "custom/<model>".
# Giá (USD / 1M token) tuỳ chọn: COST_IN=0.4 COST_OUT=1.6 (mặc định theo gpt-4.1-mini, model khác = 0).
# Key nằm ở ~/clawcompany/secrets/provider_key (uid 1000, 600), openclaw.json trỏ tới bằng SecretRef file.
set -e
cd "$(dirname "$0")/.."
BASE_URL="${1:-https://api.cometapi.com/v1}"
MODEL="${2:-gpt-4.1-mini}"
IMG=ghcr.io/openclaw/openclaw:2026.9.8
if [ "$MODEL" = "gpt-4.1-mini" ]; then CI="${COST_IN:-0.4}"; CO="${COST_OUT:-1.6}"; else CI="${COST_IN:-0}"; CO="${COST_OUT:-0}"; fi

if [ -z "$PROVIDER_ONLY_CONFIG" ]; then
  [ -t 0 ] && echo "Dán API key rồi Enter (không hiện):" >&2
  KEY=$(head -n 1 | tr -d '\r\n ')
  [ -n "$KEY" ] || { echo "Không nhận được key trên stdin — không đổi gì." >&2; exit 1; }
  printf %s "$KEY" | docker run --rm -i --user 1000:1000 -v "$PWD/secrets:/s" --entrypoint sh "$IMG" -c \
    'umask 077; cat > /s/provider_key.new && mv /s/provider_key.new /s/provider_key'
  unset KEY
  echo "đã ghi secrets/provider_key ($(stat -c '%a %u' secrets/provider_key 2>/dev/null || echo 600))"
fi

python3 - "$BASE_URL" "$MODEL" "$CI" "$CO" > /tmp/oc_provider_patch.$$.json <<'PY'
import json, sys
base, model, ci, co = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
print(json.dumps({
  "models": {"mode": "merge", "providers": {"custom": {
    "baseUrl": base, "api": "openai-completions",
    "apiKey": {"source": "file", "provider": "providerkey", "id": "value"},
    "models": [{"id": model, "name": model, "api": "openai-completions", "reasoning": False,
                "input": ["text"], "cost": {"input": ci, "output": co, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": 128000, "maxTokens": 16384}]}}},
  "agents": {"defaults": {"model": {"primary": f"custom/{model}"}}},
}))
PY
tools/oc_compose.sh run --rm --no-deps -T openclaw node openclaw.mjs config patch --stdin \
  --replace-path models.providers.custom.models < /tmp/oc_provider_patch.$$.json
rm -f /tmp/oc_provider_patch.$$.json
echo "provider: custom → $BASE_URL, model mặc định custom/$MODEL"
if [ -z "$PROVIDER_ONLY_CONFIG" ]; then
  tools/oc_compose.sh restart openclaw
  echo "đã khởi động lại gateway. Kiểm tra: openclaw models list ; openclaw agent --agent <id> -m 'chào'"
fi

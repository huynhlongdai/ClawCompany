#!/bin/sh
# Cài plugin ClawCompany Guard vào gateway OpenClaw và bật quyền hook hội thoại. Chạy lại an toàn (cập nhật code).
# OpenClaw từ chối thư mục plugin ghi được bởi group/other hoặc khác chủ (uid 1000) → chép từ mount
# /opt/clawcompany-guard vào ~/.openclaw/local-plugins rồi chỉnh quyền, thay vì link thẳng mount.
cd "$(dirname "$0")/.." || exit 1
D=/home/node/.openclaw/local-plugins
tools/oc_compose.sh exec -T -u 0 openclaw sh -c "rm -rf $D/clawcompany-guard && mkdir -p $D && cp -r /opt/clawcompany-guard $D/ \
  && rm -f $D/clawcompany-guard/*.test.mjs && chown -R 1000:1000 $D && chmod -R go-w $D" || exit 1
C="tools/oc_compose.sh exec -T openclaw node openclaw.mjs"
$C plugins install --link $D/clawcompany-guard --force || exit 1
$C config set plugins.entries.clawcompany-guard.enabled true
$C config set plugins.entries.clawcompany-guard.hooks.allowConversationAccess true
$C plugins inspect clawcompany-guard --runtime --json | head -c 1500; echo

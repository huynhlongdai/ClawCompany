#!/bin/sh
# Cài plugin ClawCompany Guard vào gateway OpenClaw (đã mount ở /opt/clawcompany-guard) và bật quyền hook hội thoại.
# Dùng: tools/install_guard.sh   (chạy lại an toàn)
cd "$(dirname "$0")/.." || exit 1
C="tools/oc_compose.sh exec -T openclaw node openclaw.mjs"
$C plugins install --link /opt/clawcompany-guard --force || exit 1
$C config set plugins.entries.clawcompany-guard.enabled true
$C config set plugins.entries.clawcompany-guard.hooks.allowConversationAccess true
$C plugins inspect clawcompany-guard --runtime --json | head -c 2000; echo

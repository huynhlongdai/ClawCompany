#!/bin/sh
# Tạo .env cho docker-compose.vm.yml với bí mật ngẫu nhiên (không ghi đè nếu đã có).
set -e
cd "$(dirname "$0")/.."
[ -f .env ] && { echo ".env đã tồn tại, giữ nguyên"; exit 0; }
umask 077
r() { head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | cut -c1-48; }
cat > .env <<EOT
POSTGRES_PASSWORD=$(r)
JWT_SECRET=$(r)$(r)
WORKLOAD_IDENTITY_DEV_SECRET=$(r)
SUPPLY_CHAIN_SIGNING_KEY=$(r)
APP_TIMEZONE=Asia/Ho_Chi_Minh
EOT
chmod 600 .env
echo "đã tạo .env (600)"

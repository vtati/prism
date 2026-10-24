#!/bin/sh
# Prism agent API — deployment start command (Railway / any PaaS).
# Binds $PORT (default 8077), all config from env.
set -e
cd "$(dirname "$0")"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8077}"

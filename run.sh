#!/bin/bash
# Start OpenProp locally. Default port 8787 (8000 is often taken); override with
# OPENPROP_PORT=9000 ./run.sh
set -e
cd "$(dirname "$0")"
PORT="${OPENPROP_PORT:-8787}"
[ -x .venv/bin/uvicorn ] && UV=.venv/bin/uvicorn || UV=uvicorn
echo "OpenProp -> http://localhost:$PORT   (Ctrl-C to stop)"
exec "$UV" app.app:app --host 127.0.0.1 --port "$PORT"

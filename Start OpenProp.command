#!/bin/bash
# Double-click to start OpenProp. (Docker Desktop must be installed and open.)
cd "$(dirname "$0")" || exit 1
echo "Starting OpenProp — the first time takes a few minutes to build. Please wait…"
docker compose up -d || { echo "Could not start. Is Docker Desktop open (the whale icon)?"; read -r; exit 1; }
for i in $(seq 1 90); do curl -s -o /dev/null http://localhost:8787/login && break; sleep 2; done
open http://localhost:8787
echo "OpenProp is open at  http://localhost:8787  — you can close this window."

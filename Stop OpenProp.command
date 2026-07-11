#!/bin/bash
cd "$(dirname "$0")" || exit 1
docker compose down
echo "OpenProp stopped. You can close this window."

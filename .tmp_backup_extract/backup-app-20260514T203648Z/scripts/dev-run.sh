#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp -n config/example.config.yaml config/config.yaml
uvicorn pi_agent_platform.api.main:app --host 0.0.0.0 --port 443 --reload

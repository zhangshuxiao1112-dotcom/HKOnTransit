#!/usr/bin/env bash
# ============================================================================
# HKOnTransit — development server launcher
# ============================================================================
#
# Prerequisites:
#   - Python 3.10+ (tested on 3.13)
#   - pip (comes with Python)
#   - Network access for Hong Kong open-data APIs (GMB/KMB/CTB/MTR/HKO)
#     [not required if only viewing the UI with offline mock data]
#
# What this script does:
#   1. Installs Python dependencies from requirements.txt
#      (fastapi, uvicorn, httpx, pydantic, pytest)
#   2. Starts the FastAPI dev server on http://127.0.0.1:8000
#
# Usage:
#   ./run.sh                         # install deps + start server
#   # then open http://127.0.0.1:8000 in a browser
#
# To run tests instead:
#   python -m pytest tests/test_api.py
#
# To activate the GenAI layer (optional, default is offline mock):
#   cp .env.example .env
#   # edit .env: set HKONTRANSIT_AI_PROVIDER=deepseek + DEEPSEEK_API_KEY=sk-...
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"
python -m pip install -r requirements.txt
env_args=()
if [[ -f .env ]]; then env_args=(--env-file .env); fi
python -m uvicorn "${env_args[@]}" server:app --host 127.0.0.1 --port 8000

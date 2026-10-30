#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv --system-site-packages /workspace/shorts-venv
/workspace/shorts-venv/bin/pip install --upgrade pip
/workspace/shorts-venv/bin/pip install -r requirements.txt
command -v ffmpeg >/dev/null || { echo 'Install ffmpeg first' >&2; exit 1; }
if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
mkdir -p /workspace/shorts-output
printf 'Start Ollama: ollama serve\nThen pull the model: ollama pull qwen2.5:7b\nCopy .env.example to .env and set the workflow node IDs.\n'

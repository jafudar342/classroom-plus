#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
export DEEPFACE_HOME="$PROJECT_DIR/models"
export MPLCONFIGDIR="$PROJECT_DIR/work/matplotlib"
export PYTHONUNBUFFERED=1
mkdir -p "$PROJECT_DIR/work"
exec "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/app/server.py" "$@"

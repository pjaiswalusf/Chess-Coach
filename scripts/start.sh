#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "Python environment missing. Run uv sync --locked from the repository root." >&2
  exit 1
fi
if [[ ! -f frontend/build/index.html || ! -d frontend/build/_app/immutable ]]; then
  echo "Frontend build missing or incomplete. Run pnpm --dir frontend build from the repository root." >&2
  exit 1
fi

unset UVICORN_RELOAD UVICORN_UDS UVICORN_FD
echo "Chess Coach: http://127.0.0.1:8000"
exec "$PYTHON" -m uvicorn chess_coach.api.app:create_packaged_app --factory \
  --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers --no-access-log --lifespan on

#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" || ! -x "$ROOT/.venv/bin/chess-coach" ]]; then
  echo "Python environment missing. Run uv sync --locked from the repository root." >&2
  exit 1
fi

# Finder's Terminal session may not have Homebrew on its search path.
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"
exec "$PYTHON" "$ROOT/scripts/launch.py" "$@"

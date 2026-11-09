"""Refresh the frontend snapshot from the same app that serves /openapi.json."""

import json
from pathlib import Path

from chess_coach.api.app import app


def main() -> None:
    snapshot = Path(__file__).resolve().parents[1] / "frontend/openapi/schema.json"
    snapshot.parent.mkdir(exist_ok=True)
    snapshot.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

"""Local API entry point."""

import uvicorn


def main() -> None:
    uvicorn.run("chess_coach.api.app:app", host="127.0.0.1", port=8000)

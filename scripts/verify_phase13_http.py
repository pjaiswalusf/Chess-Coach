"""Exercise real loopback API/Vite proxy on a disposable migrated database.

Run with: uv run python scripts/verify_phase13_http.py
Requires free ports 8000/5173 and existing frontend dependencies. No public network,
engine or model is used. Child processes and temporary database are always cleaned.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from time import monotonic, sleep

import httpx
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]


def wait_http(url: str, process: subprocess.Popen, client: httpx.Client) -> None:
    deadline = monotonic() + 30
    while monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("A fixture server stopped; inspect server startup.")
        try:
            if client.get(url).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        sleep(
            0.05
        )  # Poll the observable readiness condition, not a fixed startup delay.
    raise TimeoutError("Fixture HTTP server did not become ready.")


def main() -> None:
    for port in (8000, 5173):
        with socket.socket() as check:
            check.bind(
                ("127.0.0.1", port)
            )  # Never reuse or stop someone else's server.
    with tempfile.TemporaryDirectory(prefix="chesscoach-phase13-") as directory:
        env = dict(
            os.environ,
            CHESS_COACH_DATABASE_PATH=str(Path(directory) / "fixture.db"),
            CHESS_COACH_STOCKFISH_EXECUTABLE="/nonexistent/fixture-stockfish",
            CHESS_COACH_OLLAMA_HOST="http://127.0.0.1:9",
        )
        previous = os.environ.get("CHESS_COACH_DATABASE_PATH")
        os.environ["CHESS_COACH_DATABASE_PATH"] = env["CHESS_COACH_DATABASE_PATH"]
        try:
            command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        finally:
            if previous is None:
                os.environ.pop("CHESS_COACH_DATABASE_PATH")
            else:
                os.environ["CHESS_COACH_DATABASE_PATH"] = previous
        processes: list[subprocess.Popen] = []
        try:
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "chess_coach.api.app:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "8000",
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            processes.append(
                subprocess.Popen(
                    [
                        "pnpm",
                        "exec",
                        "vite",
                        "dev",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "5173",
                        "--strictPort",
                    ],
                    cwd=ROOT / "frontend",
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            with httpx.Client(timeout=5, trust_env=False) as client:
                wait_http("http://127.0.0.1:8000/health", processes[0], client)
                wait_http("http://127.0.0.1:5173/api/v1/system", processes[1], client)
                direct = client.get("http://127.0.0.1:8000/api/v1/system")
                proxied = client.get("http://127.0.0.1:5173/api/v1/system")
                direct_body, proxy_body = direct.json(), proxied.json()
                direct_body.pop("checked_at")
                proxy_body.pop("checked_at")
                assert (
                    direct.status_code == proxied.status_code == 200
                    and direct_body == proxy_body
                )
                missing = client.get("http://127.0.0.1:5173/api/v1/games/999")
                assert (
                    missing.status_code == 404
                    and missing.json()["code"] == "GAME_NOT_FOUND"
                )
                updated = client.put(
                    "http://127.0.0.1:5173/api/v1/player",
                    json={"username": "fixture_player"},
                    headers={"Origin": "http://127.0.0.1:5173"},
                )
                assert updated.status_code == 200
                assert (
                    client.get("http://127.0.0.1:8000/api/v1/player").json()
                    == updated.json()
                )
                assert client.get("http://127.0.0.1:8000/docs").status_code == 200
                schema = client.get("http://127.0.0.1:8000/openapi.json").json()
                assert "/api/v1/analytics/patterns" in schema["paths"]
                listeners = subprocess.check_output(
                    [
                        "lsof",
                        "-nP",
                        "-a",
                        "-p",
                        str(processes[0].pid),
                        "-iTCP:8000",
                        "-sTCP:LISTEN",
                    ],
                    text=True,
                )
                assert "127.0.0.1:8000" in listeners and "*:8000" not in listeners
                print(
                    json.dumps(
                        {
                            "proxy_success": True,
                            "proxy_404": True,
                            "proxy_mutation": True,
                            "openapi": True,
                            "loopback_listener": True,
                            "system_status": direct_body["status"],
                        }
                    )
                )
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()

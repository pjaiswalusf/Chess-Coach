"""Opt-in process tests using the actual local entrypoints and disposable storage."""

import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
from contextlib import closing, contextmanager
from pathlib import Path
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOST = "127.0.0.1"
BACKEND = f"http://{HOST}:8000"
FRONTEND = f"http://{HOST}:5173"
HTTP = build_opener(ProxyHandler({}))
LIVE = pytest.mark.skipif(
    os.environ.get("CHESS_COACH_TEST_LAUNCHERS") != "1",
    reason="requires the built frontend and free loopback ports 8000 and 5173",
)


def launch_error(script, env=None, cwd=ROOT):
    result = subprocess.run(
        [script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )
    assert result.returncode != 0
    return result.stderr


def test_missing_environment_and_build_have_actionable_errors(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for filename in ("dev.sh", "start.sh"):
        script = shutil.copy2(ROOT / "scripts" / filename, scripts)
        assert "uv sync --locked" in launch_error(script)
    finder = shutil.copy2(ROOT / "Chess Coach.command", tmp_path)
    assert "uv sync --locked" in launch_error(finder)
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    assert "pnpm --dir frontend build" in launch_error(scripts / "start.sh")


@pytest.fixture
def isolated_env(tmp_path):
    env = {
        **os.environ,
        "CHESS_COACH_DATABASE_PATH": str(tmp_path / "test.db"),
        "CHESS_COACH_STOCKFISH_EXECUTABLE": str(tmp_path / "no-stockfish"),
        "CHESS_COACH_OLLAMA_HOST": "http://127.0.0.1:9",
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    return env


def verify_port_free(port):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((HOST, port))


def verify_loopback_listener(port):
    output = subprocess.check_output(
        ["lsof", "-nP", "-Fn", f"-iTCP:{port}", "-sTCP:LISTEN"], text=True
    )
    assert {line for line in output.splitlines() if line.startswith("n")} == {
        f"n{HOST}:{port}"
    }


@contextmanager
def launch(script, env, log, cwd):
    with log.open("wb") as output:
        process = subprocess.Popen(
            [ROOT / "scripts" / script],
            env=env,
            cwd=cwd,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            yield process
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def wait_for_http(process, url, log):
    deadline = monotonic() + 12
    while monotonic() < deadline:
        assert process.poll() is None, log.read_text()
        try:
            with HTTP.open(url, timeout=0.5) as response:
                return json.load(response)
        except URLError, TimeoutError:
            sleep(0.05)
    pytest.fail(f"Timed out reaching {url}:\n{log.read_text()}")


@LIVE
@pytest.mark.parametrize("failure", ["interrupt", "backend", "frontend"])
def test_dev_start_conflicts_and_cleanup(tmp_path, isolated_env, failure):
    for port in (8000, 5173):
        verify_port_free(port)
    log = tmp_path / "dev.log"
    with launch("dev.sh", isolated_env, log, tmp_path) as process:
        assert wait_for_http(process, BACKEND + "/health", log) == {"status": "ok"}
        assert wait_for_http(process, FRONTEND + "/health", log) == {"status": "ok"}
        for port in (8000, 5173):
            verify_loopback_listener(port)
        if failure == "interrupt":
            assert "port 8000" in launch_error(ROOT / "scripts/dev.sh", isolated_env)
            assert wait_for_http(process, FRONTEND + "/health", log) == {"status": "ok"}
            process.send_signal(signal.SIGINT)
            assert process.wait(8) == 0, log.read_text()
        else:
            if failure == "backend":
                match = re.search(r"Started server process \[(\d+)\]", log.read_text())
                assert match is not None, log.read_text()
                pid = int(match[1])
            else:
                listeners = subprocess.check_output(
                    ["lsof", "-nP", "-tiTCP:5173", "-sTCP:LISTEN"], text=True
                ).splitlines()
                assert len(listeners) == 1
                pid = int(listeners[0])
            os.kill(pid, signal.SIGKILL)
            assert process.wait(10) != 0, log.read_text()
            assert f"{failure.capitalize()} exited unexpectedly" in log.read_text()
    for port in (8000, 5173):
        verify_port_free(port)


@LIVE
def test_dev_rejects_occupied_vite_port_before_starting_backend(isolated_env):
    verify_port_free(8000)
    with socket.socket() as existing:
        existing.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        existing.bind((HOST, 5173))
        existing.listen()
        assert "port 5173" in launch_error(ROOT / "scripts/dev.sh", isolated_env)
        verify_port_free(8000)


@LIVE
def test_packaged_launcher_conflicts_and_restarts(tmp_path, isolated_env):
    verify_port_free(8000)
    verify_port_free(5173)
    log = tmp_path / "start.log"
    for _ in range(2):
        with launch("start.sh", isolated_env, log, tmp_path) as process:
            assert wait_for_http(process, BACKEND + "/health/ready", log) == {
                "status": "ready"
            }
            verify_loopback_listener(8000)
            verify_port_free(5173)
            assert (
                "address already in use"
                in launch_error(ROOT / "scripts/start.sh", isolated_env).lower()
            )
            assert wait_for_http(process, BACKEND + "/health/live", log) == {
                "status": "alive"
            }
            process.send_signal(signal.SIGINT)
            assert process.wait(8) in {0, -signal.SIGINT}, log.read_text()
        verify_port_free(8000)


@LIVE
def test_packaged_launcher_refuses_stale_storage(tmp_path, isolated_env):
    db = Path(isolated_env["CHESS_COACH_DATABASE_PATH"])
    subprocess.run(
        [sys.executable, "-m", "alembic", "stamp", "c18a001"],
        cwd=ROOT,
        env=isolated_env,
        check=True,
        capture_output=True,
    )
    original = db.read_bytes()
    diagnostic = launch_error(ROOT / "scripts/start.sh", isolated_env)
    assert "MIGRATIONS_INCOMPATIBLE" in diagnostic
    assert "alembic upgrade head" in diagnostic
    assert db.read_bytes() == original


@LIVE
def test_finder_launcher_opens_ready_server_and_stops_workers(tmp_path, isolated_env):
    stockfish = shutil.which("stockfish")
    if not stockfish:
        pytest.skip("requires Stockfish for the real analysis worker")
    verify_port_free(8000)
    opened = tmp_path / "opened"
    opener = tmp_path / "open"
    opener.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$1" >> "$CHESS_COACH_TEST_BROWSER_LOG"\n'
    )
    opener.chmod(0o755)
    env = isolated_env | {
        "PATH": f"{tmp_path}:{isolated_env['PATH']}",
        "CHESS_COACH_TEST_BROWSER_LOG": str(opened),
        "CHESS_COACH_STOCKFISH_EXECUTABLE": stockfish,
        "CHESS_COACH_STOCKFISH_HASH_MB": "16",
        "CHESS_COACH_LLM_KEEP_ALIVE": "0",
    }
    log = tmp_path / "finder.log"
    script = ROOT / "Chess Coach.command"
    with (
        launch(script, env, log, tmp_path) as process,
        closing(
            sqlite3.connect(env["CHESS_COACH_DATABASE_PATH"], autocommit=True)
        ) as db,
    ):
        assert wait_for_http(process, BACKEND + "/health/ready", log) == {
            "status": "ready"
        }
        deadline = monotonic() + 8
        while monotonic() < deadline:
            assert process.poll() is None, log.read_text()
            worker = db.execute("SELECT status FROM analysis_worker_state").fetchone()
            if worker == ("ready",) and opened.exists():
                break
            sleep(0.05)
        else:
            pytest.fail(f"Browser or worker did not start:\n{log.read_text()}")
        assert "port 8000" in launch_error(script, env, tmp_path)
        assert opened.read_text().splitlines() == [BACKEND]
        assert wait_for_http(process, BACKEND + "/health/live", log) == {
            "status": "alive"
        }
        process.send_signal(signal.SIGHUP)
        assert process.wait(8) == 0, log.read_text()
        assert db.execute("SELECT status FROM analysis_worker_state").fetchone() == (
            "stopped",
        )
    verify_port_free(8000)

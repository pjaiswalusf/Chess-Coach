"""Run and supervise the two loopback development servers on POSIX."""

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import uvicorn
from uvicorn.supervisors import ChangeReload

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"


class FailFastReload(ChangeReload):
    """Let the launcher detect a failed Uvicorn child even during reload mode."""

    failed = False

    def should_restart(self) -> list[Path] | None:
        if self.process.exitcode is not None and not self.should_exit.is_set():
            self.failed = True
            raise StopIteration
        return super().should_restart()


def run_backend() -> int:
    config = uvicorn.Config(
        "chess_coach.api.app:app",
        host=HOST,
        port=8000,
        workers=1,
        reload=True,
        reload_dirs=[str(ROOT / "src")],
        proxy_headers=False,
        access_log=False,
    )
    server = uvicorn.Server(config)
    reloader = FailFastReload(config, target=server.run, sockets=[config.bind_socket()])
    reloader.run()
    return int(reloader.failed)


def signal_group(process: subprocess.Popen[bytes], sig: int) -> bool:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        return False
    return True


def stop_children(children: list[subprocess.Popen[bytes]]) -> None:
    # A package manager or reload parent can exit before its server children.
    remaining = [p for p in children if signal_group(p, signal.SIGTERM)]
    deadline = time.monotonic() + 5
    while remaining and time.monotonic() < deadline:
        for process in remaining:
            process.poll()
        remaining = [p for p in remaining if signal_group(p, 0)]
        if remaining:
            time.sleep(0.05)
    for process in remaining:
        signal_group(process, signal.SIGKILL)
    for process in children:
        process.wait()


def check_port(port: int) -> None:
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((HOST, port))
        except OSError as exc:
            raise RuntimeError(
                f"Cannot use port {port}: {exc.strerror}. Check for an existing server."
            ) from exc


def main() -> int:
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    children: list[subprocess.Popen[bytes]] = []
    frontend = ROOT / "frontend"
    pnpm = shutil.which("pnpm")
    if not pnpm or not (frontend / "node_modules" / ".bin" / "vite").is_file():
        print(
            "Frontend dependencies missing. Install pnpm, then run "
            "pnpm install --frozen-lockfile in frontend/.",
            file=sys.stderr,
        )
        return 1

    env = os.environ | {"CHESS_COACH_SERVE_FRONTEND": "0", "CHESS_COACH_E2E": "0"}
    commands = (
        (
            "Backend",
            8000,
            [sys.executable, __file__, "--backend"],
            ROOT,
        ),
        (
            "Frontend",
            5173,
            [pnpm, "dev", "--host", HOST, "--port", "5173", "--strictPort"],
            frontend,
        ),
    )
    try:
        for _, port, _, _ in commands:
            check_port(port)
        for name, port, command, directory in commands:
            if stopping:
                return 0
            children.append(
                subprocess.Popen(
                    command, cwd=directory, env=env, start_new_session=True
                )
            )
            print(f"{name}: http://{HOST}:{port}", flush=True)
        while not stopping:
            for (name, _, _, _), process in zip(commands, children, strict=True):
                status = process.poll()
                if status is not None:
                    print(
                        f"{name} exited unexpectedly (status {status}). Stopping development.",
                        file=sys.stderr,
                    )
                    return 1
            time.sleep(0.1)
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"Could not start development: {exc}", file=sys.stderr)
        return 1
    finally:
        stop_children(children)


if __name__ == "__main__":
    sys.exit(run_backend() if sys.argv[1:] == ["--backend"] else main())

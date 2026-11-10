"""Start the packaged app and its workers from the macOS Finder launcher."""

import json
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from local_processes import HOST, check_port, stop_children

ROOT = Path(__file__).resolve().parents[1]
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def wait_until_ready(
    server: subprocess.Popen[bytes], stopping: Callable[[], bool]
) -> bool:
    http = build_opener(ProxyHandler({}))
    deadline = monotonic() + 20
    while not stopping():
        if server.poll() is not None:
            raise RuntimeError(
                "The server exited during startup. See the message above."
            )
        try:
            with http.open(f"{URL}/health/ready", timeout=0.5) as response:
                if json.load(response) == {"status": "ready"} and server.poll() is None:
                    return not stopping()
        except URLError, TimeoutError, ValueError:
            pass
        if monotonic() >= deadline:
            raise RuntimeError(
                "The server did not become ready. Check the startup log above."
            )
        sleep(0.1)
    return False


def open_browser() -> None:
    try:
        subprocess.run(["open", URL], check=True, timeout=5)
    except OSError, subprocess.SubprocessError:
        print(f"Could not open your browser. Open {URL} manually.", file=sys.stderr)


def main() -> int:
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, request_stop)

    children: list[subprocess.Popen[bytes]] = []

    def launch(command: list[str]) -> subprocess.Popen[bytes]:
        child = subprocess.Popen(command, cwd=ROOT, start_new_session=True)
        children.append(child)
        return child

    try:
        check_port(PORT)
        server = launch([str(ROOT / "scripts/start.sh")])
        if not wait_until_ready(server, lambda: stopping):
            return 0

        cli = str(ROOT / ".venv/bin/chess-coach")
        workers = {}
        for name, args in (
            ("Sync worker", ["sync-worker"]),
            ("Analysis and coaching worker", ["analysis-worker", "--with-coaching"]),
        ):
            if stopping:
                return 0
            workers[name] = launch([cli, *args])

        if not stopping:
            print(
                f"Chess Coach is ready at {URL}. Press Ctrl+C here to stop it.",
                flush=True,
            )
            open_browser()
        while not stopping:
            if server.poll() is not None:
                raise RuntimeError("The server exited. See the message above.")
            for name, worker in list(workers.items()):
                if worker.poll() is not None:
                    print(
                        f"{name} stopped. Check the log above and restart the launcher to retry.",
                        file=sys.stderr,
                    )
                    del workers[name]
            sleep(0.2)
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"Could not run Chess Coach: {exc}", file=sys.stderr)
        return 1
    finally:
        stop_children(children, graceful_parents=True)


if __name__ == "__main__":
    sys.exit(main())

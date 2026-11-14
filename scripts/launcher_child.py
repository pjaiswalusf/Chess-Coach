"""Keep a detached Chess Coach process tied to its Finder launcher."""

import os
import signal
import subprocess
import sys
from threading import Event


def main() -> int:
    launcher_pid = int(sys.argv[1])
    stopping = Event()
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: stopping.set())
    if os.getppid() != launcher_pid:
        return 0
    child = subprocess.Popen(sys.argv[2:])
    try:
        while os.getppid() == launcher_pid and not stopping.is_set():
            if (status := child.poll()) is not None:
                return status
            stopping.wait(0.1)
        return 0
    finally:
        child.terminate()
        try:
            child.wait(5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


if __name__ == "__main__":
    sys.exit(main())

"""Loopback and process-group helpers for the local launchers."""

import os
import signal
import socket
import subprocess
import time

HOST = "127.0.0.1"


def signal_group(process: subprocess.Popen[bytes], sig: int) -> bool:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        return False
    return True


def stop_children(children: list[subprocess.Popen[bytes]]) -> None:
    # A reload or package-manager parent can exit before its children.
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

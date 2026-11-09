"""Kernel-owned local worker lock, released even after a hard process exit."""

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class WorkerAlreadyRunning(ValueError):
    pass


@contextmanager
def worker_guard(database: Path) -> Iterator[None]:
    path = database.resolve().with_suffix(".analysis.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WorkerAlreadyRunning(
                "ANALYSIS_ALREADY_RUNNING: a worker owns this database"
            ) from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def worker_is_locked(database: Path) -> bool:
    path = database.resolve().with_suffix(".analysis.lock")
    try:
        with path.open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except FileNotFoundError:
        return False
    except BlockingIOError:
        return True
    return False

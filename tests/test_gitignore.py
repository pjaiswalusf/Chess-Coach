"""Protect frontend source from broad Python packaging ignore patterns."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "path",
    [
        "frontend/src/lib/index.ts",
        "frontend/src/lib/assets/favicon.svg",
        "frontend/src/lib/components/Review.svelte",
        "frontend/src/lib/api/client.ts",
        "frontend/src/lib/vitest-examples/greet.spec.ts",
    ],
)
def test_frontend_source_is_not_ignored(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr


@pytest.mark.parametrize("path", ["lib/generated.py", ".venv/pyvenv.cfg"])
def test_python_build_and_environment_files_remain_ignored(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

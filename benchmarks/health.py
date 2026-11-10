"""Capture native host observations and reproducibility metadata."""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import chess

from benchmarks.prepare_dataset import PRIVATE_ROOT, private_path, sha256

ROOT = PRIVATE_ROOT.parents[1]


def command(
    *args: str,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> dict:
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            env=env,
            input=stdin,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": type(exc).__name__}
    return {
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def snapshot() -> dict:
    return {
        "captured_at_utc": utc_now(),
        "uptime": command("uptime"),
        "disk": command("df", "-h", "."),
        "swap": command("sysctl", "vm.swapusage"),
        "memory_pressure_level": command(
            "sysctl", "kern.memorystatus_vm_pressure_level"
        ),
        "memory_pressure_query": command("memory_pressure", "-Q"),
        "power_source": command("pmset", "-g", "batt"),
    }


def revision() -> dict:
    head = command("git", "rev-parse", "HEAD")
    if head.get("returncode") != 0:
        raise ValueError("Run benchmarks from a Git checkout with a readable HEAD")
    diff = subprocess.check_output(["git", "diff", "--binary", "HEAD", "--"], cwd=ROOT)
    return {
        "git_revision": head["stdout"],
        "git_status": command("git", "status", "--short")["stdout"],
        "tracked_diff_sha256": sha256(diff),
        "benchmark_sources_sha256": {
            path.name: sha256(path.read_bytes())
            for path in sorted((ROOT / "benchmarks").glob("*.py"))
        },
    }


def environment(engine: str, model: str) -> dict:
    local_ollama = {**os.environ, "OLLAMA_HOST": "127.0.0.1:11434"}
    # Filter hardware output before writing it so serial numbers stay out of logs.
    hardware = command("system_profiler", "SPHardwareDataType")
    hardware["stdout"] = "\n".join(
        line.strip()
        for line in hardware.get("stdout", "").splitlines()
        if line.strip().startswith(
            (
                "Model Name:",
                "Model Identifier:",
                "Chip:",
                "Total Number of Cores:",
                "Memory:",
            )
        )
    )
    binary = shutil.which(engine)
    stockfish = (
        command(binary, stdin="uci\nquit\n") if binary else {"error": "NotFound"}
    )
    stockfish["stdout"] = "\n".join(
        line
        for line in stockfish.get("stdout", "").splitlines()
        if line.startswith("id ")
    )
    return {
        **revision(),
        "architecture": platform.machine(),
        "macos": command("sw_vers"),
        "hardware": hardware,
        "python": sys.version,
        "chess_library_version": chess.__version__,
        "stockfish_executable": binary,
        "stockfish_uci_identity": stockfish,
        "stockfish_executable_sha256": sha256(Path(binary).read_bytes())
        if binary
        else None,
        "ollama_version": command("ollama", "--version", env=local_ollama),
        "ollama_models": command("ollama", "list", env=local_ollama),
        "ollama_model": model,
        "ollama_model_details": command("ollama", "show", model, env=local_ollama),
        "ollama_resident_models": command("ollama", "ps", env=local_ollama),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--environment", action="store_true")
    parser.add_argument("--engine", default="stockfish")
    parser.add_argument("--model", default="qwen3.5:4b-q4_K_M")
    args = parser.parse_args()
    try:
        path = private_path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"label": args.label, **snapshot()}
        if args.environment:
            record["environment"] = environment(args.engine, args.model)
        with path.open("x") as output:
            json.dump(record, output, indent=2)
            output.write("\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Health capture failed: {exc}\n")


if __name__ == "__main__":
    main()

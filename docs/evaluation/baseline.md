# Phase 15 pre-change baseline

Recorded 2026-11-09 on top of Phase 14 commit `7067ff4` with a clean worktree.

- Python 3.14.6; imports of chess, Pydantic, and Ollama succeeded.
- Local Stockfish executable reported Stockfish 19.
- Ollama client 0.40.15; local inventory contained exactly one tag:
  `qwen3.5:4b-q4_K_M` (ID `d8b0f5e9760c`, 3.3 GB). The full digest is
  recorded in the [Phase 14 baseline](phase14_baseline.md). No model was
  downloaded or changed.
- `uv run ruff check .` passed. `uv run mypy src` passed (90 files).
- `uv run pytest`: 598 passed, 1 skipped, 2 deselected. The commands reused the
  installed virtual environment with `UV_NO_SYNC=1` and a writable uv cache.
- See the Phase 14 baseline for prior coaching results. They were measured on
  move explanations and cannot be used to score this motif taxonomy.

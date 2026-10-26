# Chess Coach

## Project purpose

Chess Coach is a local-first personalized chess analysis and coaching
application.

The system imports completed chess games, analyzes positions using
Stockfish, builds longitudinal player analytics, identifies recurring
weaknesses, and uses a small local language model to turn verified
evidence into understandable coaching.

The application is intended only for post-game analysis.

It must never provide assistance during an active game.

---

## Core principle

Deterministic systems establish facts.

Generative models explain facts.

The LLM is never the source of truth for:

- legal moves
- best moves
- engine evaluations
- mate states
- centipawn loss
- game results
- historical counts
- percentages
- statistical aggregates

These values must come from deterministic systems such as:

- python-chess
- Stockfish
- persisted source data
- deterministic Python analytics

The LLM may:

- explain engine evidence
- summarize historical patterns
- classify ambiguous coaching themes
- generate training advice from supplied evidence

The LLM must never overwrite deterministic evidence.

---

## Technology

Backend:

- Python 3.12
- FastAPI
- SQLAlchemy
- SQLite
- Alembic
- python-chess
- Stockfish
- Ollama
- Pydantic

Frontend:

- Svelte 5
- SvelteKit 3
- TypeScript
- Vite

Tooling:

- uv
- Ruff
- mypy
- pytest
- Vitest
- Playwright

---

## System boundaries

The Python backend owns:

- Chess.com integration
- PGN parsing
- persistence
- Stockfish analysis
- feature extraction
- longitudinal analytics
- LLM orchestration
- training logic
- API behavior

The Svelte frontend owns:

- presentation
- interaction
- navigation
- frontend state
- API consumption

The frontend must never directly access:

- SQLite
- Stockfish
- Ollama
- Chess.com
- backend filesystem state

All frontend access to application functionality must go through the
FastAPI API.

---

## Backend layering

Use these conceptual layers:

domain
application
analytics
infrastructure
api

Domain logic should remain independent of technical integrations.

FastAPI routes should remain thin.

Business logic must not be implemented directly inside route handlers.

Infrastructure-specific code should remain outside domain logic.

---

## Data principles

Raw imported PGN must be preserved.

Game import must be idempotent.

Analysis must be:

- incremental
- resumable
- cached
- versioned

Expensive analysis must not be repeated when a compatible cached result
already exists.

---

## AI principles

Stockfish is authoritative for chess evaluation.

The local LLM exists to improve communication and limited
interpretation, not to replace deterministic analysis.

LLM responses should use structured output where practical.

Persist enough provenance to understand which:

- engine version
- analysis configuration
- analytics version
- model
- prompt version

produced an output.

---

## Development principles

Prefer the simplest implementation that satisfies the current
requirement.

Do not introduce infrastructure for hypothetical future scale.

Do not add:

- PostgreSQL
- Redis
- Celery
- Kafka
- vector databases
- Docker
- Kubernetes
- cloud inference

without demonstrated need.

Avoid unrelated refactors while implementing features.

Every bug fix should include a regression test when practical.

---

## Backend completion checks

Before considering backend work complete, run:

uv run ruff check .
uv run mypy src
uv run pytest

---

## Frontend completion checks

Before considering frontend work complete, run:

cd frontend
pnpm check
pnpm test
pnpm build

Run Playwright for critical workflows.

---

## Definition of done

A task is not complete merely because code was generated.

A task is complete when:

- the requested behavior exists
- relevant tests exist
- required checks pass
- known failure cases are handled
- architectural constraints are respected
- limitations are reported honestly

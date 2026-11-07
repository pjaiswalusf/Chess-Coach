# Phase 8: trusted completed-game PGN ingestion

Run `uv run alembic upgrade head`, then
`uv run chess-coach parse-games --username USER`. No network, Stockfish, Ollama,
API endpoint, or UI is involved. `--retry` explicitly revalidates all stored games
for that player, including ready/rejected records. Normal runs select only pending
records; failures are not retried endlessly. Configure the per-game UTF-8 byte
limit with `CHESS_COACH_PGN_MAX_BYTES` (default 1,000,000).

## Existing schema and additions

Phase 7's `games` table already owns `raw_pgn`, source identity/hash, tracked player,
White/Black names, player color/result, time control, and opening metadata.
Migration c8a001 adds parsing state, reason/safe message, attempted time, parser
and chess-library versions, compact parsed metadata, and source evidence. It
neither duplicates games nor changes their identity or raw PGN. Typed moves are
reconstructed from preserved PGN; no engine analysis records are written here.

Previously imported rows lack original end-time/result-code evidence. They become
`incomplete` until `sync --username USER --force` backfills evidence for an exactly
matching immutable PGN, followed by `parse-games --username USER --retry`.
Changed upstream PGNs are never silently attached to old records or overwritten.
New imports retain end time, terminal result codes, rules, and optional final FEN.
PGN source rows rely on the user's completion declaration, not proof of completion
from the board. This phase does not add a file-upload importer or cross-source
PGN deduplication policy.

## Acceptance boundary (parser version 1)

- Require one game, meaningful distinct players, an exact tracked-player match
  after strip/casefold, explicit matching terminal header and movetext results.
- Reject unsupported variants, invalid setup/FEN, recorded python-chess errors,
  null/illegal moves, malformed structure, unknown or skipped lexical tokens,
  moves after automatic game termination, and contradictory terminal-board results.
  SAN semantics and legality are delegated to python-chess, never a second SAN parser.
- Variations and comments are validated but only the mainline produces moves.
  Unknown annotations belong in comments. Malformed/unclosed structures are rejected.
- Custom starts require SetUp=1 plus FEN. Preserve counters and mark prior history
  unknown, even if the supplied FEN happens to equal the standard start.
- Independent provider final FEN compares piece placement and side to move only;
  en-passant/castling representation and counters are not asserted equivalent.
- A win need not be checkmate; resignation/timeout and agreed draws are accepted.
  Claimable repetition/50-move draws are not assumed claimed. Automatic terminal
  outcomes must agree with the declaration. Termination text is source metadata.

## Clocks and metadata

Clock/elapsed annotations use python-chess accessors. Finite nonnegative recorded
elapsed time takes priority. Estimate only for simple seconds or seconds+increment
controls, using the same player's preceding clock plus increment minus new clock.
This assumes increment is included in the recorded post-move clock; estimates are
explicitly labeled, never treated as recorded measurements. The base clock is used
only for the first move from a normal start. A missing clock breaks that player's
estimation chain; custom starts, complex controls, or negative estimates yield None.
Missing clocks/opening values remain unknown. Existing API opening fields survive
when absent from PGN. No opening classification or timing analytics occurs here.

## State, recovery, and diagnostics

`pending -> parsing -> ready | parse_failed | unsupported | incomplete`.
Only current-parser/current-library `ready` records with committed metadata are
eligible through `ParseRepository.eligible_ids`. Engine status remains separate.

The application holds the existing database-wide kernel import lock for a batch.
Each begin/finalization uses its own short transaction; parsing runs with no open
SQL transaction. A crashed process releases the lock. The next batch resets that
player's interrupted `parsing` records to pending and safely retries. Completed
records remain untouched. Ready metadata and status commit together. Write failures
roll back and surface; metadata from a prior attempt cannot make a parsing row
eligible. Expected per-game rejections persist and do not block later games.
Unexpected programming errors persist a safe reason, log a backend traceback,
and surface; they are not silently swallowed.

Raw PGNs are retained for every outcome. Empty/illegal/malformed input is
`parse_failed`, variants `unsupported`, missing completion evidence/results
`incomplete`. Correct source data or fix the parser and explicitly retry. Missing
clocks/ECO require no recovery. Fix database access then rerun after write failures.

The CLI emits actual batch totals, reasons, unexpected failures, source-position
mismatches, recovered states, and clock coverage; structured logs include game IDs
and final summary. Rejection rates above 2% over at least 100 attempted games merit
investigation, not automatic system failure. Clock coverage is informational.

## Verification

Synthetic fixtures: `tests/fixtures/pgn/README.md`. Parser behavior:
`tests/unit/test_pgn_parser.py`. Migration-backed transactions, mixed batches,
recovery, and eligibility: `tests/integration/persistence/test_pgn_persistence.py`.
Source-evidence backfill: `tests/integration/persistence/test_sync.py`.
Run Ruff, mypy, and the full pytest suite. No production success rate or engine
readiness beyond this validation contract is claimed from fixture results.

## Verified on 2026-11-07

- Ruff and mypy pass (38 source files); 241 pytest tests pass.
- Fresh schema, populated Phase 7 upgrade, downgrade/reupgrade, and model/schema
  parity pass. The populated upgrade preserves identity/raw PGN and initializes
  pending validation without inventing source evidence.
- Independent read-only review: PASS, with no remaining blocking findings.
  Review found root-variation misinterpretation and huge numeric annotations;
  both were fixed with regression tests before sign-off.
- Coverage command above: backend 1,199 / 1,255 executable statements (95.54%).
  Deterministic Phase 8 subset is exactly `domain/game_records.py` plus
  `infrastructure/pgn/parser.py`: 228 / 241 executable statements (94.61%).
  These are line-coverage diagnostics, not production correctness rates.
- Tests report one upstream python-chess asyncio-policy deprecation warning.
  No public network, live engine/model, or production database was used.

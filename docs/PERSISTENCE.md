# Phase 6 persistence contract

SQLite stores data in `data/chess_coach.db` by default. Override the existing
`CHESS_COACH_DATABASE_PATH` setting for another file. Settings builds the URL;
Alembic and application engines use the same settings and connection hook.
Database, WAL, and shared-memory files are ignored by Git.

Run `uv run alembic upgrade head` to construct the schema, `uv run alembic current`
to inspect its revision, and `uv run alembic check` to detect model/schema drift.
Review generated migrations manually, including named CHECK constraints, and
render `UTCDateTime` columns as `sa.DateTime()` in migrations so old revisions do
not depend on application types. Never use `create_all()` as the migration path.

## Transactions and deletion

`create_session_factory(engine)` returns a session factory. The application
owns the unit of work: `with sessions.begin() as session:` commits on successful
exit, rolls back on exceptions, and closes the session. Plain `sessions()` does
not implicitly commit. Repositories and routes do not own commits.

Game deletion cascades to its move analyses and per-game states. Player and run
deletion is restricted while referencing records exist. The shared position
cache survives game deletion. There is no deletion API in this phase.

Timestamps must be timezone-aware. Writes normalize to UTC; reads restore UTC
awareness. SQLite stores the normalized values without an offset. Pending runs
and per-game states have no start/end timestamp until work actually happens.

## Source identity

Tracked usernames are casefolded on ORM assignment. The database enforces
`UNIQUE(platform, username)` for stored identities. Source player names in games
and the original PGN are preserved. Import code must use the same normalization
when querying or using bulk SQL.

Games enforce global `UNIQUE(platform, external_id)` and `UNIQUE(canonical_hash)`.
Multiple distinct games may have NULL external IDs. This follows the script's
personal-app/global deduplication choice: one game row belongs to one tracked
player; it does not represent the same encounter separately for both players.

The **planned** canonical identity is SHA-256 of a versioned canonical JSON
payload containing the full initial standard-chess FEN, casefolded White and
Black usernames, UTC played-at value at source-supported precision, and ordered
mainline UCI moves. Comments, tag order, whitespace, and variations are excluded.
The parser and the exact policy for missing/differing source timestamps belong
to Phase 8. These tests use synthetic hashes and prove uniqueness of supplied
identities only; they do not establish real cross-source PGN deduplication.

## Analysis provenance and cache identity

Analysis runs retain the player, engine version, analysis version, configuration
hash, actual configuration/budget JSON, and draw-policy version. Configuration
includes the budget (for example nodes), Threads, Hash, and MultiPV. No engine
is launched in this phase and no budget is selected by persistence code.

With the user's approved correction to the script, cache identity is:

`(fen, history_hash, history_before_start_unknown, engine_version, analysis_version, config_hash, draw_policy_version)`.

`history_hash` must cover the full starting FEN and ordered UCI move history.
Both are also retained as `initial_fen` and `moves_uci_json`. Full FENs preserve
halfmove and fullmove clocks. A SetUp/FEN source must set
`history_before_start_unknown=True`; its unknown prehistory must not be treated
as complete history. Hash generation and legality validation arrive with the
analysis pipeline. These are storage-level compatibility checks, not an engine
cache lookup implementation.

The versioned draw policy `unclaimed-v1` does not treat claimable threefold or
50-move draws as claimed; automatic fivefold and 75-move outcomes follow
python-chess rules, including checkmate precedence. Future engine code must use
the same move history and policy as deterministic analysis. Changing this policy
requires a new identity, as do engine, budget/configuration, and analysis changes.

Scores use White's perspective. Exactly one centipawn or mate value is stored
per evaluation; mate transitions may have NULL centipawn loss. No conversion,
move-loss calculation, phase detection, or severity classification is implemented.

Per-game states are unique by game/version, while moves are unique by
game/ply/version, following the script. A later orchestrator must atomically
persist required results before marking a game done, verify run/player/version
compatibility, and replace stale results when engine settings change under the
same analysis version. A state row alone does not prove those future behaviors.

Ply is relative to the imported game's start. Move number and mover must be
validated against `fen_before` by the later analysis writer. The script's
`(ply + 1) // 2` and odd/White rule only hold for ordinary starting-position
games; they must not become database constraints that reject valid SetUp games.

## Verification

`tests/integration/persistence/` uses temporary file databases constructed only
through Alembic. It verifies configuration on separate physical connections,
fresh upgrades, downgrade/re-upgrade, drift and named checks, all seven models,
duplicate identities, incompatible cache identity components, foreign keys,
restricted/cascading deletion, UTC round trips, score and counter constraints,
transaction rollback, and persisted states queryable after reopening sessions.

No Chess.com downloads, PGN parsing/hashing, Stockfish execution, coaching,
puzzles, or frontend database screens are part of Phase 6.

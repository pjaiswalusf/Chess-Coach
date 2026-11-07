# Phase 7 synchronization contract

Input: a public Chess.com username, normalized by trimming and lowercasing.
Optional force rescan, read-only dry run, and one-month scope (`YYYY/MM`).

Operation: verify profile once; discover and validate monthly archive URLs;
plan; fetch serially; validate completed source records; insert unseen games;
commit archive checkpoint, validators and run counters together; finalize run.
Only public profile and completed monthly archives are requested.

Output: JSON report with run_id, status, archives_discovered, archives_selected,
archives_fetched, archives_completed, archives_skipped, archives_unchanged,
archives_failed, games_received, games_inserted, games_already_present,
games_skipped_unsupported, games_failed, planned_archives and errors.

- `COMPLETED`: every selected archive succeeded or has a successful historical
  checkpoint. `PARTIAL`: some successful archive work and some failures.
  `FAILED`: no successful archive work, or discovery/orchestration failure.
  `DRY_RUN`: plan only; no run/player/game/checkpoint writes.
- Existing database run enum `succeeded` maps to report `COMPLETED`; no second
  run-status system is added. `pending` and `running` remain internal states.
- Archive states: pending, running, complete, failed, unavailable. An unavailable
  archive is not automatically retried; it remains visible as an error until
  explicitly retried with `--force` after review.
- `archives_fetched` counts monthly fetch operations attempted, including failed
  requests and unchanged checks; HTTP retries are not extra archives.
- `archives_completed` counts this run's successfully committed checks, including
  empty/304/all-existing archives. `archives_unchanged` is its 304 subset.
- `archives_selected` is the scope after `--month`; discovered counts the full
  list. Selected = fetched + skipped after an ordinary finished loop.
- Received = inserted + already_present + skipped_unsupported + failed. A malformed
  supported record rejects its entire month: all non-skipped records in that
  rolled-back archive count as failed, including otherwise valid records.
  A failed request without a valid envelope has zero received games.
- Historical skips and 304s do not manufacture game counters.

Guarantees: DB-enforced uniqueness; immutable existing game content; raw PGN
preservation; atomic archive transactions; validators advance only with persisted
results; bounded serial retries; restart recovery; no false COMPLETE checkpoint;
no Stockfish, Ollama or UI involvement. Failure of one month does not undo another.

Completion evidence is an end timestamp and compatible terminal player result
codes, plus a matching terminal PGN Result header. Source metadata establishes
completion; Phase 7 does not establish move legality. Full PGN parsing, legal
replay, invalid-position handling and cross-source canonical identities remain
Phase 8. Imported rows must not be used as verified legal analysis inputs yet.

A validated stable game URL is required even when UUID is present, so UUID
omission cannot change the secondary identity. This conservative policy rejects
records without a stable URL instead of risking duplicates. Supported games use
`rules=chess`; explicit nonstandard PGN Variant headers are skipped as unsupported.
Missing/invalid required fields fail the archive. Optional ratings stay null.

No full history or PGNs are logged. Rejected PGNs and safe reason codes are stored
locally in import_rejections, identified by run, archive and zero-based record index.

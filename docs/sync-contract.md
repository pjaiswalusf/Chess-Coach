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
- Received = inserted + already_present + skipped_unsupported + failed. A record
  without valid source identity or completion evidence rejects its entire month.
  All non-skipped records in that rolled-back archive count as failed. An empty
  PGN or bad Result header in an otherwise valid source record counts as one failed
  record. Other games in that archive are committed. A failed request without a
  valid envelope has zero received games.
- Historical skips and 304s do not manufacture game counters.

Guarantees: DB-enforced uniqueness; immutable existing game content; raw PGN
preservation; atomic archive transactions; validators advance only with persisted
results; bounded serial retries; restart recovery; no false COMPLETE checkpoint;
no Stockfish, Ollama or UI involvement. Failure of one month does not undo another.

Completion evidence comes from an end timestamp and compatible terminal player
result codes. A game needs a matching terminal PGN Result header to enter the
library. The parser verifies move legality, the starting position, and agreement
with the declared result before any engine work.

A validated stable game URL is required even when UUID is present, so UUID
omission cannot change the secondary identity. This conservative policy rejects
records without a stable URL instead of risking duplicates. Supported games use
`rules=chess`; explicit nonstandard PGN Variant headers are skipped as unsupported.
Missing/invalid required fields fail the archive. Optional ratings stay null.

No full history or PGNs are logged. Rejected PGNs and safe reason codes are stored
locally in import_rejections, identified by run, archive and zero-based record index.

Sync retries each transient HTTP request up to three attempts, including the
initial request. The default waits are one and two seconds plus up to one second
of jitter. A valid `Retry-After` delay or HTTP date on a 429 overrides the delay.
Past dates retry immediately. Invalid values use the default delay. A hint over
30 seconds ends that request and asks the user to retry later. A final 429
ends the current scan. Already committed archives are retained, and archives
that were never started stay eligible for the next sync. Failed and partial
runs preserve the last failure code in the run summary. The API exposes specific
messages for `CHESSCOM_TIMEOUT`, `CHESSCOM_UNAVAILABLE`, and `CHESSCOM_RATE_LIMITED`.

The browser sync worker validates stored PGNs before publishing completion.
`games_quarantined` counts PGNs rejected at archive ingest and stored PGNs that
failed the parsing pass. An ingest rejection retains the raw PGN, diagnostic,
archive and record index under its timestamped run. A later forced sync may log
another rejection for the same input. A stored game that fails parsing retains
its raw PGN and diagnostic on its existing game row and stays out of analysis.

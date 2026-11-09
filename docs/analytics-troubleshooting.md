# Analytics troubleshooting

Run `uv run chess-coach analytics-health --player-id ID --profile PROFILE_HASH`.
Inspect `health.integrity`, coverage/status counts, and each candidate's support
separately. A valid descriptive report is not proof of sufficient evidence.

| Observation / diagnostic | Next action |
| --- | --- |
| PLAYER_NOT_FOUND / NO_GAMES | Check player ID, READY completed-game status and filters. Do not manufacture defaults. |
| ANALYSIS_PARTIAL | Inspect pending/running/failed/incompatible counts; finish a compatible run separately. |
| Missing feature snapshot | Analytics derives features in memory from valid completed analysis. The optional offline `extract-features` command stores snapshots for repeated reads. |
| GAME_REVALIDATION_REQUIRED / PARSED_METADATA_INVALID | Inspect preserved source and explicitly revalidate the earlier parsing layer. |
| ANALYSIS_SOURCE_CHANGED | Revalidate source, then create a compatible analysis run explicitly. |
| MISSING_MOVE_ANALYSIS / MISSING_POSITION_EVIDENCE | Inspect interrupted/corrupted engine evidence and repair through its normal resumable workflow. |
| DUPLICATE_MOVE_ANALYSIS / DUPLICATE_GAME | Preserve evidence; diagnose identity/uniqueness before computing a report. |
| PLAYER_ATTRIBUTION_INVALID | Check tracked player, source metadata, move colors and earlier-layer parsing. |
| INVALID_LOSS / ANALYSIS_SCORE_INVALID / SEVERITY_POLICY_MISMATCH | Check stored White-POV scores and mover loss arithmetic; do not rewrite values in analytics. |
| INCOMPATIBLE_ANALYSIS / ANALYSIS_PROVENANCE_MISSING | Select one exact engine/configuration/version/draw-policy profile. Never combine profiles silently. |
| POSITION_HISTORY_INVALID | Check initial position, ordered history and unknown pre-FEN provenance. FEN alone is insufficient. |
| FEATURE_SET_INVALID / FEATURE_CONTENT_INVALID / INVALID_STORED_EVIDENCE | Inspect matching snapshot's count, content, version and source alignment. Rebuild separately after diagnosis. |
| CLOCK_DATA_LIMITED | Inspect pre-move reconstruction and annotation coverage; below 80%, broad time-pressure patterns are suppressed. |
| OPENING_UNKNOWN | Retain UNKNOWN; do not guess ECO or family. |
| No ranked weaknesses | Inspect report coverage and per-candidate game/move support. Missing support is not proof of perfect play. |
| Slow report | Inspect structured retrieval/validation/aggregation/ranking timings and query counts before introducing caching. |
| DATABASE_INTEGRITY_FAILED / FOREIGN_KEY_FAILED | Stop calculations; preserve a SQLite backup and diagnose before repair. Never delete historical data. |

Before migrations or repairs, use SQLite's backup API so committed WAL data is
included. Example from the repository root (choose a fresh backup destination):

```python
from pathlib import Path
import sqlite3

source_path = Path("data/chess_coach.db").resolve()
backup_path = Path("/private/tmp/chess-coach-investigation.db")
assert not backup_path.exists()
with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as source:
    with sqlite3.connect(backup_path) as backup:
        source.backup(backup)
        print(backup.execute("PRAGMA integrity_check").fetchall())
        print(backup.execute("PRAGMA foreign_key_check").fetchall())
```

Expect `[("ok",)]` and no foreign-key rows. Restore/test the backup at a separate
location. Analytics never performs repairs or migrations itself. Known errors
have stable codes; unexpected database errors use the existing safe CLI handling.
No default diagnostic includes source PGNs or a complete local database path.

# Longitudinal analytics — V1 contract

Phase 12 is an offline, read-only backend service. It uses existing completed-game,
engine and feature evidence. It starts no API server, engine, model or network
client. There is no new migration, summary table, API endpoint or frontend change.

```python
from chess_coach.analytics.contracts import AnalyticsRequest, WindowType
from chess_coach.analytics.service import AnalyticsService
from chess_coach.config import Settings
from chess_coach.infrastructure.persistence.analytics_repository import AnalyticsRepository
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.session import create_session_factory

engine = create_database_engine(Settings().database_url)
try:
    service = AnalyticsService(AnalyticsRepository(create_session_factory(engine)))
    report = service.build_report(AnalyticsRequest(
        player_id=1, window=WindowType.LAST_100, profile_hash="EXISTING_PROFILE_HASH",
    ))
    print(report.model_dump_json(indent=2))
finally:
    engine.dispose()
```

An explicit profile hash is required: engine version, configuration/budget,
analysis version and draw policy must be identical. The report also declares
`longitudinal-v1`, `support-v1`, `cp-severity-v1` and `weakness-ranker-v1`.
Changing policy requires a version bump. No automatic profile selection or
cross-profile normalization is performed.

## Cohorts and health

The repository applies tracked player, READY completed standard-game status,
color, time class and UTC date filters, then orders by `(played_at DESC, id DESC)`
and limits last-20/50/100 membership. ALL has no limit. DATE_RANGE requires two
timezone-aware boundaries and uses `start <= played_at < end`; supplied offsets
normalize to UTC. Dates on another window are rejected. NULL/empty metadata is
reported as UNKNOWN. Time-control partitions preserve both imported time class
and the exact raw clock rule; unfamiliar categories are retained.

Only after selecting the actual games does it inspect engine readiness. Older
analyzed games never replace selected pending games. Missing, pending, running,
failed, and incompatible states remain in health counts. Game results include
all selected games; move statistics use only complete compatible games.

All SQL reads, including health checks, use one SQLite read transaction with
non-legacy transaction mode and `query_only`. Batched queries load only selected
games' evidence; a 20-game report uses at most 12 statements in its regression
fixture. Larger cohorts chunk IDs in groups of 500, avoiding parameter limits.
SQLite integrity and foreign-key failures stop computation. Other critical
integrity failures return DATA_ERROR, diagnostic codes and no calculated report.
They never trigger source repairs.

Validation rechecks source completion/provenance, legal PGN replay and parsed
metadata, exact move membership/attribution, source hashes, analysis-run profile,
position scores/history/PVs, stored loss arithmetic and feature snapshot identity,
content hashes and indexed fields. PGN completion is a trusted declaration;
Chess.com completion requires archive evidence. Unknown pre-FEN history stays
explicit and is never treated as full history.

Missing current feature snapshots produce FEATURES_NOT_READY; phase stays
UNCLASSIFIED, castling/time data unavailable, and supported engine statistics
remain available. A partially present matching snapshot is a data error, rather
than a plausible complete phase partition. Older feature snapshots are ignored.

NO_GAMES is a valid empty report. PARTIAL retains exploratory descriptive results
but no ranked weaknesses. With fully compatible engine evidence, fewer than ten
games gives INSUFFICIENT_DATA; ten or more gives COMPLETE. COMPLETE describes
engine coverage, not statistical certainty or completeness of every optional
metadata field. Every candidate has a separate support state. Missing clocks
or opening identifiers do not invalidate unrelated statistics.

## Mathematical populations

- Score percentage: `100 * (wins + 0.5 * draws) / selected completed games`.
  Win percentage uses wins only. Undefined ratios are null.
- Move loss: pooled comparable CP observations only. Mean and standard-library
  median omit missing/mate transitions and report omissions. Missing is never zero.
- Severity: existing engine output has nullable severity. V1 explicitly derives
  CP categories from verified stored loss: normal `[0,30)`, minor `[30,80)`,
  significant `[80,150)`, critical `[150,infinity)`. These are provisional product
  thresholds, not established chess truth. Categories are mutually exclusive.
  Non-null stored severity must agree; analytics never backfills it. Mate
  transitions are unclassifiable and retain separate White-POV mate/winner fields
  and an exclusion reason, with no conversion to CP. All CP context scores are
  normalized to the tracked player in the adapter.
- Significant/critical rates: errors / classifiable player moves, times 100.
  Every rate returns its numerator, denominator and per-100 value.
- Phase partitions cover every analyzed player move, including UNCLASSIFIED.
  Color/time-control/ECO partitions cover all selected games and their available
  moves. Segment means are descriptive; overall means pool individual losses.
  Segment game counts can overlap across phases and must not be added as if phases
  partitioned games. Color and time-class compositions accompany each segment.
- Opening: exact ECO grouping, explicit UNKNOWN, preserved imported opening names.
  Family is null because no trusted family mapping exists. Early-error metrics
  include only opening player moves. Incidence uses fully featured analyzed games
  with classifiable opening moves; median first error uses only games with errors,
  taking the actual fullmove number, including custom starts. Endgame mistakes do
  not count as opening mistakes merely because their game belongs to an ECO group.

## Contexts, conversion and castling

Contexts can overlap, but never contribute multiple times to overall error counts.
Each returns all opportunities, classifiable denominators, unknown count, a
complement population with known-false context, and phase/time-rule/color strata.
No statement of causation is generated.

- Check response means king in check immediately before the player's move.
- Capture response means the immediately preceding opponent move was a capture;
  a first move with no preceding opponent move has unknown context.
- Advantage crossing means current pre-move player CP `>=150`, previous player
  decision CP `<150`. The first point and points after missing/mate data are unknown.
  Consecutive winning moves do not create repeated crossings.
- Time pressure means known pre-move clock `<=10%` of known initial allocation.
  It uses Phase 11's conservative own-clock reconstruction, including increment
  handling, rather than the current move's post-move annotation. The absolute
  30-second Phase 11 flag is deliberately not reused. Unknown/custom clock rules
  and absent annotations remain unknown.
- Sustained advantage/disadvantage requires two consecutive player decision
  points at `>=150` / `<=-150` CP. Each qualifying game contributes once to each
  category. Win/draw/loss outcomes and non-loss recovery have explicit game
  denominators and IDs. All games with missing/mate CP evidence in the full
  evaluated path are excluded with IDs, not counted as no opportunity.
- Collapse is a separate observation: after the second qualifying winning
  decision point, any later evaluated position below +50 CP, including a final
  opponent move. A game can collapse and still be won.
- Castling frequency uses fully featured games with known starting history.
  By-move-15 uses only games that reached the tracked player's 15th decision,
  excluding shorter games and unknown custom-start castling histories. Exclusions
  are returned. Low castling frequency is never automatically ranked as weakness.

## Support and ranking

These are preliminary product heuristics, not statistical significance:

| Population | Minimum |
| --- | --- |
| Overall outcomes | 10 completed games |
| Exact opening | 10 fully usable games |
| Phase | 50 classifiable moves and 5 distinct games |
| Context | 30 classifiable opportunities and 10 distinct games |
| Conversion / recovery | 10 qualifying games |
| Broad time-pressure observations | 80% usable clock coverage plus context support |

A single long game cannot establish a recurring weakness. Zero usable support is
UNAVAILABLE; nonzero support below policy is INSUFFICIENT. Descriptive numbers are
retained. Unknown openings/phases cannot be ranked. Opening ranking additionally
requires 50 classifiable opening moves across ten games. Low opening score alone
is not ranked as evidence of opening knowledge.

Rankings are separate lists for phase, opening and context because their
opportunities differ. Only COMPLETE reports and sufficient candidates enter them.
V1 score is:

`100 * (significant + 2 * critical) / classifiable opportunities * min(1, opportunities/50, distinct games/10)`

This equals the proposed frequency × severity × support formula. Recency stays
1.0; no trend comparison is implemented or invented without comparable earlier
periods. No intermediate rounding occurs. Sort by descending score then candidate
key. Every ranked error carries a real `(game_id, ply)` reference checked against
the report's analyzed move references. Counts, ratios and partitions validate
before serialization. These are descriptive coaching priorities, not causal or
unqualified statistical conclusions.

## Operation

```sh
uv run chess-coach analytics-health --player-id 1 --profile PROFILE_HASH --window last_100
uv run chess-coach analytics-health --player-id 1 --profile PROFILE_HASH \
  --window date_range --start 2026-11-01T00:00:00Z --end 2026-11-08T00:00:00Z
```

The CLI returns the complete structured report including health, and exits 1 on
DATA_ERROR. It requires an existing migrated database. Complete feature snapshots
can be prepared separately with `extract-features`; report generation itself
never generates features, runs analysis, changes statuses or contacts Ollama.
Structured timing logs separate data retrieval, evidence validation, aggregation,
ranking and total time. Logs contain IDs and counts, not raw PGNs or full prompts.
See [troubleshooting](analytics-troubleshooting.md) and the
[validation record](PHASE12_VALIDATION.md).

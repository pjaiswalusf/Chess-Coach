# Deterministic move features — V1

Features consume completed-game PGNs and existing engine evidence. They never
launch Stockfish, contact Chess.com, or call Ollama. The public computation is
`extract_game_features(game_id, parsed_game, analyses)` in `analytics/features.py`.
Inputs are the existing trusted `ParsedGame` and optional `FeatureAnalysis`
records. One validated `MoveFeatures` is returned for every accepted ply.

## Run and recover

Apply the additive migration, then choose an explicit existing analysis profile:

```sh
uv run alembic upgrade head
uv run chess-coach extract-features --username YOUR_USERNAME --profile PROFILE_HASH
```

The profile hash is available from the existing analysis-run API/records. Use
`--profile board-only` to extract exact board and clock facts without engine
analysis. This is explicit, rather than silently selecting one of several budgets.
Only current parser/library READY games are candidates. PGN completion is checked
again; Chess.com rows additionally require terminal source evidence and consistent
players/results. An unsupported variant or incomplete/illegal game is rejected.

The command prints a JSON run summary and exits 1 if any game fails. Rerun the
same command after correcting the source and revalidating/reanalyzing it as
appropriate. Completed identical snapshots are skipped; interrupted games have no
partial committed feature set. One invalid game does not stop valid later games.
Unexpected programming errors are logged and re-raised. Structured events use the
repository's existing standard-library logger with run/game/version and optional
ply fields; no new logging dependency is introduced.

## Facts, heuristics, and unknown values

- Exact board facts: played capture/check/castling/immediate mate, captured piece,
  material totals and deltas, observed immediate recapture, central king file.
- Engine-derived observations: legal best-move capture/check/immediate mate and
  evaluation context. Search estimates are not proven game outcomes. Best-move
  mate is established by making that legal move on a copy and testing checkmate.
- Heuristics: phase, early queen move, repeated original minor movement, advantage
  bands, time pressure and fast moves. They are observations, not mistake labels.
- Optional/unknown evidence is `None`, never manufactured zero or false. Missing
  best moves or individual analysis rows still permit exact board facts. Supplied
  contradictory FEN/UCI/scores or illegal best moves fail the game. Adjacent known
  scores must agree; terminal scores must match the actual board outcome.

Material uses P=1, N/B=3, R=5, Q=9; kings contribute zero. White and Black totals
are stored before/after. Balance and delta always use the **mover's** perspective,
including promotions and en passant. A captured piece is an observed loss, not a
prediction that an attacked piece will be lost later.

Engine advantage fields always use the **tracked player's** perspective, on both
players' moves. White-oriented CP scores are multiplied by +1 for tracked White,
−1 for tracked Black. At +150 CP the band is large advantage; at −150 large
disadvantage; between them approximately equal. Advantage lost means before ≥150
and after ≤50, on either side's move. Consumers can filter `mover == tracked_player`
for the player's decisions. Opportunity created additionally requires an opponent
move crossing from below +150 to ≥+150. Preserved advantage requires the tracked
player's move with both scores ≥150. Mate scores are retained in source evidence;
they produce unknown CP-dependent features and are counted separately from absent
evaluations. No mate-to-CP conversion is introduced.

A recapture means adjacent opposing captures on the same destination square.
The exchange advantage field refers to the tracked player's evaluation **before
the preceding capture**, not after it. This conservative observation does not label
an exchange as good/bad or discover longer tactical sequences.

## Phase and development semantics

Phase refers to the position **before** the move. Total combined non-pawn material
≤14 is endgame. Otherwise a full-history standard game is opening through move 10,
then middlegame. Phase cannot move backward; promotion does not undo endgame.
The stored reason and material count explain the classification. Custom FEN games
with unknown prior history are unclassified at higher material, but can be labeled
endgame by the material rule. This preserves exact facts without inventing an opening.

Development fields describe the mover **after** the move. Actual castling is tracked
by legal castling events; side and first move number persist on later mover records.
A king walking to a castling square does not count as castling. With unknown prior
history, `has_castled` stays unknown until castling is observed. Original knights
and bishops have temporary identities, move counts and locations, removed on capture.
Repeated movement means that same original piece has moved before and this move is
in the opening phase. Starting-square counts include original pieces that returned
home; they are not a definitive undeveloped-piece count. Original identity fields
are unknown for custom starts. Queen early means a queen moves on fullmove ≤10;
it does not imply an error. Central king means file d/e, not an unsafe king.

## Time semantics

The existing parser reads `%clk` and `%emt`. Valid explicit elapsed annotations
win; otherwise only supported simple base/increment controls permit deriving
`previous own clock + increment - current own clock`. No opponent clocks are
subtracted. Missing own clocks break that player's chain; negative/nonfinite values
are unknown, with diagnostics for detected inconsistency. The initial base clock
is usable only for full-history starts with an initial own clock observation.
A game with no clock annotations has unknown pressure, including its first moves.
Custom setups do not invent a previous clock. Explicit elapsed may remain known
even when a special time control prevents clock-derived elapsed.

`time_remaining_seconds` is after the move. Pressure uses the **before** clock
≤max(30 seconds, 10% of base), only with known simple-control semantics. Fast means
elapsed ≤3 seconds for controls with estimated duration `base + 40*increment`
from 180 inclusive to 3600 exclusive seconds (V1 blitz/rapid policy). Other controls
have unknown fast classification. Critical-on-fast requires known upstream critical
severity and known fast classification. Phase 10 currently leaves severity absent,
so the extractor does not fabricate it.

## Snapshot identity and transactions

One additive `move_features` table contains indexed/queryable facts and the full
validated JSON. Unique identity is `(game_id, ply, feature_version, input_hash)`.
The input hash includes source/provenance/player metadata, parser/library versions,
explicit analysis profile, complete supplied move evidence including severity,
feature and phase versions, and the fixed threshold configuration. This extends
the playbook's suggested key because Phase 10 retains multiple engine profiles.

Changed inputs or algorithm versions create separate immutable historical snapshots;
V1 is never relabeled as V2. Policy constants are centralized in `feature_config.py`;
semantic changes require a feature-version bump. The extractor intentionally has no
per-call policy override. Repository `get(snapshot)` reads one explicit snapshot;
consumers must not mix snapshots or aggregate all historical rows as distinct moves.

All game rows commit in one SQLite transaction. A write reservation serializes
finalizers; source/evidence identity is rechecked inside it. Count, contiguous ply
sequence, game/version, payload schema and stored content hashes are checked.
A damaged/incomplete matching set is rebuilt transactionally; rollback preserves
any prior set. Engine rows and raw source are never updated by extraction. Zero-ply
completed declarations have an empty feature set and are safely skipped.

Counters use processed plies as the denominator: missing clock means absent after
clock, missing evaluation means neither CP nor mate before the move. Mate CP-context
unavailability has its own count. Run reasons distinguish FEN/analysis alignment,
illegal recommendations, score conflicts, schema errors and persistence failures.
See [validation](PHASE11_VALIDATION.md) and [benchmark](benchmarks/phase11.json).

# Coaching evaluation

The existing development corpus is
[`move_explanations_v1.jsonl`](../evaluation/datasets/move_explanations_v1.jsonl).
It contains 50 fixed engine snapshots, covering opening, middlegame, endgame,
mate and insufficient-evidence review candidates. Validation replays the
history, played move and supplied variations, and checks that the scores,
mover and centipawn loss agree. There are 50 distinct case IDs and 50 distinct
position-and-played-move pairs across 44 distinct FENs. Several mate
alternatives intentionally share positions.

The move evaluator's canonical dataset fingerprint is
`c3b94dffc4a150483a3dd66d7e977f40305a55f1c453b41f06b00df5366c68fa`.
The motif runner serializes the same source into its own evidence records and
reports `c4e887d5459bc1e6cca2302b7aec3abaf91387a9d40e6c8789ba201201ce38d4`.
These snapshots were used in earlier prompt work and are development data.
The release holdout requires adjudicated human labels, partitioned by game,
with sufficient support per class. Follow the [annotation guidelines](evaluation/annotation-guidelines.md)
and [release criteria](ACCEPTANCE.md).

## Metrics

| Metric | Population and calculation |
| --- | --- |
| First-pass schema validity | Responses parsed by the declared schema divided by all attempted generations. |
| Final schema validity | Cases with a valid result after allowed retries divided by attempted cases. The move evaluation uses first responses only. |
| Automated evidence acceptance | First responses accepted by schema and implemented evidence checks divided by attempted cases. |
| Human grounding | Outputs whose factual assertions are all supported divided by all human-audited outputs. The assertion-level failure rate counts contradictory or unsupported assertions divided by all human-audited factual assertions. |
| All-position motif accuracy | Correct theme predictions divided by all labeled holdout positions. Failures and abstentions count as incorrect. |
| Macro F1 | Mean of per-class F1 across the declared evaluated classes. Report class support, confusion and eligible coverage alongside it. |
| Clarity and actionability | Human scores on the [review rubric](../evaluation/rubrics/coaching_quality.md), with the number reviewed. |
| Latency | Wall time per attempted generation. Report median and nearest-rank p95 with the sample size and retention policy. |

The deterministic baseline renders the played move, engine-preferred move
and score fields directly from the same inputs. It supplies a fixed review
prompt. This records the evidence a prose response should preserve. Human
review would compare tactical correctness, clarity and usefulness on identical
inputs. Automated validators check specific contradictions and references.
Subtle chess or causal claims still require review.

## Reproduce

Use the [recorded machine](benchmarks/environment.md), the local installed model
and a fresh output directory below the ignored benchmark root.

```sh
uv run --locked python -m chess_coach.evaluation.move_coaching --validate-only
uv run --locked python -m chess_coach.evaluation.motifs --validate-only
uv run --locked python -m chess_coach.evaluation.move_coaching \
  --template-baseline --limit 12 --output data/benchmarks/phase23/template.json
uv run --locked python -m chess_coach.evaluation.move_coaching \
  --limit 12 --output data/benchmarks/phase23/model-alone.json
uv run --locked python -m chess_coach.evaluation.motifs \
  --output data/benchmarks/phase23/motifs-dev.json
```

The limited move run uses the first 12 case IDs in order. It covers eight
opening cases and four insufficient-evidence review candidates. The motif run
uses all 50 development cases. The evaluation files include the model digest,
schema and prompt versions, sampling settings and per-case outcomes. The
[prior motif smoke test](evaluation/model-selection.md) exercised seven
verified events, all missed mates.

## Phase 23 development results

The isolated Qwen trial used the quantized tag `qwen3.5:4b-q4_K_M`, digest
`d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04`,
prompt `coaching-v1.1` and schema `coaching-output-v1`. Generation used
temperature 0, context 4,096, output limit 800, thinking disabled, keep-alive
0 and a 90-second timeout.

| Development check | Deterministic template | Qwen move explanation |
| --- | --- | --- |
| Cases processed | 12 / 12 | 12 / 12 |
| First-pass coaching schema | Not applicable | 12 / 12 |
| Automated evidence acceptance | Moves and scores copied from 12 validated inputs | 1 / 12 |
| Rejected by text guard | Not applicable | 11 / 12 |
| Human-audited outputs | 0 | 0 |
| Generation p50 and p95 | Not applicable | 3.15 s and 4.10 s across 12 calls |

All 11 rejections were `UNSUPPORTED_CLAIM` from the prohibited-text guard.
For example, case 001 repeated square coordinates in prose, which the guard
rejects because move details come from the deterministic evidence panel. This
illustrates a gap between schema validity and usability under the application
contract. The guard's rejection category does not establish how many claims
were semantically wrong. The accepted case also awaits human review.

The real motif development run detected seven missed-mate events in the
50 cases. The other 43 produced no verified event and skipped inference. All
seven model responses passed the motif schema and evidence checks and suggested
`MISSED_TACTIC`. This was a single event type with zero human labels, so the
result measures the mechanics of the gate rather than theme accuracy.

## Release status

The development corpus and automatic checks support reproducibility of the
mechanical evidence boundary. There are zero independently adjudicated
holdout labels in the release evaluation. Human grounding, motif accuracy,
macro F1 and training advice usefulness remain unmeasured. Model motif
suggestions remain experimental.

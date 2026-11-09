# Phase 15 model decision

**Use the installed `qwen3.5:4b-q4_K_M` for Phase 15 development.**
The local inventory contained that one model. No model was downloaded, no 2B
comparison was run, and no inference was sent to a cloud service. This is an
operational choice; the smoke run cannot rank models or establish quality.

The [saved run](../../evaluation/results/phase15-4b-smoke.json) and
[per-position outcomes](../../evaluation/results/phase15-4b-smoke.predictions.jsonl)
record the full model digest, dataset hash, versioned detector, schema and prompt,
generation settings, and request timings. The experiment reused the fixed Phase
14 engine snapshots as **unlabeled development fixtures**:

| Outcome | Observed |
| --- | ---: |
| Valid input snapshots | 50 |
| No verified event; model skipped | 43 |
| First responses passing schema and evidence checks | 7 / 7 |
| Suggested themes | 7, all `MISSED_TACTIC` |
| Human-reviewed examples | 0 |

All seven model calls were for `MATE_MISSED` events. This exercises structured
inference, evidence references and abstention before inference. It does not
measure accuracy, macro F1, eligible coverage, usefulness, or memory behavior.

Reproduce or prepare candidates using the already configured local Ollama model:

```sh
uv run python -m chess_coach.evaluation.motifs --validate-only
uv run python -m chess_coach.evaluation.motifs --output evaluation/results/phase15-4b-smoke.json
uv run python -m chess_coach.evaluation.motifs --validate-only --export-candidates /tmp/motif-candidates.jsonl
```

The export has no assigned themes. For a real benchmark, export a candidate pool
from existing compatible engine analysis:

```sh
uv run python -m chess_coach.evaluation.motifs --from-local-db --limit 200 --export-candidates /tmp/motif-archive.jsonl
```

The sampler prioritizes mate transitions and large losses within each game, then
rotates through games and available color/time class groups. It retains quiet
positions as possible controls. This is a review pool, not a random sample of
gameplay; curate phase and motif coverage with the
[annotation guidelines](annotation-guidelines.md).
Set each row's `human_label`, `reviewer`, and `split` after independent review
and adjudication. Use `AMBIGUOUS` when evidence is insufficient; keep it distinct
from `OTHER`. A conversion case must include the prior same-player evidence as
`previous_move`. The runner rejects duplicates, game/position leakage and
unreviewed held-out rows. Freeze the manifest, develop on `dev`, and run the
selected configuration once against `heldout`:

```sh
uv run python -m chess_coach.evaluation.motifs --dataset path/to/reviewed.jsonl --split heldout --output evaluation/results/phase15-heldout.json
```

**Release status: held.** There is no human-reviewed multi-class benchmark yet.
The API can return deterministic events and queue experimental jobs, but
keeps suggestions out of normal coaching. The initial classifier only accepts
themes anchored to the four implemented detectors. Richer evidence for the
other taxonomy classes, and a reviewed benchmark meeting the
[Phase 15 publication criteria](phase15-acceptance.md), are still needed.

Independent review verified the bounded experimental pipeline and event
persistence, including an Ollama outage with no queued job. Review reproduced
score/variation contradictions that are now rejected and confirmed that they
cannot become verified events. Human quality remains unverified.

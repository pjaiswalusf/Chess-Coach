# Phase 14 implementation and evaluation — 2026-11-09

Release decision: **NOT RELEASE-READY**. The functional local coaching layer is
implemented, but human quality acceptance is unverified. Automated schema and
claim checks do not establish chess correctness of arbitrary prose. Independent
review found no remaining implementation blocker after its reported fixes; its
release recommendation remains FAIL pending quality evidence. See
[review record](phase14_review.md).

## Implemented behavior

- Immutable evidence from compatible completed-game engine analysis; full-history
  replay, mover POV loss, explicit mate winner, before/after variation alignment.
- Bounded Pydantic structured generation through the installed Ollama Python SDK.
  No streaming, model downloading, arbitrary inference hosts, or cloud fallback.
- Schema, numerical/notation/markup checks, selected board contradictions and
  conservative rejection of unverified material/motif claims. This is a limited
  veto, not a general natural-language factuality proof.
- Independent SQLite coaching jobs and migration `c14a001`, version/digest-aware
  cache, duplicate admission serialization, invalid-cache repair and restart
  recovery. Engine records never share coaching write transactions.
- Evidence rechecked before and after generation. Only validated output persists.
- GET/POST move and historical endpoints, durable job status, readiness without
  inference, and minimal Svelte loading/result/abstention/failure/retry controls.
- Historical priorities reuse Phase 12 ranking, support thresholds and linked
  move references; insufficient histories return without a model call.
- The coaching worker uses the existing kernel-lock/SQLite queue pattern and
  shares the analysis guard. Stop one worker before starting the other.

GET retrieves the stored model snapshot without contacting Ollama; POST probes
the current digest before generating, and can return an existing valid result
when Ollama is offline. This preserves offline access while detecting a repointed
model tag on new requests. UI prose says “Passed automated checks,” not that all
chess assertions are verified.

## Dataset and exact commands

`evaluation/datasets/move_explanations_v1.jsonl` contains 50 fixed legal engine
snapshots: 8 opening, 16 middlegame, 10 endgame, 8 mate-related, and 8 ambiguity
review candidates. Colors are balanced 25/25. The ambiguity category is named
`insufficient` in the development manifest; it does not prove abstention is
required. All expected statuses and human labels are null pending actual review.

These are synthetic development positions, including sound moves and small
engine-estimate changes, not 50 human-verified mistakes. They exercise contracts
and failure handling but do not satisfy the representative reviewed benchmark.
No human quality scores or assertion labels have been invented. The rubric is
in `evaluation/rubrics/coaching_quality.md`. They also do not satisfy the future
200-case held-out targets in `docs/ACCEPTANCE.md`.

Dataset hash:
`c3b94dffc4a150483a3dd66d7e977f40305a55f1c453b41f06b00df5366c68fa`.
Each row records the actual engine configuration and engine/evidence versions.

```sh
uv run python -m chess_coach.evaluation.move_coaching --validate-only
uv run python -m chess_coach.evaluation.move_coaching --output evaluation/results/phase14-final.json
CHESS_COACH_REAL_OLLAMA=1 uv run pytest tests/api/test_coaching_routes.py -k real_ollama -q
```

Normal tests do not invoke Ollama. The real vertical test exercises stored
analysis → evidence → actual Qwen → validation → SQLite → API retrieval;
handled model rejection is a permitted failure outcome, not a quality PASS.

## Local model and first baseline

Machine: Apple M5 MacBook Air, 16 GB unified memory. Ollama client version:
0.40.15. Model: `qwen3.5:4b-q4_K_M`, digest
`d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04`.
Installed inventory reported local GGUF, Q4_K_M, about 3.3 GB on disk.

Default thinking with an 800-token output cap returned no usable answer in 2/2
requests (24.073 s and 20.982 s). These were handled `INVALID_MODEL_OUTPUT`
failures, not parsing successes. Disabling thinking produced schema-valid JSON
in 2/2 initial smoke requests (3.174 s and 2.879 s); one was rejected by claim
checks. These tiny samples do not establish a parsing or quality rate.

The first complete run (`evaluation/results/phase14-baseline.json`, prompt
`coaching-v1`, keep_alive `1m`, temperature 0, context 4096, output cap 800,
timeout 90 seconds) measured:

| Outcome | Count / denominator |
| --- | --- |
| First-response valid schema | 50/50 |
| Explicit claim-check rejection | 32/50 |
| Accepted abstention | 18/50 |
| Accepted explanation | 0/50 |
| Human-reviewed outputs | 0/50 |

This baseline failed coaching utility. It motivated one bounded development
prompt revision allowing narrowly supported explanations of engine preference
without invented tactical causes. Full move history remains in persisted replay
and cache identity but is excluded from the compact model prompt.

After explicitly unloading the model, the baseline's first request took 3.242 s.
The 49 subsequent requests had mean 4.095 s, median 3.209 s and range
2.046–8.173 s. Individual timings and model token/load metrics are retained.
No stable p95 or optimal-settings claim is made from this mixed workload run.

## Memory observations and limitations

`ollama stop` followed by `ollama ps` confirmed unloading. During the `1m` run,
`ollama ps` reported about 3.2 GB, GPU execution, and context 4096. System swap
used increased from about 3.0 GB in the pre-run observation to about 10.1 GB in
a later observation; system-wide free percentage went from 58% to 25%.
Browser tests, builds, and other development processes overlapped this run.
These observations cannot isolate Qwen's contribution or establish absence of
memory pressure. They do not satisfy a no-swapping or unobtrusive-use claim.
The final configuration uses keep_alive `0` to release model residency after
requests; `1m` remains configurable for a separately measured tradeoff.

Ollama's structured format, timing fields and keep_alive behavior were checked
against its [official API definition](https://github.com/ollama/ollama/blob/main/docs/openapi.yaml).

## Remaining release gates

- Curate representative verified mistakes and genuinely ambiguous/insufficient
  cases; apply human assertion labels, rubric scores and independent adjudication.
- Demonstrate useful explanations and the provisional quality threshold on that
  reviewed dataset. Zero factual assertions/only abstentions is unevaluable.
- Run an isolated cold/warm/memory benchmark without concurrent browser/build
  load and confirm acceptable pressure/responsiveness. Current measurements do
  not support that claim.
- Obtain the independent reviewer's release PASS after the quality evidence.
- Actual server-kill/restart and memory-pressure UI observations were not
  performed. Deterministic tests cover transport failures, interrupted jobs,
  retries, cache access offline and database write failure; do not conflate
  simulated failures with destructive real-service fault injection.

Phase 15 motif classification has not been started.

## Automated verification

Final required backend checks passed: `uv run ruff check .`, `uv run mypy src`
(90 source files), and `uv run pytest` (598 passed, 1 opt-in real-model test
skipped, 2 real-engine tests deselected). The designated real-Ollama vertical test
was separately enabled and passed (1 passed, 14 deselected) on the then-current
prompt. Rejections/abstentions are valid reliability outcomes for that smoke test;
it does not certify explanation utility.

Frontend completion checks passed: `pnpm lint`, `pnpm check` (zero errors and
warnings), `pnpm test` (6 passed), `pnpm build`, and `pnpm test:e2e` (7 passed,
1 pre-existing real-analysis workflow skipped). Browser tests include request,
poll, cached reopening, unavailable, failed, abstention and plain-text rendering.

Known non-failing warnings: existing httpx/Starlette and python-chess deprecations,
Vitest's SvelteKit transform hook advisory, and adapter-auto's lack of a deployment
target. Tests do not install browsers or dependencies.

The schema was checked both by migrations from an empty SQLite database and
Alembic/model comparison; upgrade/downgrade and prior-data preservation checks
passed with the new coaching table. Structured failures and independent writes
are tested; successful deterministic analysis survives invalid model output,
transport errors and coaching database-write failure.


## Final configuration evaluation

`evaluation/results/phase14-final.json` records all 50 requests on prompt
`coaching-v1.1`, compact model input, thinking disabled and keep_alive `0`.
All 50 first responses matched the output schema. Outcomes were
46/50 rejected claims, 4/50 accepted abstentions, and
0/50 accepted explanations. These are real observed counts, not release
quality scores. Human-reviewed outputs remain 0/50.

The bounded prompt revision did not establish useful coaching on this development
corpus. **Coaching quality remains a failed/unverified release gate.** Neither
prompt should be described as meeting the project's quality target. The raw
responses are included only in the explicit final evaluation artifact for
assertion-level review; normal application logs do not record prompts or prose.

With immediate unloading, request times were mean 4.460 s,
median 4.102 s, range 2.195–7.462 s, n=50.
The first request was 3.002 s. This run includes repeated model loading,
so these are not warm-residency latency estimates. The separate saved `1m`
baseline supplies the residency comparison. Development/browser work overlapped
parts of the experiment; no isolated hardware acceptance claim is made.

After the final `0` run, `ollama ps` listed no resident model. A post-run system
observation reported swap used about 6.2 GB and system-wide free percentage 84%.
These are snapshots, not a peak-memory profile. The substantial change from the
prior loaded observation also reflects concurrent processes ending; no causal
attribution to keep_alive alone is claimed.

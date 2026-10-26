# Acceptance criteria

These criteria apply when the corresponding feature is implemented. The current
scaffold does not establish pipeline or model quality. Shared implementation and
completion rules live in [AGENTS.md](../AGENTS.md).

## Deterministic feature gates

Use versioned fixtures with expected outcomes and assert all cases pass:

| Feature | Required evidence |
| --- | --- |
| Import | Import the same completed-game fixture twice; the second run creates zero games. Incremental sync creates exactly the unseen IDs. |
| Completion validation | Accept terminal results including resignation, timeout, and agreed draw. Reject unfinished/missing/conflicting results, source games without completion evidence, malformed PGN, illegal moves, invalid starting positions, and unsupported variants. |
| Chess correctness | Replay every accepted fixture legally. Validate each returned best move/PV against its board. Check loss orientation for both White and Black and explicit mate semantics. |
| Cache | An identical rerun launches zero additional engine analyses. Changed engine/configuration/budget/version/draw policy or relevant history causes a miss. Include same-FEN fixtures with different repetition histories and unknown pre-FEN history. |
| Analytics | Exact expected numerators, denominators, sample sizes, and rates for synthetic data. Test below, at, and above each documented suppression threshold. Trace every reported statistical claim to evidence. |
| Reliability | Interrupt and resume a run without losing completed results. Inject a game failure and verify other games persist. Ollama failure preserves successful engine results and permits coaching retry. |
| LLM integration | Invalid schema, missing evidence references, and changed immutable facts are rejected or fall back to deterministic presentation. Numeric facts render from trusted fields. |

## Future model-quality targets

These are research targets, not current release gates. Before using them as gates,
check in a versioned evaluation manifest, fixtures, scoring code, and results.
Record dataset hash, model identifier/digest, prompt version, generation settings,
engine/evidence versions, and the exact evaluation command. Do not report a target
as achieved without an evaluation run. Do not tune prompts on the held-out set.

### Structured response parsing: at least 99%

Use at least 200 held-out evidence packages spanning ordinary, mate, low-sample,
and insufficient-evidence cases. Score the first response for each case with the
production schema: valid responses / all attempted responses. Empty responses,
timeouts, and generation errors count as failures; retries are reported separately.

### Factual contradiction rate: less than 2%

For the same corpus, label each factual assertion against its evidence package.
A contradiction is an assertion conflicting with evidence; an unsupported factual
assertion is also counted as a failure for this metric. Rate = failing assertions /
all factual assertions. Independently review annotations and adjudicate differences;
retain assertion-level labels and supporting evidence. Report output failure rate,
schema failures, unsupported claims, and refusal/empty-response rate separately.
Zero factual assertions is unevaluable, not a passing score. Any known output
changing an immutable fact must still fail integration validation regardless of
aggregate model quality.

### Coarse motif classification accuracy: at least 80%

Before evaluation, define a single-label taxonomy including ambiguous/none cases.
Use at least 200 held-out positions with at least 20 examples per supported class,
human labels, written labeling guidance, and adjudicated disagreements. Score
correct labels / all positions; invalid labels and abstentions count as incorrect.
Report per-class precision/recall and a confusion matrix as well as accuracy.
If multi-label classification is later needed, define its metric before evaluation.

## Coverage diagnostics

Once backend features exist, measure line coverage with:

```sh
uv run pytest --cov=chess_coach --cov-report=term-missing --cov-report=json
```

Targets are at least 90% for deterministic chess/analytics modules and at least
80% overall backend coverage. Include production modules even when unimported;
exclude tests, virtual environments, and generated files. List the exact modules
in the core subset in the coverage report when they exist. Compute each rate as
covered executable lines / total executable lines in that subset. No production
logic or no tests means not yet measured. These are diagnostics, not substitutes
for the behavioral gates above; do not add trivial tests to inflate coverage.

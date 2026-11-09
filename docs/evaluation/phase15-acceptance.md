# Phase 15 acceptance

Phase 15 uses compatible completed-game Stockfish evidence to detect observable
events and optionally suggest a coarse coaching theme. A theme is an
interpretation, never a confirmed event or an inference about the player's
thoughts, attention, time use, or knowledge. It does not change engine scores,
moves, game results, or historical statistics.

Use only the installed Qwen3.5 4B configuration from
[the baseline](baseline.md). No second model, download, or cloud fallback is
part of this phase. Compare prompt configurations on development data only;
freeze the chosen configuration before measuring the held-out split.

| Gate | Target | Type |
| --- | --- | --- |
| Input integrity | Reject 100% of invalid chess records before inference | Hard |
| Output integrity | 100% of accepted persisted predictions pass schema and evidence validation | Hard |
| Grounding | Zero known contradictions in published suggestions | Hard |
| Reliability | Model failure never changes engine analysis; compatible results are reused | Hard |
| Reproducibility | Record dataset hash, split, model digest, versions, and generation settings | Hard |
| Macro F1 | At least 0.65 | Provisional development goal |
| Selective accuracy | At least 0.75 of non-abstained eligible predictions correct | Provisional development goal |
| Coverage | At least 60% of eligible cases get an accepted theme | Provisional development goal |
| Usefulness | At least 80% of human-reviewed explanations rate 4/5 or better | Provisional development goal |

The project-wide [held-out release gate](../ACCEPTANCE.md) still applies: at
least 200 held-out positions, 20 per supported class, adjudicated human labels,
and at least 80% all-position accuracy. Count failures and abstentions as
incorrect for that accuracy. Report support and confusion by class, eligible
coverage, abstentions, failures, and separate human grounding and usefulness
scores. A development pilot does not satisfy this release gate.

A verified event can be returned independently of Ollama. Do not expose model
themes in normal coaching until the hard gates and held-out quality gate have
been met for the shipped configuration. Do not publish unsupported labels or
unreviewed model prose. Report insufficient data as unverified.

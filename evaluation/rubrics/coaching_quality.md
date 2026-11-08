# Coaching quality v1

Development corpus: 50 fixed positions, not the held-out 200-case corpus required
for future quality targets in docs/ACCEPTANCE.md. Do not tune and report held-out
performance on these same positions. Engine snapshots are shallow local estimates.

Review every accepted output against its fixed evidence. Label each factual
assertion supported, contradicted, or unsupported and cite the relevant evidence
field or PV. Unsupported assertions count as factual failures. Automated numeric
and notation checks cannot verify tactical prose. An abstention has no explanation
quality score; report abstention rate separately.

Human reviewers record their name, timestamp, assertion labels, and four scores:

| Dimension | 1 | 3 | 5 |
| --- | --- | --- | --- |
| Correctness | Incorrect | Mostly supported | Fully supported |
| Clarity | Confusing | Understandable | Clear and concise |
| Actionability | Generic | Some usable guidance | Specific reusable lesson |
| Player appropriateness | Wrong level | Reasonable | Well matched to available rating |

Intermediate scores 2 and 4 represent the intervening quality. Player rating is
unknown in this synthetic development corpus; flag appropriateness as limited.
Independently review and adjudicate assertion labels before quality release.

Provisional phase targets: all attempts yield valid schema or explicit failure;
no known contradictory, illegal-move, or invented-statistic output is accepted;
at least 80% of scored explanations average at least 4. Report denominators,
first-attempt schema pass rate, retries, abstentions, latency samples and failures.
Zero human reviews means unevaluated, never PASS. Human labels in the dataset and
result files remain null until actual human review is performed.

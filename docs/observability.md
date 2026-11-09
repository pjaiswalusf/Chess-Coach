# Diagnostics and observability

SQLite is authoritative for completed games, operation state, and measurements.
The API liveness endpoint is independent of persistence and optional services.

## Application events

Emit one JSON event per line to stderr. Use UTC ISO 8601 timestamps, lowercase
levels, stable snake_case event and component names, and integer milliseconds
from a monotonic clock for elapsed time. Use string IDs for requests, persisted
runs and internal games. Generate a request UUID locally and scope it to the
request. Workers correlate by persisted run ID independently of HTTP requests.

| Events | Context |
| --- | --- |
| sync_started, sync_finished, sync_failed | Run ID, terminal status, elapsed time, inserted and existing counts, failure code |
| game_inserted, game_existing | Run and internal game IDs when available |
| analysis_started, analysis_finished, analysis_failed, analysis_interrupted | Run ID, game count, terminal status, elapsed time, new engine evaluations, terminal positions and cache totals |
| cache_hit, cache_miss | Run ID, game ID and cache type, at DEBUG |
| llm_generation_started, llm_generation_finished, llm_generation_failed | Coaching job ID, model, attempt count, elapsed time, schema validity and failure code |
| request_failed, database_unavailable, internal_error | Request ID, HTTP status and stable failure code where applicable |

Use existing operation status values and safe uppercase error codes. Preserve
existing API error codes for callers. Optional fields are omitted where
inapplicable. Application logging accepts only named diagnostic fields. Log
internal IDs, counts, model/engine identity and failure categories. Keep
usernames, absolute database paths, PGNs, board history, PVs, prompts, model
output, provider bodies and exception messages out of normal logs. For
unexpected errors, record exception type and code location without local
variables or exception text. Terminal output is ephemeral by default.

## Health contract

Doctor and the System health endpoint share checks. A required failure makes
the application unavailable. Optional failures or skipped optional checks
degrade health. Unknown indicates that a prerequisite prevented verification.
The API returns 503 with the diagnostic report for core failure and 200 for
healthy and degraded results. Doctor exits 0 with core checks passing, 1 for
a required failure (or a warning with --strict), and 2 for unexpected failures.

Checks diagnose without provisioning or repairing data. Use a temporary file
for the directory write check, read-only SQLite for database checks, and keep
deep integrity checks opt-in. In WAL mode SQLite may create coordination
sidecars while opening a read-only connection. Stockfish readiness uses UCI
without analysis. New analysis also requires the separately running worker.
Ollama uses the local model inventory without inference. Network and UCI
probes have bounded budgets and no retries. A successful probe is a snapshot.

## Performance reporting

Report the latest terminal analysis run and terminal coaching requests from
the last seven days. Missing samples and zero denominators return null.
A cache hit rate is hits divided by hits plus misses, multiplied by 100.
Engine throughput is successful persisted Stockfish evaluations divided by
cumulative engine call seconds. Cache reuse and deterministic terminal-board
results do not count as new evaluations. Games per hour divides completed
games by elapsed wall hours between the persisted start and finish. The
monotonic analysis duration measures active processing across attempts.
LLM latency is the cumulative time spent in model requests for a terminal
job, including any retry. Use the median for p50. First-response schema
failures divide jobs with an invalid first response by all measured jobs. The count of
classified first responses is shown separately. Final failure rate divides failed measured
jobs by all measured terminal jobs. Fact validation failures have their own
error category. Historic rows can lack new measurements.

Compare throughput only across comparable configurations and workloads.
A repeatable drop of about 30% from a measured local baseline warrants
investigation. Performance slowdowns do not change functional health.

A lookup miss is counted before the engine call, so a failed search can
increase misses without increasing completed evaluations. Engine time includes
failed calls and retries but excludes UCI restarts and persistence. Older
analysis records used persisted misses and a broader engine timer. Their
active duration is unavailable. After a manual coaching retry, the latest
terminal measurement for the cache key replaces the previous measurement.
An abrupt process exit can leave an incomplete timing sample until recovery.

A failed direct Chess.com identity check emits `sync_preflight_failed` before
a run exists. The event has no persisted run ID. API admission of a new
analysis records `analysis_queued` with both the request and run IDs.

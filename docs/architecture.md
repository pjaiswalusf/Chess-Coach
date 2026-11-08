# Application boundary

API routes perform transport handling only. Business operations are delegated to
application services. Responses use explicit Pydantic schemas. Long-running work
is represented by persistent run IDs. Repositories own SQLite queries and job
admission; analytics owns deterministic aggregates; dedicated local workers own
Chess.com synchronization and Stockfish execution. Read endpoints never launch
these operations. See [the HTTP contract](api-contract.md) for exact behavior,
local safeguards, worker recovery and known performance limits.

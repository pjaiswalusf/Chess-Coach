"""Admission and persisted progress; workers perform the expensive operations."""

from chess_coach.infrastructure.persistence.query_repository import QueryRepository
from chess_coach.infrastructure.persistence.sync_repository import SyncRepository


class JobService:
    def __init__(self, queries: QueryRepository, sync: SyncRepository):
        self.queries, self.sync = queries, sync

    def start_sync(self) -> dict[str, object]:
        run_id = self.sync.enqueue(self.queries.player_id())
        return {"run_id": run_id, "status": "queued"}

    def sync_progress(self, run_id: int) -> dict[str, object]:
        return self.sync.progress(run_id)

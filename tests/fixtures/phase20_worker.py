"""Run the production analysis worker with a fake engine and signal checkpoint."""

import sys
from pathlib import Path

from reliability import FakeEngine

from chess_coach import analysis_worker
from chess_coach.application.analysis import AnalysisProcessor
from chess_coach.config import Settings


class CheckpointEngine(FakeEngine):
    def close(self):
        print("engine closed", flush=True)


def interrupt_after_three(store, engine, settings, stop):
    run = store.runs()[0].id

    def checkpoint(kind, position):
        if kind == "position" and position == 1 and store.get(run).games_completed == 3:
            print("checkpoint", flush=True)
            if not stop.wait(15):
                raise RuntimeError("Worker was not signaled at the checkpoint")

    return AnalysisProcessor(store, engine, settings, stop, checkpoint)


if __name__ == "__main__":
    analysis_worker.StockfishAdapter = lambda _: CheckpointEngine()
    if sys.argv[2] == "pause":
        analysis_worker.AnalysisProcessor = interrupt_after_three
    analysis_worker.run_worker(
        Settings(database_path=Path(sys.argv[1]), _env_file=None), once=True
    )

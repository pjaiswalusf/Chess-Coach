"""Prepare review candidates and evaluate motif suggestions on one installed model."""

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import median, quantiles
from time import perf_counter
from typing import Literal

from pydantic import Field, ValidationError, model_validator
from sklearn.metrics import classification_report, confusion_matrix  # type: ignore[import-untyped]

from chess_coach.analytics.motifs import detect_events
from chess_coach.application.coaching_evidence import EvidenceBuilder
from chess_coach.application.errors import OperationError
from chess_coach.config import Settings
from chess_coach.domain.analysis import fingerprint
from chess_coach.domain.coaching_models import MoveCoachingEvidence
from chess_coach.domain.feature_models import EvidenceModel
from chess_coach.domain.motif_models import (
    DETECTOR_VERSION,
    MOTIF_SCHEMA_VERSION,
    TAXONOMY_VERSION,
    ChessEventType,
    MotifPrediction,
    MotifTheme,
)
from chess_coach.infrastructure.analysis_lock import WorkerAlreadyRunning, worker_guard
from chess_coach.infrastructure.llm.client import OllamaCoach, generation_settings
from chess_coach.infrastructure.llm.health import check_health
from chess_coach.infrastructure.llm.motif_classifier import (
    MOTIF_PROMPT_VERSION,
    motif_input,
    validate_prediction,
)
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
)
from chess_coach.infrastructure.persistence.coaching_repository import (
    CoachingRepository,
)
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.query_repository import QueryRepository
from chess_coach.infrastructure.persistence.session import create_session_factory

PHASE14 = Path("evaluation/datasets/move_explanations_v1.jsonl")
ABSTAIN = "ABSTAIN"
FAILED = "FAILED"
LABELS = [theme.value for theme in MotifTheme]


class Candidate(EvidenceModel):
    sample_id: str = Field(min_length=1)
    split: Literal["dev", "heldout"]
    evidence: MoveCoachingEvidence
    previous_move: MoveCoachingEvidence | None = None
    human_label: MotifTheme | Literal["AMBIGUOUS"] | None = None
    reviewer: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def review_provenance(self) -> Candidate:
        if self.human_label is not None and not (self.reviewer or "").strip():
            raise ValueError("A label requires a named human reviewer")
        previous, move = self.previous_move, self.evidence
        if previous and (
            previous.ply != move.ply - 2
            or previous.game_id != move.game_id
            or previous.source_hash != move.source_hash
            or previous.profile_hash != move.profile_hash
            or previous.engine_version != move.engine_version
            or previous.analysis_version != move.analysis_version
            or previous.draw_policy != move.draw_policy
            or previous.initial_fen != move.initial_fen
            or previous.history_before_start_unknown
            != move.history_before_start_unknown
            or previous.player_color != move.player_color
            or previous.history_uci + (previous.played_move_uci,)
            != move.history_uci[:-1]
        ):
            raise ValueError(
                "Previous score must come from the prior move in the same analysis"
            )
        return self

    @property
    def previous_before_cp_white(self) -> int | None:
        return self.previous_move.before.cp_white if self.previous_move else None


def read_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_dataset(path: Path, *, phase14: bool = False) -> list[Candidate]:
    candidates = [
        Candidate.model_validate(
            {"sample_id": row["case_id"], "split": "dev", "evidence": row["evidence"]}
            if phase14
            else row
        )
        for row in read_rows(path)
    ]
    if not candidates or len({r.sample_id for r in candidates}) != len(candidates):
        raise ValueError("A dataset needs unique sample IDs")
    splits: dict[tuple[str, int | str], str] = {}
    position_splits: dict[tuple[str, ...], str] = {}
    positions = set()
    for row in candidates:
        move = row.evidence
        position = (move.source_hash, move.ply)
        if position in positions:
            raise ValueError("Duplicate source position")
        positions.add(position)
        for game in (("id", move.game_id), ("source", move.source_hash)):
            if splits.setdefault(game, row.split) != row.split:
                raise ValueError("Game leakage across development and held-out splits")
        # Ignore move counters so identical openings cannot leak across splits.
        position_key = tuple(move.fen_before.split()[:4])
        if position_splits.setdefault(position_key, row.split) != row.split:
            raise ValueError("Position leakage across development and held-out splits")
    return candidates


def archive_candidates(store: CoachingRepository, limit: int) -> list[Candidate]:
    builder = EvidenceBuilder(store)
    rows: list[Candidate] = []
    seen = set()
    # Give duplicate positions and stale evidence room without an unbounded scan.
    for game_id, ply in store.evaluation_move_keys(limit * 4):
        try:
            evidence = builder.motif(game_id, ply)
            move = evidence.move
            key = (move.source_hash, ply)
            if key in seen:
                continue
            previous = (
                builder.move(game_id, ply - 2, move.profile_hash)
                if any(
                    e.type == ChessEventType.WINNING_OPPORTUNITY_LOST
                    for e in evidence.events
                )
                else None
            )
        except OperationError as exc:
            if exc.code not in {
                "EVIDENCE_INCOMPLETE",
                "ANALYSIS_NOT_READY",
                "MOVE_NOT_FOUND",
            }:
                raise
            continue
        seen.add(key)
        rows.append(
            Candidate(
                sample_id=f"game-{game_id}-ply-{ply}",
                split="dev",
                evidence=move,
                previous_move=previous,
            )
        )
        if len(rows) == limit:
            break
    return rows


def score(rows: list[Candidate], predictions: dict[str, str]) -> dict[str, object]:
    labeled = [row for row in rows if row.human_label is not None]
    if not labeled:
        return {"reviewed": 0, "quality": "unmeasured; no human labels"}
    truth = [str(row.human_label) for row in labeled]
    guess = [predictions[row.sample_id] for row in labeled]
    eligible = [(t, g) for t, g in zip(truth, guess) if t in LABELS]
    selected = [(t, g) for t, g in eligible if g in LABELS]
    correct = sum(t == g for t, g in selected)
    axes = LABELS + ["AMBIGUOUS", ABSTAIN, FAILED]
    support = Counter(t for t, _ in eligible)
    supported = [label for label in LABELS if support[label]]
    per_class = classification_report(
        truth, guess, labels=LABELS, output_dict=True, zero_division=0
    )
    return {
        "reviewed": len(labeled),
        "eligible": len(eligible),
        "classified_eligible": len(selected),
        "correct": correct,
        "all_position_accuracy": correct / len(labeled),
        "selective_accuracy": correct / len(selected) if selected else None,
        "eligible_coverage": len(selected) / len(eligible) if eligible else None,
        "ambiguous": truth.count("AMBIGUOUS"),
        "ambiguous_abstained": sum(
            t == "AMBIGUOUS" and g == ABSTAIN for t, g in zip(truth, guess)
        ),
        "macro_f1": (
            sum(per_class[label]["f1-score"] for label in supported) / len(supported)
            if supported
            else None
        ),
        "macro_f1_population": supported,
        "per_class": {label: per_class[label] for label in LABELS},
        "confusion_axes": axes,
        "confusion_matrix": confusion_matrix(truth, guess, labels=axes).tolist(),
    }


def evaluate(
    rows: list[Candidate], settings: Settings, output: Path
) -> dict[str, object]:
    health = check_health(settings)
    if health.status != "ready":
        raise SystemExit(health.message)
    model = OllamaCoach(settings)
    predictions: dict[str, str] = {}
    timings: list[int] = []
    stats: Counter[str] = Counter()
    with output.open("w") as results:
        for row in rows:
            evidence = detect_events(row.evidence, row.previous_before_cp_white)
            result: dict[str, object] = {
                "sample_id": row.sample_id,
                "events": [e.model_dump(mode="json") for e in evidence.events],
                "evidence_hash": fingerprint(evidence.model_dump(mode="json")),
                "expected": row.human_label,
                "schema_valid": None,
                "evidence_valid": None,
                "attempted": bool(evidence.events),
                "model": health.model,
                "model_digest": health.model_digest,
                "prompt_version": MOTIF_PROMPT_VERSION,
                "taxonomy_version": TAXONOMY_VERSION,
            }
            if evidence.events:
                started = perf_counter()
                stats["attempted"] += 1
                try:
                    raw = model.generate(motif_input(evidence), MotifPrediction)
                    # Record first response parsing and grounding separately.
                    MotifPrediction.model_validate_json(raw)
                    result["schema_valid"] = True
                    prediction = validate_prediction(raw, evidence)
                    result["evidence_valid"] = True
                    result["prediction"] = prediction.model_dump(mode="json")
                    guess = prediction.theme.value if prediction.theme else ABSTAIN
                except ValidationError:
                    result["schema_valid"] = False
                    result["error"] = "INVALID_MODEL_OUTPUT"
                    guess = FAILED
                except OperationError as exc:
                    if result["schema_valid"] is True:
                        result["evidence_valid"] = False
                    result["error"] = exc.code
                    guess = FAILED
                latency = round((perf_counter() - started) * 1000)
                result.update(latency_ms=latency, metrics=model.metrics)
                timings.append(latency)
            else:
                guess = ABSTAIN
                stats["no_verified_event"] += 1
            stats["schema_valid"] += result["schema_valid"] is True
            stats["evidence_valid"] += result["evidence_valid"] is True
            stats["abstained"] += guess == ABSTAIN
            stats["failed"] += guess == FAILED
            stats["suggested"] += guess in LABELS
            predictions[row.sample_id] = guess
            result["outcome"] = guess
            results.write(json.dumps(result) + "\n")
            results.flush()
    return {
        "count": len(rows),
        "counts": dict(stats),
        "model": health.model,
        "model_digest": health.model_digest,
        "generation": generation_settings(settings),
        "detector_version": DETECTOR_VERSION,
        "schema_version": MOTIF_SCHEMA_VERSION,
        "prompt_version": MOTIF_PROMPT_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "first_request_latency_ms": timings[0] if timings else None,
        "median_latency_ms": median(timings) if timings else None,
        "p95_latency_ms": quantiles(timings, n=100, method="inclusive")[94]
        if len(timings) >= 20
        else None,
        "human_grounding_and_usefulness": "unmeasured; requires separate review",
        "classification": score(rows, predictions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--split", choices=("dev", "heldout"), default="dev")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--export-candidates", type=Path)
    parser.add_argument(
        "--from-local-db",
        action="store_true",
        help="Export unlabeled candidates from compatible completed local analyses",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("evaluation/results/phase15.json")
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.from_local_db:
        if not args.export_candidates or args.dataset:
            parser.error(
                "--from-local-db requires --export-candidates and no --dataset"
            )
        settings = Settings()
        if not settings.database_path.is_file():
            parser.error(
                "No local game database; import and analyze completed games first"
            )
        db = create_database_engine(settings.database_url)
        try:
            sessions = create_session_factory(db)
            store = CoachingRepository(
                QueryRepository(
                    sessions, AnalysisRepository(sessions, settings.database_path)
                )
            )
            rows = archive_candidates(store, args.limit or 200)
        except OperationError as exc:
            parser.exit(1, f"{exc}\n")
        finally:
            db.dispose()
        if not rows:
            parser.exit(
                1, "No compatible completed analysis; analyze imported games first.\n"
            )
        with args.export_candidates.open("x") as stream:
            for row in rows:
                stream.write(row.model_dump_json() + "\n")
        print(f"Exported {len(rows)} unlabeled candidate positions.")
        return
    path = args.dataset or PHASE14
    rows = load_dataset(path, phase14=args.dataset is None)
    summary: dict[str, object] = {
        "dataset_hash": fingerprint([row.model_dump(mode="json") for row in rows]),
        "dataset": str(path),
        "split": args.split,
        "limit": args.limit,
    }
    if args.export_candidates:
        with args.export_candidates.open("x") as stream:
            for row in rows:
                stream.write(row.model_dump_json() + "\n")
    selected = [row for row in rows if row.split == args.split][: args.limit]
    if not selected:
        parser.error("No positions in the requested split")
    if args.validate_only:
        events: Counter[str] = Counter()
        for row in selected:
            evidence = detect_events(row.evidence, row.previous_before_cp_white)
            events.update(e.type.value for e in evidence.events)
        print(
            json.dumps(
                summary | {"valid": len(selected), "events": dict(events)}, indent=2
            )
        )
        return
    if args.split == "heldout" and any(row.human_label is None for row in selected):
        parser.error("The held-out split requires human-reviewed labels")
    settings = Settings()
    try:
        with worker_guard(settings.database_path):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            summary.update(
                evaluate(
                    selected, settings, args.output.with_suffix(".predictions.jsonl")
                )
            )
    except WorkerAlreadyRunning:
        parser.exit(
            1, "Stop the local analysis or coaching worker before evaluation.\n"
        )
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

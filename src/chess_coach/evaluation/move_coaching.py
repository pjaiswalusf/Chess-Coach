"""Reproducible first-response evaluation, with explicit unscored human fields.

uv run python -m chess_coach.evaluation.move_coaching --validate-only
uv run python -m chess_coach.evaluation.move_coaching --output evaluation/results/run.json
"""

import argparse
import json
from collections import Counter
from pathlib import Path
from time import perf_counter

from pydantic import ValidationError

from chess_coach.application.coaching import move_prompt_payload, validated_output
from chess_coach.application.errors import OperationError
from chess_coach.config import Settings
from chess_coach.domain.analysis import fingerprint
from chess_coach.domain.coaching_models import MoveCoachingEvidence, MovePractice
from chess_coach.infrastructure.llm.client import OllamaCoach, generation_settings
from chess_coach.infrastructure.llm.health import check_health
from chess_coach.infrastructure.llm.prompts import (
    MOVE_EXPLANATION_PROMPT_VERSION,
    MOVE_PRACTICE_SCHEMA_VERSION,
)


def template_result(case_id: str, evidence: MoveCoachingEvidence) -> dict:
    return {
        "case_id": case_id,
        "summary": "Compare the played move with the engine preference.",
        "played_move_uci": evidence.played_move_uci,
        "best_move_uci": evidence.best_move_uci,
        "before": evidence.before.model_dump(),
        "after": evidence.after.model_dump(),
        "loss_cp": evidence.loss_cp,
        "human_review": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evaluation/datasets/move_explanations_v1.jsonl"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("evaluation/results/phase14.json")
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--template-baseline", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in args.dataset.read_text().splitlines()
        if line.strip()
    ]
    if len({r["case_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate case ID")
    fixtures = [(r, MoveCoachingEvidence.model_validate(r["evidence"])) for r in rows]
    if args.validate_only:
        print(
            json.dumps(
                {
                    "validated": len(fixtures),
                    "categories": dict(Counter(r["category"] for r, _ in fixtures)),
                    "dataset_hash": fingerprint(rows),
                }
            )
        )
        return
    if args.template_baseline:
        results = [
            template_result(row["case_id"], evidence)
            for row, evidence in fixtures[: args.limit]
        ]
        summary = {
            "dataset_hash": fingerprint(rows),
            "baseline": "engine-facts-v1",
            "count": len(results),
            "human_reviewed": 0,
            "results": results,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2) + "\n")
        return
    settings = Settings()
    health = check_health(settings)
    if health.status != "ready":
        raise SystemExit(health.message)
    model = OllamaCoach(settings)
    results = []
    for row, evidence in fixtures[: args.limit]:
        started = perf_counter()
        result: dict[str, object] = {"case_id": row["case_id"], "human_review": None}
        try:
            raw = model.generate(move_prompt_payload(evidence), MovePractice)
            result["raw_output"] = raw
            # First response only. A handled failure is not a parsing success.
            parsed = MovePractice.model_validate_json(raw)
            result["schema_valid"] = True
            output = validated_output(raw, evidence)
            result.update(
                output=output.model_dump(mode="json"),
                accepted=True,
                expected_status_match=(
                    parsed.status == row["expected_behavior"]["expected_status"]
                )
                if row["expected_behavior"]["expected_status"]
                else None,
            )
        except ValidationError:
            result.update(schema_valid=False, accepted=False, error="SCHEMA_INVALID")
        except OperationError as exc:
            result.update(accepted=False, error=exc.code)
        result.update(
            latency_ms=round((perf_counter() - started) * 1000), metrics=model.metrics
        )
        results.append(result)
        print(
            json.dumps(
                {
                    k: v
                    for k, v in result.items()
                    if k not in {"output", "metrics", "raw_output"}
                }
            ),
            flush=True,
        )
    summary = {
        "dataset_hash": fingerprint(rows),
        "model": settings.ollama_model,
        "model_digest": health.model_digest,
        "prompt_version": MOVE_EXPLANATION_PROMPT_VERSION,
        "schema_version": MOVE_PRACTICE_SCHEMA_VERSION,
        "generation": generation_settings(settings),
        "count": len(results),
        "schema_valid": sum(r.get("schema_valid") is True for r in results),
        "accepted": sum(r["accepted"] is True for r in results),
        "human_reviewed": 0,
        "factuality": "unmeasured; automated checks do not prove semantic correctness",
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()

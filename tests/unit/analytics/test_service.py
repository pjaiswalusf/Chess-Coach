from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from chess_coach.analytics.contracts import (
    AnalyticsReport,
    AnalyticsRequest,
    Diagnostic,
    EvidenceDataset,
)
from chess_coach.analytics.health import check_analytics_health
from chess_coach.analytics.service import AnalyticsService


@dataclass
class Source:
    dataset: EvidenceDataset

    def load(self, request):
        return self.dataset


def build(games=(), **kwargs):
    return AnalyticsService(
        Source(EvidenceDataset(games=games, **kwargs))
    ).build_report(AnalyticsRequest(player_id=1, profile_hash="fixture"))


def planted(factory):
    games = []
    for i in range(20):
        losses = []
        phases = []
        for phase, errors in [("opening", 4), ("middlegame", 6), ("endgame", 24)]:
            losses.extend(150 if i * 10 + j < errors else 0 for j in range(10))
            phases.extend([phase] * 10)
        games.append(factory(i + 1, losses=losses, phases=phases))
    return tuple(games)


def test_planted_weakness_end_to_end(factory):
    games = planted(factory)
    report = build(games)
    assert report.status == "COMPLETE"
    phases = {s.key: s for s in report.phase_metrics}
    assert [
        phases[p].summary.moves.critical.per_100
        for p in ("opening", "middlegame", "endgame")
    ] == [2, 3, 12]
    ranking = report.ranked_weaknesses["phase"]
    assert ranking[0].candidate_key == "phase:endgame"
    assert ranking[0].priority_score == 24
    assert ranking[0].source_moves and len(ranking[0].source_moves) == 24
    assert build(games) == report
    assert AnalyticsReport.model_validate_json(report.model_dump_json()) == report
    source_moves = report.model_dump()
    source_moves["ranked_weaknesses"]["phase"][0]["source_moves"] = [(1, 999)]
    with pytest.raises(ValidationError, match="provenance"):
        AnalyticsReport.model_validate(source_moves)


def test_empty_partial_and_low_sample(factory):
    assert build().status == "NO_GAMES"
    assert build((factory(),)).status == "INSUFFICIENT_DATA"
    games = tuple(
        factory(i, status="pending" if i >= 24 else "done") for i in range(6, 26)
    )
    report = build(games)
    assert report.status == "PARTIAL"
    assert report.health.analysis_coverage == 0.9
    assert report.health.selected_games == 20 and report.health.analyzed_games == 18
    assert report.overall.games_played == 20
    assert report.ranked_weaknesses == {}


@pytest.mark.parametrize(
    "kind,code",
    [
        ("duplicate", "DUPLICATE_MOVE_ANALYSIS"),
        ("attribution", "PLAYER_ATTRIBUTION_INVALID"),
        ("missing", "MISSING_MOVE_ANALYSIS"),
        ("database", "DATABASE_INTEGRITY_FAILED"),
        ("foreign_keys", "FOREIGN_KEY_FAILED"),
    ],
)
def test_integrity_blocks_all_calculations(factory, kind, code):
    g = factory()
    kwargs = {}
    if kind == "duplicate":
        g = g.model_copy(update={"moves": g.moves + (g.moves[0],)})
    elif kind == "attribution":
        g = g.model_copy(
            update={
                "moves": (g.moves[0].model_copy(update={"mover": "black"}),)
                + g.moves[1:]
            }
        )
    elif kind == "missing":
        g = g.model_copy(update={"moves": g.moves[:-1]})
    elif kind == "database":
        kwargs["database_integrity"] = False
    else:
        kwargs["foreign_keys"] = False
    report = build((g,), **kwargs)
    assert report.status == "DATA_ERROR"
    assert report.overall is None and not report.ranked_weaknesses
    assert code in [e.code for e in report.health.errors]


def test_repository_error_codes_and_duplicate_game(factory):
    report = build(
        (factory(),), errors=(Diagnostic(code="INCOMPATIBLE_ANALYSIS", game_id=1),)
    )
    assert report.status == "DATA_ERROR"
    health = check_analytics_health(EvidenceDataset(games=(factory(), factory())))
    assert "DUPLICATE_GAME" in [e.code for e in health.errors]


def test_color_imbalance_and_confounding_visible(factory):
    white = tuple(
        factory(
            i + 1,
            losses=tuple(150 if i * 10 + j < 4 else 0 for j in range(10)),
            color="white",
            phases=["opening"],
        )
        for i in range(20)
    )
    black = tuple(
        factory(
            i + 21,
            losses=tuple(150 if i * 10 + j < 20 else 0 for j in range(10)),
            color="black",
            phases=["endgame"],
        ).model_copy(update={"time_class": "rapid"})
        for i in range(20)
    )
    report = build(white + black)
    colors = {s.key: s.summary.moves.critical.per_100 for s in report.color_metrics}
    assert colors == {"white": 2, "black": 10}
    phases = {s.key: s for s in report.phase_metrics}
    assert phases["endgame"].time_class_games == {"rapid": 20}
    assert phases["opening"].time_class_games == {"blitz": 20}


def test_low_sample_opening_suppressed(factory):
    games = tuple(
        factory(i, losses=(150,) * 10, phases=["opening"], result="loss").model_copy(
            update={"eco": "C00" if i < 3 else "B12"}
        )
        for i in range(1, 33)
    )
    report = build(games)
    assert "opening:C00" not in [
        w.candidate_key for w in report.ranked_weaknesses["opening"]
    ]
    assert report.ranked_weaknesses["opening"][0].candidate_key == "opening:B12"
    groups = {s.key: s for s in report.opening_metrics}
    assert groups["C00"].summary.score_percentage == 0
    assert groups["C00"].evidence_status == "insufficient"


def test_context_support_and_clock_guard(factory):
    games = tuple(
        factory(i, losses=(150, 0, 0), phases=["opening"]) for i in range(1, 11)
    )
    games = tuple(
        g.model_copy(
            update={
                "moves": tuple(
                    m.model_copy(update={"in_check": True, "under_time_pressure": True})
                    for m in g.moves
                )
            }
        )
        for g in games
    )
    report = build(games)
    context = {c.key: c for c in report.behavioral_metrics}
    assert context["in_check"].evidence_status == "sufficient"
    assert context["under_time_pressure"].evidence_status == "sufficient"
    assert report.ranked_weaknesses["context"]


def test_priority_frequency_severity_and_ties(factory):
    # Identical populations and errors produce an alphabetical tie-break.
    games = tuple(
        factory(i, losses=(150,) * 10, phases=["opening"] * 5 + ["endgame"] * 5)
        for i in range(1, 11)
    )
    report = build(games)
    assert [w.candidate_key for w in report.ranked_weaknesses["phase"]] == [
        "phase:endgame",
        "phase:opening",
    ]
    significant = tuple(
        factory(i, losses=(80,) * 10, phases=["endgame"]) for i in range(1, 11)
    )
    critical = tuple(
        factory(i, losses=(150,) * 10, phases=["endgame"]) for i in range(1, 11)
    )
    assert (
        build(critical).ranked_weaknesses["phase"][0].priority_score
        == 2 * build(significant).ranked_weaknesses["phase"][0].priority_score
    )


def test_duplicate_games_return_diagnostic_report(factory):
    report = build((factory(), factory()))
    assert report.status == "DATA_ERROR"
    assert "DUPLICATE_GAME" in [e.code for e in report.health.errors]


@pytest.mark.parametrize("loss", [-1, float("nan"), float("inf")])
def test_unchecked_loss_diagnosed(factory, loss):
    g = factory()
    g = g.model_copy(
        update={
            "moves": (g.moves[0].model_copy(update={"loss_cp": loss}),) + g.moves[1:]
        }
    )
    report = build((g,))
    assert report.status == "DATA_ERROR"
    assert "INVALID_LOSS" in [e.code for e in report.health.errors]


def test_incorrect_severity_diagnosed(factory):
    g = factory()
    g = g.model_copy(
        update={
            "moves": (g.moves[0].model_copy(update={"severity": "critical"}),)
            + g.moves[1:]
        }
    )
    report = build((g,))
    assert "SEVERITY_POLICY_MISMATCH" in [e.code for e in report.health.errors]


@pytest.mark.parametrize(
    "field,value",
    [("comparable_moves", 999), ("mean_loss_cp", -1), ("median_loss_cp", None)],
)
def test_serialized_report_rejects_inconsistent_move_metrics(factory, field, value):
    payload = build((factory(),)).model_dump()
    payload["overall"]["moves"][field] = value
    with pytest.raises(ValidationError):
        AnalyticsReport.model_validate(payload)


def test_historical_coaching_keeps_deterministic_ranking_and_refs(factory):
    import json

    from chess_coach.application.coaching import historical_evidence, validated_output
    from chess_coach.application.errors import OperationError

    report = build(planted(factory))
    evidence = historical_evidence(report)
    assert evidence.patterns[0].candidate_key == "phase:endgame"
    assert evidence.patterns[0].critical_errors == 24
    assert evidence.patterns[0].source_moves == report.ranked_weaknesses["phase"][0].source_moves[:3]
    raw = {"status": "explained", "summary": "Review the supported phase patterns.",
        "priorities": [{"pattern_id": "phase:endgame", "explanation": "Endgame errors are represented in the supplied history.", "practice_tip": "Review the linked endgame positions."}]}
    assert validated_output(json.dumps(raw), evidence).priorities[0].pattern_id == "phase:endgame"
    raw["priorities"][0]["pattern_id"] = "invented"
    with pytest.raises(OperationError):
        validated_output(json.dumps(raw), evidence)

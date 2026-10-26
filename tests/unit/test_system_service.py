from chess_coach.application.system import DependencyStatus, collect_system_status


def test_model_failure_preserves_engine_and_service_status() -> None:
    status = collect_system_status(
        lambda: DependencyStatus("available", "Engine ready"),
        lambda: (
            DependencyStatus("available", "Service reachable"),
            DependencyStatus("unavailable", "Model missing"),
        ),
    )
    assert status.stockfish.state == "available"
    assert status.ollama.state == "available"
    assert status.ollama_model.state == "unavailable"

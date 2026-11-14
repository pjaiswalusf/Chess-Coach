"""Snapshot format shared by game imports and analytics validation."""

from dataclasses import asdict, fields

from chess_coach.domain.game_records import ParsedGame


def parsed_game_metadata(game: ParsedGame) -> dict[str, object]:
    metadata = {
        field.name: getattr(game, field.name)
        for field in fields(game)
        if field.name != "moves"
    }
    metadata["time_control"] = asdict(game.time_control)
    metadata["total_plies"] = game.total_plies
    return metadata

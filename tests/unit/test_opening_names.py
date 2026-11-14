import pytest

from chess_coach.infrastructure.chesscom.opening_names import opening_name_from_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://www.chess.com/openings/Kings-Pawn-Opening-1...e5",
            "King's Pawn Opening",
        ),
        (
            "https://www.chess.com/openings/Pirc-Defense...4.Nf3-Bg7",
            "Pirc Defense",
        ),
        (
            "https://chess.com/openings/Modern-Defense-with-1-e4?foo=bar",
            "Modern Defense with 1 e4",
        ),
        ("https://www.chess.com/openings/Undefined", None),
        ("https://example.com/openings/Caro-Kann-Defense", None),
        ("https://www.chess.com/openings/one/two", None),
        (None, None),
    ],
)
def test_opening_name_from_url(url, expected):
    assert opening_name_from_url(url) == expected

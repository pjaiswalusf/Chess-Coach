"""Decode display names from the opening URLs supplied in game metadata."""

import re
from urllib.parse import unquote, urlsplit

_MOVE_SUFFIX = re.compile(r"(?:-|\.{3})\d+\.+(?=[a-hKQRBNO0])")
_POSSESSIVES = {
    "Kings": "King's",
    "Queens": "Queen's",
    "Bishops": "Bishop's",
    "Owens": "Owen's",
    "Petrovs": "Petrov's",
    "Alekhines": "Alekhine's",
    "Birds": "Bird's",
}


def opening_name_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parts = urlsplit(url)
        slug = unquote(parts.path).removeprefix("/openings/").strip("/")
        if (
            parts.scheme not in {"http", "https"}
            or parts.hostname not in {"www.chess.com", "chess.com"}
            or not parts.path.startswith("/openings/")
            or "/" in slug
        ):
            return None
    except ValueError:
        return None
    name = _MOVE_SUFFIX.split(slug, maxsplit=1)[0].strip(".-")
    if not name or name.casefold() == "undefined":
        return None
    return " ".join(_POSSESSIVES.get(word, word) for word in name.split("-") if word)

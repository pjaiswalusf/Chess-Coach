class ChessEngineError(Exception):
    """Known engine failure."""


class EngineUnavailableError(ChessEngineError):
    """Cannot initialize the configured executable."""


class InvalidPositionError(ChessEngineError):
    """Invalid or unsupported board/history."""


class EngineAnalysisError(ChessEngineError):
    """Analysis or process cleanup failed; no partial result is usable."""

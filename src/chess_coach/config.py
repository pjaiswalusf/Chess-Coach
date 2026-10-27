from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Application-wide configuration."""

    # ------------------------------------------------------------------
    # General
    # ------------------------------------------------------------------

    log_level: str = "INFO"

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    database_path: Path = Path("data/chess_coach.db")

    @property
    def database_url(self) -> URL:
        """Build a SQLite URL without interpreting special path characters."""
        return URL.create("sqlite+pysqlite", database=str(self.database_path))

    # ------------------------------------------------------------------
    # Stockfish
    # ------------------------------------------------------------------

    stockfish_executable: str = Field(default="stockfish", min_length=1)
    stockfish_threads: int = Field(default=4, gt=0)
    stockfish_hash_mb: int = Field(default=512, gt=0)

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------

    ollama_host: HttpUrl = HttpUrl("http://localhost:11434")
    ollama_model: str = Field(default="qwen3.5:4b-q4_K_M", min_length=1)

    # ------------------------------------------------------------------
    # Chess.com
    # ------------------------------------------------------------------

    chesscom_username: str | None = None

    # ------------------------------------------------------------------
    # Pydantic Settings configuration
    # ------------------------------------------------------------------

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CHESS_COACH_",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the application's cached settings instance."""
    return Settings()

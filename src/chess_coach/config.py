from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, HttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Application-wide configuration."""

    # ------------------------------------------------------------------
    # General
    # ------------------------------------------------------------------

    log_level: str = "INFO"
    pgn_max_bytes: int = Field(default=1_000_000, gt=0)

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

    analysis_min_free_mb: int = Field(default=256, ge=0)
    stockfish_executable: str = Field(default="stockfish", min_length=1)
    stockfish_threads: int = Field(default=4, gt=0)
    stockfish_hash_mb: int = Field(default=512, gt=0)
    stockfish_nodes: int = Field(default=10_000, gt=0, strict=True)
    stockfish_max_nodes: int = Field(default=10_000_000, gt=0, strict=True)
    stockfish_search_seconds: float = Field(default=3.0, gt=0, allow_inf_nan=False)
    stockfish_timeout_seconds: float = Field(default=10.0, gt=0, allow_inf_nan=False)

    @field_validator("stockfish_nodes", "stockfish_max_nodes", mode="before")
    @classmethod
    def parse_node_environment(cls, value: object) -> object:
        # Environment settings are strings; retain strict rejection of floats/bools.
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            return int(value)
        return value

    @model_validator(mode="after")
    def validate_analysis_budget(self) -> Self:
        if self.stockfish_nodes > self.stockfish_max_nodes:
            raise ValueError("stockfish_nodes must not exceed stockfish_max_nodes")
        return self

    training_stockfish_threads: int = Field(default=1, gt=0)
    training_candidate_limit: int = Field(default=30, ge=1, le=100)
    training_verification_nodes: int = Field(default=500_000, ge=4)

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------

    ollama_host: HttpUrl = HttpUrl("http://localhost:11434")
    ollama_model: str = Field(default="qwen3.5:4b-q4_K_M", min_length=1)

    llm_timeout_seconds: float = Field(default=90, gt=0, le=300, allow_inf_nan=False)
    llm_context_tokens: int = Field(default=4096, ge=2048, le=32768)
    llm_output_tokens: int = Field(default=800, ge=64, le=2048)
    llm_keep_alive: str = "0"
    llm_think: bool | None = False

    @model_validator(mode="after")
    def local_llm(self) -> Self:
        if self.ollama_host.host not in {"localhost", "127.0.0.1", "[::1]", "::1"}:
            raise ValueError("Ollama must use a loopback host")
        if self.ollama_host.scheme != "http" or self.ollama_host.username or self.ollama_host.password:
            raise ValueError("Use a local HTTP Ollama endpoint without credentials")
        if "cloud" in self.ollama_model.lower() or "/" in self.ollama_model:
            raise ValueError("Only an installed local model tag is supported")
        if self.llm_keep_alive not in {"0", "1m"}:
            raise ValueError("Use keep alive 0 or 1m")
        return self

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

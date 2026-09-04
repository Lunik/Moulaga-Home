"""Runtime configuration for the personal budget tracker."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOULAGA_", extra="ignore")

    data_dir: Path = Path("/data")
    database_url: str | None = None
    cors_origins: str = ""
    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "moulaga.db"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attached"

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

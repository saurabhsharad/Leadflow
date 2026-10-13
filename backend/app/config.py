from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, available_timezones

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

# Repository-root .env, used when running the backend directly on the host.
# In Docker Compose the variables arrive via the container environment instead,
# and real environment variables always take precedence over this file.
ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # hide_input_in_errors keeps raw values (e.g. a DATABASE_URL containing a
    # password) out of validation error messages.
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE, extra="ignore", hide_input_in_errors=True
    )

    app_timezone: str = "Asia/Kolkata"
    database_url: str
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        # Error messages must never include the URL: it contains credentials.
        try:
            url = make_url(value)
        except (ArgumentError, ValueError):
            raise ValueError(
                "DATABASE_URL is not a valid SQLAlchemy URL; check its format and port"
            ) from None
        if url.drivername != "postgresql+psycopg":
            raise ValueError(
                f"DATABASE_URL must use the 'postgresql+psycopg' driver, got {url.drivername!r}"
            )
        return value

    @field_validator("app_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        # Compare against the exact IANA names instead of only calling ZoneInfo():
        # on case-insensitive filesystems (macOS) ZoneInfo("asia/kolkata") loads,
        # but the same value fails in a Linux container.
        known = available_timezones()
        if value not in known:
            message = f"Unknown IANA timezone: {value!r} (names are case-sensitive)"
            suggestion = next((name for name in known if name.lower() == value.lower()), None)
            if suggestion:
                message += f"; did you mean {suggestion!r}?"
            raise ValueError(message)
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list):
            value = [o.strip() if isinstance(o, str) else o for o in value]
            value = [o for o in value if o != ""]
            if not value:
                raise ValueError("CORS_ORIGINS must list at least one origin")
            if "*" in value:
                raise ValueError("Wildcard CORS origin is not allowed; list explicit origins")
        return value

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()

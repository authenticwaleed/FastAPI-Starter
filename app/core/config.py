import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"})


class Settings(BaseSettings):
    app_name: str = "FastAPI Starter"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False

    # Required and intentionally without a default: the connection string
    # carries credentials, so it must come from the environment.
    database_url: PostgresDsn

    # Required for the same reason, and more sharply so. A default here would
    # be a published signing key, and every deployment that forgot to
    # override it could have its tokens forged by anyone holding this file.
    # SecretStr keeps the value out of reprs and stray log lines.
    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # How long an invitation link stays usable. A week is long enough to
    # survive somebody being on holiday and short enough that a link found
    # in an old mailbox is no longer a way into a workspace.
    invitation_expire_hours: int = 168

    log_level: str = "INFO"
    # "text" reads better in a terminal; "json" is what a log aggregator can
    # actually query. Left unset it follows the environment, which is the
    # right default in both places.
    log_format: Literal["text", "json"] = "text"

    # Origins a browser is allowed to call this API from. Empty by default:
    # a same-origin client needs no CORS at all, and the wrong default here
    # is a security hole rather than an inconvenience.
    # NoDecode hands the validator below the raw string. Without it
    # pydantic-settings insists an env var for a list field is JSON, and
    # `CORS_ORIGINS=a,b` fails at startup before the validator is reached.
    cors_origins: Annotated[list[str], NoDecode] = []
    cors_allow_credentials: bool = True

    # Host header values the application will answer to. "*" is defensible
    # behind a proxy that already validates the header, which is why it is
    # the default, but production has to say so explicitly.
    allowed_hosts: Annotated[list[str], NoDecode] = ["*"]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        """Fail at startup on a typo rather than logging nothing all day."""
        level = value.upper()

        if level not in _LOG_LEVELS:
            raise ValueError(f"log_level must be one of {sorted(_LOG_LEVELS)}")

        return level

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _accept_a_comma_separated_list(cls, value: Any) -> Any:
        """Take `a,b` as well as the JSON `["a","b"]` pydantic expects.

        A comma-separated string is what fits comfortably in a .env file or
        a compose file, and is what people reach for first. Both forms are
        parsed here rather than relying on the settings source, so a value
        means the same thing whether it arrived from the environment or was
        passed straight to the constructor.
        """
        if not isinstance(value, str):
            return value

        text = value.strip()

        if text.startswith("["):
            # A JSONDecodeError is a ValueError, so a malformed list still
            # surfaces as an ordinary validation error.
            return json.loads(text)

        return [item.strip() for item in text.split(",") if item.strip()]

    @model_validator(mode="after")
    def _structure_logs_outside_development(self) -> "Settings":
        if "log_format" not in self.model_fields_set and not self.is_development:
            self.log_format = "json"

        return self

    @model_validator(mode="after")
    def _refuse_unsafe_combinations(self) -> "Settings":
        # Browsers reject a wildcard origin on a credentialed request, so
        # this combination does not do what whoever configured it expects.
        if self.cors_allow_credentials and "*" in self.cors_origins:
            raise ValueError(
                "cors_origins cannot be '*' while cors_allow_credentials is on: "
                "browsers refuse that combination"
            )

        if not self.is_production:
            return self

        # Everything below is a development convenience that becomes a
        # liability in production, which is how the two environments differ.
        if self.debug:
            raise ValueError("debug must be off in production")

        if "*" in self.cors_origins:
            raise ValueError("cors_origins must name real origins in production")

        if "*" in self.allowed_hosts:
            raise ValueError("allowed_hosts must be set explicitly in production")

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    # Every required field is supplied from the environment, which mypy has
    # no way of knowing, so it sees a constructor called without arguments.
    return Settings()  # type: ignore[call-arg]

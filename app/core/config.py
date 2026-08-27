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

    # Encrypts provider access tokens before they are stored. Optional so
    # that everything not touching an integration works without it, and
    # required in production by the validator below -- a deployment that
    # can connect WhatsApp must not be able to do so in plain text.
    # Generate one per environment with app.core.encryption.generate_key,
    # or from a shell:
    #   uv run python -c \
    #     "from app.core.encryption import generate_key as k; import sys; \
    #      sys.stdout.write(k())"
    # Changing it makes every token already stored undecryptable.
    encryption_key: SecretStr | None = None

    # Meta sends every workspace's webhooks to one callback URL, because
    # one Meta app serves all of them, so both of these are app-wide
    # rather than per workspace. The verify token is the string echoed
    # back during subscription; the app secret signs every delivery.
    whatsapp_verify_token: SecretStr | None = None
    whatsapp_app_secret: SecretStr | None = None

    # Turns a business's knowledge into vectors, and a customer's question
    # into one to compare against them. Optional, like the WhatsApp
    # credentials: everything that is not the knowledge base works without
    # it, and ingesting a document without it fails with a clear answer
    # rather than storing chunks nothing can ever retrieve.
    voyage_api_key: SecretStr | None = None
    embedding_model: str = "voyage-3.5-lite"
    # 1024 is the model's own default. Smaller is cheaper to store and
    # faster to scan, at some cost in accuracy; changing it invalidates
    # every vector already stored, because two vectors of different
    # lengths cannot be compared.
    embedding_dimensions: int = 1024

    # Writes the replies. Optional for the same reason, and checked at the
    # point of use: an inbox works perfectly well with no assistant.
    anthropic_api_key: SecretStr | None = None
    # The model the plan's pilots run on. Named here rather than in the
    # code that calls it, so changing it is a deployment decision.
    anthropic_model: str = "claude-opus-5"
    # A reply on WhatsApp is a few sentences. The cap is a guard against a
    # runaway response rather than a target, and it is well under what the
    # channel itself allows.
    anthropic_max_tokens: int = 1024

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

    @field_validator(
        "encryption_key",
        "whatsapp_verify_token",
        "whatsapp_app_secret",
        "voyage_api_key",
        "anthropic_api_key",
        mode="before",
    )
    @classmethod
    def _an_empty_secret_is_no_secret(cls, value: Any) -> Any:
        """Treat an empty value as unset.

        A compose file writing `KEY: ${KEY:-}` produces an empty string
        rather than an absent variable, and without this that arrives as
        SecretStr("") -- which is not None, so the production check below
        would pass and the deployment would start with a key that cannot
        encrypt anything. Blank means missing, from every source.
        """
        if isinstance(value, str) and not value.strip():
            return None

        return value

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

        # Storing a provider's access token in plain text is the kind of
        # mistake that is only discovered by somebody reading the table.
        if self.encryption_key is None:
            raise ValueError("encryption_key must be set in production")

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

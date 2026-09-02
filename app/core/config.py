import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"})


class Settings(BaseSettings):
    app_name: str = "Baton"
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

    # Short, because an access token cannot be taken back mid-flight the
    # way a refresh token can: it is checked against its session on every
    # request, but a request already in progress is already in progress.
    # Fifteen minutes is the window a stolen one is worth anything for.
    access_token_expire_minutes: int = 15

    # How long a session survives being idle. Every refresh pushes it out
    # again, so this is "sign me out if I disappear for a month" rather
    # than a fixed date -- which is what a dashboard people use weekly
    # wants, and short enough that a laptop left in a hotel does not stay
    # signed in for a year.
    refresh_token_expire_days: int = 30

    # How long a session may sit unused before the platform console
    # stops accepting it. Staff sign in through the ordinary login and
    # get an ordinary session -- one account, one password -- so this is
    # the whole of "an admin session has its own policy": the same
    # session keeps working on the tenant surface and is refused here.
    #
    # An hour, against the tenant side's thirty days, and the difference
    # is what the two can reach. A console that can read any customer's
    # account should not still be open on an unattended laptop after
    # lunch. Note that `last_used_at` moves on token rotation rather than
    # on every request, so this is accurate to about the access token's
    # lifetime, which is what makes an hour the shortest useful value.
    admin_session_idle_minutes: int = 60

    # How long a support grant lasts when whoever asks for one does not
    # say, and the longest one anybody may ask for.
    #
    # Four hours is a shift, which is the unit support work actually
    # happens in. The cap is what stops "just make it a week" becoming
    # the habit, and it is a hard ceiling rather than a default: a
    # request for longer is refused rather than quietly shortened,
    # because somebody who believes they have two days of access and
    # actually has four hours finds out halfway through an incident.
    #
    # Standing access to every customer's data is not access control, so
    # neither of these may be zero or unbounded.
    admin_support_grant_hours: int = 4
    admin_support_grant_max_hours: int = 24

    # How long a two-person approval stays usable once a colleague has
    # granted it. Thirty minutes, because the point of the second person
    # is that they are looking at the same situation -- an approval
    # collected in the morning and spent in the evening is one signature
    # on a decision, not two.
    admin_approval_expire_minutes: int = 30

    # Addresses allowed to reach /api/v1/admin. Empty means anywhere,
    # which is the default and has to be: a deployment that shipped with
    # an allowlist would lock its own operator out on the first day.
    #
    # Where it earns its place is a platform console reachable from the
    # public internet -- the address is a second factor that costs
    # nothing and cannot be phished. Behind a proxy, uvicorn needs
    # `--proxy-headers` or every caller looks like the load balancer.
    admin_ip_allowlist: Annotated[list[str], NoDecode] = []

    # The hours a support grant is unremarkable in, as UTC hours. A grant
    # outside them is not refused -- incidents do not keep office hours
    # -- it is logged at warning, which is what "alert on unusual
    # patterns" comes to in a system whose alerting channel is its log
    # stream.
    admin_working_hours_utc: Annotated[list[int], NoDecode] = list(range(6, 19))

    # How many workspaces one staff member may read in an hour before the
    # console says so. Not a limit: reading forty accounts in an hour is
    # either a migration or somebody going through the customer list, and
    # the difference is a question for a person rather than a refusal.
    admin_workspace_reads_per_hour: int = 20

    # How long an invitation link stays usable. A week is long enough to
    # survive somebody being on holiday and short enough that a link found
    # in an old mailbox is no longer a way into a workspace.
    invitation_expire_hours: int = 168

    # Two days to confirm an address, because somebody signing up on
    # Friday evening may not read their mail until Sunday.
    email_verification_expire_hours: int = 48

    # An hour to use a reset link, because it is a key to the account and
    # the person holding it asked for it a moment ago. Deliberately much
    # shorter than the verification window above: confirming an address
    # and replacing a password are not worth the same to a thief.
    password_reset_expire_minutes: int = 60

    # Where the links in those emails point -- the dashboard, not this
    # API. Unset, the email carries the bare token instead, which is
    # enough to work with locally and obviously not a link to send anyone.
    frontend_base_url: str | None = None

    # Delivering those emails. Unset outside production, where the sender
    # writes the whole message to the log instead: a laptop has no mail
    # server and a developer needs to read the link. Required in
    # production by the validator below -- a deployment that cannot send
    # mail is one where forgotten passwords silently go nowhere, and
    # where reset links would be written into a log file instead.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    # STARTTLS on the port above, which is what nearly every provider
    # wants. Off is for a local catch-all mail trap and nothing else.
    smtp_use_tls: bool = True
    email_from: str | None = None

    # Encrypts provider access tokens before they are stored. Optional so
    # that everything not touching an integration works without it, and
    # required in production by the validator below -- a deployment that
    # can connect WhatsApp must not be able to do so in plain text.
    # Generate one per environment with app.core.encryption.generate_key,
    # or from a shell:
    #   uv run python -c \
    #     "from app.core.encryption import generate_key as k; import sys; \
    #      sys.stdout.write(k())"
    encryption_key: SecretStr | None = None

    # The key this one replaced, kept readable while what it encrypted is
    # rewritten. Everything is encrypted with `encryption_key` and
    # decrypted with either, which is what turns rotating the key from a
    # deployment where every stored token stops working into an ordinary
    # one. Unset once nothing needs it -- see app/core/encryption.py for
    # the order the four steps go in.
    encryption_key_previous: SecretStr | None = None

    # Meta sends every workspace's webhooks to one callback URL, because
    # one Meta app serves all of them, so both of these are app-wide
    # rather than per workspace. The verify token is the string echoed
    # back during subscription; the app secret signs every delivery.
    whatsapp_verify_token: SecretStr | None = None
    whatsapp_app_secret: SecretStr | None = None

    # Where this API answers, as the outside world reaches it. Needed
    # because an OAuth redirect has to be an absolute URL the provider
    # will send a shop owner back to, and this application cannot work
    # that out from a request it has not received yet.
    api_base_url: str | None = None

    # Installing a Shopify storefront. Optional like every other
    # integration credential and checked where it is used: a business
    # with no online shop is most of the plan's first customers, and the
    # inbox works perfectly well without one.
    shopify_api_key: SecretStr | None = None
    shopify_api_secret: SecretStr | None = None
    # Read-only, and deliberately: this product answers questions about a
    # catalogue, it does not edit one. Asking for write access would be
    # asking a shop owner to trust it with something it never uses.
    shopify_scopes: str = "read_products,read_orders,read_customers"

    # Taking the money. Optional like every other integration credential
    # and checked where it is used: a deployment that is not selling
    # anything yet -- which the plan says is most of them for a while --
    # works without any of it, and every workspace is simply on the free
    # plan.
    #
    # The price identifiers are Stripe's names for what a plan costs, and
    # they differ between test mode and live mode. That is why they are
    # configuration rather than a fact in app/services/plans.py.
    stripe_api_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_price_growth: str | None = None
    stripe_price_business: str | None = None

    # Installing a WooCommerce store. Different in shape from Shopify's
    # credentials, and the difference is the store's rather than a
    # choice: WooCommerce signs its webhooks with a secret whoever
    # created the webhook typed into a form, so this application
    # publishes one and asks for it to be used. Without it, nothing
    # verifies -- which is refusing every delivery, and is the right way
    # round.
    woocommerce_webhook_secret: SecretStr | None = None

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

    # --- rate limiting -------------------------------------------------
    #
    # Counted per worker, in memory. See app/core/rate_limit.py for what
    # that costs and when it stops being the right trade.
    #
    # Every number is an allowance and a burst at once: ten a minute
    # means ten straight away and then one every six seconds.
    rate_limit_enabled: bool = True

    # Per client address. Generous enough for somebody mistyping a
    # password and small enough that guessing at one is hopeless.
    # Refreshing shares this bucket, because a refresh token is a
    # credential and the same argument applies to guessing at one.
    rate_limit_auth_per_minute: int = 10

    # Per client address, and the tightest limit here, because these are
    # the endpoints that send mail to an address of the caller's choosing
    # -- an unauthenticated way to have this service email a stranger.
    rate_limit_email_per_hour: int = 5

    # Per workspace, not per address: these are all authenticated, and
    # what they cost is a tenant's money rather than a stranger's
    # patience. Invitations because each is an email; the AI and search
    # because each is a paid API call; uploads because each is a file to
    # read, chunk and embed.
    rate_limit_invitations_per_hour: int = 60
    rate_limit_ai_per_minute: int = 60
    rate_limit_search_per_minute: int = 60
    rate_limit_uploads_per_hour: int = 120

    # Per staff member, not per address: every one of these is
    # authenticated, and several of them write an audit row on a GET, so
    # what a runaway console costs is rows in the platform's own log.
    # Generous, because a support engineer working through a ticket
    # clicks a great deal.
    rate_limit_admin_per_minute: int = 120

    # Per client address, and counted only against deliveries that fail
    # to authenticate. A provider sending real traffic from a handful of
    # addresses is never charged; somebody hammering the endpoint with
    # forgeries stops being answered.
    rate_limit_webhook_rejections_per_minute: int = 30

    # How long the worker waits when it finds nothing to do. Short enough
    # that a message queued by a request goes out while the person who
    # sent it is still looking at the thread, long enough that an idle
    # deployment is not one query a second against the jobs table for ever.
    worker_poll_seconds: float = 2.0

    # How many jobs one pass claims before going back to look for more.
    # Claimed one at a time regardless -- this is how many times round the
    # loop, not a batch -- so a slow job delays the next rather than
    # holding a lock over ten of them.
    worker_batch_size: int = 20

    # When a job that says it is running is assumed to have been abandoned.
    # A worker killed mid-job leaves the row claimed, and nothing but a
    # clock can tell that from a job that is simply taking a while -- so
    # this has to be comfortably longer than the slowest handler, which is
    # a WhatsApp delivery behind its own timeout.
    worker_stall_after_seconds: int = 300

    # How often the automation sweep is planned. Also the width of the
    # window its deduplication key is bucketed into, so shortening it
    # cannot produce two sweeps for one window.
    worker_sweep_every_seconds: int = 300

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

    # How long a browser should refuse to talk to this host over plain
    # HTTP once it has been told. Two years, which is what preload lists
    # require and what makes the header worth sending: a short max-age
    # leaves a window every time somebody's cache expires.
    #
    # Sent only in production. In development the API is on http://
    # localhost, and a browser that has been told to upgrade this host for
    # two years is one a developer cannot easily untell.
    hsts_max_age_seconds: int = 63_072_000

    # How long a closed workspace's data is kept before it is erased. The
    # retention policy and the deletion workflow are the same number: a
    # business that closes its account has its records destroyed on a date
    # it can be told in advance, and has until then to change its mind.
    #
    # Thirty days, which is long enough to survive a mistake and a holiday
    # and short enough to be an honest answer to "when will you delete it".
    erasure_grace_days: int = 30

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
        "encryption_key_previous",
        "whatsapp_verify_token",
        "whatsapp_app_secret",
        "voyage_api_key",
        "anthropic_api_key",
        "api_base_url",
        "shopify_api_key",
        "shopify_api_secret",
        "woocommerce_webhook_secret",
        "stripe_api_key",
        "stripe_webhook_secret",
        "stripe_price_growth",
        "stripe_price_business",
        "frontend_base_url",
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "email_from",
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

    @field_validator("admin_working_hours_utc", mode="before")
    @classmethod
    def _accept_a_comma_separated_hour_list(cls, value: Any) -> Any:
        """Take `9,10,11` as well as the JSON pydantic expects.

        The same accommodation the string lists below get, and for the
        same reason: this is what fits in a .env file and what people
        reach for first.
        """
        if not isinstance(value, str):
            return value

        text = value.strip()

        if text.startswith("["):
            return json.loads(text)

        return [int(hour.strip()) for hour in text.split(",") if hour.strip()]

    @field_validator(
        "cors_origins", "allowed_hosts", "admin_ip_allowlist", mode="before"
    )
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

        # Without these, verification and password reset do not fail --
        # they appear to work while the link goes to a log file. Refusing
        # to start is the only outcome that cannot be mistaken for one.
        if self.smtp_host is None or self.email_from is None:
            raise ValueError(
                "smtp_host and email_from must be set in production: "
                "without them no verification or reset email is delivered"
            )

        if self.frontend_base_url is None:
            raise ValueError(
                "frontend_base_url must be set in production: "
                "without it those emails carry a bare token and no link"
            )

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

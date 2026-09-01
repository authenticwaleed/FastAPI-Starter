import json
import logging
from logging.config import dictConfig
from typing import Any

from app.core import context
from app.core.config import get_settings

# What a record may carry beyond the identifiers: measurements, put there
# by the observability helpers. Named here rather than accepted wholesale,
# for the reason `context.bind` is keyword-only -- a formatter that
# serialised every attribute somebody attached to a record would ship
# whatever the next person passed as `extra`.
MEASUREMENTS = ("duration_ms", "outcome", "status", "method", "route", "error", "depth")


class ContextFilter(logging.Filter):
    """Attach the ambient identifiers to every record that passes through.

    A filter rather than an adapter, because it has to reach lines nobody
    here wrote: uvicorn's, SQLAlchemy's, and whatever a library logs when
    something goes wrong inside it. Those are exactly the lines worth
    knowing the request id of.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        fields = dict(context.current())

        for name in MEASUREMENTS:
            value = getattr(record, name, None)

            if value is not None:
                fields[name] = value

        record.fields = fields
        # Rendered here rather than in the text formatter, because a
        # format string cannot iterate. Empty when there is nothing to
        # say, so an ordinary line looks exactly as it did before.
        record.field_suffix = (
            " " + " ".join(f"{key}={value}" for key, value in fields.items())
            if fields
            else ""
        )

        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, which is what an aggregator wants.

    Written by hand rather than pulled in as a dependency: the fields worth
    shipping are few and fixed, and anything more elaborate belongs to
    whatever collects these downstream.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Top-level rather than nested under a key, because that is what
        # makes them queryable: an aggregator filters on `workspace_id`,
        # not on `fields.workspace_id`. Merged last would let a stray
        # field shadow the level or the message, so they go in first and
        # the fixed four win.
        payload = {**getattr(record, "fields", {}), **payload}

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload)


def configure_logging() -> None:
    """Configure logging from settings.

    Called by the application factory rather than at import time, so
    importing anything from `app` does not quietly take over logging for
    whoever imported it.

    Nothing here logs a value. What must never reach a log line is a
    password, a JWT secret or a database URL, and the way to guarantee that
    is to never format settings into a message: `jwt_secret_key` is a
    SecretStr whose repr is masked, and `database_url` carries a password in
    plain sight, so neither is ever passed to a logger.
    """
    settings = get_settings()

    dictConfig(
        {
            "version": 1,
            # Leave loggers configured elsewhere alone rather than silencing
            # them, which is what the default would do.
            "disable_existing_loggers": False,
            "formatters": {
                "text": {
                    "format": (
                        "%(asctime)s %(levelname)-8s %(name)s | "
                        "%(message)s%(field_suffix)s"
                    ),
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                },
                "json": {
                    "()": "app.core.logging.JsonFormatter",
                },
            },
            "filters": {
                "context": {
                    "()": "app.core.logging.ContextFilter",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": settings.log_format,
                    # On the handler rather than on a logger, so that every
                    # line reaching this stream carries the identifiers --
                    # including the ones written by libraries that know
                    # nothing about them.
                    "filters": ["context"],
                    # stdout rather than stderr: a container's log is one
                    # stream, and splitting across two makes the ordering of
                    # what you read back unreliable.
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {
                "handlers": ["console"],
                "level": settings.log_level,
            },
            "loggers": {
                # uvicorn installs handlers of its own. Pointing them here,
                # and switching propagate off, keeps one format and stops
                # every line being emitted twice.
                name: {
                    "handlers": ["console"],
                    "level": settings.log_level,
                    "propagate": False,
                }
                for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
            }
            | {
                # SQL logging is a level here rather than create_engine's
                # `echo`, which would attach a second handler and double
                # every statement. No handler of its own: these propagate to
                # root and come out in the same format as everything else.
                "sqlalchemy.engine": {
                    "level": "INFO" if settings.debug else "WARNING",
                },
            },
        }
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

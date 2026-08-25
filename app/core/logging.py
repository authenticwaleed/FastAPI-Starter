import json
import logging
from logging.config import dictConfig
from typing import Any

from app.core.config import get_settings


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
                    "format": "%(asctime)s %(levelname)-8s %(name)s | %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                },
                "json": {
                    "()": "app.core.logging.JsonFormatter",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": settings.log_format,
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

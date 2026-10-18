"""Shared logging setup for API, scheduler, and CLI scripts."""

import logging

import structlog


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """Configure stdlib logging and structlog once per process."""
    numeric_level = getattr(logging, str(level or "INFO").upper(), logging.INFO)
    logging.basicConfig(level=numeric_level, format="%(message)s")

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

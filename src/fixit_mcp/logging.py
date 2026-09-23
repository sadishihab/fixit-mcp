import logging
import sys
import time
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

import structlog

P = ParamSpec("P")
R = TypeVar("R")


def configure_logging(level: str = "INFO") -> None:
    """Configure JSON structured logging to stdout."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def log_tool_latency(tool_name: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Wrap a tool handler to log its latency in milliseconds.

    Alexa+ requires each tool call to round-trip in well under 500ms, so every
    call's latency is logged as structured data to make regressions visible.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            logger = structlog.get_logger()
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception:
                elapsed_ms = (time.perf_counter() - start) * 1000
                logger.error("tool_call_failed", tool=tool_name, latency_ms=round(elapsed_ms, 2))
                raise
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("tool_call_completed", tool=tool_name, latency_ms=round(elapsed_ms, 2))
            return result

        return wrapper

    return decorator

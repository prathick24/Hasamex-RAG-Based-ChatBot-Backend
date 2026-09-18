import json
import logging
import sys

import structlog

from src.settings import get_settings

DEFAULT_LOG_FIELDS = {
    "timestamp": "iso",
    "level": "levelname",
    "logger": "name",
    "module": "module",
    "function": "funcName",
    "line": "lineno",
    "message": "message",
}


def setup_logging() -> None:
    settings = get_settings()
    level = getattr(logging, str(settings.log_level).upper(), logging.INFO)

    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(serializer=json.dumps),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger("hasamex")

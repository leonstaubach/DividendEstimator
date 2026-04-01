from __future__ import annotations

import logging
import sys


LOGGER_NAME = "divvydiary_app"


class AppLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if record.levelno == logging.INFO:
            return record.getMessage()
        return f"{record.levelname}: {record.getMessage()}"


def configure_logging(level_name: str = "DEBUG") -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    resolved_level = getattr(logging, level_name.upper(), logging.DEBUG)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(AppLogFormatter())
        logger.addHandler(handler)

    logger.setLevel(resolved_level)
    logger.propagate = False
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    if name is None:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")

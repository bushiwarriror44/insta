"""Tests for app.logging_setup."""
from __future__ import annotations

import logging

from app.logging_setup import configure_logging, get_logger


def test_configure_logging_idempotent(reset_logging):
    configure_logging()
    handlers_first = list(logging.getLogger().handlers)
    configure_logging()
    handlers_second = list(logging.getLogger().handlers)
    assert len(handlers_first) == len(handlers_second)


def test_configure_logging_creates_file_handler(reset_logging, app_env):
    configure_logging()
    rotators = [
        h for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert rotators, "expected a rotating file handler when log_file is set"
    assert rotators[0].baseFilename.endswith("app.log")


def test_get_logger_supports_bind(reset_logging):
    log = get_logger("test")
    bound = log.bind(account="x")
    assert bound is not None
    bound.info("hello", k="v")

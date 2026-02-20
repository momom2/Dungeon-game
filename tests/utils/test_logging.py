"""Tests for dungeon_builder.utils.logging — setup_logging utility."""

import logging
import sys

import pytest

from dungeon_builder.utils.logging import setup_logging


class TestSetupLogging:
    """Unit tests for the setup_logging helper."""

    def test_returns_named_logger(self):
        logger = setup_logging()
        assert isinstance(logger, logging.Logger)
        assert logger.name == "dungeon_builder"

    def test_idempotent_no_duplicate_handlers(self):
        """Calling setup_logging twice should not add a second handler."""
        logger = setup_logging()
        handler_count = len(logger.handlers)
        setup_logging()  # Second call
        assert len(logger.handlers) == handler_count

    def test_custom_level(self):
        """When called fresh (no handlers), level is set as requested."""
        logger = logging.getLogger("dungeon_builder")
        # Clear handlers to simulate first call
        logger.handlers.clear()
        logger = setup_logging(level=logging.DEBUG)
        assert logger.level == logging.DEBUG
        # Restore default for other tests
        logger.setLevel(logging.INFO)

    def test_handler_streams_to_stdout(self):
        logger = setup_logging()
        stream_handlers = [
            h for h in logger.handlers if isinstance(h, logging.StreamHandler)
        ]
        assert len(stream_handlers) >= 1
        assert stream_handlers[0].stream is sys.stdout

    def test_formatter_pattern(self):
        logger = setup_logging()
        handler = logger.handlers[0]
        fmt = handler.formatter._fmt
        assert "%(asctime)s" in fmt
        assert "%(name)s" in fmt
        assert "%(levelname)s" in fmt

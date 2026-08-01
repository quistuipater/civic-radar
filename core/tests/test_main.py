"""Tests for app.main's process-wide error-logging setup. _configure_error_logging
is registered as a FastAPI startup event handler, which does NOT fire for
the plain `TestClient(app)` instance used throughout this test suite (only
`with TestClient(app) as client:` triggers lifespan events) -- so it's
tested directly here as a plain function instead of via the `client` fixture.
"""

import logging

import app.main as main_module
from app.log_handler import DbLogHandler


def test_configure_error_logging_attaches_a_db_log_handler():
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    try:
        main_module._configure_error_logging()

        added = [h for h in root.handlers if isinstance(h, DbLogHandler)]
        assert len(added) == 1
        assert added[0].level == logging.ERROR
    finally:
        root.handlers = original_handlers

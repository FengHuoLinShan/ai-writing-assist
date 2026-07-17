from __future__ import annotations

import logging

from app.main import _configure_application_logging


def test_debug_logging_does_not_enable_sdk_prompt_payload_logs() -> None:
    logger_names = ("openai", "httpcore", "httpx")
    previous = {name: logging.getLogger(name).level for name in logger_names}
    try:
        _configure_application_logging("DEBUG")

        assert (
            logging.getLogger("openai._base_client").getEffectiveLevel()
            >= logging.WARNING
        )
        assert logging.getLogger("httpcore.http11").getEffectiveLevel() >= logging.WARNING
        assert logging.getLogger("httpx").getEffectiveLevel() >= logging.INFO
    finally:
        for name, level in previous.items():
            logging.getLogger(name).setLevel(level)

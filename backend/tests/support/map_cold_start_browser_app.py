"""Real map-guide HTTP with a synthetic model snapshot and no worker/provider."""

import re
from types import SimpleNamespace

from sqlalchemy.engine import make_url

from core.config import get_settings

settings = get_settings()
url = make_url(settings.database_url)
if (
    settings.app_env != "test"
    or settings.auth_mode != "local"
    or url.host not in {"localhost", "127.0.0.1"}
    or not re.search(r"(?:^|[_-])(?:e2e|test)(?:$|[_-])", url.database or "")
):
    raise RuntimeError("Requires a disposable local browser database")

from app.main import app as app  # noqa: E402
from infrastructure.llm.providers import OpenAIProvider  # noqa: E402
from modules.evolution import workflow  # noqa: E402


async def _snapshot(db, novel_id):
    return {"profile": {"model": "synthetic-no-network", "provider_id": "synthetic"}}


async def _forbid_provider(*args, **kwargs):
    raise AssertionError("This browser fixture must never invoke a model")


async def _effective_model(db, novel_id):
    return SimpleNamespace(
        provider_id=SimpleNamespace(value="synthetic"),
        model=SimpleNamespace(value="synthetic-no-network"),
    )


workflow.build_project_llm_execution_snapshot = _snapshot
workflow.get_effective_llm_settings = _effective_model
OpenAIProvider.generate = _forbid_provider

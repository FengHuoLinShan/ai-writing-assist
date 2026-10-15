"""Synthetic spatial evidence for the disposable map browser workflow."""

import asyncio
import json
import re
import sys
import uuid

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bootstrap import register_container_services
from core.config import get_settings
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.project.models import Project
from modules.world.map_auto_draft_service import build_map_auto_drafts
from modules.world.tests.test_map_auto_draft_service import (
    _build_request,
    _stage_bound_clue,
)


async def seed(novel_id: str) -> None:
    settings = get_settings()
    url = make_url(settings.database_url)
    if (
        settings.app_env != "test"
        or settings.auth_mode != "local"
        or url.host not in {"localhost", "127.0.0.1"}
        or not re.search(r"(?:^|[_-])(?:e2e|test)(?:$|[_-])", url.database or "")
    ):
        raise RuntimeError("Requires a disposable local browser test database")
    register_container_services(ignore_existing=True)
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False).begin() as db:
            project = await db.get(Project, uuid.UUID(novel_id))
            if (
                project is None
                or project.owner_id != BOOTSTRAP_ACCOUNT_ID
                or not project.title.startswith("E2E map auto draft ")
            ):
                raise RuntimeError("Requires a synthetic map browser project")
            scene, _start, _end, clue = await _stage_bound_clue(
                db, novel_id, modality="character_statement", effective=True
            )
            built = await build_map_auto_drafts(db, novel_id, _build_request(scene, clue))
            result = {"batch_id": str(built.batch_id)}
    finally:
        await engine.dispose()
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(seed(sys.argv[1]))

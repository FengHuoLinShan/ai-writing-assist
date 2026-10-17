"""Seed only synthetic saved text for real map-guide preview/start HTTP."""

import asyncio
import re
import sys
from uuid import UUID

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bootstrap import register_container_services
from core.config import get_settings
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.evolution.facade import switch_project_engine
from modules.evolution.tests.test_workflow import seed as seed_scene
from modules.project.models import Project


async def seed(novel_id):
    settings = get_settings()
    url = make_url(settings.database_url)
    if (
        settings.app_env != "test"
        or settings.auth_mode != "local"
        or url.host not in {"localhost", "127.0.0.1"}
        or not re.search(r"(?:^|[_-])(?:e2e|test)(?:$|[_-])", url.database or "")
    ):
        raise RuntimeError("Requires a disposable local browser database")
    register_container_services(ignore_existing=True)
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            project = await db.get(Project, UUID(novel_id))
            if (
                not project
                or project.owner_id != BOOTSTRAP_ACCOUNT_ID
                or not project.title.startswith("E2E map cold start HTTP ")
            ):
                raise RuntimeError("Requires a synthetic map cold-start project")
            await switch_project_engine(
                db, novel_id, to_engine="evolution", expected_epoch=1
            )
            await seed_scene(db, novel_id, 1, "林舟从河湾渡口走到北堡，沿途经过旧哨所。")
            await db.commit()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed(sys.argv[1]))

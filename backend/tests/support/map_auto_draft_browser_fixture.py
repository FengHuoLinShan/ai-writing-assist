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
from modules.world.models import CoreEntity
from modules.world.tests.test_map_auto_draft_service import (
    _build_request,
    _stage_bound_clue,
)


async def seed(
    novel_id: str,
    *,
    candidate_locations: bool = False,
    mutate_entity_id: str | None = None,
    tray_navigation: bool = False,
) -> None:
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
            if mutate_entity_id:
                entity = await db.get(CoreEntity, uuid.UUID(mutate_entity_id))
                if (
                    not entity
                    or entity.novel_id != project.id
                    or entity.status != "candidate"
                ):
                    raise RuntimeError("Requires a candidate in this synthetic project")
                entity.summary = "浏览器确认期间由另一处修订的合成地点说明。"
                return
            scene, _start, _end, clue = await _stage_bound_clue(
                db,
                novel_id,
                modality="character_statement",
                effective=True,
                entity_status="candidate" if candidate_locations else "canonical",
            )
            built = await build_map_auto_drafts(db, novel_id, _build_request(scene, clue))
            result = {"batch_id": str(built.batch_id)}
            if tray_navigation:
                from app.assistant_operation_registry import world_map_operations
                from modules.assistant.contracts import (
                    AssistantOperationContext,
                    WorkContext,
                )
                from modules.world.assistant_map_tools import PrepareTrayPlacement

                tray = built.tray_items[0]
                revision = next(
                    item for item in built.revisions if item.node_id == tray.node_id
                )
                args = PrepareTrayPlacement(
                    node_id=tray.node_id,
                    revision_id=revision.revision_id,
                    item_ids=[tray.item_id],
                )
                context = AssistantOperationContext(
                    str(uuid.uuid4()),
                    str(BOOTSTRAP_ACCOUNT_ID),
                    WorkContext(page="map", scope="project"),
                )
                operation = world_map_operations["map.prepare_tray_placement"]
                preview = await operation.prepare(db, novel_id, args, context=context)
                result = await operation.apply(
                    db, novel_id, args, preview, context=context
                )
    finally:
        await engine.dispose()
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(
        seed(
            sys.argv[1],
            candidate_locations=sys.argv[2:] == ["candidate-locations"],
            mutate_entity_id=sys.argv[3] if sys.argv[2:3] == ["mutate-entity"] else None,
            tray_navigation=sys.argv[2:] == ["tray-navigation"],
        )
    )

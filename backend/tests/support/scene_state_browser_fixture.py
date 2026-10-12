"""仅供隔离浏览器验收的合成状态；不提供业务写入入口。"""

import asyncio
import json
import sys
import uuid

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings


async def seed(novel_id):
    settings = get_settings()
    url = make_url(settings.database_url)
    if (
        settings.app_env != "test"
        or settings.auth_mode != "local"
        or url.host not in {"localhost", "127.0.0.1"}
        or "agent_e2e" not in (url.database or "")
    ):
        raise RuntimeError("Requires an explicitly disposable local browser database")
    from app.bootstrap import register_container_services
    from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
    from modules.project.models import Project
    from modules.story.continuity.scene_projection import SceneMemoryProjectionService
    from modules.story.continuity.services import MemoryService
    from modules.story.continuity.tests.test_scene_state_view import (
        _custody_scene,
        _scene,
    )

    register_container_services(ignore_existing=True)
    engine = create_async_engine(url)
    async with async_sessionmaker(engine, expire_on_commit=False).begin() as db:
        project = await db.get(Project, uuid.UUID(novel_id))
        assert (
            project
            and project.owner_id == BOOTSTRAP_ACCOUNT_ID
            and project.title.startswith("E2E ")
        )
        first, ids = await _custody_scene(db, novel_id)
        lock = str(uuid.uuid4())
        events = [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": ids[key],
                "snapshot_after": {"name": name},
            }
            for key, name in (("jia", "甲"), ("yi", "乙"), ("bing", "丙"))
        ] + [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": lock,
                "snapshot_after": {
                    "name": "三簧锁",
                    "opening_key_id": ids["key"],
                    "opening_moon_phase": "full",
                    "opening_passphrase": "潮落",
                },
            },
            {
                "dimension": "locations",
                "event_type": "entity_moved",
                "entity_id": ids["jia"],
                "snapshot_after": {"node": "雾渡港灯塔", "name": "甲"},
            },
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": ids["jia"],
                "snapshot_after": {
                    "character_id": ids["jia"],
                    "subject_id": lock,
                    "fields": ["opening_passphrase"],
                    "known_values": {"opening_passphrase": "潮落"},
                    "knowledge": "甲知道口令",
                },
            },
        ]
        await MemoryService().record_scene_events(
            db,
            novel_id,
            scene_id=str(first.id),
            scene_index=0,
            chapter_index=1,
            events=events,
            producer_family="browser_state_fixture",
        )
        second = await _scene(db, novel_id, 1, 2)
        second.title = "核对三簧锁"
        second.chapter_ids = ["2"]
        second.pov_character_id = ids["jia"]
        second.structure_meta = {"related_entity_ids": [ids["key"], lock]}
        await SceneMemoryProjectionService().ensure_scene(db, novel_id, str(second.id))
        result = {**ids, "lock": lock, "scene_id": str(second.id)}
    await engine.dispose()
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(seed(sys.argv[1]))

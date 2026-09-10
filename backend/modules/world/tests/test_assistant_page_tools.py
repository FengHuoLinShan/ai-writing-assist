import json
from uuid import UUID, uuid4

import pytest

from core.errors import ConflictError
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.schemas import WorkContext
from modules.world.assistant_page_tools import OPERATIONS
from modules.world.schemas import WorldBiblePageDraftCreate, WorldBiblePageDraftUpdate
from modules.world.services.worldbuilding.world_authority_service import (
    WorldAuthorityService,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)


@pytest.mark.asyncio
async def test_edit_publish_and_restore_use_original_world_baselines(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    owner = str(current_account_id())
    context = AssistantOperationContext(str(uuid4()), owner, WorkContext(scope="project"))
    service = WorldBibleLifecycleService()
    await WorldAuthorityService().initialize_empty_canon(db, nid)
    draft = await service.create_draft(
        db, WorldBiblePageDraftCreate(novel_id=nid, title="潮汐", free_text="旧说明")
    )
    edit = OPERATIONS["world.edit_page_draft"]
    args = edit.schema(
        draft_id=draft.id,
        free_text="新说明",
        sections=[{"section_id": "rule", "title": "规律", "body_markdown": "每日两次"}],
    )
    preview = await edit.prepare(db, nid, args, context=context)
    json.dumps(preview)
    assert (await service.get_draft(db, nid, draft.id)).free_text == "旧说明"
    await edit.apply(db, nid, args, preview, context=context)
    with pytest.raises(ConflictError):
        await edit.apply(db, nid, args, preview, context=context)
    publish = OPERATIONS["world.publish_page_draft"]
    args = publish.schema(draft_id=draft.id)
    preview = await publish.prepare(db, nid, args, context=context)
    json.dumps(preview)
    receipt = await publish.apply(db, nid, args, preview, context=context)
    page_id = receipt["id"]
    assert receipt["version_number"] == 1
    assert await WorldAuthorityService().find_page_publication(db, nid, draft.id) == {
        "page_id": page_id,
        "version_number": 1,
    }
    from core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await WorldAuthorityService().find_page_publication(db, str(uuid4()), draft.id)
    from modules.evidence.contracts import VisibilityContextContract
    from modules.evidence.facade import inspect_novel_target

    history_target = {
        "target_type": "world_bible_page_history",
        "target_id": page_id,
        "target_path": "1",
    }
    history = await inspect_novel_target(
        db,
        novel_id=nid,
        target_ref=history_target,
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="author"),
    )
    assert history["visible"] and "新说明" in json.dumps(history, ensure_ascii=False)
    restricted = await inspect_novel_target(
        db,
        novel_id=nid,
        target_ref=history_target,
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="reader", cutoff_chapter=1),
    )
    assert not restricted["visible"]
    assert (await service.get_page_model(db, nid, page_id)).free_text == "新说明"
    edit_args = edit.schema(page_id=page_id, free_text="后来的新说明")
    edit_preview = await edit.prepare(db, nid, edit_args, context=context)
    assert not await service.has_active_draft(db, UUID(nid), UUID(page_id))
    result = await edit.apply(db, nid, edit_args, edit_preview, context=context)
    restore = OPERATIONS["world.restore_page_revision"]
    restore_args = restore.schema(page_id=page_id, version_number=1)
    with pytest.raises(ConflictError, match="工作稿"):
        await restore.prepare(db, nid, restore_args, context=context)
    # Use the original controlled discard before restoring a historical version.
    await service.discard_draft(db, nid, result["id"])
    restore_preview = await restore.prepare(db, nid, restore_args, context=context)
    restored = await restore.apply(
        db, nid, restore_args, restore_preview, context=context
    )
    assert (await service.get_draft(db, nid, restored["id"])).free_text == "新说明"
    assert (await service.get_page_model(db, nid, page_id)).version_number == 1
    await service.update_draft(
        db, nid, restored["id"], WorldBiblePageDraftUpdate(free_text="作者又改了稿")
    )
    with pytest.raises(ConflictError):
        await restore.apply(db, nid, restore_args, restore_preview, context=context)

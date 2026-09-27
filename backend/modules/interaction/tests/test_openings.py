from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.interaction.openings import (
    InteractionOpeningService,
    OpeningSaveRequest,
    OpeningStartRequest,
)
from modules.interaction.tests.test_public_demo import _public_source

pytestmark = pytest.mark.asyncio


def data_for(revision, anchor):
    return OpeningSaveRequest(
        title="港口问路",
        description="从日常探索开始。",
        experience_kind="exploration",
        source_setup={
            "source_revision_id": str(revision.id),
            "progress_anchor_key": anchor["anchor_key"],
            "player_identity": {"kind": "original", "name": "旅人"},
        },
        opening_text="我站在港口，先向码头工人询问旅店。请让我自由决定下一步。",
    )


async def test_opening_preserves_source_owner_cas_and_start_idempotency(
    db_session, project_factory
):
    revision, anchor, _key = await _public_source(db_session, project_factory)
    service = InteractionOpeningService()
    data = data_for(revision, anchor)
    identity = str(uuid.uuid4())
    token = bind_principal(
        AccountPrincipal(revision.owner_id, "active", "local", "local")
    )
    try:
        first = await service.save(
            db_session, str(revision.source_novel_id), identity, data
        )
        repeat = await service.save(
            db_session, str(revision.source_novel_id), identity, data
        )
        assert first["id"] == repeat["id"]
        assert first["updated_at"].replace(tzinfo=None) == repeat["updated_at"].replace(
            tzinfo=None
        )
        with pytest.raises(ConflictError):
            await service.save(
                db_session,
                str(revision.source_novel_id),
                identity,
                data.model_copy(update={"title": "已变化"}),
            )
        listed = await service.list(db_session)
        assert [card["id"] for card in listed["items"]] == [identity]
        with patch(
            "modules.interaction.services.InteractionService.create_journey",
            autospec=True,
            return_value={"ok": True},
        ) as create:
            await service.start(
                db_session,
                identity,
                OpeningStartRequest(idempotency_key="stable-key-123"),
            )
        sent = create.call_args.args[2]
        assert sent.idempotency_key == "stable-key-123"
        assert sent.source_setup == data.source_setup
        assert sent.opening_text == data.opening_text
        assert not sent.see_sea_enabled and not sent.web_search_enabled
    finally:
        reset_principal(token)
    with pytest.raises(NotFoundError):
        await service.start(
            db_session, identity, OpeningStartRequest(idempotency_key="another-key-123")
        )
    assert (await service.list(db_session))["items"] == []


async def test_opening_image_is_bound_to_visible_object_and_exact_version(
    db_session, project_factory
):
    revision, anchor, _key = await _public_source(db_session, project_factory)
    service = InteractionOpeningService()
    entity_id = revision.reference_manifest[0]["target_id"]
    image_version = str(uuid.uuid4())
    data = OpeningSaveRequest.model_validate(
        {
            **data_for(revision, anchor).model_dump(),
            "image_reference": {
                "entity_id": entity_id,
                "image_version": image_version,
                "reviewed_for_anchor": True,
            },
        }
    )
    token = bind_principal(
        AccountPrincipal(revision.owner_id, "active", "local", "local")
    )
    try:
        with patch(
            "modules.interaction.openings.read_world_object_image",
            autospec=True,
            return_value=b"image",
        ) as read:
            card = await service.save(
                db_session, str(revision.source_novel_id), str(uuid.uuid4()), data
            )
            assert await service.image(db_session, card["id"]) == b"image"
            assert read.call_args.kwargs["expected_version"] == image_version
            assert read.call_args.kwargs["novel_id"] == str(revision.source_novel_id)
        foreign = data.model_copy(
            update={
                "image_reference": data.image_reference.model_copy(
                    update={"entity_id": uuid.uuid4()}
                )
            }
        )
        with pytest.raises(ValidationError, match="尚未"):
            await service.save(
                db_session, str(revision.source_novel_id), str(uuid.uuid4()), foreign
            )
    finally:
        reset_principal(token)

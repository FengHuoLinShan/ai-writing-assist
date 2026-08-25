"""Story asset service: immutable revisions, explicit adoption, and CAS."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.facade import get_completed_task_payload
from modules.story.generation import (
    STORY_CARD_TASK,
    STORY_CHARACTER_CARD_ACTION,
    STORY_ONE_CLICK_ACTION,
    STORY_ONE_CLICK_TASK,
    STORY_SCRIPT_ACTION,
    STORY_SCRIPT_TASK,
)
from modules.story.models import (
    CharacterCard,
    CharacterCardRevision,
    SceneScriptFile,
    SceneScriptRevision,
)
from modules.story.outline_state.facade import (
    get_scene_contract,
    get_scene_execution_bundle,
)
from modules.story.outline_state.story_outline_service import StoryOutlineService
from modules.story.repositories import (
    CharacterCardRepository,
    CharacterCardRevisionRepository,
    SceneScriptFileRepository,
    SceneScriptRevisionRepository,
)
from modules.story.schemas import (
    CardPreview,
    CharacterCardContent,
    CharacterCardResponse,
    CharacterCardRevisionResponse,
    OneClickOutput,
    SceneScriptFileResponse,
    SceneScriptRevisionResponse,
    StorySceneContextResponse,
)
from modules.world.facade import get_characters_context


class StoryNotFoundError(LookupError):
    """The requested Story asset is absent from this novel."""


class StoryConflictError(ValueError):
    """A compare-and-swap or immutable-state operation conflicted."""

    def __init__(self, message: str, *, latest: Any = None) -> None:
        super().__init__(message)
        self.latest = latest


class StoryAuthorizationError(PermissionError):
    """An explicit author confirmation/submit authorization is missing."""


def _uuid(value: str | uuid.UUID, field: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"invalid {field}") from exc


def _hash_payload(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _as_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return {"value": value}


class StoryService:
    """Own Story-layer writes and read models; never mutates other domains."""

    def __init__(self) -> None:
        self.cards = CharacterCardRepository()
        self.card_revisions = CharacterCardRevisionRepository()
        self.script_files = SceneScriptFileRepository()
        self.script_revisions = SceneScriptRevisionRepository()

    async def _require_character(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_id: uuid.UUID,
    ) -> Any:
        bundle = await get_characters_context(
            db,
            str(novel_id),
            [str(character_id)],
            reveal_mode="author_only",
        )
        if not bundle.characters or str(bundle.characters[0].character_id) != str(
            character_id
        ):
            raise StoryNotFoundError("character does not belong to this novel")
        return bundle.characters[0]

    async def _require_scene(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
    ) -> Any:
        scene = await get_scene_contract(db, str(novel_id), str(scene_id))
        if scene is None:
            raise StoryNotFoundError("scene does not belong to this novel")
        return scene

    @staticmethod
    def _check_expected(
        expected: uuid.UUID | None,
        current: uuid.UUID | None,
        *,
        resource: str,
    ) -> None:
        if expected != current:
            raise StoryConflictError(
                f"{resource} changed; expected current revision "
                f"{expected}, actual {current}"
            )

    async def _validate_source_provenance(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        source_task_id: uuid.UUID | None,
        context_snapshot_id: uuid.UUID | None,
        resource: str,
    ) -> None:
        """Accept only completed Story previews from the same novel/action."""
        if source_task_id is None:
            if context_snapshot_id is not None:
                raise StoryAuthorizationError(
                    "context_snapshot_id requires a completed source_task_id"
                )
            return
        expected = {
            "card": {
                STORY_CARD_TASK: STORY_CHARACTER_CARD_ACTION,
                STORY_ONE_CLICK_TASK: STORY_ONE_CLICK_ACTION,
            },
            "script": {
                STORY_SCRIPT_TASK: STORY_SCRIPT_ACTION,
                STORY_ONE_CLICK_TASK: STORY_ONE_CLICK_ACTION,
            },
        }[resource]
        source = None
        for task_type in expected:
            source = await get_completed_task_payload(
                db,
                task_id=str(source_task_id),
                task_type=task_type,
                novel_id=str(novel_id),
            )
            if source is not None:
                break
        if source is None or source.action != expected.get(source.task_type):
            raise StoryAuthorizationError(
                "source_task_id must reference a completed Story preview "
                "of the expected action"
            )
        if context_snapshot_id is not None:
            result_snapshot_id = source.result.get("context_snapshot_id")
            if str(result_snapshot_id or "") != str(context_snapshot_id):
                raise StoryAuthorizationError(
                    "context_snapshot_id does not match the source task result"
                )

    async def _card_revision_response(
        self,
        db: AsyncSession,
        card: CharacterCard,
        revision: CharacterCardRevision | None = None,
    ) -> CharacterCardResponse:
        if revision is None and card.current_revision_id is not None:
            revision = await self.card_revisions.get(
                db,
                card.novel_id,
                card.current_revision_id,
            )
        return self._card_response(card, revision)

    @staticmethod
    def _card_response(
        card: CharacterCard,
        revision: CharacterCardRevision | None,
    ) -> CharacterCardResponse:
        revision_response = None
        if revision is not None:
            revision_response = CharacterCardRevisionResponse(
                id=revision.id,
                card_id=revision.card_id,
                novel_id=revision.novel_id,
                character_id=revision.character_id,
                scene_id=revision.scene_id,
                version_number=revision.version_number,
                content=CharacterCardContent.model_validate(revision.payload_json),
                content_hash=revision.content_hash,
                source=revision.source,
                status=revision.status,
                authorization_ref=revision.authorization_ref,
                source_manifest=revision.source_manifest_json or {},
                source_task_id=revision.source_task_id,
                context_snapshot_id=revision.context_snapshot_id,
                base_revision_id=revision.base_revision_id,
                restored_from_revision_id=revision.restored_from_revision_id,
                created_at=revision.created_at,
                is_current=revision.id == card.current_revision_id,
            )
        return CharacterCardResponse(
            id=card.id,
            novel_id=card.novel_id,
            character_id=card.character_id,
            scene_id=card.scene_id,
            current_revision_id=card.current_revision_id,
            current_version_number=card.current_version_number,
            status=card.status,
            stale=card.stale,
            stale_reason=card.stale_reason,
            revision=revision_response,
            updated_at=card.updated_at,
        )

    async def get_card(
        self,
        db: AsyncSession,
        novel_id: str | uuid.UUID,
        card_id: str | uuid.UUID,
    ) -> CharacterCardResponse:
        nid = _uuid(novel_id, "novel_id")
        card = await self.cards.get(db, nid, _uuid(card_id, "card_id"))
        if card is None:
            raise StoryNotFoundError("character card not found")
        return await self._card_revision_response(db, card)

    async def list_cards(
        self,
        db: AsyncSession,
        novel_id: str | uuid.UUID,
        *,
        scene_id: str | uuid.UUID | None = None,
        character_ids: Iterable[str] | None = None,
    ) -> list[CharacterCardResponse]:
        nid = _uuid(novel_id, "novel_id")
        normalized = (
            [_uuid(value, "character_id") for value in character_ids]
            if character_ids is not None
            else None
        )
        normalized_scene = _uuid(scene_id, "scene_id") if scene_id is not None else None
        cards = await self.cards.list(
            db,
            nid,
            scene_id=normalized_scene,
            character_ids=normalized,
        )
        revisions = await self.card_revisions.get_many(
            db,
            nid,
            [card.current_revision_id for card in cards if card.current_revision_id],
        )
        return [
            self._card_response(card, revisions.get(card.current_revision_id))
            for card in cards
        ]

    async def list_card_revisions(
        self,
        db: AsyncSession,
        novel_id: str | uuid.UUID,
        card_id: str | uuid.UUID,
    ) -> list[CharacterCardRevisionResponse]:
        nid = _uuid(novel_id, "novel_id")
        cid = _uuid(card_id, "card_id")
        card = await self.cards.get(db, nid, cid)
        if card is None:
            raise StoryNotFoundError("character card not found")
        revisions = await self.card_revisions.list_for_card(db, nid, cid)
        return [
            CharacterCardRevisionResponse(
                id=revision.id,
                card_id=revision.card_id,
                novel_id=revision.novel_id,
                character_id=revision.character_id,
                scene_id=revision.scene_id,
                version_number=revision.version_number,
                content=CharacterCardContent.model_validate(revision.payload_json),
                content_hash=revision.content_hash,
                source=revision.source,
                status=revision.status,
                authorization_ref=revision.authorization_ref,
                source_manifest=revision.source_manifest_json or {},
                source_task_id=revision.source_task_id,
                context_snapshot_id=revision.context_snapshot_id,
                base_revision_id=revision.base_revision_id,
                restored_from_revision_id=revision.restored_from_revision_id,
                created_at=revision.created_at,
                is_current=revision.id == card.current_revision_id,
            )
            for revision in revisions
        ]

    async def create_manual_card(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        character_id: str,
        content: CharacterCardContent,
        expected_revision_id: uuid.UUID | None = None,
        source_manifest: dict[str, Any] | None = None,
        source: str = "manual",
        authorization_ref: str | None = None,
        restored_from_revision_id: uuid.UUID | None = None,
        source_task_id: uuid.UUID | None = None,
        context_snapshot_id: uuid.UUID | None = None,
        _trusted_running_task: bool = False,
    ) -> CharacterCardResponse:
        nid = _uuid(novel_id, "novel_id")
        sid = _uuid(scene_id, "scene_id")
        char_id = _uuid(character_id, "character_id")
        await self._require_scene(db, nid, sid)
        await self._require_character(db, nid, char_id)
        if not _trusted_running_task:
            await self._validate_source_provenance(
                db,
                novel_id=nid,
                source_task_id=source_task_id,
                context_snapshot_id=context_snapshot_id,
                resource="card",
            )
        card = await self.cards.get_by_character(db, nid, sid, char_id, for_update=True)
        if card is None:
            if expected_revision_id is not None:
                raise StoryConflictError(
                    "character card does not have a current revision"
                )
            card = await self.cards.create(
                db,
                CharacterCard(
                    novel_id=nid,
                    scene_id=sid,
                    character_id=char_id,
                    status="active",
                    current_version_number=0,
                    stale=False,
                ),
            )
        else:
            try:
                self._check_expected(
                    expected_revision_id,
                    card.current_revision_id,
                    resource="character card",
                )
            except StoryConflictError as exc:
                latest = await self._card_revision_response(db, card)
                raise StoryConflictError(
                    str(exc),
                    latest=latest.model_dump(mode="json"),
                ) from exc
        version = await self.card_revisions.get_latest_version(db, nid, card.id) + 1
        payload = content.model_dump(mode="json")
        revision = await self.card_revisions.create(
            db,
            CharacterCardRevision(
                novel_id=nid,
                card_id=card.id,
                scene_id=sid,
                character_id=char_id,
                version_number=version,
                payload_json=payload,
                content_hash=_hash_payload(payload),
                source=source,
                status="accepted",
                authorization_ref=authorization_ref,
                source_manifest_json=source_manifest or {},
                source_task_id=source_task_id,
                context_snapshot_id=context_snapshot_id,
                base_revision_id=card.current_revision_id,
                restored_from_revision_id=restored_from_revision_id,
            ),
        )
        card.current_revision_id = revision.id
        card.current_version_number = version
        card.status = "active"
        card.stale = False
        card.stale_reason = None
        await db.flush()
        return await self._card_revision_response(db, card, revision)

    async def restore_card_revision(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        card_id: str,
        revision_id: uuid.UUID,
        expected_revision_id: uuid.UUID | None,
    ) -> CharacterCardResponse:
        nid = _uuid(novel_id, "novel_id")
        cid = _uuid(card_id, "card_id")
        card = await self.cards.get(db, nid, cid, for_update=True)
        if card is None:
            raise StoryNotFoundError("character card not found")
        source = await self.card_revisions.get(db, nid, revision_id)
        if source is None or source.card_id != card.id:
            raise StoryNotFoundError("character card revision not found")
        try:
            self._check_expected(
                expected_revision_id,
                card.current_revision_id,
                resource="character card",
            )
        except StoryConflictError as exc:
            latest = await self._card_revision_response(db, card)
            raise StoryConflictError(
                str(exc),
                latest=latest.model_dump(mode="json"),
            ) from exc
        content = CharacterCardContent.model_validate(source.payload_json)
        return await self.create_manual_card(
            db,
            novel_id=str(nid),
            scene_id=str(card.scene_id),
            character_id=str(card.character_id),
            content=content,
            expected_revision_id=card.current_revision_id,
            source_manifest=source.source_manifest_json,
            source="restored",
            restored_from_revision_id=source.id,
        )

    async def archive_card_revision(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        card_id: str,
        revision_id: uuid.UUID,
        expected_revision_id: uuid.UUID | None,
    ) -> None:
        nid = _uuid(novel_id, "novel_id")
        card = await self.cards.get(db, nid, _uuid(card_id, "card_id"), for_update=True)
        if card is None:
            raise StoryNotFoundError("character card not found")
        try:
            self._check_expected(
                expected_revision_id,
                card.current_revision_id,
                resource="character card",
            )
        except StoryConflictError as exc:
            latest = await self._card_revision_response(db, card)
            raise StoryConflictError(
                str(exc),
                latest=latest.model_dump(mode="json"),
            ) from exc
        revision = await self.card_revisions.get(db, nid, revision_id, for_update=True)
        if revision is None or revision.card_id != card.id:
            raise StoryNotFoundError("character card revision not found")
        if revision.id == card.current_revision_id:
            raise StoryConflictError("current character card revision cannot be archived")
        revision.status = "archived"
        await db.flush()

    async def persist_one_click_cards(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        output: OneClickOutput,
        requested_character_ids: list[str],
        submit_authorized: bool,
        authorization_ref: str,
        source_task_id: uuid.UUID | None = None,
        context_snapshot_id: uuid.UUID | None = None,
        source_hashes: dict[str, str] | None = None,
    ) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
        """Persist only explicitly authorized missing/stale card candidates."""
        if not submit_authorized:
            return [], []
        nid = _uuid(novel_id, "novel_id")
        sid = _uuid(output.scene_id, "scene_id")
        await self._require_scene(db, nid, sid)
        requested = {_uuid(value, "character_id") for value in requested_character_ids}
        candidates: dict[uuid.UUID, CardPreview] = {}
        for candidate in output.cards:
            if candidate.character_id not in requested:
                raise StoryAuthorizationError(
                    "one-click output contains a character outside the submitted scope"
                )
            if candidate.character_id in candidates:
                raise StoryConflictError("one-click output contains duplicate characters")
            candidates[candidate.character_id] = candidate
        if set(candidates) != requested:
            raise StoryAuthorizationError(
                "one-click output must contain exactly the submitted characters"
            )
        persisted: list[uuid.UUID] = []
        skipped_fresh: list[uuid.UUID] = []
        for character_id, candidate in candidates.items():
            await self._require_character(db, nid, character_id)
            card = await self.cards.get_by_character(
                db,
                nid,
                sid,
                character_id,
                for_update=True,
            )
            current_source_hash = (
                source_hashes.get(str(character_id)) if source_hashes else None
            )
            current_revision = None
            if card is not None and card.current_revision_id is not None:
                current_revision = await self.card_revisions.get(
                    db,
                    nid,
                    card.current_revision_id,
                )
            stored_source_hash = (
                (current_revision.source_manifest_json or {}).get("source_hash")
                if current_revision is not None
                and current_revision.source == "ai_one_click"
                else None
            )
            if (
                card is not None
                and not card.stale
                and card.current_revision_id is not None
                and current_source_hash
                and stored_source_hash == current_source_hash
            ):
                skipped_fresh.append(character_id)
                continue
            source_manifest = {"workflow": "story.one_click"}
            if current_source_hash:
                source_manifest["source_hash"] = current_source_hash
            saved = await self.create_manual_card(
                db,
                novel_id=str(nid),
                scene_id=str(sid),
                character_id=str(character_id),
                content=candidate.content,
                expected_revision_id=(card.current_revision_id if card else None),
                source_manifest=source_manifest,
                source="ai_one_click",
                authorization_ref=authorization_ref,
                source_task_id=source_task_id,
                context_snapshot_id=context_snapshot_id,
                _trusted_running_task=True,
            )
            if saved.current_revision_id is not None:
                persisted.append(saved.current_revision_id)
        return persisted, skipped_fresh

    async def create_script_file(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        file_key: str,
        title: str,
    ) -> SceneScriptFileResponse:
        nid = _uuid(novel_id, "novel_id")
        sid = _uuid(scene_id, "scene_id")
        await self._require_scene(db, nid, sid)
        file = await self.script_files.get_by_key(db, nid, sid, file_key)
        if file is None:
            file = await self.script_files.create(
                db,
                SceneScriptFile(
                    novel_id=nid,
                    scene_id=sid,
                    file_key=file_key,
                    title=title,
                    status="active",
                    current_version_number=0,
                ),
            )
        return await self._script_file_response(db, file)

    async def _script_revision_response(
        self,
        revision: SceneScriptRevision,
        current_revision_id: uuid.UUID | None,
        adopted_revision_id: uuid.UUID | None,
    ) -> SceneScriptRevisionResponse:
        return SceneScriptRevisionResponse(
            id=revision.id,
            file_id=revision.file_id,
            novel_id=revision.novel_id,
            scene_id=revision.scene_id,
            file_key=revision.file_key,
            version_number=revision.version_number,
            content=revision.content,
            content_json=revision.content_json,
            content_hash=revision.content_hash,
            source=revision.source,
            status=revision.status,
            authorization_ref=revision.authorization_ref,
            provenance=revision.provenance_json or {},
            source_task_id=revision.source_task_id,
            context_snapshot_id=revision.context_snapshot_id,
            base_revision_id=revision.base_revision_id,
            created_at=revision.created_at,
            is_current=revision.id == current_revision_id,
            is_adopted=revision.id == adopted_revision_id,
        )

    async def _script_file_response(
        self,
        db: AsyncSession,
        file: SceneScriptFile,
        revisions: dict[uuid.UUID, SceneScriptRevision] | None = None,
    ) -> SceneScriptFileResponse:
        revision = None
        adopted_revision = None
        if file.current_revision_id is not None:
            current = (
                revisions.get(file.current_revision_id)
                if revisions is not None
                else await self.script_revisions.get(
                    db,
                    file.novel_id,
                    file.current_revision_id,
                )
            )
            if current is not None and current.file_id == file.id:
                revision = await self._script_revision_response(
                    current,
                    file.current_revision_id,
                    file.adopted_revision_id,
                )
        if file.adopted_revision_id is not None:
            adopted = (
                revisions.get(file.adopted_revision_id)
                if revisions is not None
                else await self.script_revisions.get(
                    db,
                    file.novel_id,
                    file.adopted_revision_id,
                )
            )
            if adopted is not None and adopted.file_id == file.id:
                adopted_revision = await self._script_revision_response(
                    adopted,
                    file.current_revision_id,
                    file.adopted_revision_id,
                )
        return SceneScriptFileResponse(
            id=file.id,
            novel_id=file.novel_id,
            scene_id=file.scene_id,
            file_key=file.file_key,
            title=file.title,
            current_revision_id=file.current_revision_id,
            current_version_number=file.current_version_number,
            adopted_revision_id=file.adopted_revision_id,
            adopted_version_number=file.adopted_version_number,
            status=file.status,
            revision=revision,
            adopted_revision=adopted_revision,
            updated_at=file.updated_at,
        )

    async def list_script_files(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
    ) -> list[SceneScriptFileResponse]:
        nid = _uuid(novel_id, "novel_id")
        sid = _uuid(scene_id, "scene_id")
        await self._require_scene(db, nid, sid)
        files = await self.script_files.list_for_scene(db, nid, sid)
        revision_ids = {
            revision_id
            for file in files
            for revision_id in (file.current_revision_id, file.adopted_revision_id)
            if revision_id is not None
        }
        revisions = await self.script_revisions.get_many(
            db,
            nid,
            list(revision_ids),
        )
        return [
            await self._script_file_response(db, file, revisions) for file in files
        ]

    async def get_script_file(
        self,
        db: AsyncSession,
        novel_id: str,
        file_id: str,
    ) -> SceneScriptFileResponse:
        nid = _uuid(novel_id, "novel_id")
        file = await self.script_files.get(db, nid, _uuid(file_id, "file_id"))
        if file is None:
            raise StoryNotFoundError("scene script file not found")
        return await self._script_file_response(db, file)

    async def list_script_revisions(
        self,
        db: AsyncSession,
        novel_id: str,
        file_id: str,
    ) -> list[SceneScriptRevisionResponse]:
        nid = _uuid(novel_id, "novel_id")
        fid = _uuid(file_id, "file_id")
        file = await self.script_files.get(db, nid, fid)
        if file is None:
            raise StoryNotFoundError("scene script file not found")
        revisions = await self.script_revisions.list_for_file(db, nid, fid)
        return [
            await self._script_revision_response(
                revision,
                file.current_revision_id,
                file.adopted_revision_id,
            )
            for revision in revisions
        ]

    async def create_script_revision(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        file_key: str,
        content: str,
        content_json: dict[str, Any] | list[Any] | None,
        expected_revision_id: uuid.UUID | None,
        adopt: bool,
        provenance: dict[str, Any] | None = None,
        expected_adopted_revision_id: uuid.UUID | None = None,
        source_task_id: uuid.UUID | None = None,
        context_snapshot_id: uuid.UUID | None = None,
    ) -> SceneScriptFileResponse:
        nid = _uuid(novel_id, "novel_id")
        sid = _uuid(scene_id, "scene_id")
        await self._require_scene(db, nid, sid)
        await self._validate_source_provenance(
            db,
            novel_id=nid,
            source_task_id=source_task_id,
            context_snapshot_id=context_snapshot_id,
            resource="script",
        )
        file = await self.script_files.get_by_key(
            db,
            nid,
            sid,
            file_key,
            for_update=True,
        )
        if file is None:
            if expected_revision_id is not None:
                raise StoryConflictError("script file has no current revision")
            file = await self.script_files.create(
                db,
                SceneScriptFile(
                    novel_id=nid,
                    scene_id=sid,
                    file_key=file_key,
                    title=file_key.replace("_", " ").title(),
                    status="active",
                    current_version_number=0,
                ),
            )
        try:
            self._check_expected(
                expected_revision_id,
                file.current_revision_id,
                resource="scene script file",
            )
        except StoryConflictError as exc:
            latest = await self._script_file_response(db, file)
            raise StoryConflictError(
                str(exc),
                latest=latest.model_dump(mode="json"),
            ) from exc
        version = await self.script_revisions.get_latest_version(db, nid, file.id) + 1
        basis_hash = await self.get_scene_story_basis_hash(
            db,
            novel_id=str(nid),
            scene_id=str(sid),
            exclude_file_id=str(file.id),
        )
        revision_provenance = {
            **(provenance or {}),
            "basis_hash": basis_hash,
            "basis_manifest": {
                "scene_id": str(sid),
                "excluded_script_file_id": str(file.id),
            },
        }
        revision = await self.script_revisions.create(
            db,
            SceneScriptRevision(
                novel_id=nid,
                file_id=file.id,
                scene_id=sid,
                file_key=file_key,
                version_number=version,
                content=content,
                content_json=content_json,
                content_hash=_hash_payload(
                    {"content": content, "content_json": content_json}
                ),
                source="manual",
                status="candidate",
                provenance_json=revision_provenance,
                source_task_id=source_task_id,
                context_snapshot_id=context_snapshot_id,
                base_revision_id=file.current_revision_id,
            ),
        )
        file.current_revision_id = revision.id
        file.current_version_number = revision.version_number
        file.status = "active"
        if adopt:
            old_adopted = file.adopted_revision_id
            try:
                self._adopt_locked(file, revision, expected_adopted_revision_id)
            except StoryConflictError as exc:
                latest = await self._script_file_response(db, file)
                raise StoryConflictError(
                    str(exc),
                    latest=latest.model_dump(mode="json"),
                ) from exc
            if old_adopted is not None and old_adopted != revision.id:
                old = await self.script_revisions.get(
                    db,
                    nid,
                    old_adopted,
                    for_update=True,
                )
                if old is not None:
                    old.status = (
                        "working" if old.id == file.current_revision_id else "archived"
                    )
        await db.flush()
        return await self._script_file_response(db, file)

    @staticmethod
    def _adopt_locked(
        file: SceneScriptFile,
        revision: SceneScriptRevision,
        expected_adopted_revision_id: uuid.UUID | None,
    ) -> None:
        if revision.file_id != file.id:
            raise StoryNotFoundError("scene script revision not found")
        if revision.status == "archived":
            raise StoryConflictError("archived script revision cannot be adopted")
        if expected_adopted_revision_id != file.adopted_revision_id:
            raise StoryConflictError("scene script adoption changed before adoption")
        file.adopted_revision_id = revision.id
        file.adopted_version_number = revision.version_number
        file.status = "active"
        revision.status = "adopted"

    async def adopt_script_revision(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        file_id: str,
        revision_id: uuid.UUID,
        expected_revision_id: uuid.UUID | None,
    ) -> SceneScriptFileResponse:
        nid = _uuid(novel_id, "novel_id")
        file = await self.script_files.get(
            db, nid, _uuid(file_id, "file_id"), for_update=True
        )
        if file is None:
            raise StoryNotFoundError("scene script file not found")
        revision = await self.script_revisions.get(db, nid, revision_id, for_update=True)
        if revision is None or revision.file_id != file.id:
            raise StoryNotFoundError("scene script revision not found")
        old_adopted = file.adopted_revision_id
        try:
            self._adopt_locked(file, revision, expected_revision_id)
        except StoryConflictError as exc:
            latest = await self._script_file_response(db, file)
            raise StoryConflictError(
                str(exc),
                latest=latest.model_dump(mode="json"),
            ) from exc
        if old_adopted is not None and old_adopted != revision.id:
            old = await self.script_revisions.get(db, nid, old_adopted, for_update=True)
            if old is not None:
                old.status = (
                    "working" if old.id == file.current_revision_id else "archived"
                )
        if file.adopted_revision_id != revision.id:
            raise StoryConflictError("scene script adoption failed")
        await db.flush()
        return await self._script_file_response(db, file)

    async def archive_script_revision(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        file_id: str,
        revision_id: uuid.UUID,
    ) -> None:
        nid = _uuid(novel_id, "novel_id")
        file = await self.script_files.get(
            db, nid, _uuid(file_id, "file_id"), for_update=True
        )
        if file is None:
            raise StoryNotFoundError("scene script file not found")
        revision = await self.script_revisions.get(db, nid, revision_id, for_update=True)
        if revision is None or revision.file_id != file.id:
            raise StoryNotFoundError("scene script revision not found")
        if revision.id in {file.current_revision_id, file.adopted_revision_id}:
            raise StoryConflictError(
                "current or adopted script revision cannot be archived"
            )
        revision.status = "archived"
        await db.flush()

    async def unadopt_script_file(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        file_id: str,
        expected_revision_id: uuid.UUID,
    ) -> SceneScriptFileResponse:
        nid = _uuid(novel_id, "novel_id")
        file = await self.script_files.get(
            db,
            nid,
            _uuid(file_id, "file_id"),
            for_update=True,
        )
        if file is None:
            raise StoryNotFoundError("scene script file not found")
        try:
            self._check_expected(
                expected_revision_id,
                file.adopted_revision_id,
                resource="adopted scene script",
            )
        except StoryConflictError as exc:
            latest = await self._script_file_response(db, file)
            raise StoryConflictError(
                str(exc),
                latest=latest.model_dump(mode="json"),
            ) from exc
        adopted = await self.script_revisions.get(
            db,
            nid,
            expected_revision_id,
            for_update=True,
        )
        if adopted is None or adopted.file_id != file.id:
            raise StoryNotFoundError("adopted scene script revision not found")
        adopted.status = (
            "working" if adopted.id == file.current_revision_id else "archived"
        )
        file.adopted_revision_id = None
        file.adopted_version_number = 0
        await db.flush()
        return await self._script_file_response(db, file)

    async def get_scene_story_assets(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        character_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Return adopted Story assets without calling Outline's bundle seam.

        Outline uses this narrow read seam to enrich its execution bundle.  It
        intentionally does not recurse through ``get_scene_story_context``.
        """
        nid = _uuid(novel_id, "novel_id")
        sid = _uuid(scene_id, "scene_id")
        scene = await self._require_scene(db, nid, sid)
        normalized_character_ids = (
            [_uuid(value, "character_id") for value in character_ids]
            if character_ids is not None
            else None
        )
        card_models = await self.cards.list(
            db,
            nid,
            scene_id=sid,
            character_ids=normalized_character_ids,
        )
        card_revisions = await self.card_revisions.get_many(
            db,
            nid,
            [
                card.current_revision_id
                for card in card_models
                if card.current_revision_id is not None
            ],
        )
        cards = [
            self._card_response(card, card_revisions.get(card.current_revision_id))
            for card in card_models
        ]
        file_models = await self.script_files.list_for_scene(db, nid, sid)
        script_revision_ids = {
            revision_id
            for file in file_models
            for revision_id in (file.current_revision_id, file.adopted_revision_id)
            if revision_id is not None
        }
        script_revisions = await self.script_revisions.get_many(
            db,
            nid,
            list(script_revision_ids),
        )
        files = [
            await self._script_file_response(db, file, script_revisions)
            for file in file_models
        ]
        current_outline = await StoryOutlineService().get_current(db, str(nid))
        basis_components = self._story_basis_components(
            scene=scene,
            outline_revision=current_outline.revision,
            cards=card_models,
            card_revisions=card_revisions,
            files=file_models,
            script_revisions=script_revisions,
        )
        adopted_files = [item for item in files if item.adopted_revision is not None]
        beats: list[Any] = []
        snapshots: set[str] = set()
        for item in cards:
            if item.revision and item.revision.context_snapshot_id:
                snapshots.add(str(item.revision.context_snapshot_id))
        for item in adopted_files:
            revision = item.adopted_revision
            if revision is None:
                continue
            if revision.context_snapshot_id:
                snapshots.add(str(revision.context_snapshot_id))
            raw = revision.content_json
            if isinstance(raw, dict) and isinstance(raw.get("beats"), list):
                beats.extend(raw["beats"])
            elif isinstance(raw, list):
                beats.extend(raw)
        adopted_script_payloads = [
            await self._adopted_script_asset_payload(
                db,
                item,
                expected_basis_hash=self._story_basis_hash_from_components(
                    basis_components,
                    exclude_file_id=str(item.id),
                ),
            )
            for item in adopted_files
        ]
        payload = {
            "scene_id": str(sid),
            "character_cards": [item.model_dump(mode="json") for item in cards],
            "adopted_scripts": adopted_script_payloads,
            "context_snapshot_ids": sorted(snapshots),
            "beats": beats,
        }
        return {
            "adopted_assets_present": bool(cards or adopted_files),
            "character_cards": payload["character_cards"],
            "adopted_scripts": payload["adopted_scripts"],
            "context_snapshot_ids": payload["context_snapshot_ids"],
            "beats": beats,
            "story_context_hash": _hash_payload(payload),
        }

    async def _adopted_script_asset_payload(
        self,
        db: AsyncSession,
        item: SceneScriptFileResponse,
        *,
        expected_basis_hash: str | None = None,
    ) -> dict[str, Any]:
        revision = item.adopted_revision
        stored_basis_hash = (
            str((revision.provenance or {}).get("basis_hash") or "")
            if revision is not None
            else ""
        )
        if expected_basis_hash is None:
            expected_basis_hash = await self.get_scene_story_basis_hash(
                db,
                novel_id=str(item.novel_id),
                scene_id=str(item.scene_id),
                exclude_file_id=str(item.id),
            )
        stale = not stored_basis_hash or stored_basis_hash != expected_basis_hash
        return {
            "id": str(item.id),
            "novel_id": str(item.novel_id),
            "scene_id": str(item.scene_id),
            "file_key": item.file_key,
            "title": item.title,
            "adopted_revision_id": (
                str(item.adopted_revision_id) if item.adopted_revision_id else None
            ),
            "adopted_version_number": item.adopted_version_number,
            "adopted_revision": (
                revision.model_dump(mode="json") if revision else None
            ),
            "basis_hash": stored_basis_hash or None,
            "expected_basis_hash": expected_basis_hash,
            "stale": stale,
            "stale_reason": "upstream_story_assets_changed" if stale else None,
        }

    async def get_scene_story_basis_hash(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        exclude_file_id: str | None = None,
    ) -> str:
        """Hash upstream Scene/outline/cards/adopted scripts, excluding one file."""
        nid = _uuid(novel_id, "novel_id")
        sid = _uuid(scene_id, "scene_id")
        scene = await self._require_scene(db, nid, sid)
        current_outline = await StoryOutlineService().get_current(db, str(nid))
        cards = await self.cards.list(db, nid, scene_id=sid)
        card_revisions = await self.card_revisions.get_many(
            db,
            nid,
            [
                card.current_revision_id
                for card in cards
                if card.current_revision_id is not None
            ],
        )
        files = await self.script_files.list_for_scene(db, nid, sid)
        script_revisions = await self.script_revisions.get_many(
            db,
            nid,
            [
                file.adopted_revision_id
                for file in files
                if file.adopted_revision_id is not None
            ],
        )
        components = self._story_basis_components(
            scene=scene,
            outline_revision=current_outline.revision,
            cards=cards,
            card_revisions=card_revisions,
            files=files,
            script_revisions=script_revisions,
        )
        return self._story_basis_hash_from_components(
            components,
            exclude_file_id=exclude_file_id,
        )

    @staticmethod
    def _story_basis_components(
        *,
        scene: Any,
        outline_revision: Any,
        cards: list[CharacterCard],
        card_revisions: dict[uuid.UUID, CharacterCardRevision],
        files: list[SceneScriptFile],
        script_revisions: dict[uuid.UUID, SceneScriptRevision],
    ) -> dict[str, Any]:
        card_basis = []
        for card in cards:
            revision = card_revisions.get(card.current_revision_id)
            card_basis.append(
                {
                    "id": str(card.id),
                    "character_id": str(card.character_id),
                    "revision_id": str(revision.id) if revision else None,
                    "version": card.current_version_number,
                    "hash": revision.content_hash if revision else None,
                }
            )
        script_basis = []
        for file in files:
            revision = script_revisions.get(file.adopted_revision_id)
            if revision is None or revision.file_id != file.id:
                continue
            script_basis.append(
                {
                    "id": str(file.id),
                    "file_key": file.file_key,
                    "revision_id": str(revision.id),
                    "version": revision.version_number,
                    "hash": revision.content_hash,
                }
            )
        return {
            "scene": _as_dict(scene),
            "story_outline": (
                {
                    "id": str(outline_revision.id),
                    "version": outline_revision.version_number,
                    "hash": outline_revision.content_hash,
                }
                if outline_revision is not None
                else None
            ),
            "cards": card_basis,
            "adopted_scripts": script_basis,
        }

    @staticmethod
    def _story_basis_hash_from_components(
        components: dict[str, Any],
        *,
        exclude_file_id: str | None,
    ) -> str:
        scripts = components["adopted_scripts"]
        if exclude_file_id is not None:
            scripts = [item for item in scripts if item["id"] != exclude_file_id]
        return _hash_payload({**components, "adopted_scripts": scripts})

    async def get_scene_story_context(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        character_ids: Iterable[str] | None = None,
    ) -> StorySceneContextResponse | None:
        nid = _uuid(novel_id, "novel_id")
        sid = _uuid(scene_id, "scene_id")
        bundle = await get_scene_execution_bundle(db, str(nid), str(sid))
        if bundle is None:
            return None
        outline_payload = _as_dict(bundle)
        pov_id = getattr(bundle.scene, "pov_character_id", None)
        requested_cards = list(character_ids or [])
        if not requested_cards and pov_id:
            requested_cards = [pov_id]
        cards = await self.list_cards(
            db,
            str(nid),
            scene_id=str(sid),
            character_ids=requested_cards or None,
        )
        files = await self.list_script_files(db, str(nid), str(sid))
        omissions = list(getattr(bundle, "omissions", []) or [])
        if pov_id and not cards:
            omissions.append("pov_character_card")
        manifests = list(getattr(bundle, "upstream_manifest", []) or [])
        manifests.extend(
            {
                "type": "story_character_card",
                "id": str(item.character_id),
                "version": str(item.current_version_number),
                "hash": item.revision.content_hash if item.revision else "",
            }
            for item in cards
        )
        manifests.extend(
            {
                "type": "story_scene_script_file",
                "id": str(item.id),
                "version": str(item.current_version_number),
                "hash": item.revision.content_hash if item.revision else "",
            }
            for item in files
        )
        fingerprint = _hash_payload(
            {
                "outline": outline_payload,
                "cards": [item.model_dump(mode="json") for item in cards],
                "files": [item.model_dump(mode="json") for item in files],
                "omissions": omissions,
            }
        )
        return StorySceneContextResponse(
            novel_id=nid,
            scene_id=sid,
            outline_bundle=outline_payload,
            character_cards=cards,
            script_files=files,
            omissions=list(dict.fromkeys(omissions)),
            upstream_manifest=manifests,
            context_hash=fingerprint,
        )

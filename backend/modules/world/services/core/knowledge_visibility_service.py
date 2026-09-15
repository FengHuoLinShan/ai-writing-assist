"""批量知识可见性判定。

服务端在冻结任务范围内一次性判定「生成者能否看到某个 target」：
CharacterKnowledge（保守截止点前）覆盖优先 → public/tag/private（标签授予与
排除、private 无明确授权隐藏、rule draft 不参与判决）→ 与 ReaderRevealPolicy
取交集。判定只输出短原因，不携带隐藏正文；导演与生成者只能消费判定结果，
不能改写 owner、`novel_id`、角色权限、截止点或写入权限。
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.contracts import (
    KnowledgeVisibilityDecision,
    KnowledgeVisibilityRequest,
)
from modules.world.models import (
    AssetKnowledgeTag,
    CharacterKnowledgeTag,
    KnowledgeTagExclusion,
    KnowledgeVisibilityPolicy,
    ReaderRevealPolicy,
)
from modules.world.models.character import CharacterKnowledge
from modules.world.repositories import CharacterKnowledgeRepository
from shared.target_ref import target_hash
from shared.utils import parse_uuid

SOURCE_CHARACTER_KNOWLEDGE = "character_knowledge"
SOURCE_TAG_GRANT = "tag_grant"
SOURCE_PRIVATE_POLICY = "private_policy"
SOURCE_VISIBILITY_POLICY = "visibility_policy"
SOURCE_PUBLIC_DEFAULT = "public_default"

_CHARACTER_VISIBLE_LEVELS = frozenset({"full", "partial", "rumor"})


class KnowledgeVisibilityService:
    """Batch visibility decisions across characters × targets."""

    def __init__(self, knowledge_repo: CharacterKnowledgeRepository | None = None):
        self._knowledge_repo = knowledge_repo or CharacterKnowledgeRepository()

    async def check(
        self,
        db: AsyncSession,
        novel_id: str,
        requests: list[KnowledgeVisibilityRequest],
    ) -> list[KnowledgeVisibilityDecision]:
        nid = parse_uuid(novel_id, "novel_id")
        if not requests:
            return []

        refs = {
            (req.target_type, req.target_id): target_hash(
                {
                    "target_type": req.target_type,
                    "target_id": req.target_id,
                    "target_path": "",
                }
            )
            for req in requests
        }

        knowledge_map = await self._load_character_knowledge(db, nid, requests)
        granted_tags, excluded_tags = await self._load_tag_grants(db, nid, requests)
        asset_tags = await self._load_asset_tags(db, nid, refs)
        visibility_modes = await self._load_visibility_modes(db, nid, refs)
        reveal_rows = await self._load_reveal_policies(db, nid, refs)

        decisions: list[KnowledgeVisibilityDecision] = []
        for req in requests:
            decisions.append(
                self._decide(
                    req,
                    refs[(req.target_type, req.target_id)],
                    knowledge_map=knowledge_map,
                    granted_tags=granted_tags,
                    excluded_tags=excluded_tags,
                    asset_tags=asset_tags,
                    visibility_modes=visibility_modes,
                    reveal_rows=reveal_rows,
                )
            )
        return decisions

    def _decide(
        self,
        req: KnowledgeVisibilityRequest,
        ref_hash: str,
        *,
        knowledge_map: dict[tuple[str, str], CharacterKnowledge],
        granted_tags: dict[str, set[str]],
        excluded_tags: dict[str, set[str]],
        asset_tags: dict[str, set[str]],
        visibility_modes: dict[str, str],
        reveal_rows: dict[str, ReaderRevealPolicy],
    ) -> KnowledgeVisibilityDecision:
        reasons: list[str] = []
        knowledge_level: str | None = None
        visibility_source = SOURCE_PUBLIC_DEFAULT

        record = (
            knowledge_map.get((req.character_id, req.target_id))
            if req.character_id
            else None
        )
        if record is not None:
            knowledge_level = record.knowledge_level
            visibility_source = SOURCE_CHARACTER_KNOWLEDGE
            visible = record.knowledge_level in _CHARACTER_VISIBLE_LEVELS
            if not visible:
                reasons.append(f"character_knowledge:{record.knowledge_level}")
        else:
            mode = visibility_modes.get(ref_hash, "public")
            if mode == "public":
                visible = True
                visibility_source = SOURCE_PUBLIC_DEFAULT
            elif mode == "tag":
                visibility_source = SOURCE_TAG_GRANT
                granted = granted_tags.get(req.character_id or "", set()) - (
                    excluded_tags.get(req.character_id or "", set())
                )
                visible = bool(granted & asset_tags.get(ref_hash, set()))
                if not visible:
                    reasons.append("tag_not_granted")
            elif mode == "private":
                visibility_source = SOURCE_PRIVATE_POLICY
                visible = False
                reasons.append("private_without_grant")
            else:
                visibility_source = SOURCE_VISIBILITY_POLICY
                visible = False
                reasons.append(f"visibility_mode:{mode}")

        has_policy = ref_hash in reveal_rows
        reader_revealed: bool | None = None
        if req.apply_reader_reveal and has_policy:
            policy = reveal_rows[ref_hash]
            reader_revealed = self._reader_revealed(policy, req.cutoff_chapter)
            if not reader_revealed:
                reasons.append("reader_reveal_pending")
                visible = False

        return KnowledgeVisibilityDecision(
            target_type=req.target_type,
            target_id=req.target_id,
            visible=visible,
            knowledge_level=knowledge_level,
            visibility_source=visibility_source,
            has_reader_policy=has_policy,
            reader_revealed=reader_revealed,
            reasons=tuple(reasons),
        )

    @staticmethod
    def _reader_revealed(policy: ReaderRevealPolicy, cutoff_chapter: int | None) -> bool:
        """保守判定：当章不揭示；无截止点时只有 public_baseline 可见。"""
        if policy.public_baseline:
            return True
        if policy.reveal_chapter_index is None or cutoff_chapter is None:
            return False
        return policy.reveal_chapter_index < cutoff_chapter

    async def _load_character_knowledge(
        self,
        db: AsyncSession,
        nid,
        requests: list[KnowledgeVisibilityRequest],
    ) -> dict[tuple[str, str], CharacterKnowledge]:
        groups: dict[tuple[str, int | None], set[str]] = defaultdict(set)
        for req in requests:
            if req.character_id:
                groups[(req.character_id, req.cutoff_chapter)].add(req.target_id)
        result: dict[tuple[str, str], CharacterKnowledge] = {}
        for (character_id, cutoff), target_ids in sorted(groups.items()):
            records = await self._knowledge_repo.get_by_target(
                db,
                nid,
                parse_uuid(character_id, "character_id"),
                [parse_uuid(tid) for tid in sorted(target_ids)],
                visible_until_chapter=cutoff,
            )
            for record in records:
                result[(character_id, str(record.target_id))] = record
        return result

    async def _load_tag_grants(
        self,
        db: AsyncSession,
        nid,
        requests: list[KnowledgeVisibilityRequest],
    ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        character_ids = sorted(
            {
                req.character_id
                for req in requests
                if req.character_id
            }
        )
        if not character_ids:
            return {}, {}
        parsed = [parse_uuid(cid, "character_id") for cid in character_ids]

        grant_rows = (
            await db.execute(
                select(CharacterKnowledgeTag).where(
                    CharacterKnowledgeTag.novel_id == nid,
                    CharacterKnowledgeTag.character_id.in_(parsed),
                    CharacterKnowledgeTag.status == "canonical",
                )
            )
        ).scalars().all()
        granted: dict[str, set[str]] = defaultdict(set)
        for row in grant_rows:
            granted[str(row.character_id)].add(str(row.tag_id))

        exclusion_rows = (
            await db.execute(
                select(KnowledgeTagExclusion).where(
                    KnowledgeTagExclusion.novel_id == nid,
                    KnowledgeTagExclusion.character_id.in_(parsed),
                )
            )
        ).scalars().all()
        excluded: dict[str, set[str]] = defaultdict(set)
        for row in exclusion_rows:
            excluded[str(row.character_id)].add(str(row.tag_id))
        return dict(granted), dict(excluded)

    async def _load_asset_tags(
        self,
        db: AsyncSession,
        nid,
        refs: dict[tuple[str, str], str],
    ) -> dict[str, set[str]]:
        hashes = sorted(set(refs.values()))
        if not hashes:
            return {}
        rows = (
            await db.execute(
                select(AssetKnowledgeTag).where(
                    AssetKnowledgeTag.novel_id == nid,
                    AssetKnowledgeTag.target_hash.in_(hashes),
                )
            )
        ).scalars().all()
        asset_tags: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            asset_tags[row.target_hash].add(str(row.tag_id))
        return dict(asset_tags)

    async def _load_visibility_modes(
        self,
        db: AsyncSession,
        nid,
        refs: dict[tuple[str, str], str],
    ) -> dict[str, str]:
        hashes = sorted(set(refs.values()))
        if not hashes:
            return {}
        rows = (
            await db.execute(
                select(KnowledgeVisibilityPolicy).where(
                    KnowledgeVisibilityPolicy.novel_id == nid,
                    KnowledgeVisibilityPolicy.target_hash.in_(hashes),
                    KnowledgeVisibilityPolicy.status == "canonical",
                )
            )
        ).scalars().all()
        latest: dict[str, KnowledgeVisibilityPolicy] = {}
        for row in rows:
            current = latest.get(row.target_hash)
            if current is None or (row.updated_at or row.created_at or "") > (
                current.updated_at or current.created_at or ""
            ):
                latest[row.target_hash] = row
        return {ref_hash: row.visibility_mode for ref_hash, row in latest.items()}

    async def _load_reveal_policies(
        self,
        db: AsyncSession,
        nid,
        refs: dict[tuple[str, str], str],
    ) -> dict[str, ReaderRevealPolicy]:
        hashes = sorted(set(refs.values()))
        if not hashes:
            return {}
        rows = (
            await db.execute(
                select(ReaderRevealPolicy).where(
                    ReaderRevealPolicy.novel_id == nid,
                    ReaderRevealPolicy.target_hash.in_(hashes),
                )
            )
        ).scalars().all()
        latest: dict[str, ReaderRevealPolicy] = {}
        for row in rows:
            current = latest.get(row.target_hash)
            if current is None or (row.updated_at or row.created_at or "") > (
                current.updated_at or current.created_at or ""
            ):
                latest[row.target_hash] = row
        return latest


_default_service = KnowledgeVisibilityService()


async def check_knowledge_visibility(
    db: AsyncSession,
    novel_id: str,
    requests: list[KnowledgeVisibilityRequest],
) -> list[KnowledgeVisibilityDecision]:
    """批量判定生成者可见性：角色知识 → public/tag/private → ReaderReveal 交集。"""
    return await _default_service.check(db, novel_id, requests)

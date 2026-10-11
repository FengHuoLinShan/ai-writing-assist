"""RP 原作包派生缓存的 key、序列化与存取（M1 契约 §3/§4，切片 3）。

缓存行是 Evidence 私有派生内容：不进导出/备份/日志/检索索引。key 覆盖
所有决定材料的输入（含完整语义输入与实际词法计划），不含与材料无关的
task ID 或输出审查结果；方法版本不匹配的行一律不消费（fail-closed）。
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.models import InteractionSourceCache
from modules.evidence.compilation.services.interaction_source_material import (
    INTERACTION_MATERIAL_METHOD_VERSION,
    INTERACTION_RENDER_METHOD_VERSION,
    CompiledSourcePacket,
    InteractionSourceMaterial,
)

CACHE_TTL_SECONDS = 24 * 3600
"""待校准建议值（M1 契约 §6）：过期立即不可命中。"""

MAX_ENTRY_BYTES = 256 * 1024
"""单行完整材料与编译包总上限；超限跳过缓存，不截必需证据。"""

MAX_CONSUMER_CACHE_BYTES = 32 * 1024 * 1024
"""consumer 侧缓存总量上限（材料+编译正文）；超限只做惰性清理与新写跳过。"""


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _sha(value) -> str:
    import hashlib

    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def current_method_versions(lexical_planner_version: str | None) -> dict:
    return {
        "material": INTERACTION_MATERIAL_METHOD_VERSION,
        "render": INTERACTION_RENDER_METHOD_VERSION,
        "lexical": lexical_planner_version or "none",
    }


def build_material_key(
    *,
    source_novel_id: str,
    consumer_novel_id: str,
    owner_id: str,
    source_revision_id: str,
    anchor: dict,
    exact_manifest: dict[str, str],
    visible_references_digest: str,
    reference_policy: dict,
    ambiguities_digest: str,
    resolutions: dict[str, str],
    player_identity_digest: str,
    semantic_input: str,
    lexical_terms: list[str],
    method_versions: dict,
) -> tuple[dict, str]:
    """材料 key（脱敏字典）与其 SHA-256；任何输入变化必然改变 hash。"""

    key = {
        "source_novel_id": str(source_novel_id),
        "consumer_novel_id": str(consumer_novel_id),
        "owner_id": str(owner_id),
        "source_revision_id": str(source_revision_id),
        "anchor_key": str(anchor.get("anchor_key") or ""),
        "cutoff_chapter": int(anchor.get("chapter_index") or 0),
        "cutoff_offset": int(anchor.get("end_offset") or 0),
        "exact_manifest": dict(sorted(exact_manifest.items())),
        "visible_references": visible_references_digest,
        "reference_policy": {
            "pinned": list(dict.fromkeys(reference_policy.get("pinned") or [])),
            "excluded": sorted(set(reference_policy.get("excluded") or [])),
        },
        "ambiguities": ambiguities_digest,
        "resolutions": dict(sorted(resolutions.items())),
        "player_identity": player_identity_digest,
        "semantic_input_sha": _sha(semantic_input),
        "lexical_terms": list(lexical_terms),
        "method_versions": dict(sorted(method_versions.items())),
    }
    return key, _sha(key)


def serialize_material(material: InteractionSourceMaterial) -> dict:
    return {
        "identity_block": material.identity_block,
        "reference_order": list(material.reference_order),
        "mandatory_keys": sorted(material.mandatory_keys),
        "reference_blocks": dict(material.reference_blocks),
        "reference_reasons": dict(material.reference_reasons),
        "reference_labels": dict(material.reference_labels),
        "knowledge_block": material.knowledge_block,
        "mandatory_reads": [dict(read) for read in material.mandatory_reads],
        "excerpt_reads": [dict(read) for read in material.excerpt_reads],
        "warnings": list(material.warnings),
    }


def deserialize_material(payload: dict) -> InteractionSourceMaterial:
    return InteractionSourceMaterial(
        identity_block=str(payload["identity_block"]),
        reference_order=tuple(payload["reference_order"]),
        mandatory_keys=frozenset(payload["mandatory_keys"]),
        reference_blocks=dict(payload["reference_blocks"]),
        reference_reasons=dict(payload["reference_reasons"]),
        reference_labels=dict(payload["reference_labels"]),
        knowledge_block=str(payload["knowledge_block"]),
        mandatory_reads=tuple(dict(read) for read in payload["mandatory_reads"]),
        excerpt_reads=tuple(dict(read) for read in payload["excerpt_reads"]),
        warnings=tuple(payload["warnings"]),
    )


def serialize_compiled(packet: CompiledSourcePacket, *, budget_tokens: int) -> dict:
    return {
        "budget_tokens": int(budget_tokens),
        "render_version": INTERACTION_RENDER_METHOD_VERSION,
        "rendered": packet.rendered,
        "included_refs": [dict(item) for item in packet.included_refs],
        "source_refs": [dict(item) for item in packet.source_refs],
    }


def deserialize_compiled(payload: dict) -> tuple[CompiledSourcePacket, int]:
    return (
        CompiledSourcePacket(
            rendered=str(payload["rendered"]),
            included_refs=tuple(dict(item) for item in payload["included_refs"]),
            source_refs=tuple(dict(item) for item in payload["source_refs"]),
            blockers=(),
        ),
        int(payload["budget_tokens"]),
    )


@dataclass(frozen=True)
class CacheHit:
    material: InteractionSourceMaterial
    compiled: CompiledSourcePacket | None
    compiled_budget_tokens: int | None


# fetch 未命中原因（M4 契约 §4；主计划 §7.2 要求 attempt 记录失效原因）：
# absent 无行 / expired TTL 到期 / version_mismatch 方法版本不匹配 /
# integrity 材料完整性不符。命中时 miss_reason 为 None。
MISS_REASON_ABSENT = "absent"
MISS_REASON_EXPIRED = "expired"
MISS_REASON_VERSION_MISMATCH = "version_mismatch"
MISS_REASON_INTEGRITY = "integrity"


@dataclass(frozen=True)
class CacheFetch:
    hit: CacheHit | None
    miss_reason: str | None = None

    def __bool__(self) -> bool:
        return self.hit is not None


class InteractionSourceCacheStore:
    """缓存存取；DB 故障向上传播，绝不吞为 miss（M1 契约 §5）。"""

    async def fetch(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        material_key_hash: str,
        method_versions: dict,
        now: dt.datetime | None = None,
    ) -> CacheFetch:
        row = (
            await db.execute(
                select(InteractionSourceCache)
                .where(
                    InteractionSourceCache.novel_id == novel_id,
                    InteractionSourceCache.material_key_hash == material_key_hash,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return CacheFetch(hit=None, miss_reason=MISS_REASON_ABSENT)
        now = now or dt.datetime.now(dt.UTC)
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=dt.UTC)
        if expires <= now:
            return CacheFetch(hit=None, miss_reason=MISS_REASON_EXPIRED)
        if dict(row.method_versions) != dict(method_versions):
            return CacheFetch(hit=None, miss_reason=MISS_REASON_VERSION_MISMATCH)
        material_payload = dict(row.material_body)
        if _sha(material_payload) != row.material_body_sha:
            return CacheFetch(hit=None, miss_reason=MISS_REASON_INTEGRITY)
        compiled = None
        compiled_budget = None
        if row.compiled_body is not None and row.compiled_spec is not None:
            spec = dict(row.compiled_spec)
            if (
                _sha(spec) == row.compiled_sha
                and spec.get("rendered") == row.compiled_body
            ):
                try:
                    compiled, compiled_budget = deserialize_compiled(spec)
                except (KeyError, TypeError, ValueError):
                    compiled = None
        try:
            material = deserialize_material(material_payload)
        except (KeyError, TypeError, ValueError):
            return CacheFetch(hit=None, miss_reason=MISS_REASON_INTEGRITY)
        return CacheFetch(
            hit=CacheHit(
                material=material,
                compiled=compiled,
                compiled_budget_tokens=compiled_budget,
            )
        )

    async def purge_for_project(self, db: AsyncSession, project_id: uuid.UUID) -> int:
        result = await db.execute(
            delete(InteractionSourceCache)
            .where(
                or_(
                    InteractionSourceCache.novel_id == project_id,
                    InteractionSourceCache.source_novel_id == project_id,
                )
            )
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)

    async def purge_for_source(self, db: AsyncSession, source_novel_id: uuid.UUID) -> int:
        """来源失效后的立即清理（M4 契约 §4；主计划 §5.1「随后清理」）。

        只删不可达派生行，不碰权威历史；「拒绝使用」仍由门禁/key/证明重放承担。
        """
        result = await db.execute(
            delete(InteractionSourceCache)
            .where(InteractionSourceCache.source_novel_id == source_novel_id)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)

    async def store(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        source_novel_id: uuid.UUID,
        owner_id: uuid.UUID,
        material_key: dict,
        material_key_hash: str,
        material: InteractionSourceMaterial,
        method_versions: dict,
        compiled: CompiledSourcePacket | None = None,
        budget_tokens: int | None = None,
        ttl_seconds: int = CACHE_TTL_SECONDS,
        now: dt.datetime | None = None,
    ) -> bool:
        """幂等写入（UNIQUE 冲突覆盖）；超容量/超限跳过并返回 False。"""

        now = now or dt.datetime.now(dt.UTC)
        material_payload = serialize_material(material)
        material_bytes = len(_canonical(material_payload).encode("utf-8"))
        compiled_spec = None
        compiled_body = None
        compiled_sha = None
        compiled_bytes = 0
        if compiled is not None and budget_tokens is not None:
            compiled_spec = serialize_compiled(compiled, budget_tokens=budget_tokens)
            compiled_body = compiled.rendered
            compiled_sha = _sha(compiled_spec)
            compiled_bytes = len(str(compiled_body).encode("utf-8")) + len(
                _canonical(compiled_spec).encode("utf-8")
            )

        if material_bytes + compiled_bytes > MAX_ENTRY_BYTES:
            return False
        await self._lock_consumer(db, novel_id)
        await self._evict_expired(db, novel_id=novel_id, now=now)
        if not await self._fits_consumer(
            db, novel_id, material_key_hash, material_bytes + compiled_bytes
        ):
            return False

        values = {
            "novel_id": novel_id,
            "source_novel_id": source_novel_id,
            "owner_id": owner_id,
            "material_key_hash": material_key_hash,
            "material_key": material_key,
            "material_body": material_payload,
            "material_body_sha": _sha(material_payload),
            "material_bytes": material_bytes,
            "compiled_body": compiled_body,
            "compiled_spec": compiled_spec,
            "compiled_sha": compiled_sha,
            "compiled_bytes": compiled_bytes,
            "method_versions": dict(method_versions),
            "expires_at": now + dt.timedelta(seconds=ttl_seconds),
        }
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            stmt = pg_insert(InteractionSourceCache).values(**values)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_interaction_source_cache_key",
                set_={
                    "material_key": stmt.excluded.material_key,
                    "material_body": stmt.excluded.material_body,
                    "material_body_sha": stmt.excluded.material_body_sha,
                    "material_bytes": stmt.excluded.material_bytes,
                    "compiled_body": stmt.excluded.compiled_body,
                    "compiled_spec": stmt.excluded.compiled_spec,
                    "compiled_sha": stmt.excluded.compiled_sha,
                    "compiled_bytes": stmt.excluded.compiled_bytes,
                    "method_versions": stmt.excluded.method_versions,
                    "expires_at": stmt.excluded.expires_at,
                    "updated_at": now,
                },
            )
            await db.execute(stmt)
            return True
        # SQLite 窄适配：先删后插等价于覆盖写（测试路径，无并发生产写）
        await db.execute(
            delete(InteractionSourceCache).where(
                InteractionSourceCache.novel_id == novel_id,
                InteractionSourceCache.material_key_hash == material_key_hash,
            )
        )
        db.add(InteractionSourceCache(**values))
        await db.flush()
        return True

    async def _evict_expired(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        now: dt.datetime,
    ) -> None:
        # synchronize_session=False：SQLite 取回的 naive expires_at 与 aware now
        # 无法在 Python 端逐实例评估比较，这里只需要 SQL 侧删除。
        await db.execute(
            delete(InteractionSourceCache)
            .where(
                InteractionSourceCache.novel_id == novel_id,
                InteractionSourceCache.expires_at <= now,
            )
            .execution_options(synchronize_session=False)
        )

    @staticmethod
    async def _lock_consumer(db: AsyncSession, novel_id: uuid.UUID) -> None:
        # 同一 consumer 的容量检查和写入共享事务锁；无模型/检索 IO。
        if db.get_bind().dialect.name == "postgresql":
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"interaction_source_cache:{novel_id}"},
            )

    @staticmethod
    async def _fits_consumer(
        db: AsyncSession, novel_id: uuid.UUID, key_hash: str, entry_bytes: int
    ) -> bool:
        total = (
            await db.execute(
                select(
                    func.coalesce(
                        func.sum(
                            InteractionSourceCache.material_bytes
                            + InteractionSourceCache.compiled_bytes
                        ),
                        0,
                    )
                ).where(
                    InteractionSourceCache.novel_id == novel_id,
                    InteractionSourceCache.material_key_hash != key_hash,
                )
            )
        ).scalar_one()
        return int(total) + entry_bytes <= MAX_CONSUMER_CACHE_BYTES

    async def touch_compiled(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        material_key_hash: str,
        compiled: CompiledSourcePacket,
        budget_tokens: int,
    ) -> bool:
        """预算变体仍检查完整行和 consumer 容量；超限保留原缓存。"""
        spec = serialize_compiled(compiled, budget_tokens=budget_tokens)
        compiled_bytes = len(compiled.rendered.encode("utf-8")) + len(
            _canonical(spec).encode("utf-8")
        )
        if compiled_bytes > MAX_ENTRY_BYTES:
            return False
        await self._lock_consumer(db, novel_id)
        await self._evict_expired(db, novel_id=novel_id, now=dt.datetime.now(dt.UTC))
        material_bytes = (
            await db.execute(
                select(InteractionSourceCache.material_bytes).where(
                    InteractionSourceCache.novel_id == novel_id,
                    InteractionSourceCache.material_key_hash == material_key_hash,
                )
            )
        ).scalar_one_or_none()
        if material_bytes is None:
            return False
        entry_bytes = material_bytes + compiled_bytes
        if entry_bytes > MAX_ENTRY_BYTES or not await self._fits_consumer(
            db, novel_id, material_key_hash, entry_bytes
        ):
            return False
        await db.execute(
            update(InteractionSourceCache)
            .where(
                InteractionSourceCache.novel_id == novel_id,
                InteractionSourceCache.material_key_hash == material_key_hash,
            )
            .values(
                compiled_body=compiled.rendered,
                compiled_spec=spec,
                compiled_sha=_sha(spec),
                compiled_bytes=compiled_bytes,
            )
        )
        return True

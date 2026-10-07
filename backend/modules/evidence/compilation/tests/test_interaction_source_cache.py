"""RP 原作包持久缓存验收（M3 切片 3，M1 契约 §3–§6）。

覆盖：精确命中跳过检索且逐字节复用、S5 每次新建 snapshot、预算变体从
完整材料重编译（不截旧包）、来源 revision 变化换 key、TTL 过期、幂等
覆盖写、容量门禁跳过、证明漂移按未命中处理。跨 worker 语义由两个
独立 service 实例 + 数据库行表达；PG 并发写入以后续 e2e 为准。
"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from modules.evidence.compilation.models import InteractionSourceCache
from modules.evidence.compilation.services import interaction_story_context as isc
from modules.evidence.compilation.services.interaction_source_cache import (
    InteractionSourceCacheStore,
    _sha,
)
from modules.evidence.compilation.services.interaction_source_material import (
    InteractionSourceMaterial,
)
from modules.evidence.compilation.services.interaction_story_context import (
    InteractionStoryContextService,
)
from modules.evidence.indexing.repositories import RagChunkRepository
from modules.evidence.indexing.schemas import RagChunkCreate
from modules.writing.facade import build_manuscript_range_ref, create_published_draft_only

pytestmark = pytest.mark.asyncio


async def _cache_fixture(db_session, project_factory) -> SimpleNamespace:  # noqa: ANN001
    source = await project_factory.create_project(title="缓存原作")
    consumer = await project_factory.create_project(
        title="缓存旅程", project_kind="interaction"
    )
    text = "沈砚推开雾渡港灯塔下旧仓库的门，铜钥匙在掌心发烫。顾青梧站在暗处。"
    draft = await create_published_draft_only(db_session, str(source), 1, "第一章", text)
    character = str(uuid.uuid4())
    repo = RagChunkRepository()
    await repo.replace_chapter_chunks(
        db_session,
        source,
        source_type="chapter_text",
        chapter_index=1,
        content_mode="canonical",
        items=[
            RagChunkCreate(
                source_type="chapter_text",
                source_id=str(draft.id),
                source_content_hash=draft.content_hash,
                content_mode="canonical",
                chapter_index=1,
                chunk_index=0,
                start_offset=0,
                end_offset=len(text),
                char_count=len(text),
                text=text,
                character_ids=[character],
                entity_ids=[character],
                index_version="cn-novel-v1",
            )
        ],
    )
    from dataclasses import asdict

    source_ref = asdict(
        await build_manuscript_range_ref(
            db_session,
            str(source),
            draft_id=str(draft.id),
            start_offset=0,
            end_offset=len(text),
            content_mode="canonical",
        )
    )
    reference_key = "c" * 64
    return SimpleNamespace(
        source=source,
        consumer=consumer,
        revision_id=str(uuid.uuid4()),
        manifest=[
            {
                "draft_id": str(draft.id),
                "source_hash": draft.content_hash,
                "chapter_index": 1,
                "char_count": len(text),
            }
        ],
        reference_manifest=[
            {
                "reference_key": reference_key,
                "target_id": character,
                "label": "沈砚",
                "entity_type": "character",
                "first_chapter_index": 1,
                "first_end_offset": 2,
                "identity_source_refs": [source_ref],
            }
        ],
        player={
            "kind": "source_character",
            "target_id": character,
            "reference_key": reference_key,
            "label": "沈砚",
        },
        anchor={
            "anchor_key": "a" * 64,
            "chapter_index": 1,
            "end_offset": len(text),
            "label": "开局",
            "chapter_title": "第一章",
        },
    )


async def _compile(
    db, fx, *, budget: int = 16000, revision: str | None = None, public_demo: bool = False
):  # noqa: ANN001
    return await InteractionStoryContextService().compile(
        db,
        source_novel_id=str(fx.source),
        consumer_novel_id=str(fx.consumer),
        source_revision_id=revision or fx.revision_id,
        source_manifest=fx.manifest,
        anchor=fx.anchor,
        player_identity=fx.player,
        reference_manifest=fx.reference_manifest,
        ambiguities=[],
        resolutions={},
        reference_policy={"pinned": [], "excluded": []},
        query="沈砚现在在哪里？",
        task_id=None,
        model="test-model",
        budget_tokens=budget,
        public_demo_source=public_demo,
        public_demo_source_fingerprint="a" * 64 if public_demo else None,
    )


class _RetrieveSpy:
    """计数并透传真实检索；target() 返回真协程函数供 AsyncMock side_effect await。"""

    def __init__(self) -> None:
        from modules.evidence.indexing.facade import retrieve as real_retrieve

        self.real = real_retrieve
        self.calls = 0

    def target(self):  # noqa: ANN201
        async def _spy(db, novel_id, query, **kwargs):  # noqa: ANN001, ANN003
            self.calls += 1
            return await self.real(db, novel_id, query, **kwargs)

        return _spy


async def test_requery_hits_cache_skips_retrieval_and_reuses_snapshot_free(
    db_session, project_factory
) -> None:
    from unittest.mock import patch

    fx = await _cache_fixture(db_session, project_factory)
    spy = _RetrieveSpy()
    with patch.object(isc, "retrieve", autospec=True, side_effect=spy.target()):
        first = await _compile(db_session, fx)
        # 第二个实例模拟另一 worker：命中数据库行，不再检索
        second = await _compile(db_session, fx)
        assert spy.calls == 1
    assert first.blockers == [] and second.blockers == []
    assert first.rendered_context == second.rendered_context
    assert first.fingerprint == second.fingerprint
    # S5 使用记录不缓存：每次命中仍新建 snapshot
    assert second.snapshot_id is not None and second.snapshot_id != first.snapshot_id


async def test_budget_variant_recompiles_from_full_material(
    db_session, project_factory
) -> None:
    from unittest.mock import patch

    fx = await _cache_fixture(db_session, project_factory)
    spy = _RetrieveSpy()
    with patch.object(isc, "retrieve", autospec=True, side_effect=spy.target()):
        big = await _compile(db_session, fx, budget=16000)
        assert big.blockers == []
        tiny = await _compile(db_session, fx, budget=60)
        assert spy.calls == 1  # 预算变化只重裁剪，材料不重检索
    # 固定资料超出小预算：阻断（契约语义），且不被编译缓存掩盖
    assert tiny.blockers and tiny.blockers[0].startswith("已固定的作品资料超出可用篇幅")
    with patch.object(isc, "retrieve", autospec=True, side_effect=spy.target()):
        tiny_again = await _compile(db_session, fx, budget=60)
        assert spy.calls == 1
    assert tiny_again.blockers == tiny.blockers
    # 成功但预算不同于已存编译：touch 替换派生正文；再命中直接复用
    budget2 = big.token_count + 1
    with patch.object(isc, "retrieve", autospec=True, side_effect=spy.target()):
        mid = await _compile(db_session, fx, budget=budget2)
        assert spy.calls == 1
        mid_again = await _compile(db_session, fx, budget=budget2)
        assert spy.calls == 1
    assert mid.blockers == []
    assert mid.rendered_context == big.rendered_context
    assert mid_again.rendered_context == mid.rendered_context


async def test_source_revision_change_changes_key_and_requeries(
    db_session, project_factory
) -> None:
    from unittest.mock import patch

    fx = await _cache_fixture(db_session, project_factory)
    spy = _RetrieveSpy()
    with patch.object(isc, "retrieve", autospec=True, side_effect=spy.target()):
        await _compile(db_session, fx)
        await _compile(db_session, fx, revision=str(uuid.uuid4()))
        assert spy.calls == 2


async def test_store_ttl_expiry_and_idempotent_overwrite(
    db_session, project_factory
) -> None:
    fx = await _cache_fixture(db_session, project_factory)
    await _compile(db_session, fx)
    consumer = uuid.UUID(str(fx.consumer))
    row = (
        await db_session.execute(
            select(InteractionSourceCache).where(
                InteractionSourceCache.novel_id == consumer
            )
        )
    ).scalar_one()
    assert row.compiled_spec is not None

    store = InteractionSourceCacheStore()
    key_hash = row.material_key_hash
    hit = await store.fetch(
        db_session,
        novel_id=consumer,
        material_key_hash=key_hash,
        method_versions=dict(row.method_versions),
    )
    assert hit.hit is not None and hit.miss_reason is None
    # 版本不匹配不消费（旧进程保护），且行本身仍有效
    stale = await store.fetch(
        db_session,
        novel_id=consumer,
        material_key_hash=key_hash,
        method_versions={"material": "older-version"},
    )
    assert stale.hit is None and stale.miss_reason == "version_mismatch"
    # TTL 过期立即不可命中
    row.expires_at = row.created_at
    await db_session.flush()
    expired = await store.fetch(
        db_session,
        novel_id=consumer,
        material_key_hash=key_hash,
        method_versions=dict(row.method_versions),
    )
    assert expired.hit is None and expired.miss_reason == "expired"


async def test_oversized_material_is_not_cached(db_session) -> None:
    huge_text = "字" * (300 * 1024)
    material = InteractionSourceMaterial(
        identity_block="身份",
        reference_order=(),
        mandatory_keys=frozenset(),
        reference_blocks={},
        reference_reasons={},
        reference_labels={},
        knowledge_block="",
        mandatory_reads=(),
        excerpt_reads=(
            {
                "title": "巨大章节",
                "text": huge_text,
                "source_ref": {"draft_id": "d", "chapter_index": 1},
            },
        ),
        warnings=(),
    )
    novel_id = uuid.uuid4()
    stored = await InteractionSourceCacheStore().store(
        db_session,
        novel_id=novel_id,
        source_novel_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        material_key={"k": 1},
        material_key_hash="h" * 64,
        material=material,
        method_versions={"material": "v"},
    )
    assert stored is False
    rows = (
        await db_session.execute(
            select(InteractionSourceCache).where(
                InteractionSourceCache.novel_id == novel_id
            )
        )
    ).scalars()
    assert list(rows) == []


async def test_proof_drift_downgrades_to_miss(db_session, project_factory) -> None:
    from unittest.mock import patch

    fx = await _cache_fixture(db_session, project_factory)
    spy = _RetrieveSpy()
    with patch.object(isc, "retrieve", autospec=True, side_effect=spy.target()):
        await _compile(db_session, fx)
        assert spy.calls == 1
    # 篡改材料正文并同步改 sha（模拟完整性通过但与原作漂移）
    consumer = uuid.UUID(str(fx.consumer))
    row = (
        await db_session.execute(
            select(InteractionSourceCache).where(
                InteractionSourceCache.novel_id == consumer
            )
        )
    ).scalar_one()
    body = dict(row.material_body)
    reads = [dict(read) for read in body["mandatory_reads"]]
    reads[0]["text"] += "被篡改的证明"
    body["mandatory_reads"] = reads
    row.material_body = body
    row.material_body_sha = _sha(body)
    await db_session.flush()
    with patch.object(isc, "retrieve", autospec=True, side_effect=spy.target()):
        recompiled = await _compile(db_session, fx)
        assert spy.calls == 2  # 证明重验失败 → 走原路径重新检索
    assert recompiled.blockers == []
    assert "被篡改的证明" not in recompiled.rendered_context


async def test_archived_source_project_rejected_before_cache(
    db_session, project_factory
) -> None:
    """A09：源项目归档/软删后，入口门禁立即失败关闭——缓存行根本不被消费。"""
    from datetime import UTC, datetime

    from core.errors import NotFoundError
    from modules.project.models import Project

    fx = await _cache_fixture(db_session, project_factory)
    first = await _compile(db_session, fx)
    assert first.blockers == []
    row = (
        await db_session.execute(
            select(InteractionSourceCache).where(
                InteractionSourceCache.novel_id == fx.consumer
            )
        )
    ).scalar_one()
    assert row is not None

    source_project = await db_session.get(Project, fx.source)
    source_project.deleted_at = datetime.now(UTC)
    await db_session.flush()

    with pytest.raises(NotFoundError):
        await _compile(db_session, fx)


async def test_source_invalidation_purges_cache_rows(db_session, project_factory) -> None:
    """A09：来源失效清理不等 TTL——按 source_novel_id 删除派生行，权威历史不受影响。"""
    from modules.evidence.facade import purge_interaction_source_cache

    fx = await _cache_fixture(db_session, project_factory)
    first = await _compile(db_session, fx)
    assert first.blockers == []

    purged = await purge_interaction_source_cache(
        db_session, source_novel_id=str(fx.source)
    )
    assert purged >= 1
    remaining = (
        await db_session.execute(
            select(InteractionSourceCache).where(
                InteractionSourceCache.novel_id == fx.consumer
            )
        )
    ).scalar_one_or_none()
    assert remaining is None

    # 清理后再次编译走原路径（absent），结果等价
    again = await _compile(db_session, fx)
    assert again.blockers == [] and again.rendered_context == first.rendered_context


async def test_public_demo_never_reads_or_writes_private_cache(
    db_session, project_factory
):
    from unittest.mock import patch

    from core.container import container_scope
    from core.service_keys import INTERACTION_VALIDATE_PUBLIC_DEMO_SOURCE_CONTEXT

    fx = await _cache_fixture(db_session, project_factory)
    await _compile(db_session, fx)

    async def validate_public_source(*args, **kwargs):
        assert kwargs["source_novel_id"] == str(fx.source)

    with container_scope(
        {INTERACTION_VALIDATE_PUBLIC_DEMO_SOURCE_CONTEXT: validate_public_source}
    ):
        with (
            patch.object(InteractionSourceCacheStore, "fetch", autospec=True) as fetch,
            patch.object(InteractionSourceCacheStore, "store", autospec=True) as store,
            patch.object(
                InteractionSourceCacheStore, "touch_compiled", autospec=True
            ) as touch,
        ):
            result = await _compile(db_session, fx, public_demo=True)
            assert not result.blockers
            fetch.assert_not_called()
            store.assert_not_called()
            touch.assert_not_called()


async def test_combined_row_and_touch_capacity_keep_complete_material(
    db_session, project_factory, monkeypatch
):
    from modules.evidence.compilation.services import interaction_source_cache as cache
    from modules.evidence.compilation.services.interaction_source_material import (
        CompiledSourcePacket,
    )

    fx = await _cache_fixture(db_session, project_factory)
    await _compile(db_session, fx)
    row = await db_session.scalar(
        select(InteractionSourceCache).where(
            InteractionSourceCache.novel_id == fx.consumer
        )
    )
    store = InteractionSourceCacheStore()
    oversized = CompiledSourcePacket(
        rendered="x" * 150000, included_refs=(), source_refs=(), blockers=()
    )
    assert not await store.touch_compiled(
        db_session,
        novel_id=fx.consumer,
        material_key_hash=row.material_key_hash,
        compiled=oversized,
        budget_tokens=16000,
    )
    original = row.compiled_body
    hit = await store.fetch(
        db_session,
        novel_id=fx.consumer,
        material_key_hash=row.material_key_hash,
        method_versions=row.method_versions,
    )
    assert hit.hit.compiled.rendered == original
    monkeypatch.setattr(
        cache, "MAX_CONSUMER_CACHE_BYTES", row.material_bytes + row.compiled_bytes
    )
    assert await store.store(
        db_session,
        novel_id=fx.consumer,
        source_novel_id=fx.source,
        owner_id=row.owner_id,
        material_key=row.material_key,
        material_key_hash=row.material_key_hash,
        material=hit.hit.material,
        method_versions=row.method_versions,
        compiled=hit.hit.compiled,
        budget_tokens=hit.hit.compiled_budget_tokens,
    )
    assert not await store.store(
        db_session,
        novel_id=fx.consumer,
        source_novel_id=fx.source,
        owner_id=row.owner_id,
        material_key=row.material_key,
        material_key_hash="z" * 64,
        material=hit.hit.material,
        method_versions=row.method_versions,
        compiled=oversized,
        budget_tokens=16000,
    )


@pytest.mark.parametrize("transition", ["banned", "pending_deletion"])
async def test_account_revocation_purges_cached_source_and_consumer(
    db_session, project_factory, transition
):
    from datetime import UTC, datetime

    from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID, AccountPrincipal
    from modules.account.models import Account
    from modules.account.services import AccountService

    if await db_session.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
        db_session.add(
            Account(id=BOOTSTRAP_ACCOUNT_ID, status="active", support_code="U-CACHE-TEST")
        )
        await db_session.flush()
    fx = await _cache_fixture(db_session, project_factory)
    await _compile(db_session, fx)
    row = await db_session.scalar(
        select(InteractionSourceCache).where(
            InteractionSourceCache.novel_id == fx.consumer
        )
    )
    assert row is not None
    service = AccountService()
    if transition == "banned":
        await service.set_banned(db_session, row.owner_id, banned=True)
        await service.set_banned(db_session, row.owner_id, banned=False)
    else:
        principal = AccountPrincipal(
            account_id=row.owner_id,
            status="active",
            identity_type="email",
            support_code="test",
            reauthenticated_at_epoch=datetime.now(UTC).timestamp(),
        )
        await service.request_deletion(db_session, principal)
        await service.restore_account(db_session, principal)
    assert (
        await db_session.scalar(
            select(InteractionSourceCache).where(
                InteractionSourceCache.novel_id == fx.consumer
            )
        )
        is None
    )


async def test_cached_proof_failure_blocks_and_removes_private_body(
    db_session, project_factory
):
    from unittest.mock import patch

    from core.errors import NotFoundError

    fx = await _cache_fixture(db_session, project_factory)
    await _compile(db_session, fx)
    assert await db_session.scalar(
        select(InteractionSourceCache).where(
            InteractionSourceCache.source_novel_id == fx.source
        )
    )
    with patch(
        "modules.writing.facade.read_manuscript_range",
        autospec=True,
        side_effect=NotFoundError("frozen source unavailable"),
    ):
        packet = await _compile(db_session, fx)
    assert packet.blockers
    assert (
        await db_session.scalar(
            select(InteractionSourceCache).where(
                InteractionSourceCache.source_novel_id == fx.source
            )
        )
        is None
    )

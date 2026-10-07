"""P2-A A3 读取端单测：视图/试算/facade 出口的逐字段来源三态。

不依赖 A2 写入端：直接手工构造含 ``_field_provenance`` 的 checkpoint
state_json（A1 契约对象序列化），经 SceneStateViewService /
SceneMemoryProjectionService / continuity facade 公开入口断言：

- author 视图受控母题字段 fact 的 ``source["provenance"]`` 为单条记录
  ``{field, event_id, source_refs, status}``，status 三态语义正确；
- None（旧格式/无记录/非母题字段）不冒充——不带 provenance、绝无 exact；
- get_record 历史回开暴露构建当时的 field_provenance，旧格式为空列表；
- list_scene_checkpoints 倒序、含已 supersede 行、novel_id 隔离、可按维度收窄；
- state_trial 条件附带来源 status，判决理由 exact 精确回指、降级显式明示，
  三值裁决本身不受来源状态影响。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project
from modules.story.continuity.field_provenance import (
    FIELD_PROVENANCE_STATE_KEY,
    FieldProvenance,
    ProvenanceSourceRef,
)
from modules.story.continuity.models import MemorySceneCheckpoint
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.scene_state_view import SceneStateViewService
from modules.story.continuity.state_trial import compare_scene_state_trial
from modules.story.contracts import SceneStateTrialRequest
from modules.story.outline_state.models import Scene

pytestmark = pytest.mark.asyncio

_PROVENANCE_KEYS = {"field", "event_id", "source_refs", "status"}
_SOURCE_REF_KEYS = {
    "draft_id",
    "chapter_index",
    "version_number",
    "content_mode",
    "start_offset",
    "end_offset",
    "source_hash",
    "range_hash",
}


# ============================================================
# 合成数据构造（手工 state_json，不依赖 A2 写入端）
# ============================================================


async def _scene(
    db: AsyncSession, novel_id: str, scene_index: int, chapter_index: int
) -> Scene:
    item = Scene(
        novel_id=uuid.UUID(novel_id),
        scene_index=scene_index,
        title=f"Scene {scene_index}",
        chapter_ids=[chapter_index],
        scene_chunks=[{"chapter_index": chapter_index}],
        status="draft",
    )
    db.add(item)
    await db.flush()
    return item


def _ref(
    *,
    draft_id: str,
    version_number: int = 1,
    chapter_index: int = 1,
) -> ProvenanceSourceRef:
    return ProvenanceSourceRef(
        draft_id=draft_id,
        chapter_index=chapter_index,
        version_number=version_number,
        content_mode="working",
        start_offset=0,
        end_offset=48,
        source_hash="a" * 64,
        range_hash="b" * 64,
    )


def _chain(
    *,
    field_key: str,
    dimension: str,
    event_id: str,
    sequence: int,
    refs: tuple[ProvenanceSourceRef, ...] = (),
    subject_ref: str | None = None,
) -> FieldProvenance:
    return FieldProvenance(
        field_key=field_key,
        dimension=dimension,
        event_id=event_id,
        subject_ref=subject_ref,
        source_refs=refs,
        version=refs[0].version_number if refs else 0,
        recorded_at_sequence=sequence,
    )


def _embed(state: dict, records: list[FieldProvenance]) -> dict:
    """受控 state + 内嵌逐字段来源（A1 契约对象序列化；records 空则保持旧格式）。"""
    if records:
        state[FIELD_PROVENANCE_STATE_KEY] = [
            record.model_dump(mode="json") for record in records
        ]
    return state


async def _checkpoint(
    db: AsyncSession,
    novel_id: str,
    scene: Scene,
    dimension: str,
    state_json: dict,
    *,
    is_current: bool = True,
    created_at: datetime,
) -> MemorySceneCheckpoint:
    # source=manual：免基线漂移降级，读取端单测聚焦 provenance 语义本身。
    row = MemorySceneCheckpoint(
        novel_id=uuid.UUID(novel_id),
        scene_id=scene.id,
        scene_index=scene.scene_index,
        stage_index=scene.scene_index + 1,
        dimension=dimension,
        status="ready",
        source="manual",
        confirmed=False,
        is_current=is_current,
        state_json=state_json,
        evidence_refs=[],
        display_summary="",
        source_hash=f"hash-{dimension}-{created_at.isoformat()}",
        created_at=created_at,
    )
    db.add(row)
    await db.flush()
    return row


async def _author_view(db: AsyncSession, novel_id: str, scene: Scene):
    return await SceneStateViewService().get_view(
        db,
        novel_id=novel_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "author"},
    )


def _facts(view, dimension: str, field: str, subject_id: str | None = None):
    dim = next(item for item in view.dimensions if item.dimension == dimension)
    return [
        fact
        for fact in dim.facts
        if fact.field == field and (subject_id is None or fact.subject_id == subject_id)
    ]


def _provenance(fact):
    return (fact.source or {}).get("provenance")


# ============================================================
# 视图三态 + 单记录形态
# ============================================================


async def test_view_attaches_three_state_provenance_as_single_record(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)
    key_id, jia, yi = (str(uuid.uuid4()) for _ in range(3))
    ev_owner, ev_holder = (str(uuid.uuid4()) for _ in range(2))
    ev_phrase_a, ev_phrase_b = (str(uuid.uuid4()) for _ in range(2))
    ev_moved, ev_moon = (str(uuid.uuid4()) for _ in range(2))
    draft_id = str(uuid.uuid4())

    entities_state = _embed(
        {
            "entities": {
                key_id: {
                    "name": "铜钥匙",
                    "custody_owner": jia,
                    "custody_holder": yi,
                    "mood": "疲惫",
                },
                "lock-x": {
                    "name": "三簧锁",
                    "opening_passphrase": "潮落",
                },
            },
            "changes": [],
        },
        [
            _chain(
                field_key="custody_owner",
                dimension="entities",
                event_id=ev_owner,
                sequence=5,
                subject_ref=key_id,
                refs=(_ref(draft_id=draft_id),),
            ),
            # 只追到赋值事件、无稿源区间 → unverified（保留 event_id，refs 空）。
            _chain(
                field_key="custody_holder",
                dimension="entities",
                event_id=ev_holder,
                sequence=9,
                subject_ref=key_id,
            ),
            # 同序两条不同链 → conflict，无法唯一归因不冒充。
            _chain(
                field_key="opening_passphrase",
                dimension="entities",
                event_id=ev_phrase_a,
                sequence=7,
                subject_ref="lock-x",
            ),
            _chain(
                field_key="opening_passphrase",
                dimension="entities",
                event_id=ev_phrase_b,
                sequence=7,
                subject_ref="lock-x",
            ),
        ],
    )
    locations_state = _embed(
        {
            "character_locations": {
                jia: {
                    "location_id": "loc-lighthouse",
                    "text_state": "雾渡港灯塔下",
                    "chapter_index": 1,
                }
            },
            "changes": [],
        },
        [
            _chain(
                field_key="location_id",
                dimension="locations",
                event_id=ev_moved,
                sequence=6,
                subject_ref=jia,
                refs=(_ref(draft_id=draft_id),),
            )
        ],
    )
    timeline_state = _embed(
        {
            "facts": [
                {"id": "f-moon", "moon_phase": "full"},
                {
                    "id": "f-order",
                    "category": "time_order",
                    "new_value": "灯塔在集市之前",
                },
            ],
            "changes": [],
        },
        [
            _chain(
                field_key="moon_phase",
                dimension="timeline",
                event_id=ev_moon,
                sequence=6,
                refs=(_ref(draft_id=draft_id),),
            )
        ],
    )
    for dimension, state in (
        ("entities", entities_state),
        ("locations", locations_state),
        ("timeline", timeline_state),
    ):
        await _checkpoint(
            db_session,
            test_project_id,
            scene,
            dimension,
            state,
            created_at=datetime(2026, 10, 7, 9, 0, tzinfo=UTC),
        )

    view = await _author_view(db_session, test_project_id, scene)

    # exact：链完整，事件 + 稿源区间 + 版本；形态恰为四键单记录。
    owner_provenance = _provenance(_facts(view, "entities", "custody_owner", key_id)[0])
    assert set(owner_provenance) == _PROVENANCE_KEYS
    assert owner_provenance["field"] == "custody_owner"
    assert owner_provenance["status"] == "exact"
    assert owner_provenance["event_id"] == ev_owner
    [ref] = owner_provenance["source_refs"]
    assert set(ref) == _SOURCE_REF_KEYS
    assert (ref["draft_id"], ref["version_number"], ref["content_mode"]) == (
        draft_id,
        1,
        "working",
    )

    # unverified：追到事件无稿源，禁整场列表冒充。
    holder_provenance = _provenance(_facts(view, "entities", "custody_holder", key_id)[0])
    assert holder_provenance["status"] == "unverified"
    assert holder_provenance["event_id"] == ev_holder
    assert holder_provenance["source_refs"] == []
    assert "event_ids" not in holder_provenance

    # conflict：多来源竞争，事件与区间都不冒充。
    phrase_provenance = _provenance(
        _facts(view, "entities", "opening_passphrase", "lock-x")[0]
    )
    assert phrase_provenance["status"] == "conflict"
    assert phrase_provenance["event_id"] is None
    assert phrase_provenance["source_refs"] == []

    # 非母题字段不带 provenance。
    assert "provenance" not in _facts(view, "entities", "mood", key_id)[0].source

    # 位置聚合 fact 挂主锚字段 location_id（非视图聚合字段名 "location"）。
    location_provenance = _provenance(_facts(view, "locations", "location", jia)[0])
    assert location_provenance["field"] == "location_id"
    assert location_provenance["status"] == "exact"

    # timeline 仅月相事实挂链；time_order 非受控母题字段。
    moon_fact, order_fact = (
        _facts(view, "timeline", "timeline_fact", "f-moon")[0],
        _facts(view, "timeline", "timeline_fact", "f-order")[0],
    )
    assert _provenance(moon_fact)["field"] == "moon_phase"
    assert _provenance(moon_fact)["status"] == "exact"
    assert "provenance" not in order_fact.source


async def test_view_latest_chain_wins_over_stale_records(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)
    key_id = str(uuid.uuid4())
    ev_old, ev_new = str(uuid.uuid4()), str(uuid.uuid4())
    state = _embed(
        {"entities": {key_id: {"name": "铜钥匙", "custody_holder": "乙"}}, "changes": []},
        [
            _chain(
                field_key="custody_holder",
                dimension="entities",
                event_id=ev_old,
                sequence=3,
                subject_ref=key_id,
                refs=(_ref(draft_id=str(uuid.uuid4()), version_number=1),),
            ),
            _chain(
                field_key="custody_holder",
                dimension="entities",
                event_id=ev_new,
                sequence=8,
                subject_ref=key_id,
                refs=(_ref(draft_id=str(uuid.uuid4()), version_number=2),),
            ),
        ],
    )
    await _checkpoint(
        db_session,
        test_project_id,
        scene,
        "entities",
        state,
        created_at=datetime(2026, 10, 7, 9, 0, tzinfo=UTC),
    )

    view = await _author_view(db_session, test_project_id, scene)
    provenance = _provenance(_facts(view, "entities", "custody_holder", key_id)[0])
    assert provenance["status"] == "exact"
    assert provenance["event_id"] == ev_new
    assert provenance["source_refs"][0]["version_number"] == 2


# ============================================================
# None 不冒充：旧格式与部分缺失
# ============================================================


async def test_view_legacy_state_and_missing_records_never_claim_exact(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)
    key_id, jia = (str(uuid.uuid4()) for _ in range(2))

    legacy_scene = await _scene(db_session, test_project_id, 1, 2)
    for dimension, state in (
        (
            "entities",
            {
                "entities": {key_id: {"name": "铜钥匙", "custody_holder": jia}},
                "changes": [],
            },
        ),
        (
            "locations",
            {"character_locations": {jia: {"location_id": "loc-x"}}, "changes": []},
        ),
        ("timeline", {"facts": [{"id": "f1", "moon_phase": "full"}], "changes": []}),
    ):
        # 旧格式：无 _field_provenance 键（第一阶段维度级 evidence_refs 形态）。
        await _checkpoint(
            db_session,
            test_project_id,
            legacy_scene,
            dimension,
            dict(state),
            created_at=datetime(2026, 10, 7, 9, 0, tzinfo=UTC),
        )
    legacy_view = await _author_view(db_session, test_project_id, legacy_scene)
    for dim in legacy_view.dimensions:
        for fact in dim.facts:
            assert "provenance" not in fact.source, (
                f"legacy must not carry provenance: {dim.dimension}/{fact.field}"
            )

    # 新格式但仅部分字段有链：无链的受控字段同样不带 provenance。
    partial_state = _embed(
        {"entities": {key_id: {"name": "铜钥匙", "custody_holder": jia}}, "changes": []},
        [
            _chain(
                field_key="custody_holder",
                dimension="entities",
                event_id=str(uuid.uuid4()),
                sequence=2,
                subject_ref=key_id,
                refs=(_ref(draft_id=str(uuid.uuid4())),),
            )
        ],
    )
    await _checkpoint(
        db_session,
        test_project_id,
        scene,
        "entities",
        partial_state,
        created_at=datetime(2026, 10, 7, 10, 0, tzinfo=UTC),
    )
    view = await _author_view(db_session, test_project_id, scene)
    holder = _facts(view, "entities", "custody_holder", key_id)[0]
    owner = _facts(view, "entities", "custody_owner", key_id)
    assert _provenance(holder)["status"] == "exact"
    assert owner == [] or "provenance" not in owner[0].source


# ============================================================
# get_record 历史回开暴露
# ============================================================


async def test_get_record_exposes_build_time_provenance_not_current_head(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)
    key_id = str(uuid.uuid4())
    draft_v1, draft_v2 = str(uuid.uuid4()), str(uuid.uuid4())

    def _holder_state(draft_id: str) -> dict:
        return _embed(
            {
                "entities": {key_id: {"name": "铜钥匙", "custody_holder": "乙"}},
                "changes": [],
            },
            [
                _chain(
                    field_key="custody_holder",
                    dimension="entities",
                    event_id=str(uuid.uuid4()),
                    sequence=4,
                    subject_ref=key_id,
                    refs=(_ref(draft_id=draft_id),),
                )
            ],
        )

    old_row = await _checkpoint(
        db_session,
        test_project_id,
        scene,
        "entities",
        _holder_state(draft_v1),
        is_current=False,
        created_at=datetime(2026, 10, 7, 9, 0, tzinfo=UTC),
    )
    new_row = await _checkpoint(
        db_session,
        test_project_id,
        scene,
        "entities",
        _holder_state(draft_v2),
        is_current=True,
        created_at=datetime(2026, 10, 7, 10, 0, tzinfo=UTC),
    )
    legacy_row = await _checkpoint(
        db_session,
        test_project_id,
        scene,
        "locations",
        {"character_locations": {}, "changes": []},  # 旧格式：无键
        created_at=datetime(2026, 10, 7, 10, 30, tzinfo=UTC),
    )
    projection = SceneMemoryProjectionService()

    old = await projection.get_record(db_session, test_project_id, str(old_row.id))
    assert old.is_current is False
    assert old.field_provenance, "historical checkpoint must expose per-field provenance"
    holder = next(
        item
        for item in old.field_provenance
        if item.get("field", item.get("field_key")) == "custody_holder"
    )
    old_refs = holder.get("source_refs") or []
    assert [ref["draft_id"] for ref in old_refs] == [draft_v1], (
        "old checkpoint provenance must stay on its build-time version"
    )

    new = await projection.get_record(db_session, test_project_id, str(new_row.id))
    assert new.is_current is True
    new_holder = next(
        item for item in new.field_provenance if item["field"] == "custody_holder"
    )
    assert [ref["draft_id"] for ref in new_holder["source_refs"]] == [draft_v2]

    legacy = await projection.get_record(db_session, test_project_id, str(legacy_row.id))
    assert legacy.field_provenance == [], "legacy checkpoint reads an empty list"


# ============================================================
# facade 出口：list_scene_checkpoints 隔离/排序/摘要
# ============================================================


async def test_list_scene_checkpoints_orders_desc_and_isolates_novel(
    db_session: AsyncSession, test_project_id: str
) -> None:
    from modules.story.continuity import facade as continuity_facade

    assert "list_scene_checkpoints" in continuity_facade.__all__

    scene = await _scene(db_session, test_project_id, 0, 3)
    key_id = str(uuid.uuid4())

    def _entities_state(with_provenance: bool) -> dict:
        return _embed(
            {"entities": {key_id: {"name": "铜钥匙"}}, "changes": []},
            [
                _chain(
                    field_key="custody_owner",
                    dimension="entities",
                    event_id=str(uuid.uuid4()),
                    sequence=2,
                    refs=(_ref(draft_id=str(uuid.uuid4())),),
                )
            ]
            if with_provenance
            else [],
        )

    superseded = await _checkpoint(
        db_session,
        test_project_id,
        scene,
        "entities",
        _entities_state(False),
        is_current=False,
        created_at=datetime(2026, 10, 7, 9, 0, tzinfo=UTC),
    )
    current = await _checkpoint(
        db_session,
        test_project_id,
        scene,
        "entities",
        _entities_state(True),
        is_current=True,
        created_at=datetime(2026, 10, 7, 10, 0, tzinfo=UTC),
    )
    timeline_row = await _checkpoint(
        db_session,
        test_project_id,
        scene,
        "timeline",
        {"facts": [], "changes": []},
        created_at=datetime(2026, 10, 7, 11, 0, tzinfo=UTC),
    )

    # 其他 novel 的同 scene_id 行：novel_id 隔离，不得混入。
    other_project = Project(id=uuid.uuid4(), title="他作", genre="奇幻")
    db_session.add(other_project)
    await db_session.flush()
    await _checkpoint(
        db_session,
        str(other_project.id),
        scene,
        "entities",
        _entities_state(True),
        created_at=datetime(2026, 10, 7, 12, 0, tzinfo=UTC),
    )

    rows = await continuity_facade.list_scene_checkpoints(
        db_session, test_project_id, str(scene.id)
    )
    assert [item["checkpoint_id"] for item in rows] == [
        str(timeline_row.id),
        str(current.id),
        str(superseded.id),
    ], "时间倒序且含已 supersede 行"
    by_id = {item["checkpoint_id"]: item for item in rows}
    assert by_id[str(current.id)]["is_current"] is True
    assert by_id[str(superseded.id)]["is_current"] is False
    # version 是同维度链上的时间序号（1 起，越大越新），非存储列。
    assert by_id[str(superseded.id)]["version"] == 1
    assert by_id[str(current.id)]["version"] == 2
    assert by_id[str(timeline_row.id)]["version"] == 1
    assert by_id[str(current.id)]["has_field_provenance"] is True
    assert by_id[str(superseded.id)]["has_field_provenance"] is False
    assert {item["chapter_index"] for item in rows} == {3}
    assert all(item["created_at"] for item in rows)

    entities_only = await continuity_facade.list_scene_checkpoints(
        db_session, test_project_id, str(scene.id), dimension="entities"
    )
    assert [item["checkpoint_id"] for item in entities_only] == [
        str(current.id),
        str(superseded.id),
    ]

    from core.errors import ValidationError

    with pytest.raises(ValidationError):
        await continuity_facade.list_scene_checkpoints(
            db_session, test_project_id, str(scene.id), dimension="not_a_dimension"
        )


# ============================================================
# state_trial：条件附带来源 status，判决理由明示，三值裁决不变
# ============================================================


async def _trial_world(db: AsyncSession, novel_id: str, actor: str) -> None:
    from modules.world.models import Character, CoreEntity

    db.add(
        CoreEntity(
            id=uuid.UUID(actor),
            novel_id=uuid.UUID(novel_id),
            name="甲",
            entity_type="character",
            status="canonical",
        )
    )
    await db.flush()
    db.add(
        Character(
            entity_id=uuid.UUID(actor),
            novel_id=uuid.UUID(novel_id),
            name="甲",
            status="canonical",
        )
    )
    await db.flush()


def _trial_states(
    key_id: str, actor: str, lock_id: str, *, holder_refs: bool
) -> dict[str, dict]:
    draft_id = str(uuid.uuid4())
    refs = (_ref(draft_id=draft_id),) if holder_refs else ()
    entities_records = [
        _chain(
            field_key="custody_holder",
            dimension="entities",
            event_id=str(uuid.uuid4()),
            sequence=4,
            subject_ref=key_id,
            refs=refs,
        ),
        *(
            _chain(
                field_key=field_key,
                dimension="entities",
                event_id=str(uuid.uuid4()),
                sequence=5,
                subject_ref=lock_id,
                refs=(_ref(draft_id=draft_id),),
            )
            for field_key in (
                "opening_key_id",
                "opening_moon_phase",
                "opening_passphrase",
            )
        ),
    ]
    return {
        "entities": _embed(
            {
                "entities": {
                    key_id: {
                        "name": "铜钥匙",
                        "custody_owner": actor,
                        "custody_holder": actor,
                    },
                    lock_id: {
                        "name": "三簧锁",
                        "opening_key_id": key_id,
                        "opening_moon_phase": "full",
                        "opening_passphrase": "潮落",
                    },
                },
                "changes": [],
            },
            entities_records,
        ),
        "locations": _embed(
            {
                "character_locations": {actor: {"location_id": "loc-a", "name": "甲"}},
                "changes": [],
            },
            [
                _chain(
                    field_key="location_id",
                    dimension="locations",
                    event_id=str(uuid.uuid4()),
                    sequence=3,
                    subject_ref=actor,
                    refs=(_ref(draft_id=draft_id),),
                )
            ],
        ),
        "knowledge": {
            "character_knowledge": [
                {
                    "id": "k-phrase",
                    "character_id": actor,
                    "subject_id": lock_id,
                    "fields": ["opening_passphrase"],
                    "known_values": {"opening_passphrase": "潮落"},
                    "knowledge": "甲知道口令",
                }
            ],
            "changes": [],
        },
        "timeline": _embed(
            {"facts": [{"id": "f-moon", "moon_phase": "full"}], "changes": []},
            [
                _chain(
                    field_key="moon_phase",
                    dimension="timeline",
                    event_id=str(uuid.uuid4()),
                    sequence=3,
                    refs=(_ref(draft_id=draft_id),),
                )
            ],
        ),
    }


async def _seed_trial_scene(
    db: AsyncSession,
    novel_id: str,
    *,
    holder_refs: bool,
) -> tuple[Scene, dict[str, str]]:
    scene = await _scene(db, novel_id, 0, 1)
    key_id, actor, lock_id = (str(uuid.uuid4()) for _ in range(3))
    await _trial_world(db, novel_id, actor)
    states = _trial_states(key_id, actor, lock_id, holder_refs=holder_refs)
    for dimension, state in states.items():
        await _checkpoint(
            db,
            novel_id,
            scene,
            dimension,
            state,
            created_at=datetime(2026, 10, 7, 9, 0, tzinfo=UTC),
        )
    return scene, {"key": key_id, "actor": actor, "lock": lock_id}


def _open_lock_request(scene: Scene, view, ids: dict[str, str]) -> SceneStateTrialRequest:
    return SceneStateTrialRequest(
        scene_id=scene.id,
        state_fingerprint=view.state_fingerprint,
        actor_id=uuid.UUID(ids["actor"]),
        key_id=uuid.UUID(ids["key"]),
        lock_id=uuid.UUID(ids["lock"]),
        action="open_lock",
    )


async def test_state_trial_cites_exact_sources_in_reason(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene, ids = await _seed_trial_scene(db_session, test_project_id, holder_refs=True)
    view = await _author_view(db_session, test_project_id, scene)

    result = await compare_scene_state_trial(
        db_session, test_project_id, _open_lock_request(scene, view, ids)
    )

    assert result["baseline"]["outcome"] == "succeeded"
    conditions = {item["label"]: item for item in result["baseline"]["conditions"]}
    assert conditions["行动者保管所需钥匙"]["source_status"] == "exact"
    assert conditions["当前月相满足开锁条件"]["source_status"] == "exact"
    # 口令知识是信念条目，非受控母题字段，不作来源断言。
    assert conditions["行动者有口令知识依据"]["source_status"] is None
    holder_reasons = [
        item
        for item in result["baseline"]["verdict_reason"]
        if "行动者保管所需钥匙" in item
    ]
    assert holder_reasons == ["「行动者保管所需钥匙」已精确回指依据（稿件修订 v1）"]
    # 精确回指的依据链随条件来源完整透出（事件 + 稿源区间）。
    holder_provenance = conditions["行动者保管所需钥匙"]["source"]["provenance"]
    assert holder_provenance["event_id"]
    assert holder_provenance["source_refs"]


async def test_state_trial_flags_unverified_without_changing_verdict(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene, ids = await _seed_trial_scene(db_session, test_project_id, holder_refs=False)
    view = await _author_view(db_session, test_project_id, scene)

    result = await compare_scene_state_trial(
        db_session, test_project_id, _open_lock_request(scene, view, ids)
    )

    # 三值裁决不变：字段值本身满足条件，来源降级不影响 succeeded。
    assert result["baseline"]["outcome"] == "succeeded"
    conditions = {item["label"]: item for item in result["baseline"]["conditions"]}
    assert conditions["行动者保管所需钥匙"]["source_status"] == "unverified"
    holder_provenance = conditions["行动者保管所需钥匙"]["source"]["provenance"]
    assert holder_provenance["source_refs"] == []
    assert holder_provenance["event_id"]
    holder_reasons = [
        item
        for item in result["baseline"]["verdict_reason"]
        if "行动者保管所需钥匙" in item
    ]
    assert holder_reasons == ["「行动者保管所需钥匙」字段来源未核实，结论待补充稿件依据"]


async def test_view_isolates_same_name_fields_across_entities(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """同维度多实体同名字段各走各的裁决链（subject_ref 汇合批裁定）。

    实体 B 后转移、实体 A 未动：A 的 custody_holder 仍指向自己的创建
    事件（exact），不冒充 B 的转移事件；B 指向转移事件。
    """
    scene = await _scene(db_session, test_project_id, 0, 1)
    key_a, key_b = str(uuid.uuid4()), str(uuid.uuid4())
    ev_a, ev_b_old, ev_b_new = (str(uuid.uuid4()) for _ in range(3))
    draft_id = str(uuid.uuid4())
    state = _embed(
        {
            "entities": {
                key_a: {"name": "青铜钥匙", "custody_holder": "甲"},
                key_b: {"name": "黄铜钥匙", "custody_holder": "丙"},
            },
            "changes": [],
        },
        [
            _chain(
                field_key="custody_holder",
                dimension="entities",
                event_id=ev_a,
                sequence=2,
                subject_ref=key_a,
                refs=(_ref(draft_id=draft_id),),
            ),
            _chain(
                field_key="custody_holder",
                dimension="entities",
                event_id=ev_b_old,
                sequence=2,
                subject_ref=key_b,
                refs=(_ref(draft_id=draft_id),),
            ),
            _chain(
                field_key="custody_holder",
                dimension="entities",
                event_id=ev_b_new,
                sequence=7,
                subject_ref=key_b,
                refs=(_ref(draft_id=draft_id, version_number=2),),
            ),
        ],
    )
    await _checkpoint(
        db_session,
        test_project_id,
        scene,
        "entities",
        state,
        created_at=datetime(2026, 10, 7, 9, 0, tzinfo=UTC),
    )

    view = await _author_view(db_session, test_project_id, scene)
    holders = {
        fact.subject_id: _provenance(fact)
        for dim in view.dimensions
        if dim.dimension == "entities"
        for fact in dim.facts
        if fact.field == "custody_holder"
    }
    assert set(holders) == {key_a, key_b}
    assert holders[key_a]["status"] == "exact"
    assert holders[key_a]["event_id"] == ev_a
    assert holders[key_b]["status"] == "exact"
    assert holders[key_b]["event_id"] == ev_b_new
    assert holders[key_b]["event_id"] != holders[key_a]["event_id"]

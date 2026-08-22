"""Add minimal semantic kinds for relations and aliases.

Revision ID: 20260822_relation_alias_kinds
Revises: 20260821_world_validation_runs
"""

from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "20260822_relation_alias_kinds"
down_revision = "20260821_world_validation_runs"
branch_labels = None
depends_on = None

_RELATION_KIND_BY_TYPE = {
    **{
        value: "social"
        for value in (
            "parent_of",
            "child_of",
            "spouse_of",
            "sibling_of",
            "friend_of",
            "rival_of",
            "enemy_of",
            "ally_of",
            "mentor_of",
            "student_of",
            "lover_of",
            "master_of",
            "servant_of",
            "member_of",
            "leader_of",
            "allied_with",
            "at_war_with",
            "trading_with",
            "sibling",
            "成员",
            "acquaintance",
            "colleague_of",
            "family",
            "tenant_of",
            "兄妹",
            "同事",
            "塔罗会成员",
            "师生",
            "customer",
            "daughter_of",
            "engaged_to",
            "family_member",
            "membership",
            "mentors",
            "pet_of",
            "ruler_of",
            "serves",
            "subordinate_of",
            "supervisor_of",
            "teacher_of",
            "上下级",
            "下属",
            "乘客",
            "兄弟",
            "占卜服务",
            "同伴",
            "同学",
            "宣称后裔",
            "就读于",
            "师从",
            "并肩作战",
            "执行者",
            "教导",
            "朋友",
            "未婚夫妻",
            "船长",
            "领导",
            "交易对手",
        )
    },
    **{
        value: "spatial"
        for value in (
            "located_at",
            "contains",
            "located_in",
            "位于",
            "包含",
            "has_on_desk",
            "举办地点",
            "携带",
        )
    },
    **{
        value: "causal"
        for value in (
            "created_by",
            "derived_from",
            "causes",
            "founded",
            "founds",
            "key_to",
            "以命名者命名",
            "修复",
            "修理",
            "创造了",
            "基础",
            "来源",
            "配制",
        )
    },
    "sequence_progression": "temporal",
    "subsequent_sequence": "temporal",
    **{
        value: "epistemic"
        for value in (
            "knows_about",
            "提及",
            "mentions",
            "verified",
            "contains_information",
            "knows",
            "reads",
            "suspects",
            "占卜与被占卜",
            "感知",
            "被注视",
            "被观测",
            "猜测的穿越者前辈",
            "理论认同",
        )
    },
    **{
        value: "intentional"
        for value in (
            "opposes",
            "supports",
            "seeks",
            "chooses",
            "collects",
            "consumes",
            "performs",
            "plans",
            "pursuit",
            "uses",
            "被跟踪",
            "访问",
            "选择了",
            "支持",
            "服食",
        )
    },
    "belongs_to": "state",
    "controls": "state",
    "related_to": "state",
}

_TITLE_ALIAS_TYPES = {"title", "称号", "头衔", "尊称", "职称", "塔罗会称号"}
_IDENTITY_ALIAS_TYPES = {
    "identity",
    "伪装",
    "伪装身份",
    "官方身份",
    "形态",
    "穿越前身份",
}


def _alias_kind(alias_type: object) -> str:
    normalized = str(alias_type or "name").strip().casefold()
    if normalized in _TITLE_ALIAS_TYPES:
        return "title"
    if normalized in _IDENTITY_ALIAS_TYPES:
        return "identity"
    return "name"


def _content_dict(value: object) -> dict | None:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None
        return dict(parsed) if isinstance(parsed, dict) else None
    return None


def _migrate_aliases(*, remove_kind: bool) -> None:
    bind = op.get_bind()
    entities = sa.table(
        "core_entities",
        sa.column("id"),
        sa.column("content_json", sa.JSON()),
    )
    rows = list(
        bind.execute(sa.select(entities.c.id, entities.c.content_json)).mappings()
    )
    for row in rows:
        content = _content_dict(row["content_json"])
        if content is None or not isinstance(content.get("aliases"), list):
            continue
        changed = False
        aliases = []
        for item in content["aliases"]:
            if isinstance(item, str):
                if remove_kind:
                    aliases.append(item)
                    continue
                aliases.append({"alias": item, "type": "name", "kind": "name"})
                changed = True
                continue
            if not isinstance(item, dict):
                aliases.append(item)
                continue
            normalized = dict(item)
            if remove_kind:
                if "kind" in normalized:
                    normalized.pop("kind")
                    changed = True
            else:
                alias_type = normalized.get("type") or normalized.get("alias_type")
                if not normalized.get("type"):
                    normalized["type"] = alias_type or "name"
                    changed = True
                kind = _alias_kind(alias_type)
                if normalized.get("kind") != kind:
                    normalized["kind"] = kind
                    changed = True
            aliases.append(normalized)
        if changed:
            content["aliases"] = aliases
            bind.execute(
                entities.update()
                .where(entities.c.id == row["id"])
                .values(content_json=content)
            )


def upgrade() -> None:
    op.add_column(
        "entity_relations",
        sa.Column("relation_kind", sa.String(16), nullable=True),
    )
    relations = sa.table(
        "entity_relations",
        sa.column("relation_type", sa.String(64)),
        sa.column("relation_kind", sa.String(16)),
    )
    normalized_type = sa.func.lower(sa.func.trim(relations.c.relation_type))
    kind_case = sa.case(
        *[
            (normalized_type == relation_type.casefold(), kind)
            for relation_type, kind in _RELATION_KIND_BY_TYPE.items()
        ],
        else_="state",
    )
    op.get_bind().execute(
        relations.update()
        .where(relations.c.relation_kind.is_(None))
        .values(relation_kind=kind_case)
    )
    _migrate_aliases(remove_kind=False)
    op.create_check_constraint(
        "ck_entity_relations_relation_kind",
        "entity_relations",
        "relation_kind IS NULL OR relation_kind IN "
        "('state', 'social', 'spatial', 'causal', 'temporal', "
        "'epistemic', 'intentional')",
    )
    op.create_check_constraint(
        "ck_entity_relations_canonical_kind",
        "entity_relations",
        "status <> 'canonical' OR relation_kind IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_entity_relations_canonical_kind",
        "entity_relations",
        type_="check",
    )
    op.drop_constraint(
        "ck_entity_relations_relation_kind",
        "entity_relations",
        type_="check",
    )
    _migrate_aliases(remove_kind=True)
    op.drop_column("entity_relations", "relation_kind")

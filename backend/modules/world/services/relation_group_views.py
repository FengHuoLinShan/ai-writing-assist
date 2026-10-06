"""世界库关系分组视角 — 服务端注册的浏览与维护预设。

视角（group view）把已采用 EntityRelation 行按方向归类为作者可维护的分组：
分组对象（group）位于关系一端，成员（member）是另一端。浏览归类只读取
既有关系，不改写关系类型、来源或端点；写入统一走 EntityRelationService
的正式确认路径。

预设匹配沿用 review_queue 的保守口径：视角只精确匹配列出的详细关系
字符串，并要求方向与两端对象类型同时满足；未知或含糊关系不通过名称、
描述、``related_to`` 或整个分类推断成员归属。
"""

from __future__ import annotations

from dataclasses import dataclass

GROUP_SIDES = ("source", "target")
CUSTOM_VIEW_KEY = "custom"


class RelationViewError(ValueError):
    """视角配置不合法（API 层映射为 422）。"""


@dataclass(frozen=True)
class RelationMatchRule:
    """一条视角匹配规则：详细关系 + 分组对象所在端。"""

    relation_type: str
    group_side: str


@dataclass(frozen=True)
class RelationGroupViewPreset:
    """服务端注册的视角预设。"""

    key: str
    title: str
    description: str
    group_types: tuple[str, ...]
    member_types: tuple[str, ...] | None  # None 表示不限类型。
    match_rules: tuple[RelationMatchRule, ...]
    default_relation_type: str
    default_relation_kind: str
    default_group_side: str
    custom: bool = False


AFFILIATION_VIEW = RelationGroupViewPreset(
    key="affiliation",
    title="势力成员",
    description="按势力／组织查看成员人物，维护成员归属。",
    group_types=("faction", "organization"),
    member_types=("character",),
    match_rules=(
        RelationMatchRule("member_of", "target"),
        RelationMatchRule("leader_of", "target"),
        RelationMatchRule("belongs_to", "target"),
    ),
    default_relation_type="member_of",
    default_relation_kind="social",
    default_group_side="target",
)

LOCATION_VIEW = RelationGroupViewPreset(
    key="location",
    title="地点关联",
    description="按地点查看位于其中的人与物，含子地点与包含关系。",
    group_types=("location",),
    member_types=None,
    match_rules=(
        RelationMatchRule("located_at", "target"),
        RelationMatchRule("located_in", "target"),
        RelationMatchRule("位于", "target"),
        RelationMatchRule("contains", "source"),
        RelationMatchRule("包含", "source"),
    ),
    default_relation_type="located_at",
    default_relation_kind="spatial",
    default_group_side="target",
)

POSSESSIONS_VIEW = RelationGroupViewPreset(
    key="possessions",
    title="人物持有",
    description="按人物查看持有的物品与资源。",
    group_types=("character",),
    member_types=("item", "object", "artifact", "resource"),
    match_rules=(
        RelationMatchRule("belongs_to", "target"),
        RelationMatchRule("携带", "source"),
    ),
    default_relation_type="belongs_to",
    default_relation_kind="state",
    default_group_side="target",
)

EVENT_VIEW = RelationGroupViewPreset(
    key="event",
    title="事件参与",
    description="按事件查看参与人物。",
    group_types=("event",),
    member_types=("character",),
    match_rules=(
        RelationMatchRule("participates_in", "target"),
        RelationMatchRule("参与", "target"),
    ),
    default_relation_type="participates_in",
    default_relation_kind="state",
    default_group_side="target",
)

PRESET_VIEWS: dict[str, RelationGroupViewPreset] = {
    view.key: view
    for view in (AFFILIATION_VIEW, LOCATION_VIEW, POSSESSIONS_VIEW, EVENT_VIEW)
}

# 视角可添加关系的作者展示标签；匹配与写入仍使用精确 relation_type。
_RELATION_LABELS = {
    "member_of": "成员",
    "leader_of": "领导者",
    "belongs_to": "属于",
    "located_at": "位于",
    "located_in": "位于（内）",
    "位于": "位于",
    "contains": "包含",
    "包含": "包含",
    "携带": "携带",
    "participates_in": "参与",
    "参与": "参与",
}


@dataclass(frozen=True)
class ResolvedGroupView:
    """一次请求解析后的视角配置：预设或自定义。"""

    key: str
    custom: bool
    group_types: tuple[str, ...]
    member_types: tuple[str, ...] | None
    match_rules: tuple[RelationMatchRule, ...]
    default_relation_type: str
    default_relation_kind: str
    default_group_side: str
    title: str = "自定义视角"
    description: str = "按作者选择的对象类型与详细关系归类。"


def relation_option_label(relation_type: str) -> str:
    return _RELATION_LABELS.get(relation_type, relation_type)


def resolve_group_view(
    group_view: str,
    *,
    group_type: str | None = None,
    member_type: str | None = None,
    relation_type: str | None = None,
    group_side: str | None = None,
) -> ResolvedGroupView:
    """把请求参数解析成视角配置；预设忽略自定义覆盖，custom 要求显式配置。"""
    key = str(group_view or "").strip()
    preset = PRESET_VIEWS.get(key)
    if preset is not None:
        return ResolvedGroupView(
            key=preset.key,
            custom=False,
            group_types=preset.group_types,
            member_types=preset.member_types,
            match_rules=preset.match_rules,
            default_relation_type=preset.default_relation_type,
            default_relation_kind=preset.default_relation_kind,
            default_group_side=preset.default_group_side,
            title=preset.title,
            description=preset.description,
        )
    if key != CUSTOM_VIEW_KEY:
        raise RelationViewError(f"Unknown group_view: {group_view!r}")

    resolved_group_type = str(group_type or "").strip()
    if not resolved_group_type:
        raise RelationViewError("custom group_view requires group_type")
    resolved_relation_type = str(relation_type or "").strip()
    if not resolved_relation_type:
        raise RelationViewError("custom group_view requires relation_type")
    resolved_side = str(group_side or "").strip()
    if resolved_side not in GROUP_SIDES:
        raise RelationViewError("custom group_view requires group_side source/target")
    resolved_member_type = str(member_type or "").strip()
    return ResolvedGroupView(
        key=CUSTOM_VIEW_KEY,
        custom=True,
        group_types=(resolved_group_type,),
        member_types=(resolved_member_type,) if resolved_member_type else None,
        match_rules=(RelationMatchRule(resolved_relation_type, resolved_side),),
        default_relation_type=resolved_relation_type,
        # 自定义关系必须显式给出最小语义分类（RELATION_KINDS 之一）。
        default_relation_kind="",
        default_group_side=resolved_side,
    )


def preset_view_payloads() -> list[dict[str, object]]:
    """序列化预设视角，供分组查询响应的 ``views`` 字段复用。"""
    payloads: list[dict[str, object]] = []
    for preset in PRESET_VIEWS.values():
        payloads.append(
            {
                "key": preset.key,
                "title": preset.title,
                "description": preset.description,
                "group_types": list(preset.group_types),
                "member_types": list(preset.member_types)
                if preset.member_types is not None
                else None,
                "match_relations": [
                    {
                        "relation_type": rule.relation_type,
                        "label": relation_option_label(rule.relation_type),
                        # 开放字符串关系（如 participates_in）没有通用 kind
                        # 映射时回退视角注册的默认分类，保证可添加。
                        "relation_kind": _match_rule_kind(rule.relation_type)
                        or preset.default_relation_kind,
                        "group_side": rule.group_side,
                    }
                    for rule in preset.match_rules
                ],
                "default_relation": {
                    "relation_type": preset.default_relation_type,
                    "label": relation_option_label(preset.default_relation_type),
                    "relation_kind": preset.default_relation_kind,
                    "group_side": preset.default_group_side,
                },
                "custom": False,
            }
        )
    return payloads


def _match_rule_kind(relation_type: str) -> str:
    from modules.world.services.core.review_queue import default_relation_kind

    kind = default_relation_kind(relation_type)
    return kind or ""

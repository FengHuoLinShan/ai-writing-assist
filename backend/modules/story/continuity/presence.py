"""Scene 在场与历史投影（V4 G2 / 计划 02-MAP §3.1 / 验收 T03）。

地图的空间表现消费 Story 的截止点投影：本模块从已提交的记忆事件推导
人物在场与地点历史，语义边界与计划一致：

- ``confirmed_in_scene``：本场景有原文/已确认事件支撑的在场；
- ``last_observed``：最后一次明确出现于此——显示"最后出现"而不是
  "当前就在这里"；
- 路线只在两节点之间存在**移动事实**（``entity_moved`` 事件）时标记
  ``traveled``；否则标记 ``unknown``——不造路程、交通方式、速度或
  到达时间（T03：甲地出现后乙地出现、路径未知时不得虚构移动细节）。

本投影是只读 DTO，不占有地图几何、不写任何表；地图册资产仍由 world
拥有（V 系列接线）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.continuity.repositories import EventRepository
from shared.utils import parse_uuid

PresenceKind = Literal["confirmed_in_scene", "last_observed"]
RouteStatus = Literal["traveled", "unknown"]


class PresenceNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str
    scene_index: int
    location: str
    presence_kind: PresenceKind = Field(description="confirmed_in_scene / last_observed")


class RouteSegment(BaseModel):
    """两个在场节点之间的行程语义；unknown 时没有任何移动细节字段。"""

    model_config = ConfigDict(extra="forbid")

    character_id: str
    from_scene_index: int
    from_location: str
    to_scene_index: int
    to_location: str
    status: RouteStatus = Field(
        description=(
            "traveled=有 entity_moved 证据；unknown=仅两次出现，不造路程/方式/时间"
        )
    )


class MapPresenceReport(BaseModel):
    """截止某 Scene 的人物在场与地点历史（只读投影）。"""

    model_config = ConfigDict(extra="forbid")

    through_scene_index: int
    nodes: list[PresenceNode] = Field(default_factory=list)
    segments: list[RouteSegment] = Field(default_factory=list)
    unknown_route_characters: list[str] = Field(default_factory=list)


def _travel_evidence_from(after: dict[str, Any]) -> str | None:
    """事件自述的移动来源；缺失即只是"此处出现"，不构成行程证据。"""
    value = after.get("moved_from") or after.get("from_location")
    return str(value) if value else None


def project_presence_from_events(
    events: list[Any],
    *,
    through_scene_index: int,
) -> MapPresenceReport:
    """从（已按 scene_index, scene_sequence 排序的）事件流推导在场报告。

    纯函数：只读事件，不接触数据库，可在任何截止点重放。
    """
    # character -> [(scene_index, location, travel_from)]
    timeline: dict[str, list[tuple[int, str, str | None]]] = {}
    for event in events:
        if str(event.event_type) != "entity_moved":
            continue
        if not event.entity_id:
            continue
        after = event.snapshot_after or {}
        location = after.get("text_state") or after.get("location_id")
        if not location:
            continue
        scene_index = (
            int(event.scene_index)
            if event.scene_index is not None
            else through_scene_index
        )
        if scene_index > through_scene_index:
            continue
        character = str(event.entity_id)
        entries = timeline.setdefault(character, [])
        if entries and entries[-1][:2] == (scene_index, str(location)):
            continue
        entries.append((scene_index, str(location), _travel_evidence_from(after)))

    nodes: list[PresenceNode] = []
    segments: list[RouteSegment] = []
    unknown_route_characters: list[str] = []
    for character, entries in timeline.items():
        last_index = entries[-1][0]
        for scene_index, location, _ in entries:
            nodes.append(
                PresenceNode(
                    character_id=character,
                    scene_index=scene_index,
                    location=location,
                    presence_kind=(
                        "last_observed"
                        if scene_index == last_index
                        else "confirmed_in_scene"
                    ),
                )
            )
        for (from_scene, from_loc, _), (to_scene, to_loc, travel_from) in zip(
            entries, entries[1:]
        ):
            if from_loc == to_loc:
                continue
            # 只有后一事件自带移动来源且与前一地点一致才算有据行程；
            # 两次出现之间无证据 → unknown，不造路程/方式/时间（T03）。
            traveled = travel_from is not None and travel_from == from_loc
            segments.append(
                RouteSegment(
                    character_id=character,
                    from_scene_index=from_scene,
                    from_location=from_loc,
                    to_scene_index=to_scene,
                    to_location=to_loc,
                    status="traveled" if traveled else "unknown",
                )
            )
            if not traveled:
                unknown_route_characters.append(character)
    return MapPresenceReport(
        through_scene_index=through_scene_index,
        nodes=nodes,
        segments=segments,
        unknown_route_characters=sorted(set(unknown_route_characters)),
    )


async def project_scene_presence(
    db: AsyncSession,
    novel_id: str,
    *,
    through_scene_index: int,
) -> MapPresenceReport:
    """读取截止某 Scene 的记忆事件并投影在场（经 repository 单一入口）。"""
    events = await EventRepository().get_through_scene(
        db,
        parse_uuid(novel_id, "novel_id"),
        through_scene_index,
    )
    return project_presence_from_events(events, through_scene_index=through_scene_index)

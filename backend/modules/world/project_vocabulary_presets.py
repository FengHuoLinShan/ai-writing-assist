"""Versioned, copy-on-apply project vocabulary seeds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresetItem:
    key: str
    kind: str
    name: str
    description: str
    aliases: tuple[str, ...] = ()
    traits: dict[str, tuple[str, ...]] | None = None


@dataclass(frozen=True)
class VocabularyPreset:
    id: str
    version: int
    label: str
    items: tuple[PresetItem, ...]


PRESETS = {
    "xianxia": VocabularyPreset(
        id="xianxia",
        version=1,
        label="修仙",
        items=(
            PresetItem(
                "cave-heaven",
                "space",
                "洞天",
                "自成体系的独立空间",
                traits={"containment": ("independent_space",)},
            ),
            PresetItem(
                "spiritual-domain", "level", "灵域", "表示空间层级，不限定地理深度"
            ),
            PresetItem(
                "spirit-vein",
                "feature",
                "灵脉",
                "可沿线表示的灵气脉络",
                traits={"geometry": ("line",)},
            ),
            PresetItem(
                "cross-realm-array",
                "relation",
                "跨界传送",
                "连接不同空间的传送关系",
                traits={"connection": ("traversable", "cross_space")},
            ),
            PresetItem(
                "sword-flight",
                "transport",
                "御剑",
                "以御剑完成的旅行方式",
                traits={"other": ("movable",)},
            ),
        ),
    ),
    "fantasy": VocabularyPreset(
        id="fantasy",
        version=1,
        label="西幻",
        items=(
            PresetItem(
                "plane",
                "space",
                "位面",
                "可与其他位面分离的空间",
                traits={"containment": ("independent_space",)},
            ),
            PresetItem("realm", "level", "王国", "常见政治或地理层级"),
            PresetItem(
                "castle",
                "feature",
                "城堡",
                "有内部空间的地点",
                traits={"geometry": ("area",), "containment": ("can_contain",)},
            ),
            PresetItem(
                "portal",
                "relation",
                "传送门",
                "连接不同空间的通道",
                traits={"connection": ("traversable", "cross_space")},
            ),
            PresetItem("mounted-travel", "transport", "骑乘", "骑乘坐骑的旅行方式"),
        ),
    ),
    "urban": VocabularyPreset(
        id="urban",
        version=1,
        label="都市",
        items=(
            PresetItem("city-space", "space", "城市空间", "城市内的连续空间"),
            PresetItem("block", "level", "街区", "城市中的街区层级"),
            PresetItem(
                "building",
                "feature",
                "建筑",
                "可容纳楼层或房间的地点",
                traits={"geometry": ("area",), "containment": ("can_contain",)},
            ),
            PresetItem(
                "street-link",
                "relation",
                "道路连通",
                "沿道路可通行的连接",
                traits={"connection": ("traversable",)},
            ),
            PresetItem("subway", "transport", "地铁", "城市轨道交通方式"),
        ),
    ),
    "science_fiction": VocabularyPreset(
        id="science_fiction",
        version=1,
        label="科幻",
        items=(
            PresetItem(
                "star-domain",
                "space",
                "星域",
                "跨越星系的独立空间范围",
                traits={"containment": ("independent_space",)},
            ),
            PresetItem("star-system", "level", "星系", "恒星与其相关天体构成的层级"),
            PresetItem(
                "star-gate",
                "feature",
                "星门",
                "可作为连接端点的设施",
                traits={"geometry": ("point",)},
            ),
            PresetItem(
                "jump-route",
                "relation",
                "跃迁通道",
                "可连接不同空间的跃迁关系",
                traits={"connection": ("traversable", "cross_space")},
            ),
            PresetItem(
                "faster-than-light",
                "transport",
                "超光速航行",
                "跨星际的旅行方式",
                traits={"connection": ("traversable", "cross_space")},
            ),
        ),
    ),
    "mystery": VocabularyPreset(
        id="mystery",
        version=1,
        label="悬疑",
        items=(
            PresetItem("case-space", "space", "案发空间", "用于组织案件相关地点"),
            PresetItem("room-level", "level", "房间", "室内调查常用层级"),
            PresetItem(
                "entrance",
                "feature",
                "出入口",
                "可作为室内通行端点",
                traits={"geometry": ("point",)},
            ),
            PresetItem(
                "sealed-route",
                "relation",
                "封闭通道",
                "存在通行限制的连接",
                traits={"connection": ("traversable", "directed")},
            ),
            PresetItem(
                "lockdown", "access_condition", "封锁", "地点或通道当前不可自由通行"
            ),
        ),
    ),
}

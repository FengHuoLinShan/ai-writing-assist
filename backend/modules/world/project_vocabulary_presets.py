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
    profile_type: str | None = None


@dataclass(frozen=True)
class VocabularyPreset:
    id: str
    version: int
    label: str
    items: tuple[PresetItem, ...]
    extensions: tuple[tuple[int, tuple[PresetItem, ...]], ...] = ()


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

# Version 1 remains byte-for-byte the original spatial package. Version 2 adds
# copy-on-apply dossier-facing terms scoped to each built-in object type.
_DOSSIER_PRESET_ITEMS = {
    "xianxia": (
        PresetItem(
            "cultivation-path",
            "dossier_facing",
            "修行路径",
            "修为、功法与修行选择",
            profile_type="character",
        ),
        PresetItem(
            "spirit-vein-history",
            "dossier_facing",
            "灵脉与禁地",
            "灵气流向、洞天与禁地特征",
            profile_type="location",
        ),
        PresetItem(
            "artifact-spirit",
            "dossier_facing",
            "灵性与代价",
            "灵性、器灵、使用条件与反噬",
            profile_type="item",
        ),
        PresetItem(
            "sect-lineage",
            "dossier_facing",
            "宗门传承",
            "宗旨、传承、职位与资源",
            profile_type="faction",
        ),
        PresetItem(
            "bloodline-customs",
            "dossier_facing",
            "血脉与习俗",
            "种族血脉特征及修行相关习俗",
            profile_type="species",
        ),
        PresetItem(
            "realm-limits",
            "dossier_facing",
            "境界规则",
            "境界条件、突破限制与代价",
            profile_type="rule",
        ),
        PresetItem(
            "karma-reveal",
            "dossier_facing",
            "因果与揭示",
            "真相关联的因果线索和揭示顺序",
            profile_type="secret",
        ),
        PresetItem(
            "tribulation-impact",
            "dossier_facing",
            "劫变影响",
            "事件缘起、波及范围与后果",
            profile_type="event",
        ),
    ),
    "fantasy": (
        PresetItem(
            "oaths-lineage",
            "dossier_facing",
            "血统与誓约",
            "血统、封臣誓约与个人信念",
            profile_type="character",
        ),
        PresetItem(
            "old-world-traces",
            "dossier_facing",
            "古迹与传说",
            "古代遗迹、遗民和地方传说",
            profile_type="location",
        ),
        PresetItem(
            "enchantment",
            "dossier_facing",
            "附魔与诅咒",
            "附魔、诅咒、触发条件和代价",
            profile_type="item",
        ),
        PresetItem(
            "banner-covenant",
            "dossier_facing",
            "旗帜与盟约",
            "领主、骑士团、盟约及利益",
            profile_type="faction",
        ),
        PresetItem(
            "heritage",
            "dossier_facing",
            "族裔传承",
            "寿命、族裔传统与代际差异",
            profile_type="species",
        ),
        PresetItem(
            "arcane-domain",
            "dossier_facing",
            "奥术领域",
            "魔法体系、适用边界与反噬",
            profile_type="rule",
        ),
        PresetItem(
            "divine-bargain",
            "dossier_facing",
            "神祇契约",
            "秘密契约、知情范围和揭示风险",
            profile_type="secret",
        ),
        PresetItem(
            "prophecy-consequence",
            "dossier_facing",
            "预言后果",
            "预言兑现时的因果与影响",
            profile_type="event",
        ),
    ),
    "urban": (
        PresetItem(
            "work-and-routine",
            "dossier_facing",
            "职业与日常",
            "职业角色、生活习惯与社交节奏",
            profile_type="character",
        ),
        PresetItem(
            "neighborhood-life",
            "dossier_facing",
            "街区生活",
            "人群、营业节奏、声音和气味",
            profile_type="location",
        ),
        PresetItem(
            "daily-use",
            "dossier_facing",
            "日常用途",
            "物件的使用习惯、来历和情感意义",
            profile_type="item",
        ),
        PresetItem(
            "organization-culture",
            "dossier_facing",
            "组织文化",
            "团队制度、岗位关系与资源",
            profile_type="faction",
        ),
        PresetItem(
            "community-customs",
            "dossier_facing",
            "群体习俗",
            "社群生活方式和代际习惯",
            profile_type="species",
        ),
        PresetItem(
            "institutional-rules",
            "dossier_facing",
            "制度边界",
            "法律、职场或社会规则的适用范围",
            profile_type="rule",
        ),
        PresetItem(
            "private-network",
            "dossier_facing",
            "私下关系网",
            "秘密关系、知情者与暴露风险",
            profile_type="secret",
        ),
        PresetItem(
            "daily-consequences",
            "dossier_facing",
            "生活后果",
            "事件对工作、家庭和日常的影响",
            profile_type="event",
        ),
    ),
    "science_fiction": (
        PresetItem(
            "identity-carrier",
            "dossier_facing",
            "身份与载体",
            "意识、身份与生物或机械载体",
            profile_type="character",
        ),
        PresetItem(
            "habitat-conditions",
            "dossier_facing",
            "栖居条件",
            "重力、空气、辐射和环境限制",
            profile_type="location",
        ),
        PresetItem(
            "interface-upgrade",
            "dossier_facing",
            "接口与改造",
            "义体接口、升级能力和维护代价",
            profile_type="item",
        ),
        PresetItem(
            "political-structure",
            "dossier_facing",
            "政治结构",
            "组织、殖民地或舰队的权责关系",
            profile_type="faction",
        ),
        PresetItem(
            "body-lifespan",
            "dossier_facing",
            "身体与寿命",
            "生理差异、寿命和适应限制",
            profile_type="species",
        ),
        PresetItem(
            "technology-boundary",
            "dossier_facing",
            "技术边界",
            "科技原理、前提、失效与后果",
            profile_type="rule",
        ),
        PresetItem(
            "data-provenance",
            "dossier_facing",
            "数据来源",
            "秘密信息的载体、来源和可信范围",
            profile_type="secret",
        ),
        PresetItem(
            "system-impact",
            "dossier_facing",
            "系统影响",
            "技术事件的影响范围与连锁后果",
            profile_type="event",
        ),
    ),
    "mystery": (
        PresetItem(
            "cover-and-tells",
            "dossier_facing",
            "伪装与破绽",
            "角色说法、习惯反应与可观察破绽",
            profile_type="character",
        ),
        PresetItem(
            "sightlines-access",
            "dossier_facing",
            "视线与出入",
            "视线遮挡、出入口和可达路径",
            profile_type="location",
        ),
        PresetItem(
            "evidence-chain",
            "dossier_facing",
            "证据链",
            "物件保管、痕迹和证据缺口",
            profile_type="item",
        ),
        PresetItem(
            "authority-boundary",
            "dossier_facing",
            "权限与关系",
            "调查权限、利益关系和管辖范围",
            profile_type="faction",
        ),
        PresetItem(
            "forensic-traits",
            "dossier_facing",
            "身体线索",
            "可观察的生理差异与鉴别限制",
            profile_type="species",
        ),
        PresetItem(
            "investigation-limits",
            "dossier_facing",
            "调查边界",
            "证据门槛、推断条件和例外",
            profile_type="rule",
        ),
        PresetItem(
            "reveal-order",
            "dossier_facing",
            "揭示顺序",
            "秘密的知情范围、揭示安排与风险",
            profile_type="secret",
        ),
        PresetItem(
            "clue-turn",
            "dossier_facing",
            "线索转折",
            "线索出现、误导和推动的事件变化",
            profile_type="event",
        ),
    ),
}

PRESETS = {
    preset_id: VocabularyPreset(
        id=preset.id,
        version=preset.version,
        label=preset.label,
        items=preset.items,
        extensions=((2, _DOSSIER_PRESET_ITEMS[preset_id]),),
    )
    for preset_id, preset in PRESETS.items()
}


def preset_item_profile_type(
    preset_id: str | None, preset_version: int | None, item_key: str | None
) -> str | None:
    if not preset_id or not item_key:
        return None
    preset = PRESETS.get(preset_id)
    if preset is None:
        return None
    for version, items in ((preset.version, preset.items), *preset.extensions):
        if version == preset_version:
            item = next((item for item in items if item.key == item_key), None)
            return item.profile_type if item is not None else None
    return None

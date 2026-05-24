"""
全局枚举定义

所有模块公用的枚举类型，集中定义在此处，
避免跨模块的循环导入和重复定义。
"""

from __future__ import annotations

from enum import StrEnum


# ============================================================
# 实体与对象相关
# ============================================================

class EntityType(StrEnum):
    """世界对象类型 — 需要长期维护的创作资产"""

    location = "location"
    """地点 — 国家、城市、地标、建筑"""
    faction = "faction"
    """组织 — 国家势力、宗派、公会、家族"""
    item = "item"
    """物品 — 神器、信物、关键道具"""
    event = "event"
    """历史事件 — 战争、灾难、重大仪式"""
    rule = "rule"
    """规则 — 世界法则、魔法规则、社会规则"""
    power_system = "power_system"
    """能力体系 — 魔法体系、修炼体系"""
    secret = "secret"
    """秘密 — 隐藏真相、未揭示信息"""
    legend = "legend"
    """传说 — 神话、民间传说、未证实的历史"""
    resource = "resource"
    """资源 — 稀有材料、矿产资源、特殊物品"""
    character_ref = "character_ref"
    """人物引用 — 作为世界对象被引用的角色"""


class ObjectStatus(StrEnum):
    """对象生命周期状态 — 用于所有正史和候选对象"""

    draft = "draft"
    """草稿 — 用户手动创建，尚未确认"""
    candidate = "candidate"
    """候选 — AI 生成，等待 review"""
    canonical = "canonical"
    """正史 — 已确认进入正史"""
    deprecated = "deprecated"
    """弃用 — 不再使用（保留历史）"""
    ignored = "ignored"
    """忽略 — 候选被拒绝"""
    conflicted = "conflicted"
    """冲突 — 检测到冲突，待处理"""
    pending = "pending"
    """待定 — 等待用户决策"""


class CandidateAction(StrEnum):
    """候选对象建议动作"""

    create_new = "create_new"
    """创建为新正史对象"""
    merge_with_existing = "merge_with_existing"
    """合并到已有对象"""
    alias_of_existing = "alias_of_existing"
    """标记为已有对象的别名"""
    ignore = "ignore"
    """忽略该候选"""
    temporary_only = "temporary_only"
    """仅临时使用，不建议入正史"""
    needs_user_decision = "needs_user_decision"
    """需要用户决策"""


class ImportanceLevel(StrEnum):
    """对象重要性级别"""

    core = "core"
    """核心 — 推动主线不可或缺"""
    important = "important"
    """重要 — 影响关键剧情"""
    normal = "normal"
    """普通 — 有维护价值"""
    temporary = "temporary"
    """临时 — 场景相关"""
    alias = "alias"
    """别名 — 不独立建对象"""


# ============================================================
# 人物相关
# ============================================================

class KnowledgeLevel(StrEnum):
    """人物对某事物的了解程度"""

    unknown = "unknown"
    """不知道"""
    rumor = "rumor"
    """听过传闻（可能不准确）"""
    partial = "partial"
    """部分了解"""
    full = "full"
    """完全了解"""
    false_belief = "false_belief"
    """误解（自认为知道但是错的）"""


class CharacterRole(StrEnum):
    """人物角色定位"""

    protagonist = "protagonist"
    """主角"""
    antagonist = "antagonist"
    """反派/对手"""
    supporting = "supporting"
    """重要配角"""
    minor = "minor"
    """次要角色"""
    mentor = "mentor"
    """导师"""
    love_interest = "love_interest"
    """恋爱对象"""
    comic_relief = "comic_relief"
    """喜剧调剂"""
    foil = "foil"
    """对比角色"""
    narrator = "narrator"
    """叙述者"""
    cameo = "cameo"
    """客串"""


# ============================================================
# 可见性与揭示相关
# ============================================================

class Visibility(StrEnum):
    """信息的读者/角色可见性"""

    author_only = "author_only"
    """仅作者可见 — 隐藏真相"""
    author_safe = "author_safe"
    """作者安全 — 作者知道，但需防止提前泄露"""
    reader_known = "reader_known"
    """读者已知 — 已经揭示给读者"""
    public = "public"
    """公开 — 角色也知道"""


class RevealLevel(StrEnum):
    """对象的揭示层级"""

    author_only = "author_only"
    """仅作者知道"""
    hinted = "hinted"
    """已埋下伏笔"""
    revealed = "revealed"
    """已揭示"""
    fully_known = "fully_known"
    """读者和角色都知道"""


# ============================================================
# 剧情相关
# ============================================================

class PlotThreadType(StrEnum):
    """剧情线类型"""

    main = "main"
    """主线"""
    secondary = "secondary"
    """支线"""
    hidden = "hidden"
    """暗线"""
    relationship = "relationship"
    """关系线"""
    villain = "villain"
    """反派线"""
    foreshadowing = "foreshadowing"
    """伏笔线"""


# ============================================================
# 事件与时间线
# ============================================================

class EventType(StrEnum):
    """时间线事件类型"""

    plot = "plot"
    """剧情事件"""
    character = "character"
    """人物事件"""
    world = "world"
    """世界观事件"""
    battle = "battle"
    """战斗/冲突"""
    travel = "travel"
    """旅行/迁移"""
    discovery = "discovery"
    """发现/揭示"""
    relationship = "relationship"
    """关系变化"""
    geo_change = "geo_change"
    """地理变化"""
    offscreen = "offscreen"
    """幕外事件"""


# ============================================================
# 记忆相关
# ============================================================

class MemoryType(StrEnum):
    """长期记忆记录类型"""

    chapter_state = "chapter_state"
    """章节结束时的状态快照"""
    event = "event"
    """重要事件"""
    character_state = "character_state"
    """人物状态变化"""
    knowledge = "knowledge"
    """知识/信息变化"""
    foreshadowing = "foreshadowing"
    """伏笔状态"""
    resource = "resource"
    """资源状态变化"""
    outline_drift = "outline_drift"
    """大纲偏离记录"""
    geo_history = "geo_history"
    """地理/历史变化"""


# ============================================================
# 地理相关
# ============================================================

class LocationLevel(StrEnum):
    """地理层级"""

    continent = "continent"
    """大陆"""
    country = "country"
    """国家"""
    region = "region"
    """地区/省"""
    city = "city"
    """城市/城镇"""
    district = "district"
    """区/街区"""
    landmark = "landmark"
    """地标"""
    building = "building"
    """建筑"""
    room = "room"
    """房间/室内"""


class GeoEdgeType(StrEnum):
    """地理关系类型"""

    road_to = "road_to"
    """道路连接"""
    river_to = "river_to"
    """水路连接"""
    inside = "inside"
    """位于内部"""
    north_of = "north_of"
    """在...北面"""
    south_of = "south_of"
    """在...南面"""
    east_of = "east_of"
    """在...东面"""
    west_of = "west_of"
    """在...西面"""
    near = "near"
    """附近"""
    hidden_path = "hidden_path"
    """隐藏通道"""
    blocked_path = "blocked_path"
    """阻断路径"""
    borders = "borders"
    """接壤"""


class AccessLevel(StrEnum):
    """地点访问级别"""

    normal = "normal"
    """普通 — 可自由出入"""
    restricted = "restricted"
    """限制 — 需许可/条件"""
    dangerous = "dangerous"
    """危险 — 有生命危险"""
    forbidden = "forbidden"
    """禁止 — 不可进入"""
    secret = "secret"
    """秘密 — 不为人知"""


# ============================================================
# 关系相关
# ============================================================

class RelationType(StrEnum):
    """实体间关系类型（通用）"""

    # 人物关系
    parent_of = "parent_of"
    child_of = "child_of"
    spouse_of = "spouse_of"
    sibling_of = "sibling_of"
    friend_of = "friend_of"
    rival_of = "rival_of"
    enemy_of = "enemy_of"
    ally_of = "ally_of"
    mentor_of = "mentor_of"
    student_of = "student_of"
    lover_of = "lover_of"
    master_of = "master_of"
    servant_of = "servant_of"
    # 势力关系
    member_of = "member_of"
    leader_of = "leader_of"
    allied_with = "allied_with"
    at_war_with = "at_war_with"
    trading_with = "trading_with"
    # 对象关系
    belongs_to = "belongs_to"
    created_by = "created_by"
    located_at = "located_at"
    contains = "contains"
    controls = "controls"
    # 通用
    related_to = "related_to"
    opposes = "opposes"
    supports = "supports"


class RelationDirection(StrEnum):
    """关系方向"""

    directed = "directed"
    """有向 — A→B 和 B→A 含义不同"""
    undirected = "undirected"
    """无向 — 双向含义相同"""


# ============================================================
# 复查相关
# ============================================================

class ReviewDecision(StrEnum):
    """结构复查决策结果"""

    pass_ = "pass"
    """通过 — 无问题"""
    minor_revision = "minor_revision"
    """小修 — 有轻微问题需调整"""
    major_revision = "major_revision"
    """大修 — 有重大问题需修改"""
    reject = "reject"
    """拒绝 — 不可接受"""


# ============================================================
# 任务相关
# ============================================================

class TaskStatus(StrEnum):
    """异步任务状态"""

    pending = "pending"
    """等待中"""
    running = "running"
    """运行中"""
    done = "done"
    """已完成"""
    failed = "failed"
    """失败"""
    cancelled = "cancelled"
    """已取消"""


class TaskType(StrEnum):
    """异步任务类型"""

    embedding_build = "embedding_build"
    rag_reindex = "rag_reindex"
    world_structure_generate = "world_structure_generate"
    plot_structure_generate = "plot_structure_generate"
    chapter_scene_generate = "chapter_scene_generate"
    structure_review = "structure_review"
    memory_extract = "memory_extract"
    import_text = "import_text"


# ============================================================
# 其他枚举
# ============================================================

class ExtractionMode(StrEnum):
    """AI 对象抽取模式"""

    strict = "strict"
    """严格 — 只抽取 importance >= 0.75 的核心对象"""
    normal = "normal"
    """正常 — 抽取 importance >= 0.45 的常规对象"""
    full = "full"
    """全面 — 尽量全面，但只作为 Mention 或候选"""


class ProposalType(StrEnum):
    """memory update proposal 类型"""

    create_memory = "create_memory"
    update_memory = "update_memory"
    update_character_state = "update_character_state"
    update_knowledge = "update_knowledge"
    add_timeline_event = "add_timeline_event"
    update_foreshadowing = "update_foreshadowing"


class AliasType(StrEnum):
    """别名类型"""

    name = "name"
    """名称别名 — 其他名字"""
    title = "title"
    """称号 — 尊称、绰号"""
    nickname = "nickname"
    """昵称 — 亲昵称呼"""
    alias = "alias"
    """化名 — 隐藏身份用"""
    translation = "translation"
    """翻译名 — 不同语言"""
    abbreviation = "abbreviation"
    """缩写"""


class ForeshadowingStatus(StrEnum):
    """伏笔状态"""

    planned = "planned"
    """已计划"""
    seeded = "seeded"
    """已埋下"""
    reinforced = "reinforced"
    """已加强"""
    paid_off = "paid_off"
    """已收束"""
    abandoned = "abandoned"
    """已废弃"""

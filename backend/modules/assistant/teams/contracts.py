"""Team inputs and handoffs; identity and source authority remain server-owned."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from modules.assistant.schemas import (
    AssistantAnswer,
    ProposedAction,
    StrictModel,
    TurnCreate,
)


class TeamRunCreate(TurnCreate):
    blueprint: Literal[
        "deep_review",
        "world_stress",
        "cross_revision",
        "research",
        "import_consult",
        "blind_reader",
    ] = "deep_review"
    allow_web: bool = False
    reading_start_chapter: int | None = Field(default=None, ge=1)
    previous_report_id: UUID | None = None
    scenario_keys: list[str] = Field(default_factory=list, max_length=12)
    preserved_constraints: list[Annotated[str, Field(min_length=1, max_length=2000)]] = (
        Field(default_factory=list, max_length=20)
    )

    @model_validator(mode="after")
    def review_target(self):
        if (
            self.previous_report_id or self.scenario_keys
        ) and self.blueprint != "world_stress":
            raise ValueError("情境重测只适用于世界观压力测试")
        if self.scenario_keys and not self.previous_report_id:
            raise ValueError("定向重测必须指定原报告")
        if self.blueprint == "deep_review" and (
            not self.context.draft_id or not self.context.chapter_index
        ):
            raise ValueError("请先选择要审查的正文版本与章节")
        if (
            self.blueprint in {"world_stress", "import_consult"}
            and not self.context.target
        ):
            raise ValueError("请先选择要查证的世界规则或导入疑难组")
        if self.blueprint == "world_stress" and self.context.target.get(
            "target_type"
        ) not in {
            "world_entity",
            "core_entity",
            "world_bible_page",
            "world_bible_page_draft",
            "world_checkpoint",
        }:
            raise ValueError("请选择世界规则、资料页或世界模型")
        if self.blueprint == "import_consult" and (
            self.context.target.get("target_type") != "import_review_resolution"
            or not self.context.target.get("target_path")
        ):
            raise ValueError("请从原导入疑难组开始深入查证")
        if self.blueprint == "blind_reader" and not self.context.chapter_index:
            raise ValueError("盲读需要明确截止章节")
        if self.blueprint != "research" and self.allow_web:
            raise ValueError("此项检查不使用联网资料")
        if self.blueprint == "research" and (
            not self.allow_web or self.web_backend != "searxng-v1"
        ):
            raise ValueError("专题研究需要本次明确允许公开资料搜索")
        return self


class EvidenceQuote(StrictModel):
    evidence_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    excerpt: str = Field(min_length=1, max_length=2000)


class FindingDraft(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    claim: str = Field(min_length=1, max_length=3000)
    category: Literal["fact", "character", "narrative"]
    severity: Literal["major", "minor", "suggestion"]
    claim_type: Literal[
        "source_statement", "inference", "proposal", "simulation_assumption"
    ]
    evidence: list[EvidenceQuote] = Field(min_length=1, max_length=8)
    counterevidence: list[EvidenceQuote] = Field(default_factory=list, max_length=8)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    uncertainty: str = Field(default="", max_length=2000)
    suggested_repair: str = Field(default="", max_length=2000)


class Investigation(StrictModel):
    summary: str = Field(min_length=1, max_length=5000)
    findings: list[FindingDraft] = Field(default_factory=list, max_length=12)
    read_evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    checked_dimensions: list[str] = Field(default_factory=list, max_length=12)
    omissions: list[str] = Field(default_factory=list, max_length=12)


class RepairOption(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=200)
    preserves: list[str] = Field(default_factory=list, max_length=20)
    tradeoffs: list[str] = Field(default_factory=list, max_length=20)
    remaining_questions: list[str] = Field(default_factory=list, max_length=20)
    actions: list[ProposedAction] = Field(min_length=1, max_length=20)


class TeamAnswer(AssistantAnswer):
    actions: list[ProposedAction] = Field(default_factory=list, max_length=0)
    plans: list[RepairOption] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def mutually_exclusive_plans(self):
        if self.plans and self.actions:
            raise ValueError("先选择整体方案，再准备一个具体修改批次")
        if len({plan.key for plan in self.plans}) != len(self.plans):
            raise ValueError("方案标识不能重复")
        return self


class TeamPlanSelection(StrictModel):
    novel_id: str

    @field_validator("novel_id")
    @classmethod
    def canonical_project(cls, value: str):
        return str(UUID(value))

    plan_key: str
    expected_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


DEEP_REVIEW_ROLES = {
    "facts": ("事实与规则：查证时序、地点、能力和规则的因果矛盾；区分新提案与已有事实。"),
    "characters": (
        "人物动机与知识：查证承诺、行动动机和信息来源；"
        "只有实际角色资料支持时检查知识边界。"
    ),
    "narrative": (
        "叙事结构与读者信息：检查铺垫、兑现、因果和信息落差；"
        "尊重伏笔、不可靠叙述与有意留白。"
    ),
}


BLUEPRINTS = {
    "blind_reader": {
        "label": "盲读者检查",
        "roles": {"reader": "逐章盲读，只依据已经展示的正文冻结认知。"},
    },
    "deep_review": {"label": "深度审稿", "roles": DEEP_REVIEW_ROLES},
    "world_stress": {
        "label": "世界观压力测试",
        "roles": {
            "rules": (
                "规则前提：提炼已有规则与不变量，逐字引用；区分额外假设和作者决定。"
            ),
            "exploits": (
                "利益主体与利用路径：构造普通、极端和组合情境，给出行动顺序与代价。"
            ),
            "counterexamples": (
                "反例核查：寻找违反不变量的路径，同时寻找使反例无效的前提；尊重有意缺陷。"
            ),
        },
    },
    "cross_revision": {
        "label": "设定变更与跨章修订",
        "roles": {
            "dependencies": (
                "影响范围：追踪旧规则与新规则的正文关联"
                "，区分明确依赖、可能影响和未检查章节。"
            ),
            "characters": (
                "人物影响：追查动机、信息和关系后果；严格保留作者列出的事件和结局。"
            ),
            "repairs": (
                "修订路径：比较最小改动和结构调整，定"
                "位精确原文与版本；找出相互冲突的修改。"
            ),
        },
    },
    "research": {
        "label": "创作专题研究",
        "roles": {
            "sources": (
                "一手资料：独立查找并读取原文，注明版本、"
                "访问时间和实际范围；不可用搜索摘要作证。"
            ),
            "counterexamples": (
                "来源反证：查找相反结论、适用条件和来源冲突；同一原文不算多份独立证据。"
            ),
            "applications": (
                "创作应用：区分现实事实、推论与可选的虚构设计，列出采用代价和未验证事项。"
            ),
        },
    },
    "import_consult": {
        "label": "导入疑难会诊",
        "roles": {
            "identity": (
                "身份查证：回读疑难组关联原文，寻找同一"
                "身份/化名的直接证据，不以同名认定同人。"
            ),
            "distinctions": (
                "区分证据：寻找异人、称号继承、时间和类型冲突；保留作者已经裁定的条目。"
            ),
            "relations": (
                "关系核查：定位两端对象、时间和出处；缺证时保留待决，不按多数票合并。"
            ),
        },
    },
}


def blueprint_snapshot(blueprint="deep_review") -> dict:
    from infrastructure.llm.collaboration import content_hash
    from modules.assistant.evidence_tools import author_read_tools

    allowed = {"inspect_current", "search_project", "read_evidence", "current_scene"}
    if blueprint == "research":
        allowed |= {"search_general_fact", "read_web_source"}
    if blueprint == "import_consult":
        allowed = {"inspect_current", "read_evidence"}
    snapshot = {
        "id": blueprint,
        "label": BLUEPRINTS[blueprint]["label"],
        "version": 1,
        "protocol": "collaboration_v1",
        "roles": BLUEPRINTS[blueprint]["roles"],
        "concurrency": 3,
        "member_requests": 4,
        "budget_policy": "team_v1",
        "final_reserve": 12,
        "read_tools": {
            tool.name: content_hash(tool.function_schema.json_schema)
            for tool in author_read_tools(allow_web=blueprint == "research", version="3")
            if tool.name in allowed
        },
    }
    return {**snapshot, "hash": content_hash(snapshot)}

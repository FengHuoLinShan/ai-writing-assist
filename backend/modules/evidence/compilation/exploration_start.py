"""
导演多尺度独立探索：临时起点契约（P0 冻结）

Scene 锚点与临时假设（无 Scene、无正式角色）两类起点的判别联合。
本文件是确认契约的权威定义：story 模块经 `modules.evidence.contracts` 再导出引用，
不复制定义；字段语义见
`.agent/tasks/2026/T-20261017-director-scales-impl/P0-CONTRACTS.md` §1。
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

_CANDIDATE_REF_PATTERN = r"^c_[a-z0-9_]{1,63}$"

EXPLORATION_SCALE_LITERAL = Literal["sandbox", "event", "scene_line"]
HANDOFF_SELECTOR_LITERAL = Literal["author", "assistant"]


class ExplorationContractModel(BaseModel):
    """探索契约模型基类：禁止额外字段，保证冻结契约不被扩展。"""

    model_config = ConfigDict(extra="forbid")


class SceneAnchorStart(ExplorationContractModel):
    """已有 Scene 锚点起点：走既有 Scene 截止与存在性校验。"""

    kind: Literal["scene_anchor"]
    scene_id: str = Field(..., min_length=1, description="当前作品内的 Scene ID")


class CandidateRef(ExplorationContractModel):
    """临时人物/地点/物件/组织：作者侧标识仅在任务内有效，禁冒充正式对象 ID。"""

    ref_id: str = Field(..., pattern=_CANDIDATE_REF_PATTERN)
    label: str = Field(..., min_length=1, max_length=100)
    role: Literal["character", "location", "item", "organization"]


class Assumption(ExplorationContractModel):
    """作者声明的世界规则、状态或身份假设；模型推测不得伪称来源证据。"""

    kind: Literal["world_rule", "state", "identity"]
    text: str = Field(..., min_length=1, max_length=2000)


class KnowledgeEntry(ExplorationContractModel):
    """临时主体的可知包：只依据明确声明；未声明的信息一律未知。"""

    subject_ref: str = Field(..., min_length=1, max_length=64)
    knows: list[str] = Field(default_factory=list, max_length=20)
    observed: list[str] = Field(default_factory=list, max_length=20)
    misbelieves: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_texts(self):
        for field in ("knows", "observed", "misbelieves"):
            for item in getattr(self, field):
                if not item or len(item) > 500:
                    raise ValueError(
                        f"knowledge.{field} entries must be 1..500 characters"
                    )
        return self


class CanonicalSceneStimulus(ExplorationContractModel):
    """仅对正式角色的场景本地刺激/假设；以“场景本地假设”前缀进入该角色包，不升级为正史。"""

    subject_entity_id: str = Field(..., description="正式角色 entity_id（UUID）")
    stimulus: str = Field(..., min_length=1, max_length=500)


class WebRef(ExplorationContractModel):
    """作者已开启联网时助手当轮实际读取的网页快照引用；worker 不做实时检索。"""

    url: str = Field(..., min_length=1, max_length=2048)
    title: str = Field(default="", max_length=300)
    retrieved_at: str = Field(..., min_length=1, max_length=64)
    content_hash: str = Field(..., min_length=64, max_length=64)
    excerpt: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_web_ref(self):
        scheme, _, rest = self.url.partition("://")
        if scheme.lower() not in ("http", "https"):
            raise ValueError("web_refs.url must be http/https")
        authority = rest.split("/", 1)[0] if rest else ""
        if "@" in authority:
            raise ValueError("web_refs.url must not embed credentials")
        if any(
            character not in "0123456789abcdef" for character in self.content_hash.lower()
        ):
            raise ValueError("web_refs.content_hash must be 64 hex characters")
        return self


class HandoffRef(ExplorationContractModel):
    """跨尺度移交溯源（M4-A 切片 1）：只记直接父结果（一跳），不追全链。

    ``item_path`` 用冻结路径语法（chain:N/gap:N/bridge:N/line）定位被选条目，
    空串表示整结果移交（目标输入按方向语义全量继承）；
    ``selector`` 记录选择者（作者直选或助手经操作目录选择），
    ``reason`` 在助手选择时必填（0..500，记录选择理由供审计）。
    """

    source_result_id: str = Field(..., description="直接父探索结果行 ID（UUID）")
    source_scale: EXPLORATION_SCALE_LITERAL
    item_path: str = Field(default="", max_length=120)
    selector: HANDOFF_SELECTOR_LITERAL
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_handoff_ref(self):
        try:
            uuid.UUID(self.source_result_id)
        except (ValueError, AttributeError, TypeError) as error:
            raise ValueError("handoff.source_result_id must be a UUID") from error
        if self.selector == "assistant" and not self.reason:
            raise ValueError("handoff.reason 在助手选择时必填")
        return self


class ProvisionalStart(ExplorationContractModel):
    """临时假设起点：无 Scene、无正式角色也可开局；空项目资料集同样要有确认。

    ``derived_from``（M4-A）只在跨尺度移交派生的起点上出现；普通起点为
    None 且序列化时省略该键，旧载荷反序列化与指纹逐字节不变。
    """

    kind: Literal["provisional"]
    question: str = Field(..., min_length=1, max_length=4000)
    assumptions: list[Assumption] = Field(..., min_length=1, max_length=50)
    candidates: list[CandidateRef] = Field(default_factory=list, max_length=50)
    canonical_refs: list[str] = Field(default_factory=list, max_length=24)
    knowledge: list[KnowledgeEntry] = Field(default_factory=list, max_length=50)
    scene_stimuli: list[CanonicalSceneStimulus] = Field(
        default_factory=list, max_length=50
    )
    author_private: list[str] = Field(default_factory=list, max_length=20)
    time_basis: str = Field(..., description="“assumed_now” 或 1..500 字符的时点锚点描述")
    web_refs: list[WebRef] = Field(default_factory=list, max_length=10)
    derived_from: HandoffRef | None = None

    @model_serializer(mode="wrap")
    def _compatible_shape(self, handler):
        """旧载荷兼容：无移交时省略 derived_from 键，历史指纹/round-trip 不变。"""
        data = handler(self)
        if data.get("derived_from") is None:
            data.pop("derived_from", None)
        return data

    @model_validator(mode="after")
    def validate_provisional(self):
        if self.time_basis != "assumed_now" and not (1 <= len(self.time_basis) <= 500):
            raise ValueError("time_basis must be 'assumed_now' or 1..500 characters")
        for item in self.author_private:
            if not item or len(item) > 2000:
                raise ValueError("author_private entries must be 1..2000 characters")
        candidate_ids = {candidate.ref_id for candidate in self.candidates}
        if len(candidate_ids) != len(self.candidates):
            raise ValueError("candidates.ref_id must be unique")
        for entity_id in self.canonical_refs:
            try:
                uuid.UUID(entity_id)
            except (ValueError, AttributeError, TypeError) as error:
                raise ValueError("canonical_refs must be UUID entity ids") from error
        for entry in self.knowledge:
            if entry.subject_ref not in candidate_ids:
                try:
                    uuid.UUID(entry.subject_ref)
                except (ValueError, AttributeError, TypeError) as error:
                    raise ValueError(
                        "knowledge.subject_ref must be a candidate ref_id "
                        "or canonical entity id"
                    ) from error
        return self


ExplorationStart = SceneAnchorStart | ProvisionalStart
"""起点判别联合；序列化/反序列化经 `kind` 判别（请求模型上用 discriminator）。"""

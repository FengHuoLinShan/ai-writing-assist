"""方向卡 LLM step（BR-5 流程 1 的 Assistant 侧新 step）。

一句构想（+可选题材/篇幅意向）→ 一次结构化调用出 2-3 张方向卡（题材承诺、
主冲突、主角与目标、世界基调与独特设定、读者期待、主要风险）。卡片只作为
候选存进流程运行检查点（``AssistantRun.checkpoint_json``），不是资产；作者
选定并可修改字段后才冻结为流程的作者决定。配置只经
``open_project_llm_client()``（provider/model/Key 来自项目 owner 已验证的
账户连接），有 schema、预算与超时；预算硬性收敛在：单批一次结构化调用、
至多 1 次格式修复、输入长度有界、每流程至多 ``MAX_BATCHES`` 批。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from modules.project.facade import open_project_llm_client

# 单批预算：一次结构化调用 + 至多 1 次格式修复；重试不计新调用。
_MAX_FIX_ATTEMPTS = 1
# 输入有界：构想截断到 2000 字，题材/篇幅意向各 200 字。
_VISION_MAX_CHARS = 2000
_HINT_MAX_CHARS = 200
# 每个流程至多要 3 批方向卡（首批 + 再要 2 批）；超出拒绝并说明。
MAX_BATCHES = 3
# 单次调用的硬超时（秒）；同时作为请求级 timeout_override 的上限依据。
_TIMEOUT_SECONDS = 180

_STEP_NAME = "assistant.guided_flow.direction_cards"
_CAPABILITY_ID = "assistant.guided_flow.direction_cards"

_SYSTEM_PROMPT = (
    "你是小说开篇的方向顾问。根据作者的一句构想，给出 2-3 个彼此明显不同、"
    "都可行的开篇方向。每个方向用作者语言写，不出现 ID、JSON 或术语；"
    "不写正文，不决定结局，只描述方向本身。各字段都从读者体验出发，"
    "具体、可取舍：题材承诺说明这本书大致像什么；主冲突写出推动前几十章的"
    "对立；主角与目标写清谁、想要什么、为什么难；世界基调与独特设定突出"
    "和别人不一样的地方；读者期待写出读者会一直追下去的理由；主要风险"
    "诚实说明这个方向最难写好的地方。"
)


class DirectionCard(BaseModel):
    """一张方向卡：六个固定字段，全部作者语言。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=60)
    genre_promise: str = Field(min_length=1, max_length=300)
    central_conflict: str = Field(min_length=1, max_length=300)
    protagonist_goal: str = Field(min_length=1, max_length=300)
    world_tone: str = Field(min_length=1, max_length=300)
    reader_promise: str = Field(min_length=1, max_length=300)
    main_risk: str = Field(min_length=1, max_length=300)


class DirectionCardBatch(BaseModel):
    """一次调用的输出：2-3 张卡；不足或多于都算格式失败并触发修复。"""

    model_config = ConfigDict(extra="forbid")

    cards: list[DirectionCard] = Field(min_length=2, max_length=3)


def _user_content(
    vision: str, genre_hint: str, length_hint: str, batch: int
) -> str:
    parts = [f"作者的一句构想：{vision[:_VISION_MAX_CHARS]}"]
    if genre_hint:
        parts.append(f"题材意向：{genre_hint[:_HINT_MAX_CHARS]}")
    if length_hint:
        parts.append(f"篇幅意向：{length_hint[:_HINT_MAX_CHARS]}")
    if batch > 1:
        parts.append(
            f"这是第 {batch} 批方向；之前几批作者都不满意，"
            "请给出与常见写法明显不同的新方向，不要重复之前的思路。"
        )
    return "\n".join(parts)


async def draft_direction_cards(
    db,
    novel_id: str,
    *,
    vision: str,
    genre_hint: str = "",
    length_hint: str = "",
    batch: int = 1,
) -> list[DirectionCard]:
    """一次结构化调用产出一批方向卡；只返回候选，不做任何持久化。"""
    from infrastructure.llm.agent_step_harness import run_managed_structured
    from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

    async with open_project_llm_client(db, novel_id) as client:
        request = LLMCallRequest(
            model=client.model_name,
            messages=[
                LLMMessage(role="system", content=_SYSTEM_PROMPT),
                LLMMessage(
                    role="user",
                    content=_user_content(vision, genre_hint, length_hint, batch),
                ),
            ],
            temperature=0.8,
        )
        generated = await run_managed_structured(
            client,
            request,
            DirectionCardBatch,
            step_name=_STEP_NAME,
            capability_id=_CAPABILITY_ID,
            max_fix_attempts=_MAX_FIX_ATTEMPTS,
            timeout=_TIMEOUT_SECONDS,
            read_only=True,
        )
    return list(generated.cards)

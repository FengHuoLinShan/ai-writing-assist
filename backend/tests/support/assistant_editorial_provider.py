"""Scripted synthetic replies for the editorial review / comment revision closed loop.

Only the assistant browser harness imports this module: the browser still runs
the real API, SQL and worker, while every model call gets a deterministic
reply keyed off the structured-output schema title plus marker sentences that
the E2E seeds into the chapter text — the same pattern as
``creative_browser_provider.structured_reply``. No real model is contacted.
"""

from __future__ import annotations

import asyncio
import json

from infrastructure.llm.schemas import LLMCallResponse, LLMUsage

# 章节正文里的脚本开关：E2E 用它们驱动慢速/失败路径。
SLOW_MARKER = "这一段审读会刻意放慢"
FAIL_MARKER = "这一段审读会失败"
# 意见与补丁的固定文案：E2E 按同一常量断言 UI 展示。
EDITORIAL_JUDGMENT = "两处地名线索互相矛盾，建议统一口径"
READER_JUDGMENT = "旧钟异象让读者过早期待超自然解释"
EDITORIAL_QUOTE = "信封上的地址指向旧港"
READER_QUOTE = "雾港的旧钟在午夜敲了十三下"
REVISION_MARKER = "（已按处置说明收紧）"

_USAGE = LLMUsage(prompt_tokens=100, completion_tokens=30, total_tokens=130)


def _schema_title(request) -> str | None:
    final = request.messages[-1].content
    if "schema: " not in final:
        return None
    try:
        return json.loads(final.split("schema: ", 1)[1])["title"]
    except (ValueError, KeyError, TypeError):
        return None


def _user_payload(request) -> dict:
    for message in request.messages:
        if message.role == "user":
            try:
                return json.loads(message.content)
            except ValueError:
                return {}
    return {}


def _invalid_response() -> LLMCallResponse:
    # 不能用截断 JSON：客户端会把截断候选自动补全成 {}（schema 全默认值），
    # 审读反而以“零意见”完成。这里返回合法 JSON 但违反 schema（summary 非字符串），
    # max_fix_attempts=0 时立即失败关闭，审读落到 failed 终态。
    return LLMCallResponse(content='{"summary": 0}', usage=_USAGE)


def _review_pass_reply(request, payload: dict) -> LLMCallResponse:
    text = str(payload.get("text") or "")
    if FAIL_MARKER in text:
        return _invalid_response()
    reader = any(
        "顺序初读者" in (message.content or "")
        for message in request.messages
        if message.role == "system"
    )
    if reader:
        findings = (
            [
                {
                    "category": "reader",
                    "judgment": READER_JUDGMENT,
                    "reader_impact": "读者可能把异象当成主线承诺，后续不兑现会失落",
                    "severity": "low",
                    "evidence": [
                        {
                            "chapter_index": int(payload["chapter_index"]),
                            "quote": READER_QUOTE,
                        }
                    ],
                    "context_evidence": [],
                    "counterevidence": "也可能只是氛围铺垫",
                    "directions": [
                        {
                            "approach": "下一章内轻量回应一次钟声",
                            "affected_chapters": [int(payload["chapter_index"])],
                            "tradeoff": "占少量篇幅",
                        },
                        {
                            "approach": "暂时搁置，只在后文回收",
                            "affected_chapters": [int(payload["chapter_index"]) + 1],
                            "tradeoff": "悬念保留更久",
                        },
                    ],
                }
            ]
            if READER_QUOTE in text
            else []
        )
        value = {
            "summary": "顺序初读完成，记录了两条读者侧观察。",
            "reader_state": "读者已注意到旧钟异象与信封线索。",
            "findings": findings,
        }
    elif "nodes" in payload:
        # 卷/全书逐层汇总：不新增跨章根因，直接收口。
        value = {
            "summary": "汇总完成，未发现需要跨章合并的新根因。",
            "reader_state": "",
            "findings": [],
        }
    else:
        findings = (
            [
                {
                    "category": "structure",
                    "judgment": EDITORIAL_JUDGMENT,
                    "reader_impact": "读者可能过早确定地点，削弱后续悬念",
                    "severity": "medium",
                    "evidence": [
                        {
                            "chapter_index": int(payload["chapter_index"]),
                            "quote": EDITORIAL_QUOTE,
                        }
                    ],
                    "context_evidence": [],
                    "counterevidence": "也可能是人物笔误或刻意误导",
                    "why_now": "下一章将沿信件线索展开，口径需要先统一",
                    "directions": [
                        {
                            "approach": "把地址改成模糊表述，延后确认",
                            "affected_chapters": [int(payload["chapter_index"])],
                            "tradeoff": "悬念持续更久",
                        },
                        {
                            "approach": "让人物明确承认抄错地址",
                            "affected_chapters": [int(payload["chapter_index"])],
                            "tradeoff": "牺牲一点紧张感换取清晰",
                        },
                    ],
                }
            ]
            if EDITORIAL_QUOTE in text
            else []
        )
        value = {
            "summary": "已按约定审读本章，重点记录了地名线索的矛盾。"
            if findings
            else "已按约定审读本章，没有值得打断的问题。",
            "reader_state": "",
            "findings": findings,
        }
    return LLMCallResponse(
        content=json.dumps(value, ensure_ascii=False),
        finish_reason="stop",
        usage=_USAGE,
    )


def _recheck_reply(payload: dict) -> LLMCallResponse:
    snippets = payload.get("new_snippets") or []
    finding = payload.get("old_finding") or {}
    evidence = (finding.get("evidence") or [{}])[0]
    chapter = int(evidence.get("chapter_index") or 1)
    text = snippets[0].get("text") if snippets else ""
    if REVISION_MARKER in text:
        value = {
            "verdict": "possibly_improved",
            "reason": "问题引文所在句已按处置说明改写，本轮未再见原矛盾表述。",
            "new_evidence": [{"chapter_index": chapter, "quote": REVISION_MARKER}],
            "unchecked": "",
        }
    elif str(evidence.get("quote") or "") in text:
        value = {
            "verdict": "still",
            "reason": "原引文仍在当前稿中，问题未变化。",
            "new_evidence": [{"chapter_index": chapter, "quote": str(evidence["quote"])}],
            "unchecked": "",
        }
    else:
        value = {
            "verdict": "unknown",
            "reason": "原引文与修订标记都不在本次节选中，无法判断。",
            "new_evidence": [],
            "unchecked": "仅核对了与原问题有关的正文节选",
        }
    return LLMCallResponse(
        content=json.dumps(value, ensure_ascii=False),
        finish_reason="stop",
        usage=_USAGE,
    )


def _director_reply(request) -> LLMCallResponse:
    user = next(
        (message.content for message in request.messages if message.role == "user"),
        "",
    )
    keys = [
        line[2:].split(" | ", 1)[0].strip()
        for line in user.splitlines()
        if line.startswith("- ")
    ]
    value = {
        "dispositions": [
            {
                "source_key": key,
                "disposition": "required_for_generation",
                "reason": "批注修订需要这份来源",
            }
            for key in keys
        ]
    }
    return LLMCallResponse(
        content=json.dumps(value, ensure_ascii=False),
        finish_reason="stop",
        usage=_USAGE,
    )


def _revision_reply(payload: dict) -> LLMCallResponse:
    ranges = payload.get("editable_ranges") or []
    value = {
        "patches": [
            {
                "patch_id": item["patch_id"],
                "replacement": f"{item['source_text']}{REVISION_MARKER}",
            }
            for item in ranges
        ]
    }
    return LLMCallResponse(
        content=json.dumps(value, ensure_ascii=False),
        finish_reason="stop",
        usage=_USAGE,
    )


async def editorial_reply(request) -> LLMCallResponse | None:
    """Deterministic replies for editorial review / recheck / comment revision.

    Returns ``None`` when the request is not part of the editorial closed loop
    so the harness can continue with its other scripted behaviours.
    """
    title = _schema_title(request)
    if title is None:
        return None
    if title == "ReviewPass":
        payload = _user_payload(request)
        if SLOW_MARKER in str(payload.get("text") or ""):
            await asyncio.sleep(3)
        return _review_pass_reply(request, payload)
    if title == "RecheckOutput":
        return _recheck_reply(_user_payload(request))
    if title == "DirectorShardPlan":
        return _director_reply(request)
    if title == "WritingTargetedRevisionOutput":
        return _revision_reply(_user_payload(request))
    return None

"""Dedicated-database browser harness with the real API/worker and synthetic model IO."""
# ruff: noqa: E402 — validate the isolated environment before importing the application.

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.engine import make_url

from core.config import get_settings

_settings = get_settings()
_url = make_url(_settings.database_url)
if (
    os.environ.get("ASSISTANT_BROWSER_HARNESS") != "1"
    or _settings.app_env != "test"
    or _url.host not in {"localhost", "127.0.0.1"}
    or "agent_e2e" not in (_url.database or "")
):
    raise RuntimeError(
        "Assistant browser harness requires an explicit isolated local test database"
    )

from app.main import app
from core.database import get_manager
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import (
    LLMCallResponse,
    LLMStreamChunk,
    LLMToolCall,
    LLMUsage,
)
from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
from modules.account.settings_constants import (
    ACCOUNT_LLM_PROVIDER_TEMPLATES,
    LOCAL_OWNER_ID,
)
from modules.account.settings_repositories import (
    AccountLLMCredentialRepository,
    GlobalLLMDefaultsRepository,
)
from run_worker import _build_task_worker


async def _generate(_self, request):
    await asyncio.sleep(0.1)
    planning = next(
        (
            tool
            for tool in request.tools
            if "scene_intent" in tool.parameters.get("properties", {})
        ),
        None,
    )
    if planning:
        return LLMCallResponse(
            tool_calls=[
                LLMToolCall(
                    id="browser-plan",
                    name=planning.name,
                    arguments=json.dumps(
                        {"scene_intent": "沿着当前选择继续故事，保留用户身份与约定。"},
                        ensure_ascii=False,
                    ),
                )
            ],
            usage=LLMUsage(prompt_tokens=100, completion_tokens=30, total_tokens=130),
        )
    output = next(
        (
            tool
            for tool in request.tools
            if "answer" in tool.parameters.get("properties", {})
        ),
        None,
    )
    if output is None:
        return LLMCallResponse(
            content="ok",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
        )
    values = "\n".join(message.content for message in request.messages)
    latest = next(
        (
            message.content
            for message in reversed(request.messages)
            if message.role == "user"
        ),
        "",
    )
    if "IANA" in latest:
        tools = {tool.name for tool in request.tools}
        results = {
            message.tool_call_id: json.loads(message.content)
            for message in request.messages
            if message.role == "tool"
        }
        if "search_general_fact" not in tools:
            result = {"answer": "本轮未开启公开资料查证，请先开启后继续。"}
        elif "browser-search" not in results:
            return LLMCallResponse(
                tool_calls=[
                    LLMToolCall(
                        id="browser-search",
                        name="search_general_fact",
                        arguments='{"question":"IANA example domains"}',
                    )
                ],
                usage=LLMUsage(prompt_tokens=100, completion_tokens=30, total_tokens=130),
            )
        elif results["browser-search"].get("hits") and "browser-page" not in results:
            return LLMCallResponse(
                tool_calls=[
                    LLMToolCall(
                        id="browser-page",
                        name="read_web_source",
                        arguments=json.dumps(
                            {
                                "evidence_id": results["browser-search"]["hits"][0][
                                    "evidence_id"
                                ]
                            }
                        ),
                    )
                ],
                usage=LLMUsage(prompt_tokens=100, completion_tokens=30, total_tokens=130),
            )
        elif results.get("browser-page", {}).get("text"):
            result = {
                "answer": "已读取 IANA 对示例域名的说明，下面可查看实际网页依据。",
                "evidence_ids": [results["browser-page"]["evidence_id"]],
            }
        else:
            result = {
                "answer": "本次未完成网页查证。",
                "omissions": [
                    results.get("browser-page", {}).get(
                        "omission", "没有取得可读取的搜索结果"
                    )
                ],
            }
        return LLMCallResponse(
            tool_calls=[
                LLMToolCall(
                    id="browser-result",
                    name=output.name,
                    arguments=json.dumps(result, ensure_ascii=False),
                )
            ],
            usage=LLMUsage(prompt_tokens=100, completion_tokens=30, total_tokens=130),
        )
    if "相似资料" in latest:
        results = {
            message.tool_call_id: json.loads(message.content)
            for message in request.messages
            if message.role == "tool"
        }
        if "browser-dedup" not in results:
            return LLMCallResponse(
                tool_calls=[
                    LLMToolCall(
                        id="browser-dedup",
                        name="scan_duplicates",
                        arguments=json.dumps({"arguments": {"scopes": ["world_entity"]}}),
                    )
                ],
                usage=LLMUsage(prompt_tokens=100, completion_tokens=30, total_tokens=130),
            )
        receipt = results["browser-dedup"]
        return LLMCallResponse(
            tool_calls=[
                LLMToolCall(
                    id="browser-result",
                    name=output.name,
                    arguments=json.dumps(
                        {
                            "answer": "已完成相似资料扫描，可打开原比较工作台。",
                            "evidence_ids": [receipt["evidence_id"]]
                            if receipt.get("evidence_id")
                            else [],
                        },
                        ensure_ascii=False,
                    ),
                )
            ],
            usage=LLMUsage(prompt_tokens=100, completion_tokens=30, total_tokens=130),
        )
    match = re.search(r"日历日期为 (\d{4}-\d{2}-\d{2})", values)
    today = date.fromisoformat(match[1]) if match else date.today()
    result = {
        "answer": "已准备明天的核对事项。请确认后加入作者待办。",
        "actions": [
            {
                "key": "age",
                "capability": "project.add_task",
                "title": "记录年龄核对事项",
                "reason": "保留明确的下一步，方便下次继续。",
                "arguments": {
                    "title": "核对人物年龄",
                    "note": "比较当前章节与人物资料。",
                    "due_date": (today + timedelta(days=1)).isoformat(),
                },
            }
        ],
    }
    if "世界草稿" in latest:
        result = {
            "answer": "已准备一份世界资料工作稿，请确认后保存。",
            "actions": [
                {
                    "key": "page",
                    "capability": "world.create_page_draft",
                    "title": "保存钟楼设定草稿",
                    "reason": "保留本次模拟讨论的成果。",
                    "arguments": {
                        "title": "模拟钟楼",
                        "free_text": "钟楼正在修复，修复前不报时。",
                    },
                }
            ],
        }
    return LLMCallResponse(
        tool_calls=[
            LLMToolCall(
                id="browser-result",
                name=output.name,
                arguments=json.dumps(result, ensure_ascii=False),
            )
        ],
        usage=LLMUsage(prompt_tokens=100, completion_tokens=30, total_tokens=130),
    )


async def _no_external_io(*args, **kwargs):
    raise RuntimeError(
        "This harness never calls external models or supplier-native search"
    )


async def _stream(_self, request):
    async def chunks():
        for part in [
            "门外传来脚步声。",
            "你停在书架旁，",
            "等那名访客走近。",
            "他摘下帽子，",
            "把一封信放在桌上。",
            "窗边的灯仍亮着，",
            "你记得先前的约定，",
            "没有急着拆开信封。",
        ]:
            await asyncio.sleep(0.5)
            yield LLMStreamChunk(content=part)
        yield LLMStreamChunk(
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=100, completion_tokens=30, total_tokens=130),
        )

    return chunks()


OpenAIProvider.generate = _generate
OpenAIProvider.research = _no_external_io
OpenAIProvider.generate_stream = _stream
_original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _lifespan(application):
    async with _original_lifespan(application):
        async with get_manager().session() as db:
            key = "synthetic-browser-only"
            await AccountLLMCredentialRepository().upsert(
                db,
                {
                    "owner_id": LOCAL_OWNER_ID,
                    "provider_id": "deepseek",
                    "encrypted_api_key": encrypt_secret(key),
                    "key_fingerprint": fingerprint_secret(
                        key, purpose="account-llm-api-key"
                    ),
                    "verified_at": datetime.now(UTC),
                },
            )
            await GlobalLLMDefaultsRepository().upsert(
                db,
                {
                    "owner_id": LOCAL_OWNER_ID,
                    **ACCOUNT_LLM_PROVIDER_TEMPLATES["deepseek"],
                },
            )
        worker = _build_task_worker()
        task = asyncio.create_task(worker.run_forever())
        try:
            yield
        finally:
            worker.stop()
            await asyncio.wait_for(task, 10)


app.router.lifespan_context = _lifespan

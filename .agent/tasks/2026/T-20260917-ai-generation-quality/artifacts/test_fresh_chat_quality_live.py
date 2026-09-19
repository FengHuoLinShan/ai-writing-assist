"""Fresh synthetic domains, written after the port-case repairs; no human blind eval."""

import json
import os
from pathlib import Path

import pytest

from test_ai_quality_live import measured_provider  # noqa: F401
from modules.account.settings_service import SettingsService
from modules.world.tests.test_world_cocreation_sessions import _create_project

pytestmark = [
    pytest.mark.real_llm,
    pytest.mark.skipif(
        os.getenv("RUN_AI_QUALITY_LIVE") != "1" or not os.getenv("DEEPSEEK_API_KEY"),
        reason="explicit paid acceptance and process credential required",
    ),
]


@pytest.mark.parametrize(
    "case_id,context,instruction",
    [
        (
            "water-allocation",
            "原创石井村。今天只有三桶净水，病房已锁定两桶，剩一桶只够苗圃或染坊其中一处。"
            "今天不能取到新水，污染水不能处理成净水，病房的两桶不可挪用。",
            "给出村长今天的一项可执行选择、被牺牲者如何应对、明天须处理的后果。"
            "不要解决为雨水、备用库存、重复用水或两处都拿到净水；三百字以内。",
        ),
        (
            "delayed-news",
            "原创雾岭。山外议会今晨秘密否决援军，只有议员知道。守桥人阿禾昨天已离城，"
            "唯一信使今晚才能到，山内无其他通信。阿禾只知道援军申请还在等待。",
            "给出今天中午阿禾的一段值守安排与两句对话；保留等待中的不确定。"
            "他不能得知、猜中并确信或向他人透露议会今晨的结论。三百字以内。",
        ),
        (
            "two-signatures",
            "原创铜仓城。开粮仓必须保管员与轮值审计员两人同时在场签字，城主也不能豁免。"
            "今天保管员在仓前，轮值审计员要到傍晚才能赶回；无代理制度，无其他粮仓。",
            "提出午后到傍晚的一项救济安排，说明延迟代价与责任记录。"
            "不增加替代签字者、临时特权、破门放粮或新粮源。三百字以内。",
        ),
    ],
)
async def test_fresh_world_chat(
    async_client, db_session, measured_provider, case_id, context, instruction
):
    await SettingsService().connect_account_llm_provider(
        db_session, "deepseek", os.environ["DEEPSEEK_API_KEY"]
    )
    novel_id = await _create_project(async_client, f"新领域质量样本 {case_id}")
    scope = {
        "novel_id": novel_id,
        "action": "world.generation.chat",
        "task": instruction,
        "scope": "generation_center",
        "budget_tokens": 0,
    }
    preview = await async_client.post("/api/evidence/compilation/compile", json=scope)
    assert preview.status_code == 200, preview.text
    confirmed = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            **scope,
            "expected_context_fingerprint": preview.json()["context_fingerprint"],
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    response = await async_client.post(
        "/api/world/generation-center/chat",
        json={
            "novel_id": novel_id,
            "source_context": {"kind": "project"},
            "target": {"kind": "core_entity", "template": "none"},
            "messages": [{"role": "user", "content": instruction}],
            "pasted_context": context,
            "context_confirmation_id": confirmed.json()["id"],
            "quality_mode": "fast",
        },
    )
    output = response.json()
    root = Path(os.environ["AI_QUALITY_ARTIFACTS"])
    (root / f"{case_id}.json").write_text(
        json.dumps(
            {
                "context": context,
                "instruction": instruction,
                "status_code": response.status_code,
                "output": output,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    assert response.status_code == 200, output
    assert output["knowledge_review"]["status"] == "passed", output
    assert output["reply"].strip()
    assert len(output["reply"].strip()) <= 300, (
        "Visible reply exceeded the requested length"
    )


async def test_private_resource_workaround_is_blocked(
    async_client, db_session, measured_provider
):
    from modules.project.facade import open_project_llm_client
    from modules.world.services.worldbuilding.knowledge_governance import (
        govern_world_output,
    )

    await SettingsService().connect_account_llm_provider(
        db_session, "deepseek", os.environ["DEEPSEEK_API_KEY"]
    )
    novel_id = await _create_project(async_client, "私人资源不能绕过总量")
    async with open_project_llm_client(db_session, novel_id) as client:
        result = await govern_world_output(
            client,
            capability="world.generation.chat",
            novel_id=novel_id,
            source_refs=[],
            rendered_context="今天全村只有三桶净水，病房已锁定两桶。余下一桶只够苗圃或染坊其中一处；今天不能得到新水。",
            task_instruction="设计村长的取舍与被牺牲者的应对。",
            author_requirements="不能添加备用库存、新水源或让两处都拿到净水。",
            output="候选场景：村长把第三桶净水给染坊。苗圃的老周没争，他把自家的那瓢净饮水分给两畦苗，其余任它蔫。",
        )
    (
        Path(os.environ["AI_QUALITY_ARTIFACTS"]) / "private-resource-control.json"
    ).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    assert result["status"] == "blocked", result
    assert result["text"] == ""
    assert any(
        issue["severity"] in {"major", "blocker"} for issue in result["review"]["issues"]
    )

"""E09 真实模型验收：演化采样器一次真实调用（opt-in，消耗真实额度）。

默认跳过：需 ``RUN_REAL_LLM_TESTS=1`` 且 ``DEEPSEEK_API_KEY`` 在环境。
只断言结构与计量，不预设模型内容；凭据经账户连接种入（不经环境变量
直连 provider），与仓库 LLM 边界一致。
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evolution.llm_sampler import ProjectLLMSampler, SceneSample

real_llm_required = pytest.mark.skipif(
    os.getenv("RUN_REAL_LLM_TESTS") != "1" or not os.getenv("DEEPSEEK_API_KEY"),
    reason="真实模型验收默认跳过；RUN_REAL_LLM_TESTS=1 且配置 DEEPSEEK_API_KEY 才运行",
)

SCENE_TEXT = (
    "林舟与青竹在白石城东市重逢。青竹从袖中取出一枚铜钥匙，低声说："
    "“这东西我只能替你保管，不能据为己有。”林舟点头，没有伸手去接。"
)

PREVIOUS_ATTEMPT = "e09real0000000000000000000000000000000000000000"


def _manifest() -> dict[str, Any]:
    return {
        "scene_index": 1,
        "previous_scene_attempt_id": PREVIOUS_ATTEMPT,
        "previous_committed_prefix": {
            "through_scene_index": 0,
            "through_source_revision": 1,
        },
    }


@pytest.mark.real_llm
@real_llm_required
async def test_project_llm_sampler_real_call(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    from modules.account.settings_service import SettingsService
    from modules.project.facade import open_project_llm_client

    await SettingsService().connect_account_llm_provider(
        db_session,
        "deepseek",
        os.environ["DEEPSEEK_API_KEY"],
    )

    async with open_project_llm_client(db_session, test_project_id) as client:
        sampler = ProjectLLMSampler(client)
        payload = await sampler.sample(
            scene_text=SCENE_TEXT,
            input_manifest=_manifest(),
        )

    parsed = SceneSample.model_validate(
        {k: v for k, v in payload.items() if k != "paid_call_receipt"}
    )
    # 结构断言（不预设内容）：schema 化输出至少承载一条观察或显式未解析。
    assert parsed.observations or parsed.scene_events or parsed.unresolved_parts
    for observation in parsed.observations:
        assert observation.modality in {
            "event_observed",
            "character_statement",
            "belief",
            "hypothesis",
            "author_plan",
            "figurative",
            "unclear",
        }
        assert observation.quote
        for mention in observation.mentions:
            assert mention.surface
    # 计量：回执进入冻结负载。
    assert payload["paid_call_receipt"]["schema"] == "evolution.scene_sample.v1"

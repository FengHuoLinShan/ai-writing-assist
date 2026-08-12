from __future__ import annotations

import os

import pytest

from infrastructure.llm.image_client import OpenAIImageClient
from modules.world.map_atlas_storage import validate_png


@pytest.mark.asyncio
@pytest.mark.real_llm
@pytest.mark.skipif(
    os.getenv("RUN_MAP_ATLAS_LIVE_IMAGE") != "1"
    or not os.getenv("MAP_ATLAS_LIVE_OPENAI_API_KEY"),
    reason=(
        "付费 GPT Image 2 验收需 RUN_MAP_ATLAS_LIVE_IMAGE=1 "
        "且显式提供 MAP_ATLAS_LIVE_OPENAI_API_KEY"
    ),
)
async def test_paid_gpt_image_2_smoke() -> None:
    client = OpenAIImageClient(api_key=os.environ["MAP_ATLAS_LIVE_OPENAI_API_KEY"])
    try:
        result = await client.generate(
            prompt="A simple fictional island map, no text, letters, numbers or symbols.",
            size="1024x1024",
            quality="medium",
        )
    finally:
        await client.close()

    validate_png(result.data)

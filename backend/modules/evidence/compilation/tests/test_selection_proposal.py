from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from modules.evidence.compilation.contracts import CompileOptions
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextItem,
    ContextSection,
    Tier,
)
from modules.evidence.compilation.services.review_projection import (
    context_review_metadata,
)
from modules.evidence.compilation.services.selection_proposal import (
    ContextSelectionProposalService,
)


def test_excluded_item_remains_available_for_reinclude_proposal() -> None:
    selection_ref = {
        "kind": "target",
        "target_ref": {
            "target_type": "world_entity",
            "target_id": "entity-1",
            "target_path": "",
        },
    }
    compiled = CompiledContext(
        sections=[],
        excluded_items=[
            ContextItem(
                key="excluded-1",
                content="旧塔",
                title="旧塔",
                selection_ref=selection_ref,
                selection_state="excluded",
            )
        ],
    )

    assert ContextSelectionProposalService._current_candidates(compiled) == [
        {
            "selection_ref": selection_ref,
            "label": "旧塔",
            "snippet": "旧塔",
            "included": False,
        }
    ]


@pytest.mark.asyncio
async def test_model_selection_is_bounded_to_server_candidates(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_ref = {
        "draft_id": "00000000-0000-0000-0000-000000000001",
        "chapter_index": 1,
        "version_number": 1,
        "content_mode": "canonical",
        "start_offset": 0,
        "end_offset": 10,
        "source_hash": "a" * 64,
        "range_hash": "b" * 64,
    }
    section = ContextSection(
        key="retrieval_evidence_packs",
        tier=Tier.P2,
        content="北港在雨夜关闭城门。",
        token_count=10,
        title="正文证据",
        sources=[
            {
                "type": "writing_draft",
                "id": source_ref["draft_id"],
                "label": "第 1 章",
                "status": "canonical",
                "source_ref": source_ref,
            }
        ],
        truncatable_per_item=True,
    ).materialize_items()
    compiled = CompiledContext(
        sections=[section],
        total_tokens=10,
        budget_tokens=4000,
    )

    class FakeCompiler:
        async def compile_with_tiers(self, *_args, **_kwargs):
            return compiled

    class FakeClient:
        model_name = "test-model"

        async def generate_structured(self, _request, schema, **_kwargs):
            return schema(
                summary="移除当前正文证据",
                operations=[
                    {
                        "operation": "exclude",
                        "candidate_key": "candidate-001",
                        "reason": "作者明确要求本次不使用",
                    },
                    {
                        "operation": "include",
                        "candidate_key": "candidate-999",
                        "reason": "未知引用",
                    },
                ],
                unresolved=[],
            )

    @asynccontextmanager
    async def fake_open_client(*_args, **_kwargs):
        yield FakeClient()

    async def fake_search(*_args, **_kwargs):
        return {"hits": [], "warnings": []}

    monkeypatch.setattr(
        "modules.project.facade.open_project_llm_client",
        fake_open_client,
    )
    monkeypatch.setattr(ContextSelectionProposalService, "_search", fake_search)
    options = CompileOptions(
        novel_id="00000000-0000-0000-0000-000000000099",
        task="生成正文",
        scope="chapter",
        chapter_index=1,
        consumer_action="writing.generate",
    )
    fingerprint = context_review_metadata(compiled, options)["context_fingerprint"]

    result = await ContextSelectionProposalService(FakeCompiler()).propose(
        db_session,
        options=options,
        instruction="不要使用北港城门的正文",
        current_context_fingerprint=fingerprint,
    )

    assert result["operations"] == [
        {
            "operation": "exclude",
            "selection_ref": {
                "kind": "source_range",
                "source_ref": source_ref,
            },
            "label": "第 1 章",
            "reason": "作者明确要求本次不使用",
        }
    ]
    assert "未知资料引用" in "\n".join(result["warnings"])

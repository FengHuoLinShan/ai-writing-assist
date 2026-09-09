from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from pydantic import ValidationError as SchemaError

from core.errors import ConflictError, ValidationError
from modules.evidence.compilation.focused_contracts import (
    FocusedEvidenceLimits,
    FocusedEvidenceRequest,
    FocusedEvidenceResult,
    FocusedEvidenceRoot,
)
from modules.evidence.compilation.focused_tasks import FocusedSearchSubmit
from modules.evidence.compilation.services.focused_evidence import (
    FocusedEvidenceService,
    NeighborNominations,
)
from modules.writing.contracts import SourceRangeRefContract
from modules.writing.facade import (
    build_manuscript_range_ref,
    create_published_draft_only,
    read_manuscript_range,
)


class EvidenceReads:
    def __init__(self, objects=None):
        self.objects = objects or {}

    async def resolve_visibility_cursor(self, db, **kwargs):
        return kwargs["visibility"], []

    async def inspect(self, db, **kwargs):
        item = self.objects.get(kwargs["target_ref"]["target_id"])
        return {"visible": item is not None, "item": item}

    async def search(self, db, **kwargs):
        return {"hits": []}

    async def read(self, db, **kwargs):
        visibility, ref = kwargs["visibility"], kwargs["source_ref"]
        if visibility.cutoff_chapter is not None and (
            ref.chapter_index > visibility.cutoff_chapter
            or (
                ref.chapter_index == visibility.cutoff_chapter
                and visibility.cutoff_offset is not None
                and ref.end_offset > visibility.cutoff_offset
            )
        ):
            raise ValidationError("invisible manuscript range")
        result = await read_manuscript_range(
            db, kwargs["novel_id"], ref, before=0, after=0
        )
        return {
            "text": result.text,
            "highlight_start": result.highlight_start,
            "highlight_end": result.highlight_end,
        }


async def empty_terms(db, **kwargs):
    return {"entities": [], "truncated": False}


async def empty_neighbors(db, **kwargs):
    return {"entities": [], "relations": [], "truncated": False, "next_skip": None}


def request_for(novel_id, *, depth=1, chapters=1, **kwargs):
    return FocusedEvidenceRequest(
        novel_id=novel_id,
        roots=[FocusedEvidenceRoot(key="root-city", name="根城")],
        max_depth=depth,
        sources=["manuscript"],
        limits=FocusedEvidenceLimits(
            chapters_per_batch=chapters, semantic_top_k=0, evidence_per_batch=10
        ),
        **kwargs,
    )


def install_nomination(monkeypatch, calls, *, fail_once=False, invalid=False):
    async def generate(client, request, schema, **kwargs):
        assert kwargs["read_only"] is True
        if client.model_name.startswith("deepseek"):
            assert request.extra == {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "low",
            }
        assert request.max_tokens == 32_768
        assert kwargs["timeout"] == 600
        assert "输出 JSON Schema：" in request.messages[0].content
        payload = json.loads(request.messages[1].content)
        calls.append(payload)
        if fail_once and len(calls) == 1:
            raise TimeoutError("test interrupted")
        records = []
        for evidence in payload["evidence"]:
            if "根城隶属北郡" in evidence["text"]:
                records.append(
                    {
                        "root_key": "root-city",
                        "evidence_key": evidence["key"],
                        "name": "北郡",
                        "relation": "隶属",
                        "quote": "根城隶属北郡",
                    }
                )
            if invalid:
                records.append(
                    {
                        "root_key": "root-city",
                        "evidence_key": evidence["key"],
                        "name": "河港",
                        "relation": "邻接",
                        "quote": "北郡邻接河港",
                    }
                )
        return NeighborNominations(neighbors=records)

    monkeypatch.setattr(
        "modules.evidence.compilation.services.focused_evidence.run_managed_structured",
        generate,
    )


@pytest.mark.asyncio
async def test_unregistered_name_one_hop_reads_all_chapters_without_second_hop(
    db_session, test_project_id, monkeypatch
):
    await create_published_draft_only(
        db_session, test_project_id, 1, content="根城隶属北郡。"
    )
    await create_published_draft_only(
        db_session, test_project_id, 2, content="北郡邻接河港。"
    )
    await create_published_draft_only(
        db_session, test_project_id, 3, content="河港位于海边。"
    )
    service = FocusedEvidenceService(
        evidence_service=EvidenceReads(),
        terms_loader=empty_terms,
        neighbors_loader=empty_neighbors,
    )
    calls = []
    install_nomination(monkeypatch, calls)
    request = request_for(test_project_id)
    results = []
    for _ in range(15):
        result = await service.retrieve(
            db_session, request, llm_client=SimpleNamespace(model_name="fake")
        )
        assert result.asset_write_authorized is False
        await service.revalidate(db_session, request, result)
        results.append(result)
        serialized = result.model_dump(
            mode="json", exclude={"evidence": {"__all__": {"text"}}}
        )
        restored = FocusedEvidenceResult.model_validate(serialized)
        if result.continuation is None:
            break
        assert all(not item.text for item in restored.continuation.pending_nomination)
        request.continuation = restored.continuation
    assert result.coverage.complete
    assert {target.name for target in result.targets} == {"根城", "北郡"}
    assert result.coverage.scanned_chapters == 6
    assert len(calls) == 1
    assert {
        item.source_ref.chapter_index for page in results for item in page.evidence
    } == {1, 2}
    neighbor = next(target for target in result.targets if target.depth == 1)
    proof = neighbor.direct_evidence_refs[0]
    assert proof["quote"] == "根城隶属北郡"
    quote = await read_manuscript_range(
        db_session,
        test_project_id,
        SourceRangeRefContract(**proof["source_ref"]),
        before=0,
        after=0,
    )
    assert quote.text[quote.highlight_start : quote.highlight_end] == proof["quote"]


@pytest.mark.asyncio
async def test_nomination_failure_resumes_refs_without_losing_root_page(
    db_session, test_project_id, monkeypatch
):
    await create_published_draft_only(
        db_session, test_project_id, 1, content="根城隶属北郡。"
    )
    service = FocusedEvidenceService(
        evidence_service=EvidenceReads(),
        terms_loader=empty_terms,
        neighbors_loader=empty_neighbors,
    )
    calls = []
    install_nomination(monkeypatch, calls, fail_once=True)
    request = request_for(test_project_id)
    failed = await service.retrieve(
        db_session, request, llm_client=SimpleNamespace(model_name="deepseek-v4-flash")
    )
    assert failed.evidence and failed.coverage.nomination_failed
    assert failed.continuation and failed.continuation.pending_nomination
    request.continuation = failed.continuation
    recovered = await service.retrieve(
        db_session, request, llm_client=SimpleNamespace(model_name="deepseek-v4-flash")
    )
    assert not recovered.coverage.nomination_failed
    assert {t.name for t in recovered.targets} == {"根城", "北郡"}
    beta = next(target for target in recovered.targets if target.depth == 1)
    assert all(item.target_keys == [beta.key] for item in recovered.evidence)
    assert recovered.coverage.complete


@pytest.mark.asyncio
async def test_nominations_require_both_names_in_unique_direct_quote(
    db_session, test_project_id, monkeypatch
):
    await create_published_draft_only(
        db_session, test_project_id, 1, content="根城隶属北郡。北郡邻接河港。"
    )
    service = FocusedEvidenceService(
        evidence_service=EvidenceReads(),
        terms_loader=empty_terms,
        neighbors_loader=empty_neighbors,
    )
    calls = []
    install_nomination(monkeypatch, calls, invalid=True)
    result = await service.retrieve(
        db_session,
        request_for(test_project_id),
        llm_client=SimpleNamespace(model_name="fake"),
    )
    assert {t.name for t in result.targets} == {"根城", "北郡"}


@pytest.mark.asyncio
async def test_allowlist_range_is_exact_and_conflicting_pin_fails(
    db_session, test_project_id
):
    draft = await create_published_draft_only(
        db_session, test_project_id, 1, content="秘密前史。根城在北方。根城未来沉没。"
    )
    ref = await build_manuscript_range_ref(
        db_session,
        test_project_id,
        draft_id=draft.id,
        start_offset=5,
        end_offset=11,
        content_mode="canonical",
    )
    selection = {"kind": "source_range", "source_ref": asdict(ref)}
    request = request_for(test_project_id, depth=0, allowed_refs=[selection])
    service = FocusedEvidenceService(
        evidence_service=EvidenceReads(), terms_loader=empty_terms
    )
    result = await service.retrieve(db_session, request)
    assert len(result.evidence) == 1 and result.evidence[0].text == "根城在北方。"
    assert "秘密" not in result.evidence[0].text and "未来" not in result.evidence[0].text
    request.compile_options.pinned_refs = [selection]
    request.compile_options.excluded_refs = [selection]
    with pytest.raises(ValidationError, match="excluded"):
        await service.retrieve(db_session, request)


@pytest.mark.asyncio
async def test_continuation_rejects_scope_change_but_not_owned_metadata_changes(
    db_session, test_project_id
):
    for chapter in (1, 2):
        await create_published_draft_only(
            db_session, test_project_id, chapter, content="根城原文"
        )
    service = FocusedEvidenceService(
        evidence_service=EvidenceReads(), terms_loader=empty_terms
    )
    request = request_for(test_project_id, depth=0)
    result = await service.retrieve(db_session, request)
    assert result.continuation
    request.continuation = result.continuation
    request.question = "changed scope"
    with pytest.raises(ConflictError, match="scope"):
        await service.retrieve(db_session, request)


@pytest.mark.asyncio
async def test_same_name_identity_is_ambiguous_and_inactive_alias_is_not_expanded(
    db_session, test_project_id
):
    import uuid

    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    async def terms(db, **kwargs):
        return {
            "entities": [
                {"id": a, "name": "根城", "terms": ["根城", "甲别名"]},
                {"id": b, "name": "根城", "terms": ["根城", "乙别名"]},
            ],
            "truncated": False,
        }

    objects = {
        key: {"name": "根城", "public_info": "公开", "status": "canonical"}
        for key in (a, b)
    }
    service = FocusedEvidenceService(
        evidence_service=EvidenceReads(objects), terms_loader=terms
    )
    result = await service.retrieve(db_session, request_for(test_project_id, depth=0))
    root = result.targets[0]
    assert root.resolution == "ambiguous" and root.target_ref is None
    assert root.terms == ["根城"] and len(root.identity_candidates) == 2


def test_http_never_accepts_authority_or_internal_continuation():
    payload = {"novel_id": "x", "roots": [{"name": "根城"}], "question": "资料"}
    for field, value in (
        ("owner_id", "other"),
        ("consumer_action", "imports.auto_adopt"),
        ("continuation", {}),
        ("allowed_refs", []),
        ("source_manifest", {}),
    ):
        with pytest.raises(SchemaError):
            FocusedSearchSubmit.model_validate({**payload, field: value})
    with pytest.raises(SchemaError):
        FocusedSearchSubmit.model_validate({**payload, "max_depth": 2})


@pytest.mark.asyncio
async def test_context_budget_does_not_change_scan_coverage_and_pins_block(
    db_session, test_project_id
):
    draft = await create_published_draft_only(
        db_session, test_project_id, 1, content="根城" + "长篇资料" * 100
    )
    service = FocusedEvidenceService(
        evidence_service=EvidenceReads(), terms_loader=empty_terms
    )
    request = request_for(test_project_id, depth=0)
    request.compile_options.budget_tokens = 1
    result = await service.retrieve(db_session, request)
    assert result.coverage.complete and len(result.evidence) == 1
    assert result.compiled_context["omitted_items"]
    assert result.compiled_context["total_tokens"] <= 1
    assert "compiled_context" not in result.model_dump()
    ref = await build_manuscript_range_ref(
        db_session,
        test_project_id,
        draft_id=draft.id,
        start_offset=0,
        end_offset=len("根城" + "长篇资料" * 100),
        content_mode="canonical",
    )
    request.compile_options.pinned_refs = [
        {"kind": "source_range", "source_ref": asdict(ref)}
    ]
    pinned = await service.retrieve(db_session, request)
    assert pinned.compiled_context["blockers"]
    assert (
        pinned.compiled_context["sections"][0]["items"][0]["selection_state"]
        == "author_pinned"
    )


@pytest.mark.asyncio
async def test_database_neighbors_page_only_roots_and_never_expand_neighbors(
    db_session, test_project_id, monkeypatch
):
    import uuid

    identifiers = [str(uuid.uuid4()) for _ in range(3)]
    objects = {
        key: {"name": name, "public_info": name, "status": "canonical"}
        for key, name in zip(identifiers, ["根城", "北郡", "河港"], strict=True)
    }

    async def terms(db, **kwargs):
        ids = kwargs.get("entity_ids") or [identifiers[0]]
        return {
            "entities": [
                {"id": key, "name": objects[key]["name"], "terms": [objects[key]["name"]]}
                for key in ids
            ],
            "truncated": False,
        }

    pages = []

    async def neighbors(db, **kwargs):
        assert kwargs["entity_ids"] == [identifiers[0]]
        pages.append(kwargs["skip"])
        offset = kwargs["skip"]
        return {
            "entities": [],
            "relations": [
                {
                    "id": identifiers[offset + 1],
                    "source_id": identifiers[0],
                    "target_id": identifiers[offset + 1],
                    "source_hash": "a" * 64,
                }
            ],
            "next_skip": 1 if offset == 0 else None,
            "truncated": offset == 0,
        }

    service = FocusedEvidenceService(
        evidence_service=EvidenceReads(objects),
        terms_loader=terms,
        neighbors_loader=neighbors,
    )
    calls = []
    install_nomination(monkeypatch, calls)
    request = request_for(test_project_id)
    request.sources = ["world"]
    for _ in range(6):
        result = await service.retrieve(
            db_session, request, llm_client=SimpleNamespace(model_name="fake")
        )
        if result.continuation is None:
            break
        request.continuation = result.continuation
    assert set(pages) == {0, 1}
    assert result.coverage.complete
    assert len(result.targets) == 3 and [target.depth for target in result.targets] == [
        0,
        1,
        1,
    ]


@pytest.mark.asyncio
async def test_focused_http_pending_and_cross_novel_receipt_are_safe(async_client):
    project = await async_client.post("/api/projects", json={"title": "专项查阅"})
    novel_id = project.json()["id"]
    other = await async_client.post("/api/projects", json={"title": "另一个项目"})
    submitted = await async_client.post(
        "/api/evidence/compilation/focused-search",
        json={
            "novel_id": novel_id,
            "roots": [{"name": "未入库目标"}],
            "question": "查阅",
            "max_depth": 0,
        },
    )
    assert submitted.status_code == 202, submitted.text
    task_id = submitted.json()["task_id"]
    pending = await async_client.get(
        f"/api/evidence/compilation/focused-search/{task_id}",
        params={"novel_id": novel_id},
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == "pending" and pending.json()["result"] is None
    assert (
        "continuation" not in pending.text
        and "llm_execution_snapshot" not in pending.text
    )
    denied = await async_client.get(
        f"/api/evidence/compilation/focused-search/{task_id}",
        params={"novel_id": other.json()["id"]},
    )
    assert denied.status_code == 404

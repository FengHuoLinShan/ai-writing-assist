"""Shared, read-only focused retrieval contracts. Continuations never store prose."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.evidence.compilation.contracts import CompileOptions
from modules.writing.contracts import SourceRangeRefContract
from shared.target_ref import normalize_target_ref


def normalize_focused_target_ref(value: dict) -> dict:
    result = normalize_target_ref(value).canonical_dict()
    if result["target_type"] in {
        "entity",
        "core_entity",
        "world_entity",
        "location",
        "character",
    }:
        result["target_type"] = "entity"
    elif result["target_type"] == "page":
        result["target_type"] = "world_bible_page"
    elif result["target_type"] == "scene":
        result["target_type"] = "outline_scene"
    if result["target_type"] in {
        "entity",
        "world_bible_page",
        "outline_scene",
        "character_knowledge",
    }:
        result["target_id"] = str(uuid.UUID(result["target_id"]))
    return result


class FocusedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FocusedEvidenceRoot(FocusedModel):
    key: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    target_ref: dict | None = None

    @model_validator(mode="after")
    def identity(self):
        if bool(self.name and self.name.strip()) == bool(self.target_ref):
            raise ValueError("a root requires exactly one name or target_ref")
        if self.name:
            self.name = self.name.strip()
        if self.target_ref:
            raw = self.target_ref
            if "target_type" not in raw and "type" in raw:
                raw = {"target_type": raw["type"], "target_id": raw.get("id")}
            self.target_ref = normalize_focused_target_ref(raw)
        return self


class FocusedEvidenceLimits(FocusedModel):
    chapters_per_batch: int = Field(default=10, ge=1, le=100)
    evidence_per_batch: int = Field(default=80, ge=1, le=500)
    characters_per_batch: int = Field(default=40_000, ge=2000, le=200_000)
    neighbors_per_batch: int = Field(default=20, ge=1, le=100)
    semantic_top_k: int = Field(default=8, ge=0, le=50)
    nomination_characters: int = Field(default=24_000, ge=2000, le=60_000)


class FocusedEvidenceTarget(FocusedModel):
    key: str
    name: str
    target_ref: dict | None = None
    depth: Literal[0, 1] = 0
    root_keys: list[str] = Field(default_factory=list)
    resolution: Literal["resolved", "unresolved", "ambiguous"] = "unresolved"
    identity_candidates: list[dict] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    source_hash: str = ""
    proof_terms: list[str] = Field(default_factory=list)
    direct_evidence_refs: list[dict] = Field(default_factory=list)


class FocusedEvidenceItem(FocusedModel):
    key: str
    text: str = ""
    title: str = ""
    source_ref: SourceRangeRefContract | None = None
    target_ref: dict | None = None
    selection_ref: dict | None = None
    target_keys: list[str] = Field(default_factory=list)
    match_basis: Literal["literal", "metadata", "semantic", "pinned"] = "literal"
    source_hash: str = ""
    match_count: int = 0
    status: str = "canonical"


class FocusedEvidenceCoverage(FocusedModel):
    complete: bool = False
    scanned_chapters: int = 0
    total_chapters: int = 0
    matched_occurrences: int = 0
    returned_evidence: int = 0
    read_characters: int = 0
    stop_reason: str | None = None
    phase: Literal["roots", "graph", "neighbors", "done"] = "roots"
    semantic_exhaustive: Literal[False] = False
    structured_exhaustive: Literal[False] = False
    nomination_failed: bool = False
    character_ranges_verified: int = 0
    character_ranges_omitted: int = 0
    knowledge_boundary_audit: Literal["not_performed"] = "not_performed"


class FocusedEvidenceContinuation(FocusedModel):
    """Internal checkpoint. HTTP accepts only a server-owned task receipt."""

    version: Literal[1] = 1
    request_fingerprint: str
    source_manifest: dict[str, str]
    source_fingerprint: str
    identity_snapshots: dict[str, dict] = Field(default_factory=dict)
    graph_fingerprint: str | None = None
    world_fingerprint: str = ""
    targets: list[FocusedEvidenceTarget]
    phase: Literal["roots", "graph", "neighbors", "done"] = "roots"
    chapter_position: int = Field(default=0, ge=0)
    start_offset: int = Field(default=0, ge=0)
    graph_skip: int = Field(default=0, ge=0)
    semantic_done: bool = False
    outline_done: bool = False
    outline_position: int = Field(default=0, ge=0)
    outline_hit_position: int = Field(default=0, ge=0)
    allowed_position: int = Field(default=0, ge=0)
    metadata_position: int = Field(default=0, ge=0)
    scan_target_keys: list[str] | None = None
    completed_target_keys: list[str] = Field(default_factory=list)
    pinned_position: int = Field(default=0, ge=0)
    pending_nomination: list[FocusedEvidenceItem] = Field(default_factory=list)
    coverage: FocusedEvidenceCoverage = Field(default_factory=FocusedEvidenceCoverage)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def no_prose(self):
        if any(item.text for item in self.pending_nomination):
            raise ValueError("focused continuation must not persist manuscript text")
        return self


class FocusedEvidenceRequest(FocusedModel):
    novel_id: str
    roots: list[FocusedEvidenceRoot] = Field(min_length=1, max_length=1000)
    question: str = Field(
        default="补全指定对象及其直接关联资料", min_length=1, max_length=2000
    )
    compile_options: CompileOptions | None = None
    chapter_from: int | None = Field(default=None, ge=1)
    chapter_to: int | None = Field(default=None, ge=1)
    max_depth: Literal[0, 1] = 1
    continuation_target_policy: Literal["strict", "identity"] = "strict"
    limits: FocusedEvidenceLimits = Field(default_factory=FocusedEvidenceLimits)
    continuation: FocusedEvidenceContinuation | None = None
    allowed_refs: list[dict] | None = None
    sources: list[Literal["manuscript", "world", "outline"]] = Field(
        default_factory=lambda: ["manuscript", "world", "outline"], min_length=1
    )

    @model_validator(mode="after")
    def scope(self):
        if self.chapter_from and self.chapter_to and self.chapter_from > self.chapter_to:
            raise ValueError("chapter range is reversed")
        if self.compile_options is None:
            self.compile_options = CompileOptions(
                novel_id=self.novel_id,
                task=self.question,
                scope="full",
                consumer_action="evidence.focused_search",
                reveal_mode="author_safe",
            )
        if str(self.compile_options.novel_id) != self.novel_id:
            raise ValueError("focused search scope must belong to the same novel")
        if self.continuation_target_policy == "identity" and (
            self.compile_options.consumer_action != "imports.targeted_completion"
        ):
            raise ValueError(
                "identity-only continuation is restricted to import completion"
            )
        if not 1 <= self.compile_options.budget_tokens <= 200_000:
            raise ValueError("focused Context budget must be between 1 and 200000")
        keys = [root.key or f"root:{i}" for i, root in enumerate(self.roots)]
        if len(set(keys)) != len(keys):
            raise ValueError("root keys must be unique")
        return self


class FocusedEvidenceResult(FocusedModel):
    targets: list[FocusedEvidenceTarget] = Field(default_factory=list)
    evidence: list[FocusedEvidenceItem] = Field(default_factory=list)
    source_manifest: dict[str, str] = Field(default_factory=dict)
    source_fingerprint: str = ""
    world_fingerprint: str = ""
    request_fingerprint: str = ""
    coverage: FocusedEvidenceCoverage = Field(default_factory=FocusedEvidenceCoverage)
    warnings: list[str] = Field(default_factory=list)
    selection_refs: list[dict] = Field(default_factory=list)
    continuation: FocusedEvidenceContinuation | None = None
    asset_write_authorized: Literal[False] = False
    blockers: list[str] = Field(default_factory=list)
    # Derived at read time; never duplicate prose in task/import checkpoints.
    compiled_context: dict = Field(default_factory=dict, exclude=True)

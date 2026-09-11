"""Scene candidate schemas shared by enrichment and fusion phases."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from modules.imports.llm_schemas import SceneChunk

FusionOperation = Literal["kept", "merged", "split", "reordered", "rewritten"]
DiscardReason = Literal[
    "merged",
    "split",
    "duplicate_candidate",
    "low_confidence_unusable",
    "outside_scope",
]
FinalScenePhase = Literal[
    "phase1b_fusion",
    "phase1b_enrichment",
    "phase1a_fallback",
    "phase1c_fusion",
]


class FinalSceneCandidate(BaseModel):
    """One enriched Scene candidate, still not written to formal Scene rows."""

    candidate_id: str = ""
    phase: FinalScenePhase = "phase1b_fusion"
    title: str = ""
    goal: str = ""
    core_conflict: str = ""
    core_conflict_status: Literal["present", "not_applicable", "uncertain"] = (
        "uncertain"
    )
    phase1a_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    boundary_basis: str = ""
    emotional_beat: str | None = None
    must_happen: str | None = None
    must_not_happen: str | None = None
    narrative_tag: str = "draft"
    narrative_function: str = ""
    phase1b_basis: str = ""
    phase1b_field_evidence: dict[str, list[str]] = Field(default_factory=dict)
    phase1b_field_statuses: dict[
        str,
        Literal["present", "not_applicable", "uncertain"],
    ] = Field(default_factory=dict)
    phase1b_uncertain_fields: list[str] = Field(default_factory=list)
    phase1b_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    phase1b_context_fingerprint: str = ""
    phase1b_source_fingerprint: str = ""
    scene_chunks: list[SceneChunk] = Field(default_factory=list)
    source_candidate_ids: list[str] = Field(..., min_length=1)
    source_rounds: list[str] = Field(default_factory=list)
    source_chapter_indices: list[int] = Field(default_factory=list)
    operation: FusionOperation = "kept"
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    fallback_required: bool = False
    discard_reasons: dict[str, DiscardReason] = Field(default_factory=dict)
    boundary_status: str = "uncertain"
    boundary_reason: str = ""
    needs_review: bool = True
    review_reason: str = ""

    @field_validator(
        "title",
        "goal",
        "core_conflict",
        "boundary_basis",
        "narrative_tag",
        "narrative_function",
        "phase1b_basis",
        "phase1b_context_fingerprint",
        "phase1b_source_fingerprint",
        "boundary_status",
        "boundary_reason",
        "review_reason",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    @field_validator(
        "emotional_beat",
        "must_happen",
        "must_not_happen",
        mode="before",
    )
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator(
        "source_candidate_ids",
        "source_rounds",
        "phase1b_uncertain_fields",
        mode="before",
    )
    @classmethod
    def _normalize_string_list(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value if item is not None and item != ""]
        return [str(value)]

    @field_validator("source_chapter_indices", mode="before")
    @classmethod
    def _normalize_chapter_indices(cls, value: Any) -> list[int]:
        if value is None or value == "":
            return []
        values = value if isinstance(value, list) else [value]
        chapters: list[int] = []
        for item in values:
            try:
                chapter = int(item)
            except (TypeError, ValueError):
                continue
            if chapter >= 1:
                chapters.append(chapter)
        return _unique_sorted(chapters)

    @field_validator("operation", mode="before")
    @classmethod
    def _normalize_operation(cls, value: Any) -> FusionOperation:
        text = str(value or "kept").strip().lower()
        aliases: dict[str, FusionOperation] = {
            "keep": "kept",
            "kept": "kept",
            "merge": "merged",
            "merged": "merged",
            "融合": "merged",
            "合并": "merged",
            "split": "split",
            "拆分": "split",
            "reorder": "reordered",
            "reordered": "reordered",
            "排序": "reordered",
            "rewrite": "rewritten",
            "rewritten": "rewritten",
            "重写": "rewritten",
        }
        return aliases.get(text, "kept")

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> float:
        return _coerce_score(value, default=0.6)

    @field_validator("fallback_required", "needs_review", mode="before")
    @classmethod
    def _normalize_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None or value == "":
            return False
        if isinstance(value, int | float):
            return bool(value)
        text = str(value).strip().lower()
        return text in {"true", "yes", "y", "1", "是", "需要", "需复核"}

    @field_validator("discard_reasons", mode="before")
    @classmethod
    def _normalize_discard_reasons(cls, value: Any) -> dict[str, DiscardReason]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, DiscardReason] = {}
        for key, reason in value.items():
            mapped = _normalize_discard_reason(reason)
            if mapped is not None:
                normalized[str(key)] = mapped
        return normalized

    @field_validator("phase1b_field_statuses", mode="before")
    @classmethod
    def _normalize_phase1b_field_statuses(
        cls,
        value: Any,
    ) -> dict[str, Literal["present", "not_applicable", "uncertain"]]:
        if not isinstance(value, dict):
            return {}
        allowed = {"present", "not_applicable", "uncertain"}
        return {
            str(key): str(status)  # type: ignore[dict-item]
            for key, status in value.items()
            if str(status) in allowed
        }

    @field_validator("phase1b_field_evidence", mode="before")
    @classmethod
    def _normalize_phase1b_field_evidence(
        cls,
        value: Any,
    ) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            return {}
        allowed = {"emotional_beat", "must_happen", "must_not_happen"}
        return {
            str(key): list(
                dict.fromkeys(
                    str(item).strip() for item in quotes if str(item).strip()
                )
            )
            for key, quotes in value.items()
            if str(key) in allowed and isinstance(quotes, list)
        }

    @model_validator(mode="after")
    def _fill_scene_chunks_and_candidate_id(self) -> FinalSceneCandidate:
        self.source_chapter_indices = _unique_sorted(self.source_chapter_indices)
        if not self.source_chapter_indices:
            self.source_chapter_indices = _unique_sorted(
                chunk.chapter_index for chunk in self.scene_chunks
            )
        if not self.source_chapter_indices:
            self.source_chapter_indices = [1]
        if not self.source_rounds:
            self.source_rounds = ["A"]
        if not self.scene_chunks:
            self.scene_chunks = [SceneChunk(chapter_index=self.source_chapter_indices[0])]
        if not self.boundary_reason:
            self.boundary_reason = "Phase 1b reducer normalized this Scene."
        if self.needs_review and not self.review_reason:
            self.review_reason = "Phase 1b reducer output should be reviewed."
        uncertain = set(self.phase1b_uncertain_fields)
        field_values = {
            "emotional_beat": self.emotional_beat,
            "must_happen": self.must_happen,
            "must_not_happen": self.must_not_happen,
            "narrative_tag": self.narrative_tag,
            "narrative_function": self.narrative_function,
        }
        for field, value in field_values.items():
            if field in self.phase1b_field_statuses:
                continue
            self.phase1b_field_statuses[field] = (
                "uncertain"
                if field in uncertain
                else "not_applicable"
                if value in (None, "")
                or (field == "narrative_tag" and value == "draft")
                else "present"
            )
        if not self.candidate_id:
            source_key = "-".join(self.source_candidate_ids)
            chapter_key = "-".join(str(index) for index in self.source_chapter_indices)
            self.candidate_id = f"phase1b-{self.operation}-{source_key}-{chapter_key}"
        return self


class Phase1bReducerOutput(BaseModel):
    """Legacy reducer response shape retained for stored payload compatibility."""

    scenes: list[FinalSceneCandidate] = Field(default_factory=list)
    discarded_candidates: dict[str, DiscardReason] = Field(default_factory=dict)

    @field_validator("discarded_candidates", mode="before")
    @classmethod
    def _normalize_discarded_candidates(cls, value: Any) -> dict[str, DiscardReason]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            normalized: dict[str, DiscardReason] = {}
            for key, reason in value.items():
                mapped = _normalize_discard_reason(reason)
                if mapped is not None:
                    normalized[str(key)] = mapped
            return normalized
        if isinstance(value, list):
            normalized = {}
            for item in value:
                if isinstance(item, dict):
                    candidate_id = (
                        item.get("candidate_id")
                        or item.get("source_candidate_id")
                        or item.get("id")
                    )
                    reason = (
                        item.get("reason")
                        or item.get("discard_reason")
                        or item.get("discarded_reason")
                    )
                    mapped = _normalize_discard_reason(reason)
                    if candidate_id and mapped is not None:
                        normalized[str(candidate_id)] = mapped
                elif item:
                    normalized[str(item)] = "duplicate_candidate"
            return normalized
        return {}


def _coerce_score(value: Any, *, default: float = 0.5) -> float:
    if value is None or value == "" or isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        score = float(value)
        return max(0.0, min(score / 100 if score > 1 else score, 1.0))
    if isinstance(value, str):
        text = value.strip().lower()
        label_scores = {
            "高": 0.9,
            "较高": 0.8,
            "很高": 0.95,
            "中": 0.6,
            "中等": 0.6,
            "一般": 0.5,
            "低": 0.3,
            "较低": 0.25,
            "high": 0.9,
            "medium": 0.6,
            "mid": 0.6,
            "low": 0.3,
        }
        if text in label_scores:
            return label_scores[text]
        if text.endswith("%"):
            text = text[:-1].strip()
            try:
                return max(0.0, min(float(text) / 100, 1.0))
            except ValueError:
                return default
        try:
            score = float(text)
        except ValueError:
            return default
        return max(0.0, min(score / 100 if score > 1 else score, 1.0))
    return default


def _normalize_discard_reason(value: Any) -> DiscardReason | None:
    text = str(value or "").strip().lower()
    aliases: dict[str, DiscardReason] = {
        "merged": "merged",
        "merge": "merged",
        "融合": "merged",
        "合并": "merged",
        "split": "split",
        "拆分": "split",
        "duplicate": "duplicate_candidate",
        "duplicate_candidate": "duplicate_candidate",
        "重复": "duplicate_candidate",
        "low_confidence": "low_confidence_unusable",
        "low_confidence_unusable": "low_confidence_unusable",
        "低置信": "low_confidence_unusable",
        "outside_scope": "outside_scope",
        "越界": "outside_scope",
    }
    return aliases.get(text)


def _unique_sorted(values: Sequence[int] | Any) -> list[int]:
    return sorted({value for value in values if isinstance(value, int)})

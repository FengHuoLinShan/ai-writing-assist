"""POV character writing generation helpers."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from modules.context.contracts import ConfirmedAIActionContext

POV_PROMPT_NAME = "writing_pov_character"
POV_FIELDS = (
    "perception",
    "interpretation",
    "inner_monologue",
    "true_intention",
    "action",
    "expression",
    "dialogue_candidates",
    "subtext",
    "unsaid",
    "draft_prose",
)


class GenerationProfile(StrEnum):
    DEFAULT = "default"
    POV_CHARACTER = "pov_character"


@dataclass(frozen=True)
class GenerationProfileInfo:
    profile: GenerationProfile
    scene_id: str | None = None
    viewpoint_character_id: str | None = None


class GenerationProfileResolver:
    """Resolve the writing generation profile from a confirmed context."""

    def resolve(
        self,
        confirmed_context: ConfirmedAIActionContext,
    ) -> GenerationProfileInfo:
        confirmation = confirmed_context.confirmation
        options = dict(confirmed_context.compile_options or {})
        scene_id = options.get("scene_id")
        viewpoint_character_id = options.get("viewpoint_character_id")
        if (
            confirmation.action == "writing.generate"
            and confirmation.result_status == "confirmed"
            and not confirmation.stale_reasons
            and options.get("reveal_mode") == "character"
            and scene_id
            and viewpoint_character_id
        ):
            return GenerationProfileInfo(
                profile=GenerationProfile.POV_CHARACTER,
                scene_id=str(scene_id),
                viewpoint_character_id=str(viewpoint_character_id),
            )
        return GenerationProfileInfo(profile=GenerationProfile.DEFAULT)


@dataclass
class PovParseResult:
    content: str
    pov_view: dict[str, Any] | None
    warnings: list[str] = field(default_factory=list)


class PovGenerationParser:
    """Parse structured POV generation JSON with a single repair attempt."""

    def parse(self, raw_text: str) -> PovParseResult:
        raw = (raw_text or "").strip()
        if not raw:
            raise ValueError("LLM returned empty POV generation")
        try:
            parsed = json.loads(raw)
            return self._coerce(parsed, warnings=[])
        except json.JSONDecodeError:
            repaired = self._repair(raw)
            if repaired != raw:
                try:
                    parsed = json.loads(repaired)
                    return self._coerce(parsed, warnings=["json_repaired"])
                except json.JSONDecodeError:
                    pass
        return PovParseResult(
            content=raw,
            pov_view=None,
            warnings=["pov_parse_failed"],
        )

    def _coerce(
        self,
        parsed: Any,
        *,
        warnings: list[str],
    ) -> PovParseResult:
        if not isinstance(parsed, dict):
            raise ValueError("POV generation JSON must be an object")
        view = {field: parsed.get(field) for field in POV_FIELDS if field in parsed}
        draft_prose = str(view.get("draft_prose") or "").strip()
        if not draft_prose:
            draft_prose = _first_non_empty_text(view)
            warnings = [*warnings, "missing_draft_prose"]
        if not draft_prose:
            raise ValueError("POV generation did not contain usable text")
        return PovParseResult(content=draft_prose, pov_view=view, warnings=warnings)

    @staticmethod
    def _repair(raw: str) -> str:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.I).strip()
            text = re.sub(r"```$", "", text).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        text = re.sub(r",\s*([}\]])", r"\1", text)
        return text


class CharacterRevealGuard:
    """Deterministic text-level POV leakage diagnostics."""

    def validate(
        self,
        *,
        pov_view: dict[str, Any] | None,
        draft_prose: str,
        guard_terms: list[Any],
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        fields = _flatten_text_fields(pov_view or {}, prefix="pov_view")
        fields.append(("draft_prose", draft_prose or ""))

        for field_path, value in fields:
            normalized_value = _normalize_for_match(value)
            if not normalized_value:
                continue
            for term in guard_terms:
                normalized_phrase = _normalize_for_match(term.phrase)
                if normalized_phrase and normalized_phrase in normalized_value:
                    findings.append(
                        {
                            "rule": term.rule,
                            "severity": term.severity,
                            "field_path": field_path,
                            "generated_excerpt": _generated_excerpt(
                                value,
                                term.phrase,
                            ),
                            "source_type": term.source_type,
                            "source_id": term.source_id,
                            "source_label": term.source_label,
                            "redacted": True,
                        }
                    )

        status = "passed"
        if any(item["severity"] == "error" for item in findings):
            status = "failed"
        elif findings:
            status = "warning"
        return {
            "status": status,
            "findings": findings,
            "warnings": list(warnings or []),
        }


def build_pov_generation_prompt(
    *,
    chapter_index: int,
    instruction: str | None,
    context_markdown: str,
) -> str:
    note = instruction.strip() if instruction else "无额外要求"
    schema = {
        "perception": "角色此刻可感知到的事实",
        "interpretation": "角色基于有限认知形成的理解或误解",
        "inner_monologue": "角色内心活动",
        "true_intention": "角色此刻真实意图",
        "action": "动作行为",
        "expression": "神态表情",
        "dialogue_candidates": [
            {"line": "可能台词", "tone": "语气", "subtext": "潜台词"}
        ],
        "subtext": "整体潜台词",
        "unsaid": "角色已经知道但选择不说出口的内容",
        "draft_prose": "可直接作为正文候选的小说段落",
    }
    return (
        f"请基于以下已确认的 AI 参考资料，生成第 {chapter_index} 章当前 Scene 的"
        "单角色 POV 正文候选。\n\n"
        f"本次额外要求：{note}\n\n"
        "必须只输出一个 JSON object，不要 Markdown 围栏。\n"
        "unsaid 不是作者隐藏真相；只能写 POV 角色已经知道但没有说出口的内容。\n"
        "draft_prose 必须只使用结构化字段中已符合角色有限认知的信息。\n\n"
        f"JSON schema 示例：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        f"## AI 参考资料\n\n{context_markdown}"
    )


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _flatten_text_fields(value: Any, *, prefix: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    if isinstance(value, str):
        result.append((prefix, value))
    elif isinstance(value, dict):
        for key, nested in value.items():
            result.extend(_flatten_text_fields(nested, prefix=f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            result.extend(_flatten_text_fields(nested, prefix=f"{prefix}[{index}]"))
    return result


def _normalize_for_match(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").lower()
    return re.sub(r"[\s\W_]+", "", normalized, flags=re.UNICODE)


def _generated_excerpt(value: str, phrase: str) -> str:
    raw = value or ""
    index = raw.find(phrase)
    if index < 0:
        return raw[:120]
    start = max(0, index - 20)
    end = min(len(raw), index + len(phrase) + 20)
    return raw[start:end]


def _first_non_empty_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for nested in value.values():
            found = _first_non_empty_text(nested)
            if found:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _first_non_empty_text(nested)
            if found:
                return found
    return ""

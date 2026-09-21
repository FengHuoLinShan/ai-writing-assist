"""在途兼容分类（V4 E07.d，计划 §7.2）。

旧 deep_import 在途任务的处置是确定性分类，不是猜测：

- 冻结契约字段齐全且版本已知 → ``continue_compatible``：按 adapter 继续，
  不伪装“原任务原地换引擎”；
- 其余 → ``incompatible``：保留已耗费用与成果，提示从可验证批次继续；
  兼容结论只对“能否安全续接”负责，不对语义质量背书（E09）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

KNOWN_LEGACY_CONTRACT_VERSIONS = frozenset({"deep_import.v1", "deep_import.v2"})
_REQUIRED_FIELDS = ("workflow_id", "phase", "source_chapter_index", "sources")


class LegacyCompatibility(BaseModel):
    """一条在途旧任务/checkpoint 的兼容判定。"""

    model_config = ConfigDict(extra="forbid")

    verdict: str = Field(description="continue_compatible / incompatible")
    contract_version: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    preserve_costs: bool = True
    resume_hint: str = ""


def classify_legacy_checkpoint(checkpoint: dict[str, Any] | None) -> LegacyCompatibility:
    payload = checkpoint or {}
    version = str(payload.get("contract_version") or "")
    missing = [
        field for field in _REQUIRED_FIELDS if payload.get(field) in (None, [], {})
    ]
    if version in KNOWN_LEGACY_CONTRACT_VERSIONS and not missing:
        return LegacyCompatibility(
            verdict="continue_compatible",
            contract_version=version,
            resume_hint="按冻结契约 adapter 续接：从 checkpoint 声明的批次边界继续，"
            "不重放已完成阶段、不重复计费",
        )
    return LegacyCompatibility(
        verdict="incompatible",
        contract_version=version or None,
        missing_fields=missing,
        preserve_costs=True,
        resume_hint="契约版本未知或字段缺失：保留已耗费用与成果，"
        "从最近一个可验证批次继续（不无条件跳过 checkpoint）",
    )

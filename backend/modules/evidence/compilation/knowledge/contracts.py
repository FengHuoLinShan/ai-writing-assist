"""
知识治理版本化契约

全产品知识治理（全知导演、最小知情生成、独立复核）的稳定数据契约。
契约只携带来源身份、指纹与判定结果，不携带隐藏事实正文、Prompt 或秘密。
其他模块只能导入本包的 contracts/facade 出口，实现细节留在包内部。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

KNOWLEDGE_POLICY_VERSION = 1
"""知识治理契约版本；随确认冻结，旧记录按当时版本回放。"""


class KnowledgeContractError(ValueError):
    """知识治理契约构造或校验失败。"""


class KnowledgeContractVersionError(KnowledgeContractError):
    """记录携带了未知的更高契约版本，不能按当前版本解释。"""


def knowledge_canonical_hash(payload: Any) -> str:
    """对规范化 JSON 载荷取 sha256，作为回执指纹的基础。"""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise KnowledgeContractError(f"{name} must be a mapping")
    return value


def _require_version(payload: dict[str, Any]) -> int:
    version = payload.get("policy_version")
    if not isinstance(version, int):
        raise KnowledgeContractError("policy_version is required")
    if version > KNOWLEDGE_POLICY_VERSION:
        raise KnowledgeContractVersionError(
            f"knowledge contract version {version} is newer than supported "
            f"{KNOWLEDGE_POLICY_VERSION}"
        )
    return version


@dataclass(frozen=True)
class KnowledgeSourceEntry:
    """冻结来源清单中的一条来源记录；只含身份与指纹，不含正文。"""

    source_key: str
    """服务端签发的稳定短 key，如 world_entity:<id>；导演/审查只引用 key"""
    source_type: str
    """来源类型：world_entity / character / scene / draft / thread / page 等"""
    source_id: str
    content_hash: str
    label: str = ""
    dimensions: tuple[str, ...] = ()
    """该来源覆盖的知识维度"""
    depends_on: tuple[str, ...] = ()
    """声明依赖闭包中的其他 source_key"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "content_hash": self.content_hash,
            "label": self.label,
            "dimensions": list(self.dimensions),
            "depends_on": list(self.depends_on),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> KnowledgeSourceEntry:
        data = _require_mapping(payload, "source entry")
        try:
            return cls(
                source_key=str(data["source_key"]),
                source_type=str(data["source_type"]),
                source_id=str(data["source_id"]),
                content_hash=str(data["content_hash"]),
                label=str(data.get("label") or ""),
                dimensions=tuple(str(item) for item in data.get("dimensions") or ()),
                depends_on=tuple(str(item) for item in data.get("depends_on") or ()),
            )
        except KeyError as exc:  # pragma: no cover - defensive
            raise KnowledgeContractError(f"source entry missing field: {exc}") from exc


@dataclass(frozen=True)
class KnowledgeSubject:
    """任务的知识主体与揭示截止点。"""

    subject_type: str
    """主体类型：author / reader / character / scene 等"""
    character_id: str | None = None
    cutoff_chapter: int | None = None
    cutoff_scene_id: str | None = None
    cutoff_offset: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_type": self.subject_type,
            "character_id": self.character_id,
            "cutoff_chapter": self.cutoff_chapter,
            "cutoff_scene_id": self.cutoff_scene_id,
            "cutoff_offset": self.cutoff_offset,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> KnowledgeSubject:
        data = _require_mapping(payload, "knowledge subject")
        return cls(
            subject_type=str(data["subject_type"]),
            character_id=data.get("character_id"),
            cutoff_chapter=data.get("cutoff_chapter"),
            cutoff_scene_id=data.get("cutoff_scene_id"),
            cutoff_offset=data.get("cutoff_offset"),
        )


@dataclass(frozen=True)
class KnowledgeDimensionCoverage:
    """单个必查维度的覆盖情况；omitted 的维度不能签署 PASS。"""

    dimension: str
    covered_by: tuple[str, ...] = ()
    omitted: bool = False
    omission_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "covered_by": list(self.covered_by),
            "omitted": self.omitted,
            "omission_reason": self.omission_reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> KnowledgeDimensionCoverage:
        data = _require_mapping(payload, "dimension coverage")
        return cls(
            dimension=str(data["dimension"]),
            covered_by=tuple(str(item) for item in data.get("covered_by") or ()),
            omitted=bool(data.get("omitted") or False),
            omission_reason=data.get("omission_reason"),
        )


@dataclass(frozen=True)
class KnowledgeScopeReceipt:
    """冻结任务范围回执：任务范围内完整、可回读的来源清单与判定。

    「完整」指冻结任务范围内每个来源都出现在 included/excluded/omitted 之一；
    excluded 为作者显式排除（不得回流），omitted 为预算或不可读缺失（不能签 PASS）。
    """

    policy_version: int
    capability: str
    novel_id: str
    subject: KnowledgeSubject
    included: tuple[KnowledgeSourceEntry, ...] = ()
    excluded: tuple[KnowledgeSourceEntry, ...] = ()
    omitted: tuple[KnowledgeSourceEntry, ...] = ()
    coverage: tuple[KnowledgeDimensionCoverage, ...] = ()
    authority_fingerprint: str = ""
    generator_fingerprint: str = ""
    scope_complete: bool = False
    continuation: str | None = None
    created_at: str = ""

    def source_keys(self) -> tuple[str, ...]:
        return tuple(entry.source_key for entry in self.included)

    def entry(self, source_key: str) -> KnowledgeSourceEntry | None:
        for item in self.included:
            if item.source_key == source_key:
                return item
        return None

    def dimension_coverage(self, dimension: str) -> KnowledgeDimensionCoverage | None:
        for item in self.coverage:
            if item.dimension == dimension:
                return item
        return None

    def has_omissions(self) -> bool:
        return bool(self.omitted) or any(
            item.omitted for item in self.coverage
        )

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "capability": self.capability,
            "novel_id": self.novel_id,
            "subject": self.subject.to_dict(),
            "included": [entry.to_dict() for entry in self.included],
            "excluded": [entry.to_dict() for entry in self.excluded],
            "omitted": [entry.to_dict() for entry in self.omitted],
            "coverage": [item.to_dict() for item in self.coverage],
            "authority_fingerprint": self.authority_fingerprint,
            "generator_fingerprint": self.generator_fingerprint,
            "scope_complete": self.scope_complete,
            "continuation": self.continuation,
        }

    def receipt_fingerprint(self) -> str:
        """范围回执指纹；任何来源/判定/指纹字段漂移都会改变结果。"""
        return knowledge_canonical_hash(
            {"kind": "knowledge_scope_receipt", **self._fingerprint_payload()}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "knowledge_scope_receipt",
            **self._fingerprint_payload(),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> KnowledgeScopeReceipt:
        data = _require_mapping(payload, "scope receipt")
        version = _require_version(data)
        return cls(
            policy_version=version,
            capability=str(data["capability"]),
            novel_id=str(data["novel_id"]),
            subject=KnowledgeSubject.from_dict(data["subject"]),
            included=tuple(
    KnowledgeSourceEntry.from_dict(item) for item in data.get("included") or ()
            ),
            excluded=tuple(
                KnowledgeSourceEntry.from_dict(item)
                for item in data.get("excluded") or ()
            ),
            omitted=tuple(
                KnowledgeSourceEntry.from_dict(item)
                for item in data.get("omitted") or ()
            ),
            coverage=tuple(
                KnowledgeDimensionCoverage.from_dict(item)
                for item in data.get("coverage") or ()
            ),
            authority_fingerprint=str(data.get("authority_fingerprint") or ""),
            generator_fingerprint=str(data.get("generator_fingerprint") or ""),
            scope_complete=bool(data.get("scope_complete") or False),
            continuation=data.get("continuation"),
            created_at=str(data.get("created_at") or ""),
        )


DIRECTOR_DISPOSITION_REQUIRED = "required_for_generation"
DIRECTOR_DISPOSITION_ALLOWED = "allowed_for_generation"
DIRECTOR_DISPOSITION_AUDIT_ONLY = "director_audit_only"
DIRECTOR_DISPOSITION_FORBIDDEN = "forbidden"
DIRECTOR_DISPOSITIONS = frozenset(
    {
        DIRECTOR_DISPOSITION_REQUIRED,
        DIRECTOR_DISPOSITION_ALLOWED,
        DIRECTOR_DISPOSITION_AUDIT_ONLY,
        DIRECTOR_DISPOSITION_FORBIDDEN,
    }
)


@dataclass(frozen=True)
class KnowledgeDirectorDisposition:
    """导演对单个来源 key 的处置；reason 只能是短说明，不得回传隐藏事实正文。"""

    source_key: str
    disposition: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "disposition": self.disposition,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> KnowledgeDirectorDisposition:
        data = _require_mapping(payload, "director disposition")
        return cls(
            source_key=str(data["source_key"]),
            disposition=str(data["disposition"]),
            reason=str(data.get("reason") or ""),
        )


@dataclass(frozen=True)
class KnowledgeDirectorPlan:
    """导演规划：把冻结范围内每个来源 key 恰好处置一次。

    导演只能缩小服务端已判定的可见集合；owner、novel_id、角色权限、
    截止点与写入权限由服务端策略决定，不在导演可调整范围。
    """

    policy_version: int
    capability: str
    receipt_fingerprint: str
    dispositions: tuple[KnowledgeDirectorDisposition, ...] = ()
    notes: tuple[str, ...] = ()

    def disposition_for(self, source_key: str) -> KnowledgeDirectorDisposition | None:
        for item in self.dispositions:
            if item.source_key == source_key:
                return item
        return None

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "capability": self.capability,
            "receipt_fingerprint": self.receipt_fingerprint,
            "dispositions": [item.to_dict() for item in self.dispositions],
            "notes": list(self.notes),
        }

    def plan_fingerprint(self) -> str:
        return knowledge_canonical_hash(
            {"kind": "knowledge_director_plan", **self._fingerprint_payload()}
        )

    def validate_against_receipt(self, receipt: KnowledgeScopeReceipt) -> None:
        """要求每个来源 key 恰好被处置一次，且处置值合法。"""
        problems: list[str] = []
        seen: set[str] = set()
        for item in self.dispositions:
            if item.disposition not in DIRECTOR_DISPOSITIONS:
                problems.append(
                    f"unknown disposition {item.disposition!r} for {item.source_key}"
                )
            if item.source_key in seen:
                problems.append(f"duplicate disposition for {item.source_key}")
            seen.add(item.source_key)
        for key in receipt.source_keys():
            if key not in seen:
                problems.append(f"missing disposition for {key}")
        for key in sorted(seen - set(receipt.source_keys())):
            problems.append(f"unknown source key {key}")
        if problems:
            raise KnowledgeContractError(
                "director plan does not cover receipt exactly once: "
                + "; ".join(problems)
            )

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "knowledge_director_plan", **self._fingerprint_payload()}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> KnowledgeDirectorPlan:
        data = _require_mapping(payload, "director plan")
        version = _require_version(data)
        return cls(
            policy_version=version,
            capability=str(data["capability"]),
            receipt_fingerprint=str(data["receipt_fingerprint"]),
            dispositions=tuple(
                KnowledgeDirectorDisposition.from_dict(item)
                for item in data.get("dispositions") or ()
            ),
            notes=tuple(str(item) for item in data.get("notes") or ()),
        )


AUDIT_FINDING_MISSING_REQUIRED = "missing_required"
AUDIT_FINDING_UNSUPPORTED_FACT = "unsupported_fact"
AUDIT_FINDING_OUT_OF_SCOPE = "out_of_scope_knowledge"
AUDIT_FINDING_PREMATURE_REVEAL = "premature_reveal"
AUDIT_FINDING_IRRELEVANT = "irrelevant_content"
AUDIT_FINDING_CONFLICT = "conflict"
AUDIT_FINDING_UNCHECKED = "unchecked"
AUDIT_FINDING_KINDS = frozenset(
    {
        AUDIT_FINDING_MISSING_REQUIRED,
        AUDIT_FINDING_UNSUPPORTED_FACT,
        AUDIT_FINDING_OUT_OF_SCOPE,
        AUDIT_FINDING_PREMATURE_REVEAL,
        AUDIT_FINDING_IRRELEVANT,
        AUDIT_FINDING_CONFLICT,
        AUDIT_FINDING_UNCHECKED,
    }
)

AUDIT_SEVERITY_BLOCKER = "blocker"
AUDIT_SEVERITY_MAJOR = "major"
AUDIT_SEVERITY_MINOR = "minor"
AUDIT_SEVERITIES = frozenset(
    {AUDIT_SEVERITY_BLOCKER, AUDIT_SEVERITY_MAJOR, AUDIT_SEVERITY_MINOR}
)
BLOCKING_SEVERITIES = frozenset({AUDIT_SEVERITY_BLOCKER, AUDIT_SEVERITY_MAJOR})

AUDIT_VERDICT_PASS = "pass"
AUDIT_VERDICT_BLOCKED = "blocked"
AUDIT_VERDICT_NOT_CHECKED = "not_checked"
AUDIT_VERDICT_UNVERIFIABLE = "unverifiable"
AUDIT_VERDICTS = frozenset(
    {
        AUDIT_VERDICT_PASS,
        AUDIT_VERDICT_BLOCKED,
        AUDIT_VERDICT_NOT_CHECKED,
        AUDIT_VERDICT_UNVERIFIABLE,
    }
)


@dataclass(frozen=True)
class KnowledgeAuditFinding:
    """审查发现；message 必须按当前用户可见性脱敏，excerpt 只定位生成输出。"""

    kind: str
    severity: str
    message: str
    excerpt: str = ""
    source_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "excerpt": self.excerpt,
            "source_key": self.source_key,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> KnowledgeAuditFinding:
        data = _require_mapping(payload, "audit finding")
        return cls(
            kind=str(data["kind"]),
            severity=str(data["severity"]),
            message=str(data["message"]),
            excerpt=str(data.get("excerpt") or ""),
            source_key=data.get("source_key"),
        )


@dataclass(frozen=True)
class KnowledgeAuditReceipt:
    """独立复核回执：绑定输出 hash，记录逐类发现与检查覆盖。"""

    policy_version: int
    capability: str
    receipt_fingerprint: str
    plan_fingerprint: str
    output_hash: str
    verdict: str
    findings: tuple[KnowledgeAuditFinding, ...] = ()
    coverage: tuple[KnowledgeDimensionCoverage, ...] = ()
    checked_at: str = ""

    def blocking_findings(self) -> tuple[KnowledgeAuditFinding, ...]:
        return tuple(
            item for item in self.findings if item.severity in BLOCKING_SEVERITIES
        )

    def finding_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {kind: 0 for kind in sorted(AUDIT_FINDING_KINDS)}
        for item in self.findings:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        return counts

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "capability": self.capability,
            "receipt_fingerprint": self.receipt_fingerprint,
            "plan_fingerprint": self.plan_fingerprint,
            "output_hash": self.output_hash,
            "verdict": self.verdict,
            "findings": [item.to_dict() for item in self.findings],
            "coverage": [item.to_dict() for item in self.coverage],
        }

    def audit_fingerprint(self) -> str:
        return knowledge_canonical_hash(
            {"kind": "knowledge_audit_receipt", **self._fingerprint_payload()}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "knowledge_audit_receipt",
            **self._fingerprint_payload(),
            "checked_at": self.checked_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> KnowledgeAuditReceipt:
        data = _require_mapping(payload, "audit receipt")
        version = _require_version(data)
        return cls(
            policy_version=version,
            capability=str(data["capability"]),
            receipt_fingerprint=str(data["receipt_fingerprint"]),
            plan_fingerprint=str(data["plan_fingerprint"]),
            output_hash=str(data["output_hash"]),
            verdict=str(data["verdict"]),
            findings=tuple(
                KnowledgeAuditFinding.from_dict(item)
                for item in data.get("findings") or ()
            ),
            coverage=tuple(
                KnowledgeDimensionCoverage.from_dict(item)
                for item in data.get("coverage") or ()
            ),
            checked_at=str(data.get("checked_at") or ""),
        )


@dataclass(frozen=True)
class KnowledgeReviewProjection:
    """面向 API/前端的加性审查状态投影；不暴露隐藏事实或内部枚举正文。"""

    status: str
    """checking / passed / blocked / unverifiable / legacy_unchecked"""
    repaired: bool = False
    coverage: tuple[KnowledgeDimensionCoverage, ...] = ()
    issue_counts: dict[str, int] = field(default_factory=dict)
    issues: tuple[dict[str, str], ...] = ()
    """脱敏问题列表（kind/severity/message/open_target）"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "repaired": self.repaired,
            "coverage": [item.to_dict() for item in self.coverage],
            "issue_counts": dict(self.issue_counts),
            "issues": [dict(item) for item in self.issues],
        }


REVIEW_STATUS_CHECKING = "checking"
REVIEW_STATUS_PASSED = "passed"
REVIEW_STATUS_BLOCKED = "blocked"
REVIEW_STATUS_UNVERIFIABLE = "unverifiable"
REVIEW_STATUS_LEGACY_UNCHECKED = "legacy_unchecked"
REVIEW_STATUSES = frozenset(
    {
        REVIEW_STATUS_CHECKING,
        REVIEW_STATUS_PASSED,
        REVIEW_STATUS_BLOCKED,
        REVIEW_STATUS_UNVERIFIABLE,
        REVIEW_STATUS_LEGACY_UNCHECKED,
    }
)

STAGE_COLLECTING_CONTEXT = "collecting_context"
STAGE_DIRECTING = "directing"
STAGE_GENERATING = "generating"
STAGE_REVIEWING = "reviewing"
STAGE_REPAIRING = "repairing"
GOVERNANCE_STAGES = frozenset(
    {
        STAGE_COLLECTING_CONTEXT,
        STAGE_DIRECTING,
        STAGE_GENERATING,
        STAGE_REVIEWING,
        STAGE_REPAIRING,
    }
)

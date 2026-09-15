"""Zero-provider workload manifests for resumable import admission.

The manifest is deliberately a small JSON projection.  It records only the
work units and deterministic request formula needed before provider I/O; the
product safety gate (H) remains an explicit input rather than an invented
default.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

from infrastructure.llm.workflow_budget import AIRunEnvelopeError
from infrastructure.stable_hash import stable_hash
from modules.world.contracts import ENTITY_FUSION_CHECKPOINT_PAIR_BATCH_SIZE

ADMISSION_VERSION = "imports.run-admission.v1"
ENTITY_FUSION_DEEP_REQUESTS_PER_PAIR = 6
ENTITY_FUSION_DEEP_AUDIT_REQUESTS = 9
IMPORT_RUN_REQUEST_LIMIT = 256


def propagate_run_envelope_error(error: BaseException) -> None:
    """Never turn a shared admission decision into a domain fallback."""
    if isinstance(error, AIRunEnvelopeError):
        raise error


@dataclass(frozen=True)
class WorkloadManifest:
    """Secret-free, deterministic admission information."""

    task_type: str
    capability: str
    unit: str
    unit_count: int | None
    request_upper_bound: int | None
    batch_size: int | None
    batch_count: int | None
    status: str
    formula: str
    reason: str | None = None
    safety_limit: int = IMPORT_RUN_REQUEST_LIMIT

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "version": ADMISSION_VERSION,
            "task_type": self.task_type,
            "capability": self.capability,
            "unit": self.unit,
            "unit_count": self.unit_count,
            "request_upper_bound": self.request_upper_bound,
            "batch_size": self.batch_size,
            "batch_count": self.batch_count,
            "status": self.status,
            "formula": self.formula,
            "reason": self.reason,
            "safety_limit": self.safety_limit,
        }
        payload["fingerprint"] = stable_hash(payload, stringify_unknown=False)
        return payload


def build_scene_phase_manifest(*, window_count: int) -> dict[str, Any]:
    """Record the known Phase 0 scope without pretending Scene cardinality is known."""

    windows = max(0, int(window_count))
    return WorkloadManifest(
        task_type="deep_import",
        capability="imports.scene_slicing",
        unit="phase0_window",
        unit_count=windows,
        request_upper_bound=None,
        batch_size=1,
        batch_count=windows,
        status="segmented",
        formula="scene_slicing requires model-produced Scene count before A is finite",
        reason=(
            "scene_count_is_produced_by_phase1a; "
            "author continuation is required per segment"
        ),
    ).as_dict()


def build_entity_fusion_deep_manifest(
    *,
    pair_count: int,
    batch_size: int = ENTITY_FUSION_CHECKPOINT_PAIR_BATCH_SIZE,
) -> dict[str, Any]:
    """Calculate the deep-import fusion upper bound before its first LLM call.

    One pair uses structured initial + format repair over transport R=3, i.e.
    six provider requests.  The final knowledge audit is three structured
    attempts over the same transport retry policy, i.e. nine more requests.
    """

    pairs = max(0, int(pair_count))
    size = max(1, int(batch_size))
    request_upper_bound = (
        pairs * ENTITY_FUSION_DEEP_REQUESTS_PER_PAIR
        + ENTITY_FUSION_DEEP_AUDIT_REQUESTS
    )
    return WorkloadManifest(
        task_type="deep_import",
        capability="world.entity_fusion",
        unit="candidate_pair",
        unit_count=pairs,
        request_upper_bound=request_upper_bound,
        batch_size=size,
        batch_count=ceil(pairs / size) if pairs else 0,
        status="segmented",
        formula="6 * candidate_pairs + 9 knowledge_audit requests",
        reason="request_upper_bound above safety_limit requires author continuation",
    ).as_dict()

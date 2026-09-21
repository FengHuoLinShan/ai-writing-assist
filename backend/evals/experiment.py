"""Small, shared provenance helpers for offline comparison artifacts.

This module performs no provider or database I/O. Receipts are observations,
never inferred consumption, and do not make an offline report quality evidence.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evals.cache import EvalCache
from evals.schemas import DatasetCase, SystemUnderTestProfile


class RequestObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    status: Literal["succeeded", "failed", "unknown"]
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    duration_ms: float | None = Field(default=None, ge=0)
    error_kind: str | None = None


def summarize_requests(receipts: list[RequestObservation]) -> dict:
    if len({item.request_id for item in receipts}) != len(receipts):
        raise ValueError("request observations must be unique; retries need distinct IDs")
    unknown = sum(
        item.status == "unknown"
        or item.input_tokens is None
        or item.output_tokens is None
        for item in receipts
    )
    known_input = sum(item.input_tokens or 0 for item in receipts)
    known_output = sum(item.output_tokens or 0 for item in receipts)
    return {
        "actual_requests": len(receipts),
        "unknown_usage_requests": unknown,
        "usage_complete": not unknown,
        "known_input_tokens": known_input,
        "known_output_tokens": known_output,
        "total_input_tokens": None if unknown else known_input,
        "total_output_tokens": None if unknown else known_output,
        "failed_requests": sum(item.status == "failed" for item in receipts),
    }


def validate_story_splits(cases: list[DatasetCase]) -> None:
    """A story or immutable source must not occur in multiple splits."""
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("duplicate case_id")
    splits: dict[str, str] = {}
    for case in cases:
        identities = [f"story:{case.source_group_id}"]
        identities.extend(
            f"source:{ref.corpus_id}:{ref.source_alias}:{ref.content_hash}"
            for ref in [*case.source_refs, *case.hard_negative_refs]
        )
        for identity in identities:
            if splits.setdefault(identity, case.split.value) != case.split.value:
                raise ValueError(f"cross-split source/story leakage: {identity}")


def experiment_evidence(
    *,
    dataset: object,
    source_fingerprints: dict[str, str],
    implementation_files: list[Path],
    receipts: list[RequestObservation],
    effective_profile: SystemUnderTestProfile | None = None,
    reasoning_effort: str | None = None,
    observation_mode: Literal["offline", "recorded", "live"] = "offline",
) -> dict:
    root = Path(__file__).resolve().parents[2]
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    patch = subprocess.check_output(["git", "diff", "HEAD", "--binary"], cwd=root)
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "-z", "HEAD"], cwd=root
    ) + subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root
    )
    implementation_files = [
        *implementation_files,
        *[
            root / name
            for name in changed.decode().split("\0")
            if name.startswith(("backend/", "frontend-console/"))
            and Path(name).suffix
            in {".py", ".js", ".vue", ".json", ".jsonl", ".toml", ".lock"}
            and (root / name).is_file()
        ],
    ]
    files = {
        str(file.resolve().relative_to(root)): hashlib.sha256(
            file.read_bytes()
        ).hexdigest()
        for file in implementation_files
    }
    return {
        "schema_version": "technical-evidence-v1",
        "metric_version": "range-v2+legacy-ranking-v1",
        "code_revision": revision,
        "python_version": sys.version.split()[0],
        "tracked_patch_hash": hashlib.sha256(patch).hexdigest(),
        "implementation_hashes": files,
        "dataset_hash": EvalCache.key({"dataset": dataset}),
        "source_fingerprints": source_fingerprints,
        "effective_profile": (
            effective_profile.model_dump(mode="json") if effective_profile else None
        ),
        "reasoning_effort": reasoning_effort,
        "observation_mode": observation_mode,
        "usage": summarize_requests(receipts),
        "requests": [item.model_dump(mode="json") for item in receipts],
        "quality_claim_allowed": False,
    }

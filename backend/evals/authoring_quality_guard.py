"""Bounded authoring evaluation; real output readers gate director/progression judges."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from evals.schemas import EVAL_TEACHER_MODEL, EVAL_TEACHER_REASONING_EFFORT

AUTHORING_QUALITY_LIVE_ENV = "AUTHORING_QUALITY_EVAL_ALLOW_LIVE"
AUTHORING_QUALITY_VERSION = "authoring-quality-v1"
AUTHORING_QUALITY_MAX_REQUESTS = 12
AUTHORING_QUALITY_MAX_PROMPT_BYTES = 160_000
REPO_ROOT = Path(__file__).resolve().parents[2]

DOMAINS = frozenset(
    {"dossier", "forecast", "director", "notices", "world_progression", "goal"}
)
PHASES = frozenset({"seed", "teacher", "judge"})
SPLITS = frozenset({"calibration", "development", "holdout"})
STEPS = {
    (domain, phase): f"eval.authoring_quality.v1.{domain}.{phase}"
    for domain in DOMAINS
    for phase in PHASES
}

# These anchors check evidence-calibration behavior only. Passing them is not a
# product-quality score, a human agreement result, or permission to enable a feature.
SEED_CASES = (
    {
        "seed_id": "direct-support",
        "evidence": "The signed ledger says the east gate is closed.",
        "claim": "The east gate is closed.",
        "expected": "supported",
    },
    {
        "seed_id": "direct-contradiction",
        "evidence": "The signed ledger says the east gate is closed.",
        "claim": "The east gate is open.",
        "expected": "contradicted",
    },
    {
        "seed_id": "insufficient-evidence",
        "evidence": "The map shows two places but has no scale or route data.",
        "claim": "The journey takes three hours.",
        "expected": "unknown",
    },
    {
        "seed_id": "absent-evidence",
        "evidence": "The record contains no information about the key's color.",
        "claim": "The key is brass.",
        "expected": "not_evidenced",
    },
)


class AuthoringQualityError(RuntimeError):
    """A closed authoring-quality evaluation boundary."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SeedDecision(StrictModel):
    seed_id: Literal[
        "direct-support",
        "direct-contradiction",
        "insufficient-evidence",
        "absent-evidence",
    ]
    label: Literal["supported", "contradicted", "unknown", "not_evidenced"]
    reason: str = Field(min_length=1, max_length=1200)


class SeedCalibrationResult(StrictModel):
    decisions: list[SeedDecision] = Field(min_length=4, max_length=4)


class TeacherClaim(StrictModel):
    claim: str = Field(min_length=1, max_length=2000)
    status: Literal["supported", "contradicted", "unknown"]
    source_ids: list[str] = Field(max_length=20)
    rationale: str = Field(min_length=1, max_length=2000)


class TeacherReferenceResult(StrictModel):
    case_id: str = Field(min_length=1, max_length=160)
    reference_points: list[TeacherClaim] = Field(min_length=1, max_length=80)
    omissions: list[str] = Field(max_length=40)


class JudgeCriterionResult(StrictModel):
    criterion_id: str = Field(min_length=1, max_length=120)
    outcome: Literal["pass", "fail", "unknown"]
    evidence_ids: list[str] = Field(max_length=40)
    rationale: str = Field(min_length=1, max_length=2000)


class JudgeResult(StrictModel):
    case_id: str = Field(min_length=1, max_length=160)
    criteria: list[JudgeCriterionResult] = Field(min_length=1, max_length=80)
    missing_evidence: list[str] = Field(max_length=40)


class ProductReference(StrictModel):
    kind: Literal["director", "world_progression"]
    scene_id: str = Field(min_length=1, max_length=100)
    root_id: str = Field(min_length=1, max_length=100)
    branch_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=100)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_ids: list[str] = Field(min_length=1, max_length=40)


class SourceExcerpt(StrictModel):
    source_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    source_kind: Literal["author_source", "manuscript", "world_state", "evidence_excerpt"]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(min_length=1, max_length=40000)

    @model_validator(mode="after")
    def source_hash_matches_text(self) -> SourceExcerpt:
        actual = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if actual != self.source_sha256:
            raise ValueError("source excerpt hash mismatch")
        return self


class FrozenInput(StrictModel):
    schema_version: Literal[1]
    domain: str
    case_id: str
    task: str = Field(min_length=1, max_length=12000)
    sources: list[SourceExcerpt] = Field(max_length=40)
    constraints: list[str] = Field(max_length=40)

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        if value not in DOMAINS:
            raise ValueError("unsupported authoring-quality domain")
        return value


class CaseArtifact(StrictModel):
    schema_version: Literal[1]
    domain: str
    case_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._-]+$")
    source_group_id: str = Field(min_length=1, max_length=160)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    product_ref: ProductReference | None = None

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        if value not in DOMAINS:
            raise ValueError("unsupported authoring-quality domain")
        return value


class SplitArtifact(StrictModel):
    schema_version: Literal[1]
    domain: str
    case_id: str
    source_group_id: str
    split: Literal["calibration", "development", "holdout"]

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        if value not in DOMAINS:
            raise ValueError("unsupported authoring-quality domain")
        return value


class RubricCriterion(StrictModel):
    criterion_id: str = Field(
        min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9._-]+$"
    )
    description: str = Field(min_length=1, max_length=2000)
    scale: Literal["pass_fail_unknown"]


class RubricArtifact(StrictModel):
    schema_version: Literal[1]
    version: Literal[AUTHORING_QUALITY_VERSION]
    domain: str
    case_id: str = Field(min_length=1, max_length=160)
    human_validated: Literal[False]
    criteria: list[RubricCriterion] = Field(min_length=1, max_length=80)

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        if value not in DOMAINS:
            raise ValueError("unsupported authoring-quality domain")
        return value

    @model_validator(mode="after")
    def unique_criteria(self) -> RubricArtifact:
        ids = [item.criterion_id for item in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("rubric criterion IDs must be unique")
        return self


class CaseBinding(StrictModel):
    domain: str
    phase: Literal["seed", "teacher", "judge"]
    case_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._-]+$")
    split: Literal["calibration", "development", "holdout"]
    schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    product_evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        if value not in DOMAINS:
            raise ValueError("unsupported authoring-quality domain")
        return value


class AuthoringQualityManifest(StrictModel):
    schema_version: Literal[1]
    suite: Literal["authoring_quality"]
    version: Literal[AUTHORING_QUALITY_VERSION]
    owner_id: str = Field(min_length=1, max_length=100)
    project_id: str = Field(min_length=1, max_length=100)
    project_title: str = Field(min_length=1, max_length=200)
    project_snapshot: dict
    project_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pipeline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    private_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_budget: Literal[AUTHORING_QUALITY_MAX_REQUESTS]
    human_validated: Literal[False]
    cases: list[CaseBinding] = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_manifest(self) -> AuthoringQualityManifest:
        keys = [(row.domain, row.phase, row.case_id) for row in self.cases]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate authoring-quality case binding")
        if not self.project_title.startswith("AUTHORING-QUALITY:"):
            raise ValueError("authoring-quality runs require a dedicated Project")
        return self


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _product_source_paths(repo_root: Path) -> list[Path]:
    roots = (
        "backend/app",
        "backend/core",
        "backend/shared",
        "backend/modules/account",
        "backend/modules/assistant",
        "backend/modules/evolution",
        "backend/modules/evidence",
        "backend/modules/imports",
        "backend/modules/interaction",
        "backend/modules/project",
        "backend/modules/story",
        "backend/modules/world",
        "backend/modules/writing",
        "backend/infrastructure/llm",
        "backend/infrastructure/tasks",
        "backend/prompts",
        "frontend-console/vue",
        "frontend-console/api",
    )
    allowed = {".py", ".js", ".ts", ".tsx", ".vue", ".json", ".yaml", ".yml", ".jinja2"}
    excluded = {"tests", "__tests__", "node_modules", "dist", "build", "__pycache__"}
    paths: set[Path] = set()
    for relative in roots:
        root = repo_root / relative
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in allowed:
                continue
            if any(part in excluded for part in path.parts):
                continue
            paths.add(path)
    for relative in (
        "backend/evals/authoring_quality_guard.py",
        "backend/evals/authoring_quality_product.py",
        "backend/evals/codex_executor.py",
        "backend/evals/schemas.py",
        "frontend-console/api.js",
    ):
        path = repo_root / relative
        if path.is_file():
            paths.add(path)
    return sorted(paths)


def pipeline_fingerprint(repo_root: Path = REPO_ROOT) -> str:
    paths = _product_source_paths(repo_root)
    if not paths:
        raise AuthoringQualityError("authoring-quality product pipeline is unavailable")
    return digest(
        {
            str(path.relative_to(repo_root)): _sha256_bytes(path.read_bytes())
            for path in paths
        }
    )


def schema_fingerprint(response_model: type[BaseModel], schema: dict) -> str:
    product_schemas = []
    for path in _product_source_paths(REPO_ROOT):
        relative = path.relative_to(REPO_ROOT)
        parts = relative.parts
        if path.suffix == ".py" and (
            "schemas" in parts
            or "contracts" in parts
            or path.name.endswith("_schemas.py")
            or path.name == "schemas.py"
            or path.name == "contracts.py"
        ):
            product_schemas.append((str(relative), _sha256_bytes(path.read_bytes())))
    if not product_schemas:
        raise AuthoringQualityError("authoring-quality product schemas are unavailable")
    return digest(
        {
            "product_schemas": product_schemas,
            "response_model": response_model.__name__,
            "response_schema": schema,
        }
    )


def _assert_private_root(path: Path) -> Path:
    absolute = path.absolute()
    if any(parent.is_symlink() for parent in (absolute, *absolute.parents)):
        raise AuthoringQualityError("authoring-quality private root forbids symlinks")
    resolved = absolute.resolve(strict=True)
    repo_boundaries = [
        REPO_ROOT,
        *(parent for parent in REPO_ROOT.parents if (parent / ".git").is_dir()),
    ]
    if any(
        resolved == parent or resolved.is_relative_to(parent)
        for parent in repo_boundaries
    ):
        raise AuthoringQualityError("authoring-quality artifacts must stay outside repo")
    if not resolved.is_dir() or stat.S_IMODE(resolved.stat().st_mode) != 0o700:
        raise AuthoringQualityError("authoring-quality private root must be mode 0700")
    return resolved


def _read_private_file(root: Path, relative: str, *, max_bytes: int = 1_000_000) -> bytes:
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise AuthoringQualityError("private artifact path is invalid")
    path = root / relative
    current = path.parent
    while current != root.parent:
        if current.is_symlink():
            raise AuthoringQualityError("authoring-quality artifacts forbid symlinks")
        if current == root:
            break
        current = current.parent
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise AuthoringQualityError(
            "authoring-quality artifact is missing or unsafe"
        ) from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise AuthoringQualityError(
                "authoring-quality artifacts must be regular 0600 files"
            )
        if info.st_size > max_bytes:
            raise AuthoringQualityError("authoring-quality artifact exceeds size limit")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            payload = stream.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise AuthoringQualityError("authoring-quality artifact exceeds size limit")
        return payload
    finally:
        os.close(fd)


def _read_json(root: Path, relative: str, model: type[BaseModel]) -> BaseModel:
    try:
        return model.model_validate_json(_read_private_file(root, relative))
    except AuthoringQualityError:
        raise
    except (ValueError, UnicodeError) as error:
        raise AuthoringQualityError(
            "authoring-quality artifact schema is invalid"
        ) from error


def _case_relative(domain: str, phase: str, case_id: str, filename: str) -> str:
    if case_id in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", case_id):
        raise AuthoringQualityError("authoring-quality case ID is invalid")
    return f"cases/{domain}/{phase}/{case_id}/{filename}"


def _require_private_case_dirs(root: Path, domain: str, phase: str, case_id: str) -> None:
    directory = root / "cases" / domain / phase / case_id
    cursor = root
    for part in ("cases", domain, phase, case_id):
        cursor = cursor / part
        if cursor.is_symlink() or not cursor.is_dir():
            raise AuthoringQualityError(
                "authoring-quality case directory is missing or unsafe"
            )
        if stat.S_IMODE(cursor.stat().st_mode) != 0o700:
            raise AuthoringQualityError(
                "authoring-quality case directories must be mode 0700"
            )
    if not directory.resolve().is_relative_to(root):
        raise AuthoringQualityError(
            "authoring-quality case directory escaped private root"
        )


def _entry(
    manifest: AuthoringQualityManifest, domain: str, phase: str, case_id: str
) -> CaseBinding:
    matches = [
        row
        for row in manifest.cases
        if (row.domain, row.phase, row.case_id) == (domain, phase, case_id)
    ]
    if len(matches) != 1:
        raise AuthoringQualityError("authoring-quality scope is not in frozen manifest")
    row = matches[0]
    if phase == "seed" and (case_id != "seed-v1" or row.split != "calibration"):
        raise AuthoringQualityError("seed scope requires its fixed calibration case")
    if phase == "teacher" and (case_id == "seed-v1" or row.split != "development"):
        raise AuthoringQualityError("teacher scope only permits frozen development cases")
    if row.split == "holdout":
        raise AuthoringQualityError("authoring-quality holdout is unavailable")
    if phase == "judge":
        if (
            domain not in {"director", "world_progression"}
            or row.product_evidence_sha256 is None
        ):
            raise AuthoringQualityError(
                "judge is limited to director/progression with a frozen evidence hash"
            )
        if row.split != "development":
            raise AuthoringQualityError(
                "authoring-quality judge only permits development cases"
            )
    elif row.product_evidence_sha256 is not None:
        raise AuthoringQualityError("non-judge scope cannot bind product-evidence output")
    return row


def _load_case_artifacts(
    root: Path, manifest: AuthoringQualityManifest, entry: CaseBinding
) -> tuple[CaseArtifact, FrozenInput, RubricArtifact, SplitArtifact, dict[str, str]]:
    _require_private_case_dirs(root, entry.domain, entry.phase, entry.case_id)
    paths = {
        name: _case_relative(entry.domain, entry.phase, entry.case_id, f"{name}.json")
        for name in ("case", "input", "rubric", "split")
    }
    raw = {name: _read_private_file(root, path) for name, path in paths.items()}
    expected = {
        "case": entry.case_sha256,
        "input": entry.input_sha256,
        "rubric": entry.rubric_sha256,
        "split": entry.split_sha256,
    }
    if any(_sha256_bytes(raw[name]) != expected[name] for name in expected):
        raise AuthoringQualityError("authoring-quality case fingerprint drift")
    try:
        case = CaseArtifact.model_validate_json(raw["case"])
        case_input = FrozenInput.model_validate_json(raw["input"])
        rubric = RubricArtifact.model_validate_json(raw["rubric"])
        split = SplitArtifact.model_validate_json(raw["split"])
    except ValueError as error:
        raise AuthoringQualityError(
            "authoring-quality case artifacts are invalid"
        ) from error
    identity = (entry.domain, entry.case_id)
    if any(
        (row.domain, row.case_id) != identity for row in (case, case_input, rubric, split)
    ):
        raise AuthoringQualityError("authoring-quality case artifact identity drift")
    if (
        case.input_sha256 != entry.input_sha256
        or split.split != entry.split
        or case.source_group_id != split.source_group_id
    ):
        raise AuthoringQualityError("authoring-quality case/split binding drift")
    if entry.phase == "seed":
        if case.product_ref is not None or case_input.sources:
            raise AuthoringQualityError(
                "seed calibration must use only fixed in-code anchors"
            )
    elif entry.phase == "teacher":
        if case.product_ref is not None or not case_input.sources:
            raise AuthoringQualityError(
                "teacher input must be source-only and exclude SUT output"
            )
    elif entry.phase == "judge":
        if (
            case.product_ref is None
            or case_input.sources
            or case.product_ref.kind != entry.domain
        ):
            raise AuthoringQualityError(
                "judge case must use a product reference, not caller evidence"
            )
    return case, case_input, rubric, split, {key: value for key, value in paths.items()}


def _seed_prompt(domain: str, rubric: RubricArtifact, manifest_sha256: str) -> str:
    payload = {
        "suite": "authoring_quality",
        "version": AUTHORING_QUALITY_VERSION,
        "phase": "seed",
        "domain": domain,
        "manifest_sha256": manifest_sha256,
        "rubric": rubric.model_dump(mode="json"),
        "anchors": [
            {key: value for key, value in row.items() if key != "expected"}
            for row in SEED_CASES
        ],
        "instruction": (
            "仅按给定证据对每条claim分类为supported、contradicted、unknown或not_evidenced。"
            "缺少依据时不得猜测；逐项给出简短理由，只返回严格结构化结果。"
        ),
    }
    return canonical_json(payload).decode("utf-8")


def _teacher_prompt(
    entry: CaseBinding,
    case: CaseArtifact,
    case_input: FrozenInput,
    rubric: RubricArtifact,
    manifest_sha256: str,
) -> str:
    payload = {
        "suite": "authoring_quality",
        "version": AUTHORING_QUALITY_VERSION,
        "phase": "teacher",
        "domain": entry.domain,
        "case_id": entry.case_id,
        "split": entry.split,
        "manifest_sha256": manifest_sha256,
        "case": case.model_dump(mode="json"),
        "input": case_input.model_dump(mode="json"),
        "rubric": rubric.model_dump(mode="json"),
        "instruction": (
            "只基于冻结输入、来源片段和评分标准形成参考要点；逐项引用source_id。"
            "证据不足时标unknown并说明缺口。你看不到被测产品输出，不得推测其行为或声称验收通过。"
        ),
    }
    return canonical_json(payload).decode("utf-8")


def _judge_prompt(
    entry: CaseBinding,
    case: CaseArtifact,
    case_input: FrozenInput,
    rubric: RubricArtifact,
    product_evidence: dict,
    manifest_sha256: str,
    teacher_reference: dict,
) -> str:
    payload = {
        "suite": "authoring_quality",
        "version": AUTHORING_QUALITY_VERSION,
        "phase": "judge",
        "domain": entry.domain,
        "case_id": entry.case_id,
        "split": entry.split,
        "manifest_sha256": manifest_sha256,
        "case": case.model_dump(mode="json"),
        "task": case_input.task,
        "rubric": rubric.model_dump(mode="json"),
        "product_evidence": product_evidence,
        "teacher_reference": teacher_reference,
        "instruction": (
            "只按已绑定的真实产品运行、来源快照和确认回执评分。逐项引用evidence_ids；"
            "证据缺失、来源变化或不能证明的指标必须为unknown。不得接受证据包外的成功声明。"
        ),
    }
    return canonical_json(payload).decode("utf-8")


@contextmanager
def _journal_lock(root: Path):
    path = root / ".authoring-quality.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError as error:
        raise AuthoringQualityError("authoring-quality journal lock is unsafe") from error
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise AuthoringQualityError(
                "authoring-quality journal lock must be a regular file"
            )
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        locked = True
        yield
    finally:
        if locked:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _write_private_json(root: Path, filename: str, payload: dict) -> None:
    target = root / filename
    if target.is_symlink():
        raise AuthoringQualityError("authoring-quality journal forbids symlinks")
    temp = root / f".{filename}.{uuid.uuid4().hex}.tmp"
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        data = canonical_json(payload)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, target)
    directory_fd = os.open(root, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _read_journal(root: Path) -> dict:
    path = root / "request-journal.json"
    if not path.exists():
        return {
            "schema_version": 1,
            "request_budget": AUTHORING_QUALITY_MAX_REQUESTS,
            "requests": {},
        }
    raw = _read_private_file(root, "request-journal.json", max_bytes=500_000)
    try:
        journal = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise AuthoringQualityError(
            "authoring-quality request journal is invalid"
        ) from error
    if (
        not isinstance(journal, dict)
        or set(journal) != {"schema_version", "request_budget", "requests"}
        or journal.get("schema_version") != 1
        or journal.get("request_budget") != AUTHORING_QUALITY_MAX_REQUESTS
        or not isinstance(journal.get("requests"), dict)
    ):
        raise AuthoringQualityError("authoring-quality request journal schema drift")
    for key, record in journal["requests"].items():
        if (
            not re.fullmatch(r"[0-9a-f]{64}", key)
            or not isinstance(record, dict)
            or set(record)
            != {
                "domain",
                "phase",
                "case_id",
                "step_name",
                "status",
                "started_at",
                "response_sha256",
            }
            or record.get("domain") not in DOMAINS
            or record.get("phase") not in PHASES
            or record.get("status") not in {"started", "completed", "unknown"}
        ):
            raise AuthoringQualityError(
                "authoring-quality request journal entry is invalid"
            )
    if len(journal["requests"]) > AUTHORING_QUALITY_MAX_REQUESTS:
        raise AuthoringQualityError("authoring-quality request budget was exceeded")
    return journal


def _request_key(entry: CaseBinding, step_name: str, prompt: str, schema: dict) -> str:
    return digest(
        {
            "domain": entry.domain,
            "phase": entry.phase,
            "case_id": entry.case_id,
            "step_name": step_name,
            "prompt_sha256": _sha256_bytes(prompt.encode("utf-8")),
            "schema_sha256": digest(schema),
        }
    )


def _start_request(
    root: Path, entry: CaseBinding, step_name: str, prompt: str, schema: dict
) -> str:
    key = _request_key(entry, step_name, prompt, schema)
    with _journal_lock(root):
        journal = _read_journal(root)
        if key in journal["requests"]:
            raise AuthoringQualityError(
                "started/unknown/completed request cannot be replayed"
            )
        if len(journal["requests"]) >= AUTHORING_QUALITY_MAX_REQUESTS:
            raise AuthoringQualityError("authoring-quality request budget is exhausted")
        _write_private_json(
            root,
            f"request-{key}.json",
            {
                "step_name": step_name,
                "prompt": prompt,
                "response_schema": schema,
            },
        )
        journal["requests"][key] = {
            "domain": entry.domain,
            "phase": entry.phase,
            "case_id": entry.case_id,
            "step_name": step_name,
            "status": "started",
            "started_at": datetime.now(UTC).isoformat(),
            "response_sha256": None,
        }
        _write_private_json(root, "request-journal.json", journal)
    return key


def _finish_request(
    root: Path, key: str, response: str | None, *, completed: bool
) -> None:
    with _journal_lock(root):
        journal = _read_journal(root)
        record = journal["requests"].get(key)
        if record is None or record["status"] != "started":
            raise AuthoringQualityError("authoring-quality request is not pending")
        record["status"] = "completed" if completed else "unknown"
        record["response_sha256"] = (
            digest(json.loads(response)) if completed and response is not None else None
        )
        if completed and response is not None:
            _write_private_json(root, f"response-{key}.json", json.loads(response))
        elif response is not None:
            _write_private_json(
                root,
                f"unknown-response-{key}.json",
                {
                    "raw_response": response,
                    "sha256": _sha256_bytes(response.encode("utf-8")),
                },
            )
        _write_private_json(root, "request-journal.json", journal)


def _require_seed(root: Path, domain: str) -> None:
    from evals.codex_executor import _strict_json_schema

    raw_manifest = _read_private_file(root, "manifest.json")
    manifest = AuthoringQualityManifest.model_validate_json(raw_manifest)
    entry = _entry(manifest, domain, "seed", "seed-v1")
    _case, _input, rubric, *_ = _load_case_artifacts(root, manifest, entry)
    schema = _strict_json_schema(SeedCalibrationResult.model_json_schema())
    if entry.schema_sha256 != schema_fingerprint(SeedCalibrationResult, schema):
        raise AuthoringQualityError("seed schema binding drifted")
    expected_key = _request_key(
        entry,
        STEPS[(domain, "seed")],
        _seed_prompt(domain, rubric, _sha256_bytes(raw_manifest)),
        schema,
    )
    journal = _read_journal(root)
    for key, row in journal["requests"].items():
        if key != expected_key:
            continue
        if (
            row["domain"] != domain
            or row["phase"] != "seed"
            or row["status"] != "completed"
        ):
            continue
        raw = _read_private_file(root, f"response-{key}.json")
        if digest(json.loads(raw)) != row["response_sha256"]:
            raise AuthoringQualityError(
                "seed response differs from its completed request receipt"
            )
        result = SeedCalibrationResult.model_validate_json(raw)
        if {item.seed_id: item.label for item in result.decisions} == {
            item["seed_id"]: item["expected"] for item in SEED_CASES
        } and len({item.seed_id for item in result.decisions}) == len(SEED_CASES):
            return
    raise AuthoringQualityError("same-domain seeded evidence calibration has not passed")


def _require_teacher(
    root: Path, manifest: AuthoringQualityManifest, entry: CaseBinding
) -> dict:
    teacher_entry = _entry(manifest, entry.domain, "teacher", entry.case_id)
    teacher_case, case_input, _rubric, _split, _paths = _load_case_artifacts(
        root, manifest, teacher_entry
    )
    judge_case, *_ = _load_case_artifacts(root, manifest, entry)
    if (
        teacher_case.source_group_id != judge_case.source_group_id
        or teacher_entry.rubric_sha256 != entry.rubric_sha256
    ):
        raise AuthoringQualityError("judge and teacher case/rubric bindings differ")
    from evals.codex_executor import _strict_json_schema

    schema = _strict_json_schema(TeacherReferenceResult.model_json_schema())
    if teacher_entry.schema_sha256 != schema_fingerprint(TeacherReferenceResult, schema):
        raise AuthoringQualityError("teacher schema binding drifted")
    expected_prompt = _teacher_prompt(
        teacher_entry,
        teacher_case,
        case_input,
        _rubric,
        _sha256_bytes(_read_private_file(root, "manifest.json")),
    )
    expected_key = _request_key(
        teacher_entry, STEPS[(entry.domain, "teacher")], expected_prompt, schema
    )
    for key, row in _read_journal(root)["requests"].items():
        if key != expected_key:
            continue
        if (row["domain"], row["phase"], row["case_id"], row["status"]) != (
            entry.domain,
            "teacher",
            entry.case_id,
            "completed",
        ):
            continue
        raw = _read_private_file(root, f"response-{key}.json")
        if digest(json.loads(raw)) != row["response_sha256"]:
            raise AuthoringQualityError("teacher response receipt drifted")
        result = TeacherReferenceResult.model_validate_json(raw)
        AuthoringQualityEvaluationScope.validate_result(result, teacher_entry, case_input)
        return {
            "input_sha256": teacher_entry.input_sha256,
            "reference": result.model_dump(mode="json"),
        }
    raise AuthoringQualityError(
        "same-case source-only teacher reference has not completed"
    )


def database_fingerprint() -> str:
    from sqlalchemy.engine import make_url

    from core.config import get_settings

    url = make_url(get_settings().database_url)
    if url.host != "127.0.0.1" or not (url.database or "").startswith(
        ("authoring_quality_eval_", "map_spatial_eval_")
    ):
        raise AuthoringQualityError(
            "authoring evaluation requires its isolated loopback database"
        )
    return digest(
        {
            "driver": url.drivername,
            "host": url.host,
            "port": url.port,
            "database": url.database,
        }
    )


async def verify_project_runtime(db, manifest: AuthoringQualityManifest) -> None:
    """Recheck the active owner, dedicated Project, and verified Luna/max snapshot."""
    from sqlalchemy import select

    from modules.account.facade import current_account_id, require_account_active
    from modules.project.facade import (
        build_project_llm_execution_snapshot,
        require_active_project,
        restore_project_llm_execution_settings,
    )
    from modules.project.models import Project

    try:
        if database_fingerprint() != manifest.database_sha256:
            raise AuthoringQualityError("authoring-quality database binding drifted")
        if os.environ.get("AUTH_MODE") != "local":
            raise AuthoringQualityError(
                "authoring-quality execution requires local owner auth"
            )
        owner_id = str(current_account_id())
        if owner_id != manifest.owner_id:
            raise AuthoringQualityError(
                "active owner differs from frozen authoring-quality owner"
            )
        await require_account_active(db, uuid.UUID(owner_id), allow_local_bootstrap=False)
        await require_active_project(db, manifest.project_id, allow_demo_readonly=False)
        project = await db.scalar(
            select(Project).where(Project.id == uuid.UUID(manifest.project_id))
        )
        if (
            project is None
            or str(project.id) != manifest.project_id
            or str(project.owner_id) != owner_id
            or project.project_kind != "author"
            or project.title != manifest.project_title
            or not project.title.startswith("AUTHORING-QUALITY:")
        ):
            raise AuthoringQualityError(
                "active Project does not match frozen isolated owner scope"
            )
        current = await build_project_llm_execution_snapshot(db, manifest.project_id)
        restored = await restore_project_llm_execution_settings(
            db, manifest.project_id, current
        )
        profile = current.get("profile") or {}
        if (
            current != manifest.project_snapshot
            or current.get("novel_id") != manifest.project_id
            or digest(current) != manifest.project_snapshot_sha256
            or profile.get("provider_id") != "codex"
            or profile.get("model") != "gpt-6-luna"
            or profile.get("connection_verified") is not True
            or restored.get("llm", {}).get("extra", {}).get("reasoning_effort") != "max"
        ):
            raise AuthoringQualityError("verified Project Luna/max snapshot drifted")
    except AuthoringQualityError:
        raise
    except Exception as error:
        raise AuthoringQualityError(
            "active owner/Project runtime verification failed"
        ) from error
    finally:
        # Release all read work before the standalone Sol model call.
        await db.rollback()


@dataclass(frozen=True)
class AuthoringQualityEvaluationScope:
    db: object
    private_root: Path
    manifest: dict
    domain: str
    phase: str
    case_id: str
    execute: bool = False

    async def authorize(
        self,
        prompt: str,
        response_model: type[BaseModel],
        step_name: str,
        schema: dict,
    ) -> tuple[AuthoringQualityManifest, CaseBinding, str]:
        if not self.execute or os.environ.get(AUTHORING_QUALITY_LIVE_ENV) != "1":
            raise AuthoringQualityError(
                "authoring-quality model calls require execute plus "
                f"{AUTHORING_QUALITY_LIVE_ENV}=1"
            )
        if self.domain not in DOMAINS or self.phase not in PHASES:
            raise AuthoringQualityError("unsupported authoring-quality scope")
        if len(prompt.encode("utf-8")) > AUTHORING_QUALITY_MAX_PROMPT_BYTES:
            raise AuthoringQualityError(
                "authoring-quality frozen prompt exceeds the request limit"
            )
        expected_model = {
            "seed": SeedCalibrationResult,
            "teacher": TeacherReferenceResult,
            "judge": JudgeResult,
        }[self.phase]
        expected_step = STEPS[(self.domain, self.phase)]
        if response_model is not expected_model or step_name != expected_step:
            raise AuthoringQualityError("authoring-quality scope/schema/step mismatch")
        if (
            EVAL_TEACHER_MODEL != "gpt-6.1-sol"
            or EVAL_TEACHER_REASONING_EFFORT != "xhigh"
        ):
            raise AuthoringQualityError("authoring-quality teacher contract drifted")

        root = _assert_private_root(self.private_root)
        raw_manifest = _read_private_file(root, "manifest.json")
        try:
            persisted = AuthoringQualityManifest.model_validate_json(raw_manifest)
            supplied = AuthoringQualityManifest.model_validate(self.manifest)
        except ValueError as error:
            raise AuthoringQualityError(
                "authoring-quality manifest is invalid"
            ) from error
        if persisted != supplied:
            raise AuthoringQualityError(
                "authoring-quality manifest changed after preflight"
            )
        if persisted.private_root_sha256 != digest(str(root)):
            raise AuthoringQualityError("authoring-quality private root binding drifted")
        if persisted.pipeline_sha256 != pipeline_fingerprint():
            raise AuthoringQualityError(
                "authoring-quality product pipeline fingerprint drifted"
            )
        entry = _entry(persisted, self.domain, self.phase, self.case_id)
        if entry.schema_sha256 != schema_fingerprint(response_model, schema):
            raise AuthoringQualityError(
                "authoring-quality response/product schema fingerprint drifted"
            )

        case, case_input, rubric, _split, _paths = _load_case_artifacts(
            root, persisted, entry
        )
        rubric_raw = _read_private_file(
            root,
            _case_relative(entry.domain, entry.phase, entry.case_id, "rubric.json"),
        )
        if _sha256_bytes(rubric_raw) != entry.rubric_sha256:
            raise AuthoringQualityError("authoring-quality rubric fingerprint drifted")
        manifest_hash = _sha256_bytes(raw_manifest)
        if entry.phase != "seed":
            _require_seed(root, entry.domain)
        await verify_project_runtime(self.db, persisted)
        if entry.phase == "judge":
            from evals.authoring_quality_product import read_product_evidence

            try:
                evidence = await read_product_evidence(
                    self.db, persisted, case.product_ref
                )
                if digest(evidence) != entry.product_evidence_sha256:
                    raise AuthoringQualityError(
                        "authoring-quality product evidence drifted"
                    )
                teacher = _require_teacher(root, persisted, entry)
                expected_prompt = _judge_prompt(
                    entry, case, case_input, rubric, evidence, manifest_hash, teacher
                )
            finally:
                await self.db.rollback()
        elif entry.phase == "seed":
            expected_prompt = _seed_prompt(entry.domain, rubric, manifest_hash)
        else:
            expected_prompt = _teacher_prompt(
                entry, case, case_input, rubric, manifest_hash
            )
        if prompt != expected_prompt:
            raise AuthoringQualityError(
                "authoring-quality prompt differs from frozen source/rubric"
            )
        if (
            _read_private_file(root, "manifest.json") != raw_manifest
            or persisted.pipeline_sha256 != pipeline_fingerprint()
        ):
            raise AuthoringQualityError(
                "authoring-quality binding changed during verification"
            )
        _load_case_artifacts(root, persisted, entry)
        return persisted, entry, manifest_hash

    def start_request(
        self, entry: CaseBinding, step_name: str, prompt: str, schema: dict
    ) -> str:
        root = _assert_private_root(self.private_root)
        return _start_request(root, entry, step_name, prompt, schema)

    def finish_request(
        self, request_key: str, response: str | None, *, completed: bool
    ) -> None:
        root = _assert_private_root(self.private_root)
        _finish_request(root, request_key, response, completed=completed)

    @staticmethod
    def validate_result(
        result: BaseModel, entry: CaseBinding, case_input: FrozenInput
    ) -> None:
        if entry.phase == "seed":
            ids = [item.seed_id for item in result.decisions]
            if len(ids) != len(set(ids)) or set(ids) != {
                row["seed_id"] for row in SEED_CASES
            }:
                raise AuthoringQualityError(
                    "seed response omitted or duplicated an anchor"
                )
            return
        if entry.phase == "teacher":
            if result.case_id != entry.case_id:
                raise AuthoringQualityError("teacher reference returned another case ID")
            known_source_ids = {row.source_id for row in case_input.sources}
            if any(
                not set(item.source_ids).issubset(known_source_ids)
                for item in result.reference_points
            ):
                raise AuthoringQualityError("teacher reference cited an unfrozen source")
            if any(
                item.status != "unknown" and not item.source_ids
                for item in result.reference_points
            ):
                raise AuthoringQualityError(
                    "teacher factual claims require frozen source citations"
                )

    def validate_response(self, result: BaseModel, entry: CaseBinding) -> None:
        root = _assert_private_root(self.private_root)
        manifest = AuthoringQualityManifest.model_validate(self.manifest)
        _case, case_input, rubric, _split, _paths = _load_case_artifacts(
            root, manifest, entry
        )
        self.validate_result(result, entry, case_input)
        if entry.phase == "judge":
            if result.case_id != entry.case_id:
                raise AuthoringQualityError("judge returned another case ID")
            actual = [item.criterion_id for item in result.criteria]
            if len(actual) != len(set(actual)) or set(actual) != {
                item.criterion_id for item in rubric.criteria
            }:
                raise AuthoringQualityError(
                    "judge criteria differ from the frozen rubric"
                )
            known = {"source", "confirmation", "task", *(_case.product_ref.output_ids)}
            if any(
                not set(item.evidence_ids).issubset(known) for item in result.criteria
            ):
                raise AuthoringQualityError(
                    "judge cited evidence outside the product receipt"
                )
            if any(
                item.outcome != "unknown" and not item.evidence_ids
                for item in result.criteria
            ):
                raise AuthoringQualityError(
                    "judge decisions require product evidence citations"
                )

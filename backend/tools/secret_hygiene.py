"""Fail CI when tracked repository files contain high-confidence credentials."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template")
_PRIVATE_KEY_FILENAMES = {"id_dsa", "id_ecdsa", "id_ed25519", "id_rsa"}
_FIXTURE_PATH_PARTS = {"fixtures", "test", "testdata", "tests"}
_PLACEHOLDER_PATTERN = re.compile(
    r"(?:^|[-_])(?:"
    r"abcdef[0-9]*|dummy|example|fake|must-not|placeholder|redacted|secret|"
    r"should-not|test"
    r")(?:[-_]|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SecretRule:
    name: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True, repr=False)
class Finding:
    path: str
    rule: str
    line: int | None = None
    fingerprint: str | None = None

    def format(self) -> str:
        safe_path = _safe_display_path(self.path)
        location = safe_path if self.line is None else f"{safe_path}:{self.line}"
        suffix = "" if self.fingerprint is None else f" fingerprint={self.fingerprint}"
        return f"{location}: {self.rule}{suffix}"

    def __repr__(self) -> str:
        return f"Finding({self.format()!r})"


@dataclass(frozen=True, slots=True)
class _GitEntry:
    mode: str
    object_id: str
    stage: int
    path: str


_SECRET_RULES = (
    SecretRule(
        "private_key_block",
        re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    ),
    SecretRule(
        "putty_private_key",
        re.compile(r"(?m)^PuTTY-User-Key-File-[23]:[ \t]*(?:ssh-|ecdsa-)", re.I),
    ),
    SecretRule("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    SecretRule("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    SecretRule(
        "github_token",
        re.compile(
            r"\b(?:gh[pousr]_[0-9A-Za-z]{36,255}|github_pat_[0-9A-Za-z_]{22,255})\b"
        ),
    ),
    SecretRule("gitlab_token", re.compile(r"\bglpat-[0-9A-Za-z_-]{20,}\b")),
    SecretRule("npm_token", re.compile(r"\bnpm_[0-9A-Za-z]{36}\b")),
    SecretRule("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    SecretRule("stripe_live_key", re.compile(r"\b[rs]k_live_[0-9A-Za-z]{16,}\b")),
    SecretRule("openai_compatible_key", re.compile(r"\bsk-[0-9A-Za-z_-]{20,}\b")),
)
_SECRET_PREFIX_PATTERN = re.compile(
    rb"-----BEGIN |PuTTY-User-Key-File-|AKIA|ASIA|AIza|"
    rb"gh[pousr]_|github_pat_|glpat-|npm_|xox[baprs]-|[rs]k_live_|sk-"
)


def _normalize_path(path: str) -> PurePosixPath:
    return PurePosixPath(path.replace("\\", "/"))


def _redact_secret_shapes(value: str) -> str:
    for rule in _SECRET_RULES:
        value = rule.pattern.sub("[REDACTED]", value)
    return value


def _safe_display_path(path: str) -> str:
    """Escape log controls and redact credential-shaped filename fragments."""
    redacted = _redact_secret_shapes(path)
    quoted = json.dumps(redacted, ensure_ascii=False)[1:-1]
    return quoted.encode("utf-8", errors="backslashreplace").decode("utf-8")


def _is_env_template_name(name: str) -> bool:
    return name.startswith(".env.") and name.endswith(_ENV_TEMPLATE_SUFFIXES)


def sensitive_path_rule(path: str) -> str | None:
    normalized = _normalize_path(path)
    name = normalized.name.lower()
    if (name == ".env" or name.startswith(".env.")) and not _is_env_template_name(name):
        return "tracked_env_file"
    if name in _PRIVATE_KEY_FILENAMES:
        return "tracked_private_key_file"
    return None


def _allows_placeholder(path: str, value: str) -> bool:
    normalized = _normalize_path(path)
    parts = {part.lower() for part in normalized.parts}
    name = normalized.name.lower()
    fixture_like = (
        bool(_FIXTURE_PATH_PARTS & parts)
        or name.startswith("test_")
        or name.endswith((".md", ".rst"))
        or _is_env_template_name(name)
    )
    return fixture_like and _PLACEHOLDER_PATTERN.search(value) is not None


def scan_text(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for rule in _SECRET_RULES:
        for match in rule.pattern.finditer(text):
            value = match.group(0)
            if _allows_placeholder(path, value):
                continue
            findings.append(
                Finding(
                    path=path,
                    rule=rule.name,
                    line=text.count("\n", 0, match.start()) + 1,
                    fingerprint=hashlib.sha256(value.encode("utf-8")).hexdigest()[:12],
                )
            )
    return findings


def _git_entries(repo_root: Path) -> list[_GitEntry]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--stage", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    entries: list[_GitEntry] = []
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        metadata, path_bytes = record.split(b"\t", maxsplit=1)
        mode, object_id, stage = metadata.decode("ascii").split()
        entries.append(
            _GitEntry(
                mode=mode,
                object_id=object_id,
                stage=int(stage),
                path=os.fsdecode(path_bytes),
            )
        )
    return entries


def tracked_files(repo_root: Path) -> list[str]:
    return sorted({entry.path for entry in _git_entries(repo_root)})


def _read_index_blobs(repo_root: Path, entries: list[_GitEntry]) -> dict[str, bytes]:
    object_ids = sorted({entry.object_id for entry in entries if entry.mode != "160000"})
    if not object_ids:
        return {}
    result = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        input=("\n".join(object_ids) + "\n").encode("ascii"),
    )
    blobs: dict[str, bytes] = {}
    offset = 0
    for expected_object_id in object_ids:
        header_end = result.stdout.index(b"\n", offset)
        header = result.stdout[offset:header_end].decode("ascii")
        object_id, object_type, size_text = header.split()
        if object_id != expected_object_id or object_type != "blob":
            raise RuntimeError("git returned an unexpected object for a tracked file")
        size = int(size_text)
        content_start = header_end + 1
        content_end = content_start + size
        blobs[object_id] = result.stdout[content_start:content_end]
        if result.stdout[content_end : content_end + 1] != b"\n":
            raise RuntimeError("git returned a malformed batch response")
        offset = content_end + 1
    return blobs


def _read_worktree_file(repo_root: Path, relative_path: str) -> bytes | None:
    absolute_path = repo_root / relative_path
    try:
        mode = absolute_path.lstat().st_mode
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(mode):
        return os.fsencode(os.readlink(absolute_path))
    if not stat.S_ISREG(mode):
        return None
    return absolute_path.read_bytes()


def _scan_bytes(path: str, data: bytes) -> list[Finding]:
    # surrogateescape preserves invalid bytes as boundaries instead of silently joining
    # otherwise separate ASCII fragments. Credential patterns themselves are ASCII.
    if _SECRET_PREFIX_PATTERN.search(data) is None:
        return []
    return scan_text(path, data.decode("utf-8", errors="surrogateescape"))


def scan_repository(repo_root: Path) -> list[Finding]:
    findings: set[Finding] = set()
    entries = _git_entries(repo_root)
    paths = sorted({entry.path for entry in entries})
    for relative_path in paths:
        path_rule = sensitive_path_rule(relative_path)
        if path_rule is not None:
            findings.add(Finding(path=relative_path, rule=path_rule))

    # Inspect every cached stage as well as the tracked working-tree version. This
    # catches both staged secrets hidden by a later edit and unstaged secrets that
    # have not reached the index yet. Gitlinks are intentionally content-opaque.
    index_blobs = _read_index_blobs(repo_root, entries)
    scanned_content: dict[str, set[bytes]] = {}
    for entry in entries:
        data = index_blobs.get(entry.object_id)
        if data is not None:
            scanned_content.setdefault(entry.path, set()).add(
                hashlib.sha256(data).digest()
            )
            findings.update(_scan_bytes(entry.path, data))
    for relative_path in paths:
        data = _read_worktree_file(repo_root, relative_path)
        if data is not None:
            content_hash = hashlib.sha256(data).digest()
            if content_hash in scanned_content.get(relative_path, set()):
                continue
            findings.update(_scan_bytes(relative_path, data))

    return sorted(
        findings,
        key=lambda finding: (
            finding.path,
            finding.line or 0,
            finding.rule,
            finding.fingerprint or "",
        ),
    )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        findings = scan_repository(repo_root)
    except Exception:
        # A file path or Git error may itself contain sensitive text. Keep the CI
        # failure actionable without echoing exception details into shared logs.
        print("Repository secret hygiene check could not complete safely.")
        return 2
    if findings:
        print("Repository secret hygiene check failed:")
        for finding in findings:
            print(f"- {finding.format()}")
        print("Credential values are intentionally omitted; rotate any real credential.")
        return 1
    print("Repository secret hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import subprocess
from pathlib import Path

import tools.secret_hygiene as secret_hygiene
from tools.secret_hygiene import (
    Finding,
    scan_repository,
    scan_text,
    sensitive_path_rule,
)


def test_sensitive_path_rule_rejects_runtime_env_files_but_allows_templates() -> None:
    assert sensitive_path_rule(".env") == "tracked_env_file"
    assert sensitive_path_rule("backend/.env.local") == "tracked_env_file"
    assert sensitive_path_rule("backend/.env.production") == "tracked_env_file"
    assert sensitive_path_rule("backend/.env.example") is None
    assert sensitive_path_rule("backend/.ENV.TEMPLATE") is None
    assert sensitive_path_rule(r"backend\.env.production") == "tracked_env_file"
    assert sensitive_path_rule("backend/.envrc") is None
    assert sensitive_path_rule("backend/.environment") is None
    assert sensitive_path_rule("docs/example.env") is None


def test_sensitive_path_rule_rejects_common_private_ssh_key_names() -> None:
    assert sensitive_path_rule("deploy/id_rsa") == "tracked_private_key_file"
    assert sensitive_path_rule("secrets/id_ed25519") == "tracked_private_key_file"
    assert sensitive_path_rule("docs/id_rsa.example") is None


def test_scan_text_reports_fingerprint_without_retaining_credential() -> None:
    credential = "sk-" + "A" * 24

    findings = scan_text("backend/core/config.py", f'API_KEY = "{credential}"')

    assert len(findings) == 1
    assert findings[0].rule == "openai_compatible_key"
    assert findings[0].line == 1
    assert findings[0].fingerprint
    assert credential not in findings[0].format()
    assert credential not in repr(findings[0])


def test_scan_text_allows_explicit_test_placeholder_only_in_fixture_context() -> None:
    placeholder = "sk-test-secret-placeholder-value"

    assert scan_text("backend/tests/unit/test_client.py", placeholder) == []
    assert scan_text("docs/provider-example.md", placeholder) == []
    assert scan_text("backend/app/main.py", placeholder)


def test_placeholder_marker_must_be_a_delimited_explicit_marker() -> None:
    credential_with_marker_substrings = "sk-contestsecretvalue" + "A" * 20

    findings = scan_text(
        "backend/tests/unit/test_client.py", credential_with_marker_substrings
    )

    assert len(findings) == 1
    assert findings[0].rule == "openai_compatible_key"


def test_placeholder_context_matching_is_case_and_separator_independent() -> None:
    placeholder = "sk-example-placeholder-value"

    assert scan_text(r"Backend\Tests\Unit\client.py", placeholder) == []
    assert scan_text("backend/FIXTURES/client.json", placeholder) == []


def test_scan_text_detects_private_key_blocks_and_other_high_confidence_tokens() -> None:
    aws_key = "AKIA" + "A" * 16
    github_token = "ghp_" + "B" * 36
    text = "\n".join(
        [
            "-----BEGIN " + "PRIVATE KEY-----",
            aws_key,
            github_token,
        ]
    )

    findings = scan_text("backend/app/main.py", text)

    assert [(finding.rule, finding.line) for finding in findings] == [
        ("private_key_block", 1),
        ("aws_access_key", 2),
        ("github_token", 3),
    ]


def test_scan_text_detects_extended_private_key_and_service_token_shapes() -> None:
    text = "\n".join(
        [
            "-----BEGIN SSH2 " + "ENCRYPTED PRIVATE KEY-----",
            "PuTTY-User-Key-File-3:" + " ssh-ed25519",
            "ASIA" + "C" * 16,
            "glpat-" + "D" * 20,
            "npm_" + "E" * 36,
            "sk_live_" + "F" * 24,
        ]
    )

    findings = scan_text("deploy/credentials.txt", text)

    assert [(finding.rule, finding.line) for finding in findings] == [
        ("private_key_block", 1),
        ("putty_private_key", 2),
        ("aws_access_key", 3),
        ("gitlab_token", 4),
        ("npm_token", 5),
        ("stripe_live_key", 6),
    ]


def test_finding_format_never_requires_a_raw_value() -> None:
    finding = Finding(
        path="backend/.env",
        rule="tracked_env_file",
        line=2,
        fingerprint="abc123",
    )

    assert finding.format() == "backend/.env:2: tracked_env_file fingerprint=abc123"


def test_finding_output_escapes_controls_and_redacts_credentials_in_paths() -> None:
    credential = "sk-" + "G" * 24
    finding = Finding(path=f"bad\n\x1b[31m/{credential}.txt", rule="credential")

    formatted = finding.format()

    assert "\n" not in formatted
    assert "\x1b" not in formatted
    assert "\\n" in formatted
    assert "\\u001b" in formatted
    assert credential not in formatted
    assert credential not in repr(finding)


def test_finding_output_escapes_non_utf8_filename_bytes() -> None:
    finding = Finding(path="bad-\udcff-name", rule="credential")

    assert finding.format() == "bad-\\udcff-name: credential"


def test_main_omits_exception_details_that_may_contain_credentials(
    monkeypatch,
    capsys,
) -> None:
    credential = "sk-" + "N" * 24

    def fail_scan(_repo_root: Path) -> list[Finding]:
        raise OSError(f"cannot read {credential}")

    monkeypatch.setattr(secret_hygiene, "scan_repository", fail_scan)

    assert secret_hygiene.main() == 2
    output = capsys.readouterr().out
    assert "could not complete safely" in output
    assert credential not in output


def test_scanner_source_and_tests_do_not_trigger_their_own_rules() -> None:
    backend_root = Path(__file__).resolve().parents[2]

    for relative_path in ("tools/secret_hygiene.py", "tests/unit/test_secret_hygiene.py"):
        text = (backend_root / relative_path).read_text(encoding="utf-8")
        assert scan_text(f"backend/{relative_path}", text) == []


def test_current_repository_passes_secret_hygiene_gate() -> None:
    repo_root = Path(__file__).resolve().parents[3]

    assert scan_repository(repo_root) == []


def test_scan_repository_does_not_follow_tracked_symlinks(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    credential = "sk-" + "Z" * 24
    outside = tmp_path / "outside.txt"
    outside.write_text(credential, encoding="utf-8")
    (repo_root / "external-link").symlink_to(outside)
    subprocess.run(["git", "add", "external-link"], cwd=repo_root, check=True)

    assert scan_repository(repo_root) == []


def test_scan_repository_checks_index_and_tracked_worktree_versions(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    tracked = repo_root / "settings.py"
    index_credential = "sk-" + "H" * 24
    worktree_credential = "sk-" + "J" * 24

    tracked.write_text(index_credential, encoding="utf-8")
    subprocess.run(["git", "add", "settings.py"], cwd=repo_root, check=True)
    tracked.write_text(worktree_credential, encoding="utf-8")

    findings = scan_repository(repo_root)

    assert len(findings) == 2
    assert len({finding.fingerprint for finding in findings}) == 2
    assert {finding.rule for finding in findings} == {"openai_compatible_key"}
    output = "\n".join(finding.format() for finding in findings)
    assert index_credential not in output
    assert worktree_credential not in output


def test_scan_repository_checks_index_for_unstaged_deleted_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    tracked = repo_root / "credential.txt"
    tracked.write_text("sk-" + "K" * 24, encoding="utf-8")
    subprocess.run(["git", "add", "credential.txt"], cwd=repo_root, check=True)
    tracked.unlink()

    findings = scan_repository(repo_root)

    assert len(findings) == 1
    assert findings[0].rule == "openai_compatible_key"


def test_scan_repository_ignores_file_after_staged_removal(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    runtime_env = repo_root / ".env"
    runtime_env.write_text("sk-" + "L" * 24, encoding="utf-8")
    subprocess.run(["git", "add", ".env"], cwd=repo_root, check=True)
    subprocess.run(["git", "rm", "--cached", ".env"], cwd=repo_root, check=True)

    assert scan_repository(repo_root) == []


def test_scan_repository_scans_ascii_credentials_inside_binary_files(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    credential = b"sk-" + b"M" * 24
    binary = repo_root / "artifact.bin"
    binary.write_bytes(b"\x00\xff" + credential + b"\x00")
    subprocess.run(["git", "add", "artifact.bin"], cwd=repo_root, check=True)

    findings = scan_repository(repo_root)

    assert len(findings) == 1
    assert findings[0].rule == "openai_compatible_key"
    assert credential.decode() not in findings[0].format()

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

DEPLOY_ROOT = Path(__file__).parents[1]
HELPER = DEPLOY_ROOT / "scripts" / "production_operation_lock.py"
COMMON_SCRIPT = DEPLOY_ROOT / "scripts" / "common.sh"
LOCK_ENV = "AI_WRITING_ASSIST_PRODUCTION_OPERATION_LOCK_FD"


def _run_helper(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), *arguments],
        capture_output=True,
        text=True,
        timeout=5,
    )


def _holder_command(lock_path: Path, *, nested: bool = False) -> list[str]:
    if nested:
        return [
            "/bin/sh",
            "-c",
            'python3 "$1" verify "$2" "$AI_WRITING_ASSIST_PRODUCTION_OPERATION_LOCK_FD" '
            '&& printf "ready\\n" && cat',
            "sh",
            str(HELPER),
            str(lock_path),
        ]
    return ["/bin/sh", "-c", 'printf "ready\\n"; exec cat']


def _start_holder(lock_path: Path, *, nested: bool = False) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [
            sys.executable,
            str(HELPER),
            "acquire",
            str(lock_path),
            *_holder_command(lock_path, nested=nested),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline() == "ready\n"
    return process


def _stop_holder(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        assert process.stdin is not None
        process.stdin.close()
    process.wait(timeout=5)
    assert process.stderr is not None
    assert process.stderr.read() == ""


def test_lock_holder_excludes_second_operation_and_file_persists(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / ".state" / "production-operation.lock"
    holder = _start_holder(lock_path)
    try:
        contender = _run_helper(
            "acquire",
            str(lock_path),
            "/bin/sh",
            "-c",
            ":",
        )
        assert contender.returncode == 1
        assert contender.stdout == ""
        assert contender.stderr == "Another production operation is already running.\n"
    finally:
        _stop_holder(holder)

    released = _run_helper("acquire", str(lock_path), "/bin/sh", "-c", ":")

    assert released.returncode == 0, released.stderr
    assert released.stdout == ""
    lock_stat = lock_path.stat()
    assert stat.S_ISREG(lock_stat.st_mode)
    assert stat.S_IMODE(lock_stat.st_mode) == 0o600
    assert lock_stat.st_uid == os.getuid()
    assert stat.S_IMODE(lock_path.parent.stat().st_mode) == 0o700


def test_killing_holder_releases_the_os_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / ".state" / "production-operation.lock"
    holder = _start_holder(lock_path)
    try:
        holder.terminate()
        holder.wait(timeout=5)
        released = _run_helper("acquire", str(lock_path), "/bin/sh", "-c", ":")
        assert released.returncode == 0, released.stderr
        assert released.stdout == ""
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


def test_acquire_wait_enters_after_the_holder_releases_within_its_deadline(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / ".state" / "production-operation.lock"
    holder = _start_holder(lock_path)
    contender = subprocess.Popen(
        [
            sys.executable,
            str(HELPER),
            "acquire-wait",
            str(lock_path),
            "1",
            "/bin/sh",
            "-c",
            'printf "entered\\n"',
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(0.1)
        assert contender.poll() is None
        _stop_holder(holder)
        stdout, stderr = contender.communicate(timeout=5)
    finally:
        if holder.poll() is None:
            _stop_holder(holder)
        if contender.poll() is None:
            contender.kill()
            contender.wait(timeout=5)

    assert contender.returncode == 0, stderr
    assert stdout == "entered\n"
    assert stderr == ""


def test_acquire_wait_fails_closed_after_a_bounded_timeout(tmp_path: Path) -> None:
    lock_path = tmp_path / ".state" / "production-operation.lock"
    holder = _start_holder(lock_path)
    try:
        started = time.monotonic()
        contender = _run_helper(
            "acquire-wait",
            str(lock_path),
            "0.1",
            "/bin/sh",
            "-c",
            ":",
        )
        elapsed = time.monotonic() - started
    finally:
        _stop_holder(holder)

    assert contender.returncode == 1
    assert contender.stdout == ""
    assert contender.stderr == "Another production operation is already running.\n"
    assert 0.08 <= elapsed < 1


def test_runtime_acquire_or_skip_is_a_noop_when_busy_and_reenters_when_free(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / ".state" / "production-operation.lock"
    holder = _start_holder(lock_path)
    nested_command = [
        "/bin/sh",
        "-c",
        'python3 "$1" verify "$2" "$AI_WRITING_ASSIST_PRODUCTION_OPERATION_LOCK_FD" '
        '&& printf "ran\\n"',
        "sh",
        str(HELPER),
        str(lock_path),
    ]
    try:
        skipped = _run_helper("acquire-or-skip", str(lock_path), *nested_command)
    finally:
        _stop_holder(holder)

    assert skipped.returncode == 0
    assert skipped.stdout == ""
    assert skipped.stderr == (
        "Runtime health check skipped: another production operation is running.\n"
    )

    entered = _run_helper("acquire-or-skip", str(lock_path), *nested_command)

    assert entered.returncode == 0, entered.stderr
    assert entered.stdout == "ran\n"
    assert entered.stderr == ""


def test_nested_shell_reentry_verifies_the_inherited_lock_fd(tmp_path: Path) -> None:
    lock_path = tmp_path / ".state" / "production-operation.lock"
    holder = _start_holder(lock_path, nested=True)

    try:
        contender = _run_helper(
            "acquire",
            str(lock_path),
            "/bin/sh",
            "-c",
            ":",
        )
        assert contender.returncode == 1
        assert contender.stderr == "Another production operation is already running.\n"
    finally:
        _stop_holder(holder)


def test_common_wrapper_restarts_and_reenters_across_nested_shells(
    tmp_path: Path,
) -> None:
    scripts_dir = tmp_path / "repo" / "deploy" / "scripts"
    scripts_dir.mkdir(parents=True)
    for source in (COMMON_SCRIPT, HELPER):
        shutil.copy2(source, scripts_dir / source.name)

    driver = scripts_dir / "lock_driver.sh"
    driver.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        '. "$SCRIPT_DIR/common.sh"\n'
        'acquire_production_operation_lock "$@"\n'
        'if [ "${1:-}" = nested ]; then\n'
        '    /bin/sh "$SCRIPT_DIR/lock_driver.sh" terminal\n'
        '    printf "outer verified\\n"\n'
        "else\n"
        '    printf "nested verified\\n"\n'
        "fi\n",
        encoding="utf-8",
    )
    driver.chmod(0o700)

    result = subprocess.run(
        ["/bin/sh", str(driver), "nested"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "nested verified\nouter verified\n"
    assert result.stderr == ""
    lock_path = scripts_dir.parent / ".state" / "production-operation.lock"
    assert stat.S_ISREG(lock_path.stat().st_mode)
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


@pytest.mark.parametrize("fd_value", ("", "not-a-fd", "-1", "99999"))
def test_forged_or_invalid_inherited_fd_fails_closed(
    tmp_path: Path,
    fd_value: str,
) -> None:
    lock_path = tmp_path / ".state" / "production-operation.lock"
    created = _run_helper("acquire", str(lock_path), "/bin/sh", "-c", ":")
    assert created.returncode == 0, created.stderr

    result = _run_helper("verify", str(lock_path), fd_value)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Production operation lock is unsafe.\n"


def test_symlinked_or_unsafe_lock_metadata_fails_closed(tmp_path: Path) -> None:
    state_dir = tmp_path / ".state"
    state_dir.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.write_text("target")
    lock_path = state_dir / "production-operation.lock"
    lock_path.symlink_to(target)

    symlinked = _run_helper("acquire", str(lock_path), "/bin/sh", "-c", ":")

    assert symlinked.returncode == 1
    assert symlinked.stdout == ""
    assert symlinked.stderr == "Production operation lock is unsafe.\n"

    skipped_symlink = _run_helper(
        "acquire-or-skip", str(lock_path), "/bin/sh", "-c", ":"
    )
    assert skipped_symlink.returncode == 1
    assert skipped_symlink.stdout == ""
    assert skipped_symlink.stderr == "Production operation lock is unsafe.\n"

    lock_path.unlink()
    created = _run_helper("acquire", str(lock_path), "/bin/sh", "-c", ":")
    assert created.returncode == 0, created.stderr
    lock_path.chmod(0o644)

    unsafe_mode = _run_helper("acquire", str(lock_path), "/bin/sh", "-c", ":")

    assert unsafe_mode.returncode == 1
    assert unsafe_mode.stdout == ""
    assert unsafe_mode.stderr == "Production operation lock is unsafe.\n"


def test_symlinked_state_directory_fails_closed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    state_dir = tmp_path / ".state"
    state_dir.symlink_to(outside, target_is_directory=True)

    result = _run_helper(
        "acquire",
        str(state_dir / "production-operation.lock"),
        "/bin/sh",
        "-c",
        ":",
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Production operation lock is unsafe.\n"


def test_mutating_scripts_enter_shared_lock_before_production_work() -> None:
    common = COMMON_SCRIPT.read_text(encoding="utf-8")

    assert "acquire_production_operation_lock()" in common
    assert "acquire_runtime_health_lock()" in common
    assert "production_operation_lock.py" in common
    assert (
        'exec python3 "$SCRIPT_DIR/production_operation_lock.py" acquire-wait'
        in common
    )
    assert '"$lock_path" 300 /bin/sh "$0" "$@"' in common
    assert (
        'exec python3 "$SCRIPT_DIR/production_operation_lock.py" acquire-or-skip'
        in common
    )
    assert 'python3 "$SCRIPT_DIR/production_operation_lock.py" verify' in common
    assert '"$lock_path" /bin/sh "$0" "$@"' in common

    release = (DEPLOY_ROOT / "scripts" / "release.sh").read_text(encoding="utf-8")
    release_lock = release.index('acquire_production_operation_lock "$@"')
    release_validation = release.index("validate_environment")
    release_guard = release.index("verify_deployment_checkout")
    assert release_lock < release_validation < release_guard < release.index(
        'git -C "$REPO_ROOT" fetch --prune origin'
    )

    restore = (DEPLOY_ROOT / "scripts" / "restore.sh").read_text(encoding="utf-8")
    restore_lock = restore.index('acquire_production_operation_lock "$@"')
    restore_validation = restore.index("validate_environment")
    restore_guard = restore.index("verify_deployment_checkout")
    assert restore_lock < restore_validation < restore_guard < restore.index(
        "ensure_private_backup_directory"
    ) < restore.index("BACKUP_PATH=$(realpath")

    for script_name, validator in (
        ("backup.sh", "validate_environment >&2"),
        ("account_maintenance.sh", "validate_environment"),
    ):
        script = (DEPLOY_ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        assert script.index('acquire_production_operation_lock "$@"') < script.index(
            validator
        )

    runtime_health = (DEPLOY_ROOT / "scripts" / "runtime_health.sh").read_text(
        encoding="utf-8"
    )
    runtime_lock = runtime_health.index('acquire_runtime_health_lock "$@"')
    assert runtime_lock < runtime_health.index("validate_environment")
    assert "acquire_production_operation_lock" not in runtime_health

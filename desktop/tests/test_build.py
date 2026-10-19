import sys

import pytest

from desktop import build, build_assets


def test_native_build_does_not_inherit_outer_make_recursion(monkeypatch, tmp_path):
    for name in ("MAKELEVEL", "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES"):
        monkeypatch.setenv(name, "outer make")
    monkeypatch.setenv("PATH", "/native/tools")
    calls = []
    monkeypatch.setattr(
        build_assets.subprocess, "run", lambda *args, **kwargs: calls.append(kwargs)
    )
    build_assets.run("make", cwd=tmp_path)
    assert calls[0]["env"]["PATH"] == "/native/tools"
    assert not any(
        name.startswith("MAKE") or name == "MFLAGS" for name in calls[0]["env"]
    )
    build_assets.run(
        "make", cwd=tmp_path, env={"PG_CONFIG": "/pinned/pg_config", "MAKELEVEL": "1"}
    )
    assert calls[1]["env"] == {"PG_CONFIG": "/pinned/pg_config"}


@pytest.mark.parametrize(
    ("system", "machine", "target"),
    [
        ("darwin", "arm64", "macos-x64"),
        ("darwin", "x86_64", None),
        ("win32", "AMD64", None),
        ("linux", "x86_64", None),
    ],
)
def test_build_rejects_other_hosts_before_download_or_packaging(
    monkeypatch, system, machine, target
):
    monkeypatch.setattr(sys, "platform", system)
    monkeypatch.setattr(
        sys, "argv", ["build.py", *(["--target", target] if target else [])]
    )
    monkeypatch.setattr(build.platform, "machine", lambda: machine)
    monkeypatch.setattr(
        build.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("must not build")
    )
    with pytest.raises(SystemExit, match="native host|Build on"):
        build.main()


@pytest.mark.parametrize(
    ("system", "machine", "target"),
    [
        ("darwin", "arm64", None),
        ("darwin", "x86_64", "macos-x64"),
        ("win32", "AMD64", "windows-x64"),
    ],
)
def test_build_accepts_default_arm64_or_explicit_native_target(
    monkeypatch, system, machine, target
):
    monkeypatch.setattr(sys, "platform", system)
    monkeypatch.setattr(
        sys, "argv", ["build.py", *(["--target", target] if target else [])]
    )
    monkeypatch.setattr(build.platform, "machine", lambda: machine)

    def preparing(command, **kwargs):
        assert command == [sys.executable, str(build.ROOT / "desktop/build_assets.py")]
        raise RuntimeError("validated; stop before native compilation")

    monkeypatch.setattr(build.subprocess, "run", preparing)
    with pytest.raises(RuntimeError, match="validated"):
        build.main()

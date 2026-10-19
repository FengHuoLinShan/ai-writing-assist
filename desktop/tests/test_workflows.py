from pathlib import Path

import yaml

from desktop import release

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.load(
        (ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader
    )


def test_installers_and_releases_are_manual_with_arm64_default():
    build = workflow("desktop.yml")
    draft = workflow("desktop-release.yml")
    assert set(build["on"]) == {"workflow_dispatch", "workflow_call"}
    assert set(draft["on"]) == {"workflow_dispatch"}
    for spec in (
        build["on"]["workflow_dispatch"],
        build["on"]["workflow_call"],
        draft["on"]["workflow_dispatch"],
    ):
        assert spec["inputs"]["target"]["default"] == release.DEFAULT_TARGET
    for spec in (build, draft):
        assert spec["on"]["workflow_dispatch"]["inputs"]["target"]["options"] == list(
            release.TARGETS
        )
    assert (
        build["jobs"]["build"]["strategy"]["matrix"]["include"]
        == "${{ fromJSON(needs.select.outputs.matrix) }}"
    )
    selection = build["jobs"]["select"]["steps"][-1]
    assert selection["env"]["BUILD_TARGET"] == "${{ inputs.target }}"
    assert 'release.py matrix "$BUILD_TARGET"' in selection["run"]
    assert draft["jobs"]["installers"]["with"]["target"] == "${{ inputs.target }}"
    collection = draft["jobs"]["draft"]["steps"][-1]
    assert collection["env"]["BUILD_TARGET"] == "${{ inputs.target }}"
    assert '--target "$BUILD_TARGET"' in collection["run"]
    assert "--draft" in collection["run"]


def test_automatic_backend_ci_keeps_desktop_checks_without_building_installers():
    steps = workflow("backend-ci.yml")["jobs"]["backend-quality"]["steps"]
    assert any(step.get("run") == "make desktop-test" for step in steps)
    assert not any("desktop/build.py" in step.get("run", "") for step in steps)
    images = workflow("production-image-ci.yml")
    assert set(images["on"]) == {"workflow_dispatch", "pull_request", "push"}
    assert (
        images["jobs"]["production-image-contract"]["if"]
        == "github.event_name == 'workflow_dispatch'"
    )
    assert "production-image-ci.yml" not in release.REQUIRED_WORKFLOWS


def test_local_quality_gate_checks_desktop_lint_and_tests():
    makefile = (ROOT / "Makefile").read_text()
    lint = makefile.split("\nlint:", 1)[1].split("\nlint-fix:", 1)[0]
    quality = makefile.split("\ntest-ci:", 1)[1].split("\neval-corpus:", 1)[0]
    assert "ruff check --config backend/pyproject.toml desktop" in lint
    assert "$(MAKE) desktop-test" in quality

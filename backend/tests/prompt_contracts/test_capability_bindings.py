from __future__ import annotations

from tools.prompt_contracts import capability_bindings


def test_unreadable_production_module_is_a_blocking_binding_issue(
    monkeypatch, tmp_path
) -> None:
    modules_root = tmp_path / "modules" / "broken"
    modules_root.mkdir(parents=True)
    (modules_root / "bad.py").write_text("def broken(:\n", encoding="utf-8")

    monkeypatch.setattr(capability_bindings, "BACKEND_ROOT", tmp_path)
    monkeypatch.setattr(capability_bindings, "EXEMPT_FILES", frozenset())
    monkeypatch.setattr(capability_bindings, "CAPABILITY_BINDINGS", {})

    issues = capability_bindings.validate_capability_bindings()

    assert any(
        issue.severity == "P1"
        and issue.code == "binding.ast_unreadable"
        and issue.path == "modules/broken/bad.py"
        for issue in issues
    )


def test_unbound_research_call_is_a_blocking_binding_issue(monkeypatch, tmp_path) -> None:
    modules_root = tmp_path / "modules" / "assistant"
    modules_root.mkdir(parents=True)
    (modules_root / "web.py").write_text(
        "async def run(client):\n    return await client.research('fact')\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(capability_bindings, "BACKEND_ROOT", tmp_path)
    monkeypatch.setattr(capability_bindings, "EXEMPT_FILES", frozenset())
    monkeypatch.setattr(capability_bindings, "CAPABILITY_BINDINGS", {})

    issues = capability_bindings.validate_capability_bindings()

    assert any(
        issue.severity == "P1"
        and issue.code == "binding.missing"
        and "modules/assistant/web.py" in issue.message
        for issue in issues
    )

"""Safety and real-parser contracts for the opt-in synthetic diagnostic."""

import json
import os

import pytest

from modules.imports.parsers import parse_file
from tools import performance_probe as probe


def test_diagnostic_refuses_dotenv_before_creating_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "OUT", tmp_path / "evidence")
    monkeypatch.setenv("DATABASE_URL", "preserve-caller-value")
    (tmp_path / ".env").write_text("DATABASE_URL=operator-database\n")
    with pytest.raises(RuntimeError, match=r"without backend/\.env"):
        probe.configure()
    assert not probe.OUT.exists()
    assert os.environ["DATABASE_URL"] == "preserve-caller-value"


def test_diagnostic_refuses_retargeting_before_changing_environment(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "OUT", tmp_path)
    monkeypatch.setenv("DATABASE_URL", "preserve-caller-value")
    (tmp_path / "runtime-private.json").write_text(
        json.dumps(
            {
                "DATABASE_URL": "postgresql+asyncpg://localhost/ai_novel_engine",
                "E2E_DATABASE_URL": probe.DATABASE,
            }
        )
    )
    with pytest.raises(RuntimeError, match="Refusing"):
        probe.configure()
    assert os.environ["DATABASE_URL"] == "preserve-caller-value"


def test_synthetic_imports_have_exact_chapter_counts_with_real_parsers(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(probe, "OUT", tmp_path)
    probe.epub()
    for tier, expected in [("S", 30), ("L", 300)]:
        for kind in ("txt", "epub"):
            chapters = parse_file(
                (tmp_path / f"synthetic-{tier}.{kind}").read_bytes(), kind
            )
            assert len(chapters) == expected
            assert all(len(chapter["content"]) >= 2500 for chapter in chapters)

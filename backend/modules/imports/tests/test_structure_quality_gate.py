from __future__ import annotations

from modules.imports.workflow_structure_phase import structure_quality_gate


def test_structure_quality_gate_requires_structure_output() -> None:
    gate = structure_quality_gate({"total_threads": 0, "total_arcs": 0})
    assert gate == {"ok": False, "reasons": ["empty_structure_output"]}


def test_structure_quality_gate_accepts_referenced_structure() -> None:
    gate = structure_quality_gate(
        {
            "threads": [{"related_scene_ids": ["scene-1"]}],
            "arcs": [{"start_chapter": 1, "end_chapter": 2}],
        }
    )
    assert gate["ok"] is True

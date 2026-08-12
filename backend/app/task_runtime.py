"""Explicit startup composition for domain task handlers."""

from __future__ import annotations

import importlib

__all__ = ["register_task_handlers"]


_TASK_HANDLER_MODULES = (
    "modules.imports.tasks",
    "modules.world.map_atlas_tasks",
    "modules.interaction.tasks",
    "modules.outline.tasks",
    "modules.project.tasks",
    "modules.rag.tasks",
    "modules.world.tasks",
    "modules.writing.tasks",
)


def register_task_handlers() -> None:
    """Import every domain-owned task declaration in deterministic order."""
    for module_name in _TASK_HANDLER_MODULES:
        importlib.import_module(module_name)

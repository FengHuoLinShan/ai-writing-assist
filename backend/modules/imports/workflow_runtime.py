"""Runtime interface for Deep Import phase runners."""

from __future__ import annotations

from typing import Any, Protocol


class DeepImportWorkflowRuntime(Protocol):
    """Explicit phase-runner runtime surface.

    The concrete runtime is `DeepImportWorkflow`. The private method names are
    preserved for compatibility with existing monkeypatch-based tests while
    phase runner constructors stop accepting an untyped owner object.
    """

    def __getattr__(self, name: str) -> Any: ...

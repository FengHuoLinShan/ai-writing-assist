"""Process-local execution-scope markers shared by platform and business code.

Worker/system execution (task queue handlers, recovery, maintenance) runs
without a bound request principal. Business gates may keep that explicit
system identity only inside this scope; anything else without a principal
is an unauthenticated caller and must fail closed.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_system_execution: ContextVar[bool] = ContextVar(
    "system_execution_scope",
    default=False,
)


def is_system_execution() -> bool:
    """Whether the current context is worker/system execution."""
    return _system_execution.get()


@contextmanager
def system_execution_scope() -> Iterator[None]:
    """Mark the current context as worker/system execution.

    Async tasks created inside the scope inherit the marker through their
    copied context; the marker never leaks back into the caller.
    """
    token: Token[bool] = _system_execution.set(True)
    try:
        yield
    finally:
        _system_execution.reset(token)

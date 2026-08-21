"""Compatibility import helper for the one-release owner migration."""

from __future__ import annotations

import importlib
from types import ModuleType


class _CompatibilityModule(ModuleType):
    """Forward compatibility-path monkeypatches to the owner module."""

    def __setattr__(self, name: str, value: object) -> None:
        target = self.__dict__.get("_compat_target")
        if isinstance(target, ModuleType) and not name.startswith("_compat_"):
            setattr(target, name, value)
        super().__setattr__(name, value)


def alias_module(
    public_name: str,
    implementation_name: str,
    *,
    export_module_name: str | None = None,
) -> ModuleType:
    """Expose one implementation through an old import path.

    Copying the implementation namespace into the already-importing wrapper
    keeps both paths on the same classes/functions.  Replacing ``sys.modules``
    from inside a compatibility module leaves the import machinery holding a
    second wrapper object, which makes monkeypatches on the old public path
    miss production consumers.
    """

    implementation = importlib.import_module(implementation_name)
    public_module = importlib.import_module(public_name)
    export_names: set[str] | None = None
    if export_module_name is not None:
        export_module = importlib.import_module(export_module_name)
        export_names = set(getattr(export_module, "__all__", ()))
    for name, value in implementation.__dict__.items():
        if name not in {
            "__name__",
            "__loader__",
            "__package__",
            "__spec__",
            "__path__",
        } and (export_names is None or name in export_names):
            public_module.__dict__[name] = value
    if export_names is not None:
        public_module.__dict__["__all__"] = sorted(export_names)
    public_module.__dict__["_compat_target"] = implementation
    public_module.__class__ = _CompatibilityModule
    return implementation

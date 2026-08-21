"""Context 服务层 — 与旧 services.py 兼容的导出"""

from modules.evidence.compilation.contracts import CompileOptions
from modules.evidence.compilation.services.confirmation_service import (
    ContextConfirmationService,
)
from modules.evidence.compilation.services.context_compiler import (
    SCOPE_LOADERS,
    ContextCompiler,
)
from modules.evidence.compilation.services.snapshot_service import (
    ContextSnapshotService,
    DurableContextSnapshotService,
)

__all__ = [
    "CompileOptions",
    "ContextConfirmationService",
    "ContextSnapshotService",
    "DurableContextSnapshotService",
    "ContextCompiler",
    "SCOPE_LOADERS",
]

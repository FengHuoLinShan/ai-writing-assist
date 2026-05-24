"""
Review 模块 — 结构复查

复查结构化创作结果，输出问题和修改建议。
不改正史，只检查。
"""

from __future__ import annotations

from modules.review.contracts import (
    ReviewReportContract,
    ReviewWarningContract,
)
from modules.review.facade import get_review_report, review_structure_candidate
from modules.review.schemas import ReviewReportResponse

__all__ = [
    "review_structure_candidate",
    "get_review_report",
    "ReviewReportContract",
    "ReviewWarningContract",
    "ReviewReportResponse",
]

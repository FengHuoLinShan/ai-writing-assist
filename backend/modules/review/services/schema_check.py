"""Schema 校验检查"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.review.schemas import ReviewWarning
from modules.review.services.helpers import is_valid_uuid
from modules.review.services.protocol import CheckStrategy


class SchemaCheck(CheckStrategy):
    """检查 1: Schema 校验 — 必填字段、枚举值、UUID 格式"""

    @property
    def name(self) -> str:
        return "schema"

    REQUIRED_FIELDS_MAP: dict[str, list[str]] = {
        "world_structure": ["world_entities", "relationships"],
        "plot_structure": ["plot_threads", "outline_arcs", "chapter_cards"],
        "chapter_cards": ["chapter_index", "chapter_goal", "main_conflict"],
        "memory_update": ["proposal_type", "payload"],
        "entity_candidates": ["name", "entity_type"],
        "geo_structure": ["locations", "edges"],
    }

    ENUM_CHECKS: dict[str, list[str]] = {
        "entity_type": [
            "location", "faction", "item", "event", "rule",
            "power_system", "secret", "legend", "resource", "character",
        ],
        "knowledge_level": [
            "unknown", "rumor", "partial", "full", "false_belief",
        ],
    }

    UUID_FIELDS = ["novel_id", "arc_id", "thread_id"]

    async def check(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        warnings: list[ReviewWarning] = []

        # 推断 target_type
        target_type = candidate_payload.get("target_type", "")
        if not target_type:
            if "world_entities" in candidate_payload:
                target_type = "world_structure"
            elif "plot_threads" in candidate_payload:
                target_type = "plot_structure"
            elif "proposal_type" in candidate_payload:
                target_type = "memory_update"
            elif "locations" in candidate_payload:
                target_type = "geo_structure"

        # 检查必填字段
        required = self.REQUIRED_FIELDS_MAP.get(target_type, [])
        for field in required:
            if field not in candidate_payload:
                warnings.append(
                    ReviewWarning(
                        type="schema",
                        message=f"缺少必填字段: {field}",
                        severity="high",
                        location={"field": field},
                    )
                )

        # 检查 UUID 格式
        for field in self.UUID_FIELDS:
            value = candidate_payload.get(field)
            if value is not None and isinstance(value, str):
                if not is_valid_uuid(value):
                    warnings.append(
                        ReviewWarning(
                            type="schema",
                            message=f"字段 {field} 不是有效的 UUID: {value}",
                            severity="medium",
                            location={"field": field, "value": value},
                        )
                    )

        # 检查枚举值
        for field, valid_values in self.ENUM_CHECKS.items():
            value = candidate_payload.get(field)
            if value is not None and isinstance(value, str):
                if value not in valid_values:
                    warnings.append(
                        ReviewWarning(
                            type="schema",
                            message=f"字段 {field} 的值 '{value}' 不在合法范围内",
                            severity="medium",
                            location={"field": field, "value": value},
                        )
                    )

        # 检查 chapter_index
        chapter_index = candidate_payload.get("chapter_index")
        if chapter_index is not None:
            if not isinstance(chapter_index, int) or chapter_index < 1:
                warnings.append(
                    ReviewWarning(
                        type="schema",
                        message=f"chapter_index 必须为正整数，收到: {chapter_index}",
                        severity="high",
                        location={"field": "chapter_index", "value": chapter_index},
                    )
                )

        return warnings

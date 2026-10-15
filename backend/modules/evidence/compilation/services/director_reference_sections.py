"""Render the advisory-only director-reference dimension into context IR."""

from __future__ import annotations

import json

from infrastructure.llm.token_estimation import estimate_token_count
from infrastructure.stable_hash import stable_hash
from modules.evidence.compilation.contracts import StructureContextBundle
from modules.evidence.compilation.services.compiled_context import (
    ContextItem,
    ContextSection,
    Tier,
)


class DirectorReferenceSectionBuilder:
    @staticmethod
    def build(bundle: StructureContextBundle) -> list[ContextSection]:
        brief = bundle.director_reference_brief or {}
        items: list[ContextItem] = []
        for raw in brief.get("items") or []:
            if not isinstance(raw, dict):
                continue
            reference_id = str(raw.get("reference_id") or "")
            name = str(raw.get("name") or "导演参考")
            content_copy = raw.get("content_copy") or {}
            if not reference_id or not content_copy:
                continue
            payload = {
                "name": name,
                "angle": content_copy.get("angle"),
                "performances": content_copy.get("performances") or [],
                "materials": content_copy.get("materials") or [],
                "annotation": raw.get("annotation") or "",
                "warnings": raw.get("warnings") or [],
                "source_changed": bool(raw.get("source_changed")),
                "source_deleted": bool(raw.get("source_deleted")),
                "advisory_only": True,
                "adoption_status": "not_adopted",
            }
            content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            source = {
                "type": "director_reference",
                "id": reference_id,
                "label": name,
                "status": "source_changed" if raw.get("source_changed") else "saved_copy",
                "content_hash": stable_hash(content),
                "source_basis_hash": raw.get("source_basis_hash"),
                "source_round_id": raw.get("source_round_id"),
                "source_deleted": bool(raw.get("source_deleted")),
                "advisory_only": True,
                "adoption_status": "not_adopted",
            }
            items.append(
                ContextItem(
                    key=f"director_reference:{reference_id}",
                    content=content,
                    token_count=estimate_token_count(content),
                    title=name,
                    preview=(content_copy.get("angle") or {}).get("label") or name,
                    status=source["status"],
                    activation_reason=(
                        "作者显式选择的 Scene 导演参考副本；"
                        + "仅作建议，不是正史或正文约束"
                    ),
                    source=source,
                    selection_ref={
                        "kind": "target",
                        "target_ref": {
                            "target_type": "director_reference",
                            "target_id": reference_id,
                            "target_path": "",
                        },
                    },
                    can_exclude=True,
                )
            )
        if not items:
            return []
        content = "\n".join(item.content for item in items)
        section = ContextSection(
            key="director_reference",
            tier=Tier.P3,
            content=content,
            token_count=estimate_token_count(content),
            title="场景导演参考",
            preview=f"已选择 {len(items)} 份作者保存的表演/素材参考副本",
            status="advisory",
            activation_reason=(
                "作者本次显式选择；按独立参考维度使用，"
                + "不替代 Scene 正史、采用剧本或正文"
            ),
            sources=[item.source for item in items],
            can_exclude=True,
            retrieval_metadata={
                "scene_id": brief.get("scene_id"),
                "reference_ids": [item.source["id"] for item in items],
                "omitted": list(brief.get("omitted") or []),
                "warnings": list(brief.get("warnings") or []),
                "advisory_only": True,
            },
            items=items,
        )
        return [section]

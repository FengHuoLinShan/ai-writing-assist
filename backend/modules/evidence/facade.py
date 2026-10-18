"""Single stable cross-module facade for evidence indexing and compilation."""

from core.container import get
from core.service_keys import WORLD_READ_ASSISTANT_FOCUS
from modules.evidence.compilation.facade import *  # noqa: F403
from modules.evidence.indexing.facade import *  # noqa: F403
from modules.evidence.team_projection import (
    project_team_artifact as project_team_artifact,
)


def restrict_object_dossier_brief(brief: dict, compiled) -> dict:
    """Keep only complete, selected dossier items from a materialized confirmation."""
    from modules.evidence.compilation.services.object_dossier_sections import (
        ObjectDossierSectionBuilder,
    )

    return ObjectDossierSectionBuilder.restrict_brief(brief, compiled)


def _render_author_world_focus(material: dict) -> str:
    content = material.get("content") or {}
    lines = [
        str(material.get("title") or "作者指定的世界资料"),
        "作者视角资料；不证明任何角色已知。",
    ]
    kind = material.get("kind")
    if kind == "entity":
        for label, field in (
            ("概述", "summary"),
            ("公开信息", "public_info"),
            ("作者掌握的设定", "hidden_truth"),
        ):
            value = content.get(field)
            if value:
                lines.append(f"{label}：{value}")
    elif kind == "dossier_entry":
        if content.get("facing_label"):
            lines.append(f"面向：{content['facing_label']}")
        if content.get("content"):
            lines.append(f"内容：{content['content']}")
        if content.get("tags"):
            lines.append(f"标签：{'、'.join(content['tags'])}")
        visibility = {"public": "公开", "secret": "作者秘密"}.get(
            content.get("visibility")
        )
        if visibility:
            lines.append(f"可见范围：{visibility}")
    elif kind == "relation":
        if content.get("source_name") and content.get("target_name"):
            lines.append(f"关系方向：{content['source_name']} → {content['target_name']}")
        relation_type = content.get("relation_type_label") or content.get("relation_type")
        if relation_type:
            lines.append(f"关系：{relation_type}")
        category = {
            "state": "状态",
            "social": "社会关系",
            "spatial": "空间",
            "causal": "因果",
            "temporal": "时间",
            "epistemic": "认知",
            "intentional": "意图",
        }.get(content.get("relation_kind"), "尚未分类")
        lines.append(f"类别：{category}")
        if content.get("strength") is not None:
            lines.append(f"关系强度：{content['strength']:g}")
        status = {"canonical": "已采用", "candidate": "待确认", "draft": "草稿"}.get(
            content.get("status"), "待核实"
        )
        lines.append(f"状态：{status}")
        validity = content.get("validity") or {}
        bounds = []
        for key, prefix, suffix in (("start", "从", "起"), ("end", "至", "止")):
            anchor = validity.get(key)
            if anchor:
                label = {"scene": "指定场景", "chapter": "指定章节"}[anchor["kind"]]
                bounds.append(f"{prefix}{label}{suffix}")
        lines.append(f"生效范围：{'，'.join(bounds) if bounds else '未限定起止'}")
        if bounds:
            lines.append("具体起止位置请查看原关系；此摘录不代表当前场景仍然有效。")
        if content.get("description"):
            lines.append(f"说明：{content['description']}")
        if content.get("quote"):
            lines.append(f"原文依据：{content['quote']}")
    return "\n".join(lines)


async def read_assistant_world_focus(db, *, novel_id: str, focus_ref: dict) -> dict:
    """Materialize one exact, current author-selected World source as Evidence."""
    material = await get(WORLD_READ_ASSISTANT_FOCUS)(db, novel_id, focus_ref)
    return {
        "source_kind": "world_focus",
        "kind": material["kind"],
        "title": material["title"],
        "perspective": "author",
        "content": material["content"],
        "snippet": _render_author_world_focus(material),
        "warning": "作者视角资料；不证明任何角色已知。",
    }


async def retrieve_focused_evidence(db, request, *, llm_client=None, before_llm=None):
    """Read the next scoped root/one-hop evidence slice; never adopt assets."""
    from modules.evidence.compilation.services.focused_evidence import (
        FocusedEvidenceService,
    )

    service = FocusedEvidenceService()
    result = await service.retrieve(
        db, request, llm_client=llm_client, before_llm=before_llm
    )
    await service.revalidate(db, request, result)
    return result


async def revalidate_focused_evidence(db, request, result):
    """Recheck the frozen source and selection before a consumer uses this slice."""
    from modules.evidence.compilation.services.focused_evidence import (
        FocusedEvidenceService,
    )

    return await FocusedEvidenceService().revalidate(db, request, result)


async def read_review_resolution_sources(db, **kwargs):
    from modules.evidence.compilation.services.review_resolution_sources import (
        read_sources,
    )

    return await read_sources(db, **kwargs)


async def read_review_resolution_chapters(db, **kwargs):
    from modules.evidence.compilation.services.review_resolution_sources import (
        read_chapters,
    )

    return await read_chapters(db, **kwargs)


async def read_review_resolution_evidence(db, *, novel_id, task_id, visibility):
    from core.errors import NotFoundError
    from modules.imports.facade import inspect_review_resolution

    if visibility.mode != "author":
        raise NotFoundError("整理结果仅对作者开放")
    return await inspect_review_resolution(
        db, novel_id=novel_id, task_id=task_id, cutoff_chapter=visibility.cutoff_chapter
    )


def build_group_audit_request(**kwargs):
    from modules.evidence.compilation.knowledge.group import (
        build_group_audit_request as build,
    )

    return build(**kwargs)


def materialize_group_audit(**kwargs):
    from modules.evidence.compilation.knowledge.group import (
        materialize_group_audit as materialize,
    )

    return materialize(**kwargs)

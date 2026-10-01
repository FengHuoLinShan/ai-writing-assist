"""AI 用量诊断的能力名映射必须覆盖真实能力编号。"""

from __future__ import annotations

from modules.evidence.compilation.knowledge.policies import CAPABILITY_REGISTRY
from modules.project.ai_usage import _capability_label


def test_common_capability_ids_resolve_to_author_labels() -> None:
    assert _capability_label("writing.generate") == "AI 写作"
    assert _capability_label("writing.semantic_review") == "正文独立审查"
    assert _capability_label("writing.targeted_revision") == "定向返修"
    assert _capability_label("writing.comment_revision") == "批注改写"
    # 前缀回退：冲突检查的两个子能力共享命名空间标签
    assert _capability_label("writing.conflict_check.ai_review") == "设定冲突检查"
    assert _capability_label("writing.conflict_check.ai_suggestion") == "设定冲突检查"
    assert _capability_label("story.outline.analyze") == "大纲整理"
    assert _capability_label("world.generation.suggestion") == "世界观生成"
    assert _capability_label("infrastructure.rag_index_chapter") == "资料索引"
    assert _capability_label("interaction.forecast") == "读者互动"


def test_unknown_capability_still_shows_raw_id() -> None:
    assert _capability_label("totally.unknown") == "其他 AI 能力（totally.unknown）"
    assert _capability_label("") == "其他 AI 能力（）"


def test_every_registered_capability_has_a_label() -> None:
    """注册表与绑定表里的真实能力编号不得落入"其他 AI 能力"回退。

    之前的映射表用了虚构编号（如 writing.generation），导致最常用的
    写作能力在界面上显示内部 id。
    """
    from tools.prompt_contracts.capability_bindings import CAPABILITY_BINDINGS

    registered = set(CAPABILITY_REGISTRY)
    for capability_ids in CAPABILITY_BINDINGS.values():
        registered.update(capability_ids)
    unlabeled = sorted(
        capability_id
        for capability_id in registered
        if _capability_label(capability_id).startswith("其他 AI 能力")
    )
    assert unlabeled == []

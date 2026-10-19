"""确定性探索尺度推荐（P0 §8）：无模型调用，规则钉死可单测。

输入是作者当轮的问题/提示/选区与项目是否已有内容；输出 ``(scale, reason)``。
推荐只决定默认尺度，作者可在预览里覆盖。
"""

from __future__ import annotations

_SCENE_HINTS = ("回应", "台词", "他说", "她说", "对白", "一句话", "开口")
_EVENT_HINTS = ("为什么", "缺口", "矛盾", "说不通", "漏洞", "解释", "诊断", "补桥")
_SANDBOX_HINTS = ("如果", "会不会", "影响", "假设", "会怎样", "推演", "后果")

SCENE_LINE_SCALE = "scene_line"
EVENT_SCALE = "event"
SANDBOX_SCALE = "sandbox"


def recommend_exploration_scale(
    question_text: str,
    task_hint: str = "",
    *,
    has_selection: bool = False,
    project_has_content: bool = True,
) -> tuple[str, str]:
    """按确定性关键词与选区信号推荐观察尺度；同分时按 选区>场景>事件>沙盘。"""

    text = " ".join([str(question_text or ""), str(task_hint or "")])
    if has_selection:
        return (
            SCENE_LINE_SCALE,
            "你在正文中选中了片段，先就这段给一句角色回应最直接",
        )
    if any(hint in text for hint in _SCENE_HINTS):
        return (SCENE_LINE_SCALE, "问题在问某个角色如何回应，适合先试一句对白")
    if any(hint in text for hint in _EVENT_HINTS):
        return (EVENT_SCALE, "问题指向因果缺口或矛盾，先做事件诊断")
    if any(hint in text for hint in _SANDBOX_HINTS):
        return (SANDBOX_SCALE, "假设式问题适合先推一条影响链")
    if not project_has_content:
        return (
            SANDBOX_SCALE,
            "项目还没有正文，先从沙盘假设开始，不动既有情节",
        )
    return (
        EVENT_SCALE,
        "没有命中明确信号，默认先诊断问题里的因果是否完整",
    )


__all__ = [
    "EVENT_SCALE",
    "SANDBOX_SCALE",
    "SCENE_LINE_SCALE",
    "recommend_exploration_scale",
]

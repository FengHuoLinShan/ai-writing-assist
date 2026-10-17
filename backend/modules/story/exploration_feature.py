"""Director multi-scale exploration is opt-in until its evaluation is accepted.

对齐 ``director_feature.py``：历史与比较读取不挂本 gate（关闭后仍可读），
执行类端点与两个 worker 必须先调用本函数失败关闭。
"""

from core.config import get_settings
from core.errors import DomainError


def require_story_exploration_enabled() -> None:
    if not get_settings().story_exploration_enabled:
        raise DomainError(
            "独立探索尚未开启",
            code="story_exploration_disabled",
            status_code=503,
        )

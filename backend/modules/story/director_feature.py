"""The Scene Director is opt-in until its quality evaluation is accepted."""

from core.config import get_settings
from core.errors import DomainError


def require_scene_director_enabled() -> None:
    if not get_settings().story_scene_director_enabled:
        raise DomainError(
            "场景导演尚未开启",
            code="scene_director_disabled",
            status_code=503,
        )

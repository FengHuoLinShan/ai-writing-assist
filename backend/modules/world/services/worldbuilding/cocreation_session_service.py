"""World compatibility entry; discussions are persisted by Assistant only."""

from modules.assistant.facade import (
    AssistantSessionService as WorldCocreationSessionService,
)

__all__ = ["WorldCocreationSessionService"]

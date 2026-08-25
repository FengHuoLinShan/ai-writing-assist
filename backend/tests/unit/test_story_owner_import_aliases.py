"""One-release Story import aliases must expose the canonical implementation."""

from modules.memory import facade as legacy_memory_facade
from modules.memory import models as legacy_memory_models
from modules.outline import facade as legacy_outline_facade
from modules.outline import models as legacy_outline_models
from modules.story.continuity import facade as continuity_facade
from modules.story.continuity import models as continuity_models
from modules.story.outline_state import facade as outline_state_facade
from modules.story.outline_state import models as outline_state_models


def test_story_import_aliases_reexport_canonical_owners() -> None:
    assert legacy_outline_facade.get_scene is outline_state_facade.get_scene
    assert legacy_outline_models.Scene is outline_state_models.Scene
    assert legacy_memory_facade.capture_snapshot is continuity_facade.capture_snapshot
    assert legacy_memory_models.DeltaLog is continuity_models.DeltaLog

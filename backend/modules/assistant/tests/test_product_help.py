from modules.assistant.product_help import PRODUCT_HELP
from modules.assistant.schemas import CONTROLLED_DESTINATIONS, AssistantAnswer


def test_versioned_help_uses_only_actual_controlled_navigation_and_conditions():
    assert PRODUCT_HELP["version"] == "author-workspaces-2026-10-18.1"
    topics = PRODUCT_HELP["items"]
    assert len({item["id"] for item in topics}) == len(topics)
    assert {item["id"] for item in topics} >= {
        "find",
        "dossier",
        "relations",
        "adopt",
        "timing",
        "recovery",
    }
    for item in topics:
        assert item["destination"] in CONTROLLED_DESTINATIONS
        assert item["steps"] and item["condition"]
    AssistantAnswer(answer="请先比较", next_steps=["world_objects", "world_relations"])

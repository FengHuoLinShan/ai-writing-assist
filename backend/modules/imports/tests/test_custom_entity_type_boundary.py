import pytest
from pydantic import ValidationError

from modules.imports.llm_schemas import ExtractedEntity, Phase2WorldObject
from modules.world.services.core.entity_types import ENTITY_TYPE_MAP


@pytest.mark.parametrize("schema", [ExtractedEntity, Phase2WorldObject])
def test_deep_import_ai_entity_types_remain_system_only(schema) -> None:
    with pytest.raises(ValidationError):
        schema(name="月廷", entity_type="宗教/神祇")


@pytest.mark.parametrize("schema", [ExtractedEntity, Phase2WorldObject])
def test_deep_import_ai_entity_type_aliases_are_normalized(schema) -> None:
    assert schema(name="月廷", entity_type="组织").entity_type == "organization"


@pytest.mark.parametrize("schema", [ExtractedEntity, Phase2WorldObject])
@pytest.mark.parametrize(
    ("alias", "expected"),
    [*ENTITY_TYPE_MAP.items(), ("character_ref", "character")],
)
def test_deep_import_ai_aliases_match_frozen_world_catalog(
    schema,
    alias: str,
    expected: str,
) -> None:
    assert schema(name="契约对象", entity_type=alias).entity_type == expected

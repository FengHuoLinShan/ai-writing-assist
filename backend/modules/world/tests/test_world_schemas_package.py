"""守护 world schemas 拆包后的对外契约。

FastAPI/pydantic 对跨模块短名冲突的 Pydantic 模型用「定义模块路径 + 类名」
生成 OpenAPI 组件名；world 的 EventUpdate / EventListResponse 与
modules.local_agent.api.EventUpdate、modules.story.continuity.schemas.EventListResponse
短名冲突，类体内固定 ``__module__`` 以保持组件名与拆包前一致。
"""

from __future__ import annotations

from modules.world.schemas import EventListResponse, EventUpdate


def test_event_schema_module_pins_stay_stable() -> None:
    assert EventUpdate.__module__ == "modules.world.schemas"
    assert EventListResponse.__module__ == "modules.world.schemas"
    assert EventUpdate.__pydantic_core_schema__["ref"].startswith(
        "modules.world.schemas.EventUpdate"
    )
    assert EventListResponse.__pydantic_core_schema__["ref"].startswith(
        "modules.world.schemas.EventListResponse"
    )


def test_schemas_package_public_names_reexported() -> None:
    # 薄再导出层：原公开名必须全部可从 modules.world.schemas 导入。
    for name in (
        "CoreEntityResponse",
        "WorldBiblePageDraftResponse",
        "WorldGenerationChatRequest",
        "CreationSuggestionResponse",
        "RelationKind",
    ):
        assert hasattr(__import__("modules.world.schemas", fromlist=[name]), name)

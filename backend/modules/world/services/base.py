"""BaseCRUDService — 5 个 CRUD 服务的共享骨架 (entity / event /
entity_relation / character / character_knowledge)

ADR-0002: 4 typevar 表达类型差异, 4 ClassVar 注入实现, 不上 port。
`EntityRevisionService` opt-in, 不继承。

实现已提升至 core.crud。本文件保留为 re-export, 保持 world/ 模块的 import 路径不变。
"""

from core.crud import (  # noqa: F401
    CreateT,
    CrudService,
    ModelT,
    ResponseT,
    UpdateT,
    _CrudRepo,
)

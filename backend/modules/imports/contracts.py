"""
Import 对外契约

定义其他模块可以安全依赖的导入模块数据接口。
"""


# facade 返回类型（Pydantic schema），供跨模块导入使用
from modules.imports.schemas import ImportResponse  # noqa: F401 — facade.import_file 返回

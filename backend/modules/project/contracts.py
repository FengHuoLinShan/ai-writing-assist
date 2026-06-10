"""
Project 对外契约

定义其他模块可以安全依赖的项目接口和数据类。
仅可导入 contracts.py 和 facade.py。
"""

from __future__ import annotations

from modules.project.schemas import ProjectContext  # noqa: F401

"""
Import Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.schemas import ImportResponse
from modules.imports.services import ImportService

_service = ImportService()


async def import_file(
    db: AsyncSession,
    novel_id: str,
    file_name: str,
    file_content: bytes,
) -> ImportResponse:
    """导入小说文件

    供其他模块（如生成中心、命令行工具）调用导入能力。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        file_name: 原始文件名
        file_content: 文件二进制内容

    Returns:
        ImportResponse — 导入结果
    """
    return await _service.upload_and_import(db, novel_id, file_name, file_content)

"""表格迁移会话服务（计划 §4 L4）— L4 车道实现。

上传经 require_active_project + asyncio.to_thread(parse_spreadsheet_file) + classify；
每个请求按 (id, novel_id, owner) 加载会话；mapping/decisions 带 revision CAS；
apply 在同一事务内重算 preview、校验 hash、world.apply、story.apply、mark_applied。
"""

from __future__ import annotations

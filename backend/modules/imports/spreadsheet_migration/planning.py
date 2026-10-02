"""按 mapping 把 rows 转成 world/story 迁移请求（计划 §4 L4）— L4 车道实现。

文件内同名同类型合并、item_key 确定性生成、source_hash 为行单元格 sha256、
AI 条目合并（仅已通过审查且作者接受的条目）、AI 未覆盖行回落规则映射。
"""

from __future__ import annotations

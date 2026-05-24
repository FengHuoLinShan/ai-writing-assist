"""
Memory — 长期记忆模块

维护小说推进过程中的状态变化历史。
AI 只生成 proposal，用户确认后写入 memory_records。
"""

from __future__ import annotations

"""表格迁移共享常量与冻结的字面量契约（计划 §3.1）。"""

from __future__ import annotations

from typing import Literal

MIGRATION_SOURCE = "spreadsheet_migration"
SPREADSHEET_EXTENSIONS = frozenset({".xlsx", ".csv"})

MAX_FILES = 5
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_SHEETS_PER_FILE = 20
MAX_ROWS_PER_SHEET = 5000
MAX_COLUMNS = 60
MAX_CELL_CHARS = 20_000
MAX_SESSION_CHARS = 2_000_000
MAX_APPLY_ITEMS = 1500
MAX_RELATIONS = 3000

XLSX_MAX_MEMBERS = 500
XLSX_MAX_UNCOMPRESSED = 60 * 1024 * 1024

AI_PACKET_CHARS = 24_000
AI_MAX_PACKETS = 24

SheetKind = Literal[
    "characters",
    "world_objects",
    "relations",
    "chapter_outline",
    "arcs",
    "threads",
    "foreshadowing",
    "story_outline",
    "freeform_outline",
    "skip",
]

ColumnTarget = Literal[
    # world
    "name",
    "aliases",
    "entity_type",
    "summary",
    "public_info",
    "hidden_truth",
    "author_note",
    "ignore",
    # character
    "role",
    "appearance",
    "personality",
    "desire",
    "fear",
    "weakness",
    "current_goal",
    "current_state",
    "stance",
    "voice_style",
    "relationship_summary",
    # relation
    "source_name",
    "target_name",
    "relation_type",
    "relation_description",
    "direction",
    # story
    "chapter_ref",
    "title",
    "content",
    "core_conflict",
    "emotional_beat",
    "must_not_happen",
    "pov_name",
    "chapter_start",
    "chapter_end",
    "thread_type",
    "seed_chapter",
    "payoff_chapter",
    "reinforce_chapters",
    "surface_meaning",
    "hidden_meaning",
    "related_names",
    "arc_goal",
    "climax",
    "result",
    "next_hook",
]

# 各表类型可用的列目标（计划 §3.1）：
# - characters / world_objects：world 组 + character 组（character 组只对人物有效）；
# - relations：relation 组；
# - 其余故事表：story 组 + ignore / author_note。
WORLD_COLUMN_TARGETS = frozenset({
    "name",
    "aliases",
    "entity_type",
    "summary",
    "public_info",
    "hidden_truth",
    "author_note",
    "ignore",
})
CHARACTER_COLUMN_TARGETS = frozenset({
    "role",
    "appearance",
    "personality",
    "desire",
    "fear",
    "weakness",
    "current_goal",
    "current_state",
    "stance",
    "voice_style",
    "relationship_summary",
})
RELATION_COLUMN_TARGETS = frozenset({
    "source_name",
    "target_name",
    "relation_type",
    "relation_description",
    "direction",
})
STORY_COLUMN_TARGETS = frozenset({
    "chapter_ref",
    "title",
    "content",
    "core_conflict",
    "emotional_beat",
    "must_not_happen",
    "pov_name",
    "chapter_start",
    "chapter_end",
    "thread_type",
    "seed_chapter",
    "payoff_chapter",
    "reinforce_chapters",
    "surface_meaning",
    "hidden_meaning",
    "related_names",
    "arc_goal",
    "climax",
    "result",
    "next_hook",
    "author_note",
    "ignore",
})

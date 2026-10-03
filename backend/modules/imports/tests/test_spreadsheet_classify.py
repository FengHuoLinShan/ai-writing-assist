"""表格迁移识别测试 — 表头行定位、表类型识别、列映射建议与同义词规则。"""

from __future__ import annotations

import pytest

from modules.imports.spreadsheet_migration.classify import (
    classify_sheet,
    detect_header_row,
)
from modules.imports.spreadsheet_migration.parsing import ParsedSheet
from modules.imports.spreadsheet_migration.synonyms import (
    guess_relation_kind,
    normalize_entity_type,
    parse_chapter_ref,
    split_aliases,
)


def _sheet(
    name: str,
    rows: list[list[str]],
    *,
    hidden: bool = False,
) -> ParsedSheet:
    return ParsedSheet(
        sheet_key="f0s0",
        file_key="f0",
        name=name,
        hidden=hidden,
        rows=rows,
    )


def _targets(suggestion) -> dict[str, str]:
    return {column.column_key: column.target for column in suggestion.columns}


# ============================================================
# detect_header_row
# ============================================================


class TestDetectHeaderRow:
    def test_merged_title_row_skipped(self):
        rows = [
            ["人物设定总表（第一卷）", "", ""],
            ["姓名", "性格", "简介"],
            ["张三", "沉稳", "主角"],
        ]
        assert detect_header_row(rows) == 1

    def test_data_rows_do_not_beat_header(self):
        rows = [
            ["姓名", "别名", "简介"],
            ["张三丰·武当掌门·太极拳创始人之类很长的人名", "阿三", "一段很长的简介"],
            ["李四", "四儿", "另一段很长的简介"],
        ]
        assert detect_header_row(rows) == 0

    def test_empty_leading_rows_skipped(self):
        rows = [["", ""], ["", ""], ["名称", "类型"], ["灵气", "设定"]]
        assert detect_header_row(rows) == 2

    def test_defaults_to_first_row(self):
        assert detect_header_row([]) == 0
        assert detect_header_row([["随便什么"]]) == 0


# ============================================================
# classify_sheet：表类型识别
# ============================================================


class TestClassifySheetKind:
    def test_characters_by_name_and_columns(self):
        suggestion = classify_sheet(
            _sheet(
                "人物",
                [["姓名", "别名", "性格", "简介"], ["张三", "阿三", "沉稳", "主角"]],
            )
        )
        assert suggestion.kind == "characters"
        assert suggestion.header_row == 0
        assert _targets(suggestion) == {
            "c0": "name",
            "c1": "aliases",
            "c2": "personality",
            "c3": "summary",
        }

    def test_characters_by_columns_without_name_hint(self):
        suggestion = classify_sheet(
            _sheet("Sheet1", [["姓名", "外貌", "性格"], ["张三", "高", "沉稳"]])
        )
        assert suggestion.kind == "characters"

    def test_naming_confusion_prefers_relations(self):
        suggestion = classify_sheet(
            _sheet("人物关系", [["人物", "关系", "人物2"], ["张三", "师徒", "李四"]])
        )
        assert suggestion.kind == "relations"
        assert _targets(suggestion) == {
            "c0": "source_name",
            "c1": "relation_type",
            "c2": "target_name",
        }

    def test_relations_by_two_name_columns_and_relation_column(self):
        suggestion = classify_sheet(
            _sheet("Sheet1", [["名称", "关系类型", "对方"], ["张三", "师徒", "李四"]])
        )
        assert suggestion.kind == "relations"
        assert _targets(suggestion) == {
            "c0": "source_name",
            "c1": "relation_type",
            "c2": "target_name",
        }

    def test_matrix_relations_detected(self):
        matrix = [
            ["", "张三", "李四", "王五"],
            ["张三", "", "敌对", "盟友"],
            ["李四", "敌对", "", "师徒"],
            ["王五", "盟友", "", ""],
        ]
        suggestion = classify_sheet(_sheet("关系一览", matrix))
        assert suggestion.kind == "relations"

    def test_world_objects_setting_sheet(self):
        suggestion = classify_sheet(
            _sheet("设定", [["名称", "类型", "简介"], ["灵气", "设定", "修行根基"]])
        )
        assert suggestion.kind == "world_objects"
        assert _targets(suggestion) == {
            "c0": "name",
            "c1": "entity_type",
            "c2": "summary",
        }

    def test_world_objects_character_fields_rerouted_to_author_note(self):
        suggestion = classify_sheet(
            _sheet("地点", [["名称", "性格", "外貌"], ["武当山", "庄严", "巍峨"]])
        )
        assert suggestion.kind == "world_objects"
        targets = _targets(suggestion)
        assert targets["c0"] == "name"
        assert targets["c1"] == "author_note"
        assert targets["c2"] == "author_note"

    def test_chapter_outline_by_name(self):
        suggestion = classify_sheet(
            _sheet("细纲", [["章号", "内容", "核心冲突"], ["3", "开端", "冲突A"]])
        )
        assert suggestion.kind == "chapter_outline"
        assert _targets(suggestion) == {
            "c0": "chapter_ref",
            "c1": "content",
            "c2": "core_conflict",
        }

    def test_chapter_outline_by_chapter_and_content_columns(self):
        suggestion = classify_sheet(_sheet("Sheet1", [["章", "内容"], ["1", "事件"]]))
        assert suggestion.kind == "chapter_outline"

    @pytest.mark.parametrize(
        ("name", "kind"),
        [
            ("卷纲", "arcs"),
            ("分卷规划", "arcs"),
            ("主线", "threads"),
            ("支线", "threads"),
            ("伏笔", "foreshadowing"),
            ("埋线", "foreshadowing"),
            ("总纲", "story_outline"),
            ("故事大纲", "story_outline"),
        ],
    )
    def test_story_kinds_by_sheet_name(self, name: str, kind: str):
        suggestion = classify_sheet(_sheet(name, [["标题", "内容"], ["x", "y"]]))
        assert suggestion.kind == kind

    def test_arc_columns_mapped(self):
        suggestion = classify_sheet(
            _sheet("卷纲", [["卷目标", "高潮", "结果"], ["夺宝", "大战", "胜利"]])
        )
        assert _targets(suggestion) == {
            "c0": "arc_goal",
            "c1": "climax",
            "c2": "result",
        }

    def test_foreshadowing_columns_mapped(self):
        suggestion = classify_sheet(
            _sheet(
                "伏笔",
                [["表面", "深层", "埋设章", "回收章"], ["a", "b", "3", "10"]],
            )
        )
        assert _targets(suggestion) == {
            "c0": "surface_meaning",
            "c1": "hidden_meaning",
            "c2": "seed_chapter",
            "c3": "payoff_chapter",
        }

    @pytest.mark.parametrize("name", ["时间线", "字数记录", "写作计划"])
    def test_skip_by_sheet_name(self, name: str):
        suggestion = classify_sheet(_sheet(name, [["时间", "事件"], ["1", "x"]]))
        assert suggestion.kind == "skip"

    def test_hidden_sheet_skipped(self):
        suggestion = classify_sheet(_sheet("人物", [["姓名"], ["张三"]], hidden=True))
        assert suggestion.kind == "skip"

    def test_freeform_outline_by_long_content(self):
        rows = [["想法"], ["这是一个很长的自由文本大纲" * 10]]
        suggestion = classify_sheet(_sheet("灵感", rows))
        assert suggestion.kind == "freeform_outline"

    def test_unknown_table_skipped(self):
        suggestion = classify_sheet(_sheet("Sheet1", [["列A", "列B"], ["1", "2"]]))
        assert suggestion.kind == "skip"

    def test_empty_sheet_skipped(self):
        suggestion = classify_sheet(_sheet("空表", []))
        assert suggestion.kind == "skip"
        assert suggestion.header_row == 0

    def test_unrecognized_column_goes_to_author_note(self):
        suggestion = classify_sheet(
            _sheet("人物", [["姓名", "口头禅", "神秘列"], ["张三", "哼", "？"]])
        )
        targets = _targets(suggestion)
        assert targets["c0"] == "name"
        assert targets["c1"] == "voice_style"
        assert targets["c2"] == "author_note"

    def test_explicit_header_row_overrides_detection(self):
        suggestion = classify_sheet(
            _sheet(
                "人物",
                [
                    ["人物设定总表", "", ""],
                    ["姓名", "性格", "简介"],
                    ["张三", "沉稳", "主角"],
                ],
            ),
            header_row=1,
        )
        assert suggestion.header_row == 1
        assert _targets(suggestion) == {
            "c0": "name",
            "c1": "personality",
            "c2": "summary",
        }


class TestClassifySheetLengthRerouting:
    def test_overlong_summary_rerouted_to_author_note(self):
        suggestion = classify_sheet(
            _sheet(
                "人物",
                [["姓名", "简介"], ["张三", "超" * 5001]],
            )
        )
        assert _targets(suggestion)["c1"] == "author_note"

    def test_overlong_role_rerouted_to_author_note(self):
        suggestion = classify_sheet(
            _sheet("人物", [["姓名", "身份"], ["张三", "衔" * 65]])
        )
        assert _targets(suggestion)["c1"] == "author_note"

    def test_normal_summary_stays_summary(self):
        suggestion = classify_sheet(
            _sheet("人物", [["姓名", "简介"], ["张三", "主角，武当弟子"]])
        )
        assert _targets(suggestion)["c1"] == "summary"


# ============================================================
# synonyms：实体类型
# ============================================================


class TestNormalizeEntityType:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("设定", "concept"),
            ("词条", "concept"),
            ("名词", "concept"),
            ("术语", "concept"),
            ("法宝", "item"),
            ("装备", "item"),
            ("门派", "faction"),
            ("宗门", "faction"),
            ("功法", "skill"),
            ("境界", "power_system"),
            ("修炼体系", "power_system"),
            ("人物", "character"),
            ("地点", "location"),
            ("其他", "other"),
            ("御剑术", "御剑术"),
            ("Custom Type", "custom type"),
        ],
    )
    def test_mapping(self, label: str, expected: str):
        assert normalize_entity_type(label) == expected

    def test_setting_overrides_world_secret_mapping(self):
        """「设定」覆盖 ENTITY_TYPE_MAP["设定"]="secret"，归为 concept。"""
        from modules.world.services.core.entity_types import ENTITY_TYPE_MAP

        assert ENTITY_TYPE_MAP["设定"] == "secret"
        assert normalize_entity_type("设定") == "concept"

    def test_blank_label_returns_empty(self):
        assert normalize_entity_type("") == ""
        assert normalize_entity_type("   ") == ""


# ============================================================
# synonyms：别名拆分
# ============================================================


class TestSplitAliases:
    def test_splits_on_all_separators(self):
        assert split_aliases("阿三、张三丰, 小张；张郎/张老大|老张\n张哥") == [
            "阿三",
            "张三丰",
            "小张",
            "张郎",
            "张老大",
            "老张",
            "张哥",
        ]

    def test_deduplicates_preserving_order(self):
        assert split_aliases("张三、阿三、张三") == ["张三", "阿三"]

    def test_empty_and_blank(self):
        assert split_aliases("") == []
        assert split_aliases("  \n ") == []


# ============================================================
# synonyms：章号解析
# ============================================================


class TestParseChapterRef:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("第3章", (3, 3)),
            ("第三章", (3, 3)),
            ("第 3 章", (3, 3)),
            ("第12章 开始", None),  # 带标题文本不解析
            ("3", (3, 3)),
            ("十二", (12, 12)),
            ("3-5", (3, 5)),
            ("第3-5章", (3, 5)),
            ("第3章-第5章", (3, 5)),
            ("第三章至第五章", (3, 5)),
            ("第1到3章", (1, 3)),
            ("第一千零一章", (1001, 1001)),
            ("第两百章", (200, 200)),
            ("", None),
            ("序章", None),
            ("第0章", None),
            ("5-3", None),
            ("随便", None),
        ],
    )
    def test_parse(self, text: str, expected):
        assert parse_chapter_ref(text) == expected


# ============================================================
# synonyms：关系种类
# ============================================================


class TestGuessRelationKind:
    @pytest.mark.parametrize(
        ("relation_type", "expected_kind"),
        [
            ("师徒", "social"),
            ("父子", "social"),
            ("敌人", "social"),
            ("恋人", "social"),
            ("位于", "spatial"),
            ("坐落于", "spatial"),
            ("导致", "causal"),
            ("引发", "causal"),
            ("知道", "epistemic"),
            ("隐瞒", "epistemic"),
            ("追杀", "intentional"),
            ("保护", "intentional"),
            ("效忠", "intentional"),
            ("持有", "state"),
            ("隶属于", "state"),
            ("继任", "temporal"),
        ],
    )
    def test_keyword_match_is_not_guessed(self, relation_type: str, expected_kind: str):
        kind, guessed = guess_relation_kind(relation_type, both_characters=True)
        assert kind == expected_kind
        assert guessed is False

    def test_fallback_both_characters_is_social_guessed(self):
        assert guess_relation_kind("？？", both_characters=True) == ("social", True)

    def test_fallback_otherwise_is_state_guessed(self):
        assert guess_relation_kind("？？", both_characters=False) == ("state", True)

    def test_blank_falls_back(self):
        assert guess_relation_kind("", both_characters=True) == ("social", True)

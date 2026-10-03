"""真实表格文件验收（未 mock）——tests/fixtures/spreadsheets/ 下的落盘文件。

覆盖：常规 xlsx 多表、GBK csv、Notion 导出形状。真实来源（Excel/WPS/飞书/腾讯文档/
Google 表格/Notion 各自导出）的原始文件尚未取得，取得并脱敏后放入同一目录再扩展
本测试；未实测来源不得对外宣称支持（ADR-0030）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.imports.parsers import parse_spreadsheet_file

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "spreadsheets"


def test_real_xlsx_multi_sheet_parses_and_classifies() -> None:
    from modules.imports.spreadsheet_migration.classify import classify_sheet

    upload = parse_spreadsheet_file(
        (FIXTURES / "sample_characters_relations_outline.xlsx").read_bytes(),
        "sample_characters_relations_outline.xlsx",
    )
    assert upload.file_type == "xlsx"
    assert [sheet.name for sheet in upload.sheets] == ["人物", "关系", "细纲"]
    kinds = {}
    for sheet in upload.sheets:
        kinds[sheet.name] = classify_sheet(sheet).kind
    assert kinds["人物"] == "characters"
    assert kinds["关系"] == "relations"
    assert kinds["细纲"] == "chapter_outline"
    characters = upload.sheets[0]
    assert characters.rows[1][0] == "林昭"
    assert characters.rows[1][3] == "沉默寡言的老斥候"


def test_real_gbk_csv_parses() -> None:
    upload = parse_spreadsheet_file(
        (FIXTURES / "sample_characters_gbk.csv").read_bytes(),
        "sample_characters_gbk.csv",
    )
    sheet = upload.sheets[0]
    assert upload.file_type == "csv"
    assert sheet.rows[0] == ["姓名", "身份", "简介"]
    assert sheet.rows[2][1] == "医女"


def test_real_notion_export_suffixes_stripped() -> None:
    from modules.imports.spreadsheet_migration.classify import classify_sheet

    upload = parse_spreadsheet_file(
        (FIXTURES / "sample_notion_export.csv").read_bytes(),
        "sample_notion_export.csv",
    )
    sheet = upload.sheets[0]
    flat = [cell for row in sheet.rows for cell in row]
    assert not any("notion.so" in cell for cell in flat), "Notion URL 后缀应被清理"
    def _is_hex32(cell: str) -> bool:
        return len(cell) == 32 and all(c in "0123456789abcdef" for c in cell)

    assert not any(_is_hex32(cell) for cell in flat), "32 位 hex 后缀应被清理"
    # 英文表名/表头可能判为 skip（作者可在预览中调整），此处只验证清理与可识别性
    assert classify_sheet(sheet).kind is not None


@pytest.mark.parametrize(
    "name",
    sorted(path.name for path in FIXTURES.iterdir() if path.suffix in {".xlsx", ".csv"}),
)
def test_every_fixture_is_accepted_by_signature_checks(name: str) -> None:
    upload = parse_spreadsheet_file((FIXTURES / name).read_bytes(), name)
    assert upload.sheets, name

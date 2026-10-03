"""表格迁移解析测试 — xlsx/csv 有界解析、恶意包拒绝、限额与分派。

夹具全部用 openpyxl / zipfile 在测试内生成（见 spreadsheet_fixtures.py），
不使用二进制 fixture 文件。
"""

from __future__ import annotations

import io
import struct
import zipfile

import pytest

from modules.imports.parsers import ALLOWED_EXTENSIONS, parse_spreadsheet_file
from modules.imports.spreadsheet_migration.constants import (
    MAX_CELL_CHARS,
    MAX_COLUMNS,
    MAX_ROWS_PER_SHEET,
    MAX_SHEETS_PER_FILE,
    XLSX_MAX_MEMBERS,
    XLSX_MAX_UNCOMPRESSED,
)
from modules.imports.spreadsheet_migration.parsing import parse_csv, parse_xlsx
from modules.imports.tests.spreadsheet_fixtures import (
    NOTION_HEX_SUFFIX,
    OLE_BYTES,
    build_member_bomb_xlsx,
    build_xlsx,
    build_zip_bomb_xlsx,
    inject_formula_cache,
    rebuild_zip_with_extra_members,
    replace_member,
)

# ============================================================
# audit_zip_container
# ============================================================


def _minimal_zip(members: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return output.getvalue()


class TestAuditZipContainer:
    def test_valid_zip_passes(self):
        from modules.imports.parsers import audit_zip_container

        audit_zip_container(
            _minimal_zip([("a.txt", b"hello")]),
            max_members=10,
            max_member_bytes=1024,
            max_total_uncompressed=4096,
        )

    def test_non_zip_signature_rejected(self):
        from modules.imports.parsers import audit_zip_container

        with pytest.raises(ValueError, match="文件内容与扩展名不匹配"):
            audit_zip_container(
                b"plain text, not a zip",
                max_members=10,
                max_member_bytes=1024,
                max_total_uncompressed=4096,
            )

    def test_member_count_limit_rejected(self):
        from modules.imports.parsers import audit_zip_container

        payload = _minimal_zip([(f"m{i}.txt", b"x") for i in range(5)])
        with pytest.raises(ValueError, match="文件数量超出安全限制"):
            audit_zip_container(
                payload,
                max_members=4,
                max_member_bytes=1024,
                max_total_uncompressed=4096,
            )

    def test_member_size_limit_rejected(self):
        from modules.imports.parsers import audit_zip_container

        payload = _minimal_zip([("big.txt", b"A" * 2048)])
        with pytest.raises(ValueError, match="单个文件超出安全限制"):
            audit_zip_container(
                payload,
                max_members=4,
                max_member_bytes=1024,
                max_total_uncompressed=4096,
            )

    def test_total_uncompressed_limit_rejected(self):
        from modules.imports.parsers import audit_zip_container

        payload = _minimal_zip([("a.txt", b"A" * 2500), ("b.txt", b"B" * 2500)])
        with pytest.raises(ValueError, match="解压后体积超出安全限制"):
            audit_zip_container(
                payload,
                max_members=4,
                max_member_bytes=4096,
                max_total_uncompressed=4096,
            )

    def test_unsafe_member_path_rejected(self):
        from modules.imports.parsers import audit_zip_container

        payload = _minimal_zip([("../outside.txt", b"x")])
        with pytest.raises(ValueError, match="文件内容与扩展名不匹配"):
            audit_zip_container(
                payload,
                max_members=4,
                max_member_bytes=1024,
                max_total_uncompressed=4096,
            )

    def test_forged_declared_size_bomb_rejected(self):
        """伪造中央目录声明体积的解压炸弹必须被实测审计拦截。"""
        from modules.imports.parsers import audit_zip_container

        bomb_payload = b"A" * (4 * 1024 * 1024)
        data = bytearray(_minimal_zip([("bomb.txt", bomb_payload)]))
        del bomb_payload
        eocd = bytes(data).rfind(b"PK\x05\x06")
        cd_offset = struct.unpack("<I", bytes(data[eocd + 16 : eocd + 20]))[0]
        cursor = cd_offset
        while bytes(data[cursor : cursor + 4]) == b"PK\x01\x02":
            name_len = struct.unpack("<H", bytes(data[cursor + 28 : cursor + 30]))[0]
            extra_len = struct.unpack("<H", bytes(data[cursor + 30 : cursor + 32]))[0]
            comment_len = struct.unpack("<H", bytes(data[cursor + 32 : cursor + 34]))[0]
            # 把声明 file_size 改小，实际解压输出远超声明值
            data[cursor + 24 : cursor + 28] = struct.pack("<I", 1024)
            cursor += 46 + name_len + extra_len + comment_len

        with pytest.raises(ValueError):
            audit_zip_container(
                bytes(data),
                max_members=4,
                max_member_bytes=1024 * 1024,
                max_total_uncompressed=8 * 1024 * 1024,
            )


# ============================================================
# parse_spreadsheet_file 分派
# ============================================================


class TestParseSpreadsheetFile:
    def test_dispatches_xlsx(self):
        payload = build_xlsx([{"name": "人物", "rows": [["姓名"], ["张三"]]}])
        parsed = parse_spreadsheet_file(payload, "人物.xlsx")
        assert parsed.file_type == "xlsx"
        assert parsed.file_key == "f0"
        assert parsed.sheets[0].rows == [["姓名"], ["张三"]]
        assert parsed.sha256 and parsed.size == len(payload)

    def test_dispatches_uppercase_extension(self):
        payload = build_xlsx([{"name": "人物", "rows": [["姓名"], ["张三"]]}])
        parsed = parse_spreadsheet_file(payload, "人物.XLSX")
        assert parsed.file_type == "xlsx"

    def test_dispatches_csv(self):
        parsed = parse_spreadsheet_file("名称,简介\n张三,好人\n".encode(), "人物.csv")
        assert parsed.file_type == "csv"
        assert parsed.sheets[0].rows == [["名称", "简介"], ["张三", "好人"]]

    def test_ignores_path_prefix_in_file_name(self):
        parsed = parse_spreadsheet_file("名称\n张三\n".encode(), "../../etc/人物.csv")
        assert parsed.sheets[0].name == "人物"

    def test_rejects_unsupported_extension(self):
        with pytest.raises(ValueError, match="仅支持 .xlsx 和 .csv"):
            parse_spreadsheet_file(b"data", "table.xls")

    def test_does_not_touch_prose_whitelist(self):
        assert ".xlsx" not in ALLOWED_EXTENSIONS
        assert ".csv" not in ALLOWED_EXTENSIONS
        assert ".txt" in ALLOWED_EXTENSIONS


# ============================================================
# parse_xlsx：内容与转换
# ============================================================


class TestParseXlsxContent:
    def test_value_conversion(self):
        import datetime as dt

        payload = build_xlsx(
            [
                {
                    "name": "混合",
                    "rows": [["文本", "整数浮点", "布尔", "日期", "小数"]],
                    "cell": [
                        (2, 1, "张三"),
                        (2, 2, 25.0),
                        (2, 3, True),
                        (2, 4, dt.datetime(2024, 1, 1)),
                        (2, 5, 1.5),
                        (3, 4, dt.datetime(2024, 1, 1, 8, 30, 0)),
                    ],
                }
            ]
        )
        parsed = parse_xlsx(payload, file_key="f0", file_name="混合.xlsx")
        rows = parsed.sheets[0].rows
        assert rows[0] == ["文本", "整数浮点", "布尔", "日期", "小数"]
        assert rows[1] == ["张三", "25", "是", "2024-01-01", "1.5"]
        assert rows[2][3] == "2024-01-01 08:30:00"

    def test_merged_cells_filled_with_top_left_value(self):
        payload = build_xlsx(
            [
                {
                    "name": "合并",
                    "rows": [["姓名", "备注", ""], ["张三", "", ""]],
                    "merges": ["B2:C2"],
                    "cell": [(2, 2, "合并值")],
                }
            ]
        )
        parsed = parse_xlsx(payload, file_key="f0", file_name="合并.xlsx")
        assert parsed.sheets[0].rows[1] == ["张三", "合并值", "合并值"]

    def test_hidden_sheet_flagged(self):
        payload = build_xlsx(
            [
                {"name": "可见", "rows": [["姓名"]]},
                {"name": "隐藏", "rows": [["姓名"]], "hidden": True},
            ]
        )
        parsed = parse_xlsx(payload, file_key="f0", file_name="多表.xlsx")
        flags = {sheet.name: sheet.hidden for sheet in parsed.sheets}
        assert flags == {"可见": False, "隐藏": True}
        assert [sheet.sheet_key for sheet in parsed.sheets] == ["f0s0", "f0s1"]

    def test_formula_without_cache_becomes_empty_with_warning(self):
        payload = build_xlsx(
            [
                {
                    "name": "公式",
                    "rows": [["数值", "合计"], [1, None], [2, None]],
                    "cell": [(2, 2, "=SUM(A2:A3)")],
                }
            ]
        )
        parsed = parse_xlsx(payload, file_key="f0", file_name="公式.xlsx")
        assert parsed.sheets[0].rows[1][1] == ""
        assert any("公式" in warning for warning in parsed.sheets[0].warnings)

    def test_formula_with_cached_value_uses_cache(self):
        payload = build_xlsx(
            [
                {
                    "name": "公式",
                    "rows": [["数值", "合计"], [1, None], [2, None]],
                    "cell": [(2, 2, "=SUM(A2:A3)")],
                }
            ]
        )
        cached = inject_formula_cache(payload, cached_value="3")
        parsed = parse_xlsx(cached, file_key="f0", file_name="公式.xlsx")
        assert parsed.sheets[0].rows[1][1] == "3"
        assert parsed.sheets[0].warnings == []

    def test_comments_counted_and_reported(self):
        payload = build_xlsx(
            [
                {
                    "name": "批注",
                    "rows": [["姓名"], ["张三"]],
                    "comment": [(2, 1, "主角")],
                }
            ]
        )
        parsed = parse_xlsx(payload, file_key="f0", file_name="批注.xlsx")
        assert any("批注" in warning for warning in parsed.sheets[0].warnings)

    def test_trailing_empty_rows_and_columns_stripped(self):
        payload = build_xlsx(
            [
                {
                    "name": "尾部",
                    "rows": [["姓名", "年龄"], ["张三", "20"], [None, None]],
                }
            ]
        )
        parsed = parse_xlsx(payload, file_key="f0", file_name="尾部.xlsx")
        assert parsed.sheets[0].rows == [["姓名", "年龄"], ["张三", "20"]]

    def test_title_first_row_kept_in_rows_for_classify(self):
        payload = build_xlsx(
            [
                {
                    "name": "人物",
                    "rows": [
                        ["人物设定总表"],
                        ["姓名", "性格", "简介"],
                        ["张三", "沉稳", "主角"],
                    ],
                }
            ]
        )
        parsed = parse_xlsx(payload, file_key="f0", file_name="人物.xlsx")
        # 行按最大列宽补齐成矩形；表头行定位交给 classify。
        assert parsed.sheets[0].rows[0] == ["人物设定总表", "", ""]
        assert parsed.sheets[0].rows[1] == ["姓名", "性格", "简介"]


# ============================================================
# parse_xlsx：限额
# ============================================================


class TestParseXlsxLimits:
    def test_too_many_sheets_rejected(self):
        payload = build_xlsx(
            [
                {"name": f"表{i}", "rows": [["姓名"]]}
                for i in range(MAX_SHEETS_PER_FILE + 1)
            ]
        )
        with pytest.raises(ValueError, match="工作表数量超过上限"):
            parse_xlsx(payload, file_key="f0", file_name="多表.xlsx")

    def test_too_many_rows_rejected(self):
        rows = [["姓名"]] + [[f"人物{i}"] for i in range(MAX_ROWS_PER_SHEET + 1)]
        payload = build_xlsx([{"name": "人物", "rows": rows}])
        with pytest.raises(ValueError, match="行数超过上限"):
            parse_xlsx(payload, file_key="f0", file_name="人物.xlsx")

    def test_too_many_columns_rejected(self):
        header = [f"列{i}" for i in range(MAX_COLUMNS + 1)]
        payload = build_xlsx([{"name": "宽表", "rows": [header]}])
        with pytest.raises(ValueError, match="列数超过上限"):
            parse_xlsx(payload, file_key="f0", file_name="宽表.xlsx")

    def test_overlong_cell_rejected(self):
        payload = build_xlsx(
            [{"name": "长文", "rows": [["简介"], ["x" * (MAX_CELL_CHARS + 1)]]}]
        )
        with pytest.raises(ValueError, match="单元格内容超过"):
            parse_xlsx(payload, file_key="f0", file_name="长文.xlsx")


# ============================================================
# parse_xlsx：恶意与伪装
# ============================================================


class TestParseXlsxMalformed:
    def test_ole_xls_disguised_as_xlsx_rejected_with_hint(self):
        with pytest.raises(ValueError, match="另存为 .xlsx"):
            parse_xlsx(OLE_BYTES, file_key="f0", file_name="旧版.xlsx")

    def test_plain_zip_without_xlsx_parts_rejected(self):
        payload = _minimal_zip([("hello.txt", b"world")])
        with pytest.raises(ValueError, match="格式不符"):
            parse_xlsx(payload, file_key="f0", file_name="伪装.xlsx")

    def test_zip_bomb_total_uncompressed_rejected(self):
        payload = build_zip_bomb_xlsx(
            declared_total_uncompressed=XLSX_MAX_UNCOMPRESSED * 2
        )
        with pytest.raises(ValueError):
            parse_xlsx(payload, file_key="f0", file_name="炸弹.xlsx")

    def test_too_many_members_rejected(self):
        payload = build_member_bomb_xlsx(XLSX_MAX_MEMBERS + 1)
        with pytest.raises(ValueError, match="文件数量超出安全限制"):
            parse_xlsx(payload, file_key="f0", file_name="多成员.xlsx")

    def test_vba_project_member_rejected(self):
        base = build_xlsx([{"name": "人物", "rows": [["姓名"], ["张三"]]}])
        payload = rebuild_zip_with_extra_members(
            base, [("xl/vbaProject.bin", b"\x00\x01\x02")]
        )
        with pytest.raises(ValueError, match="宏"):
            parse_xlsx(payload, file_key="f0", file_name="宏表.xlsx")

    def test_macro_enabled_content_type_rejected(self):
        base = build_xlsx([{"name": "人物", "rows": [["姓名"], ["张三"]]}])
        payload = replace_member(
            base,
            "[Content_Types].xml",
            b'<?xml version="1.0"?><Types xmlns="x">'
            b'<Override PartName="/xl/workbook.xml" '
            b'ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml"/></Types>',
        )
        with pytest.raises(ValueError, match="宏"):
            parse_xlsx(payload, file_key="f0", file_name="宏表.xlsx")

    def test_doctype_in_workbook_xml_rejected(self):
        base = build_xlsx([{"name": "人物", "rows": [["姓名"], ["张三"]]}])
        payload = replace_member(
            base,
            "xl/workbook.xml",
            b'<?xml version="1.0"?><!DOCTYPE workbook [<!ENTITY xxe "y">]>'
            b'<workbook xmlns="x"/>',
        )
        with pytest.raises(ValueError, match="文件内容与扩展名不匹配"):
            parse_xlsx(payload, file_key="f0", file_name="注入.xlsx")

    def test_path_traversal_member_rejected(self):
        base = build_xlsx([{"name": "人物", "rows": [["姓名"], ["张三"]]}])
        payload = rebuild_zip_with_extra_members(
            base, [("../outside.xml", b"<p>escape</p>")]
        )
        with pytest.raises(ValueError, match="文件内容与扩展名不匹配"):
            parse_xlsx(payload, file_key="f0", file_name="穿越.xlsx")


# ============================================================
# parse_csv
# ============================================================


class TestParseCsvContent:
    def test_utf8_bom_stripped(self):
        text = "名称,简介\n张三,好人\n"
        parsed = parse_csv(text.encode("utf-8-sig"), file_key="f1", file_name="人物.csv")
        assert parsed.sheets[0].rows == [["名称", "简介"], ["张三", "好人"]]
        assert parsed.sheets[0].name == "人物"

    def test_gbk_decoded(self):
        text = "名称,简介\n张三丰,武当掌门\n"
        parsed = parse_csv(text.encode("gbk"), file_key="f1", file_name="gbk.csv")
        assert parsed.sheets[0].rows == [["名称", "简介"], ["张三丰", "武当掌门"]]

    def test_tab_delimiter(self):
        text = "名称\t简介\n张三\t好人\n"
        parsed = parse_csv(text.encode("utf-8"), file_key="f1", file_name="tab.csv")
        assert parsed.sheets[0].rows == [["名称", "简介"], ["张三", "好人"]]

    def test_semicolon_delimiter(self):
        text = "名称;简介\n张三;好人\n"
        parsed = parse_csv(text.encode("utf-8"), file_key="f1", file_name="semi.csv")
        assert parsed.sheets[0].rows == [["名称", "简介"], ["张三", "好人"]]

    def test_embedded_newline_in_quoted_field(self):
        text = '名称,简介\n张三,"第一行\n第二行"\n'
        parsed = parse_csv(text.encode("utf-8"), file_key="f1", file_name="多行.csv")
        assert parsed.sheets[0].rows[1] == ["张三", "第一行\n第二行"]

    def test_notion_url_suffix_stripped_from_cells(self):
        text = f"名称,简介\n张三 (https://www.notion.so/Page-{NOTION_HEX_SUFFIX}),好人\n"
        parsed = parse_csv(text.encode("utf-8"), file_key="f1", file_name="导出.csv")
        assert parsed.sheets[0].rows[1][0] == "张三"

    def test_notion_hex_suffix_stripped_from_sheet_name(self):
        parsed = parse_csv(
            "名称\n张三\n".encode(),
            file_key="f1",
            file_name=f"Characters {NOTION_HEX_SUFFIX}.csv",
        )
        assert parsed.sheets[0].name == "Characters"

    def test_empty_csv_yields_empty_sheet(self):
        parsed = parse_csv(b"", file_key="f1", file_name="空.csv")
        assert len(parsed.sheets) == 1
        assert parsed.sheets[0].rows == []

    def test_trailing_empty_rows_stripped(self):
        parsed = parse_csv(
            "名称,简介\n张三,好人\n,\n".encode(), file_key="f1", file_name="尾空.csv"
        )
        assert parsed.sheets[0].rows == [["名称", "简介"], ["张三", "好人"]]


class TestParseCsvLimits:
    def test_overlong_cell_rejected(self):
        text = f"名称,简介\n张三,{'x' * (MAX_CELL_CHARS + 1000)}\n"
        with pytest.raises(ValueError, match="单元格内容超过"):
            parse_csv(text.encode("utf-8"), file_key="f1", file_name="长文.csv")

    def test_too_many_rows_rejected(self):
        lines = ["名称"] + [f"人物{i}" for i in range(MAX_ROWS_PER_SHEET + 1)]
        with pytest.raises(ValueError, match="行数超过上限"):
            parse_csv("\n".join(lines).encode(), file_key="f1", file_name="长表.csv")

    def test_undecodable_bytes_rejected(self):
        with pytest.raises(ValueError, match="编码"):
            parse_csv(b"\xff\xfe\x00\xd8\x00\x00", file_key="f1", file_name="乱码.csv")

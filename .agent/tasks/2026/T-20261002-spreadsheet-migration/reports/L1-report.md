# L1 交接报告 — 表格解析与识别

车道：L1　分支：`codex/spreadsheet-migration-l1`　提交：`9a8007a42`（本报告为随后单独提交）

## 已完成

- `parsers.py` 新增 `audit_zip_container(data, *, max_members, max_member_bytes, max_total_uncompressed)`：EPUB 与 XLSX 共用的 zip 容器审计（zip 签名、成员数、重名、加密标记、不安全路径、符号链接、压缩白限、单成员与总解压上限、按实测输出的解压炸弹拦截）。EPUB 校验改为调用它，原有 EPUB 测试全部保持绿色；限额类违规的文案更具体（成员数/单成员/总量），EPUB 侧统一归一为“文件内容与扩展名不匹配”。
- `parsers.py` 新增 `parse_spreadsheet_file(data, file_name)`：按扩展名分派到 `spreadsheet_migration.parsing.parse_xlsx/parse_csv`；未修改 `ALLOWED_EXTENSIONS`，并有测试钉住。
- `parsing.py` 实现 `parse_xlsx`：
  - 内容签名：OLE（D0CF11E0）→“请在 Excel/WPS 中另存为 .xlsx”；必须含 `[Content_Types].xml` 与 `xl/workbook.xml`；拒绝 `vbaproject.bin`（任意路径、大小写不敏感）与 `[Content_Types].xml` 中的 macroEnabled；xml/rels 成员头 1MB 内出现 DOCTYPE/ENTITY 即拒绝；成员数 ≤500、解压总量 ≤60MB（单成员上限复用同一常量，因 L0 constants 冻结无单成员常量）。
  - 加载：`load_workbook(BytesIO, read_only=False, data_only=True, keep_vba=False, keep_links=False)`；公式探测（zip 内 `<f>`）命中时额外加载一本 `data_only=False` 工作簿用于区分“公式无缓存”，无公式的文件不付第二本的开销。
  - 单元格：合并单元格左上值填充；datetime/date/time 转 ISO（零时刻日期只留日期部分）；整数型浮点转 int 字符串；布尔转“是/否”；公式取缓存值、无缓存留空并加 warning；图片（`_images`）与批注只计数提示；隐藏表 `hidden=True`；全部转 str，超 `MAX_CELL_CHARS` 拒绝该文件。
- `parsing.py` 实现 `parse_csv`：`detect_encoding`（BOM/GBK→GB18030 宽化）；`csv.Sniffer` 候选 `,` Tab `;`（失败回落 `,`）；`field_size_limit(MAX_CELL_CHARS+1)` + 显式长度复核；去 Notion URL 后缀与 32 位 hex 后缀（单元格与表名）；内嵌换行（`StringIO(newline="")`）；尾部空行/空列清理；限额拒绝。
- `classify.py` 实现 `detect_header_row`（前 10 行内短单元格多、同义词命中多者优先，跳过单格长文案的合并标题行）与 `classify_sheet`（表名关键词优先级：关系 > 人物 > 世界对象 > 细纲 > 卷纲 > 主线支线 > 伏笔 > 总纲 > 跳过；结构判断含矩阵关系表、双名称列+关系列、“章”列+内容列；未识别列 → author_note；表类型可用目标组由 constants 的四组 frozenset 约束）。
- `synonyms.py` 实现 4 个函数：`normalize_entity_type`（设定/词条/名词/术语→concept，覆盖 `ENTITY_TYPE_MAP["设定"]="secret"`；法宝/装备→item、门派/宗门→faction、功法→skill、境界/修炼体系→power_system；其余走 `normalize_author_entity_type`）、`split_aliases`（`、,，;；/|` 与换行，去重保序）、`parse_chapter_ref`（第N章/阿拉伯/中文数字/区间/至/到，中文数字支持到万级）、`guess_relation_kind`（七类关键词 + 双人物 social / 其余 state 兜底，兜底带 `guessed=True`）。

## 改动文件

全部在本车道独占清单内：

- `backend/modules/imports/parsers.py`（修改）
- `backend/modules/imports/spreadsheet_migration/parsing.py`、`classify.py`、`synonyms.py`（实现 stub 函数体，dataclass/常量未动）
- `backend/modules/imports/tests/test_spreadsheet_parsing.py`、`test_spreadsheet_classify.py`、`spreadsheet_fixtures.py`（新增）

## 契约偏离

无（L0 冻结文件零改动）。三点实现说明，供集成者知悉：

1. **xlsx 单成员上限**：L0 constants 只有 `XLSX_MAX_MEMBERS` 与 `XLSX_MAX_UNCOMPRESSED`，没有单成员常量；我在 `parsing.py` 内以 `XLSX_MAX_UNCOMPRESSED` 作为单成员上限（总量上限天然约束单成员），未新增冻结常量。
2. **`parse_spreadsheet_file` 的 file_key 固定为 `"f0"`**：冻结签名没有 file_idx 参数；多文件会话中 L4 需要用 `dataclasses.replace` 按文件序号重编 `file_key`/`sheet_key`（均为 frozen dataclass，replace 即可），或在调用 `parse_xlsx/parse_csv` 时直接传序号。
3. **超长简介/身份“改投作者备注并给出 warning”只完成改投**：`SheetSuggestion` 契约没有 warnings 字段，无法携带提示文案；classify 已按列数据长度把 target 换成 author_note，warning 文案需 L4 在预览层补（属于契约缺口，不是实现遗漏）。

## 测试

- `make test TESTS="modules/imports/tests/test_spreadsheet_parsing.py modules/imports/tests/test_spreadsheet_classify.py modules/imports/tests/test_imports.py"` → **191 passed**（注意：Makefile 会先 cd backend，任务书给出的 `backend/` 前缀路径会报 “file not found”，需用 backend 相对路径）。
- 扩展回归：`make test TESTS="modules/imports/tests tests/unit/test_facade_public_api.py"` → **863 passed**（整个 imports 模块 + 公共面）。
- `make lint` → 通过。`ruff format --check` 对本车道 7 个文件通过（L0 的 constants/repository/schemas 存在与当前 ruff 版本的格式漂移，属 L0 既有状态，未动）。
- 夹具全部用 openpyxl/zipfile 在测试内生成；生产代码无 Mock、无 `@patch`。
- 覆盖场景：合并单元格、日期、缓存公式（注入 `<v>` 模拟 Excel 缓存）与无缓存公式、隐藏表、批注计数、首行标题、恶意包（DOCTYPE、vbaProject、macroEnabled、成员过多、zip 炸弹、伪造声明体积、路径穿越、伪装 .xls、缺部件 zip）、CSV BOM/GBK/Tab/分号/内嵌换行/超长单元格、限额（表数/行数/列数）、“设定”→concept、矩阵关系表、双名称列关系表、Notion 后缀（单元格与表名）、别名拆分、中文章号区间（含千级组合）、关系种类关键词与兜底、EPUB 原有测试全绿。

## 文档要点（供 L7b）

- xlsx 按有界固定部件 OOXML 处理：不落盘、不执行公式/宏；公式只取上次保存的缓存值，无缓存按空值处理并在表上提示；图片与批注只提示已忽略。
- `.xls`/OLE 与含宏表格的拒绝文案是“另存为 .xlsx”指引；错误信息不含路径与单元格内容（行/列/表数超限文案含表名与上限数字，便于作者定位）。
- 单元格统一转字符串：日期 ISO、整数浮点去 `.0`、布尔“是/否”；行按最大列宽补齐为矩形，尾部空行/空列剔除。
- 识别默认值均可被作者调整：表类型优先按表名关键词（“人物关系”判为关系表而非人物表），矩阵表按首行/首列皆名称识别；未识别列默认进作者备注。
- 限额：单文件 ≤20 表、单表 ≤5000 行、≤60 列、单元格 ≤20000 字；超限明确拒绝，不截断。

## 风险与待决

- **内存**：限额上限夹具（5000 行 × 60 列 × 约 40 字）实测峰值约 147MB；含公式的同规模文件因双工作簿加载约 284MB。10MB 文件 + 60MB 解压上限已封顶攻击面，但 L4 并发解析多文件时建议控制 `to_thread` 并发度，L8 的 1000 行 apply 实测时可一并观察。
- **矩阵关系表的列建议**：矩阵表的行/列表头是数据名称，ColumnSuggestion 只能给 `ignore`；矩阵 → 边列表的展开需要 L4 planning 识别 `kind=relations` 且首行/首列皆名称的结构自行处理（classify 已给 kind）。
- **表名关键词的误判面**：如“人际关系表”会被判为关系表、“人物时间线”会被跳过（skip 关键词命中）；均可在预览中由作者改回，属产品可接受误差。
- **xlsx 表名未做 Notion 后缀清理**：计划把 Notion 后缀写在 csv 要点下，xlsx 表名如带 ` 48e2…` hex 后缀会原样展示；如需要，L4 展示层可复用 `parsing._strip_notion_suffixes` 或由集成者决定是否提升为共享工具。
- **待 L8**：真实文件验收（WPS/飞书/腾讯文档/Google 表格/Notion 导出）尚未发生，对外不得宣称已支持这些来源。

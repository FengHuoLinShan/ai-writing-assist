# Module: imports / 小说导入模块（原设计以外新增）

## 定位

imports 模块负责将本地小说文件解析并导入系统，创建 WritingDraft 记录以供后续实体抽取和创作使用。

## 数据表

- import_records — file_name / file_type / file_size / total_chapters / imported_chapters / status / error_message

## 文件解析器（parsers.py）

| 格式 | 库 | 说明 |
|------|----|------|
| .txt | 内置 + chardet | 编码检测 + 章节正则分割 |
| .epub | ebooklib | 逐章提取 |
| .html/.htm | beautifulsoup4 | 提取文本 |
| .mobi/.azw3 | 内置 | 原始解析 |

## 服务

- ImportService.upload_and_import()：文件校验 → 解析 → 创建 WritingDraft → 更新 ImportRecord

## 安全约束

- 文件类型白名单：`.txt .epub .html .htm .mobi .azw3`
- 大小上限：50MB
- 文件名必须 `os.path.basename` 处理，防止路径穿越

## API

```
POST /api/imports/upload           # 上传并导入（multipart/form-data）
GET  /api/imports                  # 导入记录列表
GET  /api/imports/{id}            # 导入记录详情
POST /api/imports/deep            # 提交深度导入任务
POST /api/imports/deep/resume     # 继续深度导入（确认候选后）
```

## 深度导入流水线

DeepImportWorkflow 将三步串成全自动流水线，直接入库无需用户中途确认：

1. **extract_world** — 调用 world facade 从章节正文抽取世界对象（LLM → 去重 → 自动入库 `status="canonical"`）
2. **sync_characters** — 将已确认的 character_ref 实体同步到人物档案
3. **generate_plot** — 调用 LLM 生成剧情线和篇章纲（增量更新；minimal-core 中 outline 模块不可用时静默跳过）

状态转换：`pending → running → done`

每步完成后不等待用户确认直接进入下一步。候选管理已拆除，所有实体不经候选池直接入库。

## 跨模块依赖

- 写入 writing_drafts 通过 `writing/facade.create_draft()`
- `writing/facade.create_draft()` 会同时提交 `rag_index_chapter` 任务，确保导入正文可被 RAG 和人物档案抽取检索
- 不直接访问 writing/models.py

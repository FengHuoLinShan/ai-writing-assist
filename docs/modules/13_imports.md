# Module: imports / 小说导入模块（原设计以外新增）

## 定位

imports 模块负责将本地小说文件解析并导入系统，创建 WritingDraft 记录以供后续实体抽取和创作使用。

## 数据表

- import_records — file_name / file_type / file_size / total_chapters / imported_chapters / status / error_message

## 文件解析器（parsers.py）

| 格式 | 库 | 说明 |
|------|----|------|
| .txt | 内置 + chardet | 编码检测 + 5 种章节正则分割 |
| .epub | ebooklib | 逐章提取 |
| .html/.htm | beautifulsoup4 | 提取 `<body>` 或 `<article>` 文本 |
| .mobi/.azw3 | 内置（二选一） | mobi 原始解析或使用 mobi 包 |

### 章节分割正则

支持 5 种中文/英文章节标题格式：
- `第X章` / `第X节` / `第X话`
- `Chapter X` / `Ch.X` / `Ch X`
- `VOL.X` / `卷X`
- `Part X`
- `Episode X`

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
```

## 跨模块依赖

- 写入 writing_drafts 通过 `writing/facade.create_draft()`
- 不直接访问 writing/models.py

## 测试

- parsers：每种格式 happy path + 空内容
- repository：CRUD + 分页
- service：导入流程 + 非法类型拒绝
- conftest 必须 import `modules.project.models` 和 `modules.outline.models`

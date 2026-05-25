# Module: imports / 小说文件导入模块

## 定位

imports 模块负责小说文件的导入与解析。它不是一个独立的创作模块，而是将外部小说文件转换为系统内部章节正文的通道。

## 负责

- 上传并解析 txt / epub / html / mobi / azw3 格式的小说文件
- 自动检测文本编码
- 按章节模式（第X章、Chapter X、卷X 等）自动分章
- 将解析结果写入 writing_drafts（每章一个 draft）
- 记录导入历史

## 不负责

- 正文内容的结构化分析
- 实体抽取
- 文本改写
- 格式转换导出

## 数据表

- import_records：导入操作记录（元信息，不存正文）

## 跨模块依赖

- writing.facade.create_draft — 写入解析后的章节正文

## Facade

```python
async def import_file(db, novel_id, file_name, file_content) -> ImportResponse:
    """导入小说文件"""
```

## API

```http
POST /api/imports/upload      — 上传文件（multipart multipart）
GET  /api/imports             — 导入记录列表
GET  /api/imports/{id}        — 导入记录详情
```

## 安全约束

- 文件类型白名单：txt, epub, html, htm, mobi, azw3
- 文件大小上限：50MB
- 文件名 sanitize：防止路径穿越
- 不保存上传文件到可执行目录，解析后即释放

## 测试

```bash
pytest modules/imports/tests/
```

# Module: imports / 小说文件导入模块

## 定位

imports 模块负责小说文件的导入与解析。它不是一个独立的创作模块，而是将外部小说文件转换为系统内部章节正文的通道。
同时，imports 负责深度导入的工作流编排：把已导入章节交给 Scene 切分、实体抽取和结构分析三个阶段执行。

## 负责

- 上传并解析 txt / epub / html / mobi / azw3 格式的小说文件
- 自动检测文本编码
- 按章节模式（第X章、Chapter X、卷X 等）自动分章
- 将解析结果写入 writing_drafts（每章一个 draft）
- 记录导入历史
- 提交并编排深度导入任务（基于 async_tasks）
- 在重复导入时返回覆盖确认要求，确认后才入队

## 不负责

- 直接实现世界对象、记忆或大纲的业务规则
- 绕过各模块 facade 直接写跨模块内部模型
- 文本改写或格式转换导出

## 数据表

- import_records：导入操作记录（元信息，不存正文）
- async_tasks：深度导入任务载体，运行中写入 progress/result 供前端轮询

## 跨模块依赖

- writing.facade.create_draft — 写入解析后的章节正文
- outline facade / DI handler — 深度导入 Phase 1/3
- world facade / DI handler — 深度导入 Phase 2
- memory.facade.capture_snapshot — Phase 2 后记录记忆快照

## Facade

```python
async def import_file(db, novel_id, file_name, file_content) -> ImportResponse:
    """导入小说文件"""

async def start_deep_import(db, novel_id, start_chapter, end_chapter, force=False) -> dict:
    """提交深度导入任务；重复导入时先返回 requires_confirmation"""
```

## API

```http
POST /api/imports/upload      — 上传文件（multipart multipart）
GET  /api/imports             — 导入记录列表
GET  /api/imports/{id}        — 导入记录详情
POST /api/imports/deep        — 提交深度导入任务；重复导入时先返回 requires_confirmation
POST /api/imports/deep/sync   — 同步执行深度导入（测试/无 worker 场景）
POST /api/imports/deep/resume — 兼容旧候选确认流程，当前已废弃
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

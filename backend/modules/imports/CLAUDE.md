# CLAUDE.md — modules/imports

## 模块职责

小说文件导入。解析 txt/epub/html/mobi，写入 WritingDraft。

## 开发规则

- 跨模块依赖仅通过 `writing/facade.py`，不直接访问 `writing/models.py`
- 新增格式解析在 `parsers.py` 中添加，统一返回 `list[dict{title, content}]`
- `ImportService` 必须更新 `ImportRecord` 状态，不允许记录卡在 `processing`

## 安全约束

- 文件类型白名单：`.txt .epub .html .htm .mobi .azw3`
- 大小上限：50MB
- 文件名必须 `os.path.basename` 处理，防止路径穿越

## 测试要求

- parsers: 每种格式至少一个 happy path 测试 + 空内容测试
- repository: CRUD + 分页
- service: 导入流程 + 非法类型拒绝
- conftest 必须 import `modules.project.models` 和 `modules.outline.models`（WritingDraft 的 FK 依赖）

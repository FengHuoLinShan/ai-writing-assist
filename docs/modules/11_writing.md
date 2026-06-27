# Module: writing / 正文草稿承载模块

## 定位

writing 模块不是核心 AI 正文生成模块，而是人工正文草稿和结构化创作成果的承载模块。

## 数据表

- `writing_drafts` — chapter_index / title / content / version_number（UniqueConstraint: novel_id + chapter_index + version_number）

## 版本管理

每次保存创建新版本（version_number 自增），旧版本保留供版本历史查看和回滚。
API 提供了两种写入模式：

1. **发布草稿**（`POST /drafts`）→ 新版本 + 自动入队 `publish_chapter` 任务
2. **更新草稿**（`PUT /drafts/{id}`）→ 原地更新最新版本内容，无副作用（暂存模式）

## Facade

```python
async def create_draft_only(db, novel_id, chapter_index, title: str | None = None, content: str = "") -> WritingDraftResponse
async def create_draft(db, novel_id, chapter_index, title: str | None = None, content: str = "") -> tuple[WritingDraftResponse, str]
async def get_draft(db, draft_id) -> WritingDraftContract | None
async def get_latest_draft_for_chapter(db, novel_id, chapter_index) -> WritingDraftContract | None
async def list_chapter_indices(db, novel_id) -> list[int]
```

## API

```
POST   /api/writing/drafts                              # 发布草稿（新版本 + publish_chapter 任务）
GET    /api/writing/drafts/{id}                         # 获取草稿
PUT    /api/writing/drafts/{id}                         # 暂存草稿（原地更新，支持 expected_version 冲突检测）
DELETE /api/writing/drafts/{id}                         # 删除单个版本
DELETE /api/writing/chapters/{index}                    # 删除整章所有版本
GET    /api/writing/chapters/{index}/draft              # 按章节索引获取最新草稿
GET    /api/writing/chapters/{index}/versions           # 章节版本历史
GET    /api/writing/chapters                            # 列出有草稿的章节索引
POST   /api/writing/chapters/{chapter_index}/split     # 断章：在 split_pos 处切分当前章，生成下一章草稿
```

`POST /api/writing/chapters/{chapter_index}/split?novel_id=...` splits the latest draft at `split_pos`, creates the next chapter draft, shifts later chapter indices, and delegates Scene chunk remapping to outline facade. It does not enqueue `publish_chapter`; RAG indexing waits for an explicit save/publish.

## 版本历史

`GET /chapters/{index}/versions` 返回该章所有版本（版本号/创建时间/字数），前端写作工作台显示为模态框，支持预览和恢复到历史版本。

## 多 Tab 冲突检测

`PUT /drafts/{id}` 支持 `expected_version` 字段；当传入期望版本与当前最新版本不一致时，后端返回 409。
当前 `writing.spec.js` 仅验证了草稿被删除后的 404；基于 409 的预期版本冲突 E2E 仍待补充。

## 手动工作台

writingView（frontend-console/views/writingView.js）扩展为手动工作台：

- **左侧 Scene 树**：Scene 一级节点 → Chapter 二级节点折叠结构，支持 Scene 间导航
- **中间编辑器**：textarea + 保存/上一章/下一章/导出
- **右侧 Scene 卡面板**：当前 Scene 卡详情（goal / core_conflict / emotional_beat / must_happen / must_not_happen / narrative_tag）
- **版本历史**：模态框列出所有版本，支持预览和恢复
- **深度导入按钮**：触发三阶段进度条（40%/40%/20%），每 3 秒轮询进度
- **章节卡提取**：批量调用 LLM 从正文提取 Scene 卡字段

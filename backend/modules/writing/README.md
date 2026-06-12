# Writing 模块 — 正文草稿承载

## 定位

Writing 模块当前 **不是** 核心 AI 正文生成模块，而是**人工正文草稿和结构化创作成果的承载模块**。

系统的核心创作产物仍然是结构化资产（世界对象、人物档案、剧情线、章节卡等），正文草稿仅为作者手动写作或后续 AI 辅助写作提供基础承载。

## 职责

- 手写正文草稿的存储与管理
- 正文版本控制（version_number 递增）
- 章节卡关联（通过 chapter_card_id）
- 按章节索引获取最新草稿
- 版本历史查看
- 创建草稿后提交 `publish_chapter` 异步索引任务

## 不负责

- AI 自动生成完整正文
- 复杂正文审稿
- 文风润色
- 多版本自动融合
- 正文的 RAG 分块（由 RAG 模块负责）

## 数据表

- `writing_drafts` — 正文草稿表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| novel_id | UUID FK | 所属小说项目 |
| chapter_index | INT | 章节索引 |
| chapter_card_id | UUID nullable | 关联的章节卡 |
| title | TEXT nullable | 草稿标题 |
| content | TEXT nullable | 草稿正文 |
| version_number | INT | 版本号（从 1 递增） |
| status | TEXT | 状态：draft / candidate / canonical / deprecated |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

## 对外契约

```python
# contracts.py
@dataclass(frozen=True)
class WritingDraftContract:
    novel_id: str
    chapter_index: int
    chapter_card_id: str | None
    title: str | None
    content: str | None
    version_number: int
    status: str
```

## Facade 入口

```python
async def create_draft_only(db: AsyncSession, novel_id: str, chapter_index: int, title: str | None = None, content: str = "") -> WritingDraftResponse
async def create_draft(db: AsyncSession, novel_id: str, chapter_index: int, title: str | None = None, content: str = "") -> tuple[WritingDraftResponse, str]
async def get_draft(db: AsyncSession, draft_id: str) -> WritingDraftContract | None
async def get_latest_draft_for_chapter(db: AsyncSession, novel_id: str, chapter_index: int) -> WritingDraftContract | None
async def list_chapter_indices(db: AsyncSession, novel_id: str) -> list[int]
```

通过 `facade.create_draft` 创建草稿会提交 `publish_chapter` 章节发布任务；`facade.create_draft_only` 仅创建草稿，不会提交发布任务。导入模块等内部调用方不需要直接访问 RAG 模块。

## API

```http
POST /api/writing/drafts                          → 发布草稿（新版本 + publish_chapter 任务）
GET  /api/writing/drafts/{id}                     → 获取草稿
PUT  /api/writing/drafts/{id}                     → 暂存草稿（原地更新，支持 expected_version 冲突检测）
DELETE /api/writing/drafts/{id}                   → 删除单个版本
DELETE /api/writing/chapters/{chapter_index}      → 删除整章所有版本
GET /api/writing/chapters/{chapter_index}/draft   → 获取章节最新草稿
GET /api/writing/chapters/{chapter_index}/versions → 版本历史
GET /api/writing/chapters                         → 列出有草稿的章节索引
POST /api/writing/chapters/{chapter_index}/split  → 断章：在 split_pos 处切分当前章
```

`POST /api/writing/chapters/{chapter_index}/split` 将最新草稿在 `split_pos` 处切分为两章，生成下一章草稿并位移后续章节索引，同时委托 outline facade 完成 Scene chunk 重映射。该操作不入队 `publish_chapter`，RAG 索引需等待显式保存/发布。

## 后续扩展方向

- 根据章节卡生成正文 Prompt
- 正文局部重写
- 文风润色
- 正文审稿
- 章节正文 RAG 分块

## 测试方式

```bash
pytest modules/writing/tests/ -v
```

测试使用 SQLite 内存数据库，无需真实 PostgreSQL。

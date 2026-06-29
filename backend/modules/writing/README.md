# Writing 模块 — 正文草稿承载

## 定位

Writing 模块当前 **不是** 核心 AI 正文生成模块，而是**人工正文草稿和结构化创作成果的承载模块**。

系统的核心创作产物仍然是结构化资产（世界对象、人物档案、剧情线、章节卡等），正文草稿仅为作者手动写作或后续 AI 辅助写作提供基础承载。

## 职责

- 手写正文草稿的存储与管理
- 正文版本控制（version_number 递增）
- 按章节索引获取最新草稿
- 版本历史查看
- 创建草稿后提交 `publish_chapter` 异步索引任务
- 写作页剧情设定冲突检查记录、问题状态与发布前检查快照归档

## 不负责

- AI 自动生成完整正文
- 复杂正文审稿
- 文风润色
- 多版本自动融合
- 正文的 RAG 分块（由 RAG 模块负责）

## 数据表

- `writing_drafts` — 正文草稿表
- `writing_conflict_checks` — Scene 写作冲突检查记录
- `writing_conflict_items` — 单条检查问题项

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| novel_id | UUID FK | 所属小说项目 |
| chapter_index | INT | 章节索引 |
| title | TEXT nullable | 草稿标题 |
| content | TEXT nullable | 草稿正文 |
| conflict_check_snapshot_json | JSON nullable | 发布时归档的最近一次冲突检查快照 |
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
POST /api/writing/drafts/autosave                 → 创建纯草稿版本，不触发发布任务
POST /api/writing/conflict-checks                 → 创建剧情设定冲突检查
GET /api/writing/conflict-checks                  → 获取章节/Scene 检查历史
GET /api/writing/conflict-checks/{id}             → 获取检查详情
POST /api/writing/conflict-checks/{id}/ai-review  → 为检查追加 AI 软冲突判断
PATCH /api/writing/conflict-check-items/{id}      → 更新问题处理状态
POST /api/writing/conflict-check-items/{id}/ai-suggestion → 生成单条问题 AI 修复建议
```

`POST /api/writing/chapters/{chapter_index}/split` 将最新草稿在 `split_pos` 处切分为两章，生成下一章草稿并位移后续章节索引，同时委托 outline facade 完成 Scene chunk 重映射。该操作不入队 `publish_chapter`，RAG 索引需等待显式保存/发布。

`POST /api/writing/conflict-checks` 默认只做规则层检查。请求体的 `include_candidates` 默认为 `false`；写作页会在检查前弹出确认，只有用户勾选“包含待确认对象”时才传 `true`。

- 通过 `outline.facade.get_scene_contract` 读取当前 Scene 的目标、必须发生、禁止发生和核心冲突。
- 通过 `world.map_facade.summarize_scene_map_for_writing` 读取写作页地图摘要，默认不纳入待确认对象；`include_candidates=true` 时会纳入候选 observation，相关问题标记 `needs_review=true` 并写入复核原因。
- 通过 `memory.facade.get_continuity_evidence_for_writing` 获取上一章位置连续性证据；来源不可用时写入 `summary_json.degraded_sources`。
- 每条问题的 `location_json` 保存轻量证据：`source` 描述来源模块/类型/标签/字段/摘录，`open_target` 描述前端可打开目标（`text_range` / `outline_scene` / `map_scene` / `map_object` / `memory_chapter`），`needs_review_reason` 描述候选证据复核原因。
- 问题状态为 `open / resolved / ignored / later`；发布章节时会把最近一次检查快照写入 `writing_drafts.conflict_check_snapshot_json`，快照保留 `source` / `open_target`，不保留正文 `text_range`，之后问题状态变化不会改写该发布快照。

Phase 2 AI 能力是显式追加，不影响规则层检查：

- `POST /api/writing/conflict-checks/{id}/ai-review` 需要 `context_confirmation_id`，且确认记录 action 必须是 `writing.conflict_check.ai_review`。
- AI 软冲突判断保存为 `is_ai_judgment=true` 的问题项，保留 `source_confirmation_id`、`confidence`、`llm_rationale`；包含待确认对象或依赖待确认对象时标记 `needs_review=true`。
- LLM 输出逐条校验；非法条目丢弃并记录到 `summary_json.ai_review.discarded_count`，LLM 失败只把 `ai_review_status` 置为 `failed`，不删除规则层结果。
- `POST /api/writing/conflict-check-items/{id}/ai-suggestion` 需要 action 为 `writing.conflict_check.ai_suggestion` 的确认记录，只把最新建议写入该问题项，不修改正文、Scene、地图、世界对象、记忆或正史资产。

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

真实 LLM 写作冲突检查验收默认跳过，不进入常规 CI。需要配置
`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 后手动运行：

```bash
RUN_REAL_LLM_TESTS=1 pytest modules/writing/tests/test_conflict_checks_real_llm.py -q -s
```

前端真实 UI 烟测同样默认跳过，需要后端可调用真实 LLM：

```bash
cd frontend-console
ENABLE_REAL_LLM=1 npx playwright test e2e/writing-conflict-real-llm.spec.js --reporter=list --timeout=300000
```

真实 LLM 验收只校验结构、状态机、持久化和不可变副作用，不固化模型生成文本。

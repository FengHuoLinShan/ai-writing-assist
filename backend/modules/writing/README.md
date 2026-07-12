# Writing 模块 — 正文草稿承载

## 定位

Writing 模块当前 **不是** 核心 AI 正文生成模块，而是**人工正文草稿和结构化创作成果的承载模块**。

系统的核心创作产物仍然是结构化资产（世界对象、人物档案、剧情线、章节卡等），正文草稿仅为作者手动写作或后续 AI 辅助写作提供基础承载。

## 职责

- 手写正文草稿的存储与管理
- 正文版本控制（version_number 递增）
- 按 `canonical` / `working` 选择章节事实源
- 字面 grep、稳定范围引用与段落扩展读取
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
| content_hash | CHAR(64) | 正文 SHA-256，用于范围与派生索引校验 |
| conflict_check_snapshot_json | JSON nullable | 发布时归档的最近一次冲突检查快照 |
| version_number | INT | 版本号（从 1 递增） |
| status | TEXT | 状态：draft / published / candidate / canonical / deprecated |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

## 对外契约

```python
# contracts.py
@dataclass(frozen=True)
class WritingDraftContract:
    novel_id: str
    chapter_index: int
    id: str | None
    title: str | None
    content: str | None
    content_hash: str | None
    version_number: int
    status: str
    conflict_check_snapshot_json: dict | None
    provenance_json: dict[str, Any] | None
    display_state: str  # active / review / archived
    source: str         # manual / ai_generated / ...
    attention_reasons: list[str]
    created_at: datetime | None
    updated_at: datetime | None
```

## Facade 入口

```python
async def create_draft_only(db: AsyncSession, novel_id: str, chapter_index: int, title: str | None = None, content: str = "") -> WritingDraftContract
async def create_published_draft_only(db: AsyncSession, novel_id: str, chapter_index: int, title: str | None = None, content: str = "") -> WritingDraftContract
async def create_draft(db: AsyncSession, novel_id: str, chapter_index: int, title: str | None = None, content: str = "") -> tuple[WritingDraftContract, str]
async def get_draft(db: AsyncSession, novel_id: str, draft_id: str) -> WritingDraftContract | None
async def adopt_candidate_to_working(db: AsyncSession, novel_id: str, draft_id: str, *, adopted_by: str = "author") -> WritingDraftContract
async def get_latest_draft_for_chapter(db: AsyncSession, novel_id: str, chapter_index: int) -> WritingDraftContract | None
async def list_latest_drafts_for_chapters(db: AsyncSession, novel_id: str, chapter_indices: list[int], *, content_limit: int | None = None) -> list[WritingDraftContract]
async def list_chapter_indices(db: AsyncSession, novel_id: str) -> list[int]
async def list_manuscript_sources(db, novel_id, chapter_indices=None, *, content_mode="canonical") -> list[WritingDraftContract]
async def grep_manuscript(db, novel_id, pattern, *, content_mode="canonical", ...) -> ManuscriptSearchPageContract
async def read_manuscript_range(db, novel_id, source_ref, *, before_paragraphs=0, after_paragraphs=0) -> ManuscriptReadContract
async def build_manuscript_range_ref(db, novel_id, draft_id, start_offset, end_offset) -> SourceRangeRefContract
```

通过 `facade.create_draft` 创建已发布正文版本并提交 `publish_chapter` 章节发布任务；`facade.create_published_draft_only` 只创建已发布正文版本，不入队；`facade.create_draft_only` 仅创建草稿，不会提交发布任务。facade create 系列返回跨模块 `WritingDraftContract`，API 层负责适配为 `WritingDraftResponse`。导入模块等内部调用方不需要直接访问 RAG 模块。
AI 生成结果会在 `provenance_json` 中记录 `source_confirmation_id` 和来源任务。兼容期内底层仍以 `candidate` 保存建议，但 API/contract 投影为 `display_state=review` 和 `source=ai_generated`，不将其当作工作稿。

`canonical` 严格选择每章最新非废弃 `published` 版本；缺失时返回警告，
不回退到 working。`working` 只选择已采用的 `draft / published / canonical` 兼容状态；未采用 `candidate` 不进入章节最新稿、项目统计、原文 grep 或 RAG working 来源。`SourceRangeRefContract`
包含 draft/version/mode/offset 与 source/range hash；范围不得跨章，读取时必须
重新校验 novel 归属、源 hash 和范围 hash。V1 grep 只支持有上限、可分页的
字面匹配，不接受正则表达式。

`facade.list_latest_drafts_for_chapters(..., content_limit=N)` 供跨模块批量加载正文时做 DB-side 截断；默认 `None` 保持返回完整最新正文。`content_limit` 必须为正整数，启用时仅投影跨模块契约必要字段，不加载完整 `WritingDraft` ORM。

## 跨模块依赖

Writing 对外继续通过 `contracts.py` / `facade.py` 暴露草稿和章节索引。outline 可以只读消费这些契约，用于结构生成上下文、Scene 工作台和跨章检测，不直接访问 writing 的 model / repository / service。

Writing 服务需要同步 outline 结构时通过可注入 port 调用：断章使用 `split_scene_chunk_to_new_chapter` provider，冲突检查使用 Scene contract loader provider。默认 provider 在函数内部 lazy import `modules.outline.facade`，保持旧的用户流程和 HTTP/API 返回形状；测试可注入 fake callable，不需要 monkeypatch outline facade。

## API

```http
POST /api/writing/drafts                          → 发布草稿（新版本 + publish_chapter 任务）
GET  /api/writing/drafts/{id}                     → 获取草稿
POST /api/writing/drafts/{id}/adopt               → 将 AI 建议复制为最新工作稿，原建议归档
PUT  /api/writing/drafts/{id}                     → 暂存；published 首次编辑 copy-on-write 为新 working ID
DELETE /api/writing/drafts/{id}                   → 软废弃单个版本
DELETE /api/writing/chapters/{chapter_index}      → 软废弃整章所有版本
GET /api/writing/chapters/{chapter_index}/draft   → 获取章节最新草稿
GET /api/writing/chapters/{chapter_index}/versions → 版本历史
GET /api/writing/chapters                         → 列出有草稿的章节索引
POST /api/writing/chapters/{chapter_index}/split  → 断章：在 split_pos 处切分当前章
POST /api/writing/drafts/autosave                 → 创建纯草稿版本，不发布；合并标脏 working 索引
POST /api/writing/conflict-checks                 → 创建剧情设定冲突检查
GET /api/writing/conflict-checks                  → 获取章节/Scene 检查历史
GET /api/writing/conflict-checks/{id}             → 获取检查详情
POST /api/writing/conflict-checks/{id}/ai-review  → 为检查追加 AI 软冲突判断
PATCH /api/writing/conflict-check-items/{id}      → 更新问题处理状态
POST /api/writing/conflict-check-items/{id}/ai-suggestion → 生成单条问题 AI 修复建议
```

`POST /api/writing/chapters/{chapter_index}/split` 仅允许未发布的 working 章节拓扑变更；
从切分位置起存在 published 版本时拒绝，避免修改已发布源的章号。通过注入的
split provider 同步 Scene chunk；该操作不入队 `publish_chapter`。

已发布版本不得原地修改。单版本/整章删除仅将状态改为 `deprecated`，
`version_number` 永不重排；只有项目永久删除可通过外键级联硬删除。

采用 AI 建议使用 copy-on-adopt：新建一个最高 `version_number` 的普通 `draft`，写入 `adopted_from_candidate_id / adopted_at / adopted_by`；原 candidate 改为 `deprecated` 并记录 `adoption_result_draft_id`。这使采用结果即使晚于其他手工保存也会成为最新 working，同时保留建议历史。

`POST /api/writing/conflict-checks` 默认只做规则层检查。请求体的 `include_candidates` 默认为 `false`；写作页会在检查前弹出确认，只有用户勾选“包含待确认对象”时才传 `true`。

- 通过注入的 Scene contract loader 读取当前 Scene 的目标、必须发生、禁止发生和核心冲突；默认 loader 仍 lazy 调用 `outline.facade.get_scene_contract`。
- 通过 `world.map_facade.summarize_scene_map_for_writing` 读取写作页地图摘要，默认不纳入待确认对象；`include_candidates=true` 时会纳入候选 observation，相关问题标记 `needs_review=true` 并写入复核原因。
- 通过 `memory.facade.get_continuity_evidence_for_writing` 获取上一章位置连续性证据；来源不可用时写入 `summary_json.degraded_sources`。
- 每条问题的 `location_json` 保存轻量证据：`source` 描述来源模块/类型/标签/字段/摘录，`open_target` 描述前端可打开目标（`text_range` / `outline_scene` / `map_scene` / `map_object` / `memory_chapter`），`needs_review_reason` 描述候选证据复核原因。
- 问题状态为 `open / resolved / ignored / later`；发布章节时会把最近一次检查快照写入 `writing_drafts.conflict_check_snapshot_json`，快照保留 `source` / `open_target`，不保留正文 `text_range`，之后问题状态变化不会改写该发布快照。

Phase 2 AI 能力是显式追加，不影响规则层检查：

- `POST /api/writing/conflict-checks/{id}/ai-review` 需要 `context_confirmation_id`，且确认记录 action 必须是 `writing.conflict_check.ai_review`。
- AI 软冲突判断保存为 `is_ai_judgment=true` 的问题项，保留 `source_confirmation_id`、`confidence`、`llm_rationale`；包含待确认对象或依赖待确认对象时标记 `needs_review=true`。
- LLM 输出逐条校验；非法条目丢弃并记录到 `summary_json.ai_review.discarded_count`，LLM 失败只把 `ai_review_status` 置为 `failed`，不删除规则层结果。
- `POST /api/writing/conflict-check-items/{id}/ai-suggestion` 需要 action 为 `writing.conflict_check.ai_suggestion` 的确认记录，只把最新建议写入该问题项，不修改正文、Scene、地图、世界对象、记忆或正史资产。
- 前端把 AI 修复建议当作可编辑草稿展示；用户可修改后显式插入当前正文编辑器，插入只影响当前草稿和自动保存队列，不发布章节，也不自动把问题标记为已解决。

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

真实 LLM 写作冲突检查验收默认跳过，不进入常规 CI。需要先在项目设置页配置
项目级 LLM API Key / Base URL / 模型后手动运行：

```bash
RUN_REAL_LLM_TESTS=1 pytest modules/writing/tests/test_conflict_checks_real_llm.py -m real_llm -q -s
```

前端真实 UI 烟测同样默认跳过，需要后端可调用真实 LLM：

```bash
cd frontend-console
ENABLE_REAL_LLM=1 npx playwright test e2e/writing-conflict-real-llm.spec.js --reporter=list --timeout=300000
```

真实 LLM 验收只校验结构、状态机、持久化和不可变副作用，不固化模型生成文本。

正文 candidate、冲突 AI review 和修复建议均通过 project runtime seam 消费
effective 项目 profile；确认校验仍在 LLM 调用前，candidate/adopt/publish 状态语义不变。
candidate provenance 额外保留 secret-free `managed_llm_steps`，记录
`novel_id`、step name、实际 request model 和 profile summary/hash，不保存
API Key、完整 Base URL/query、prompt 或正文。

# Writing 模块 — 正文事实源与受控候选生成

## 定位

Writing 模块是章节正文的事实源，同时负责在 fresh context confirmation 约束下生成
可审查的 AI 正文 candidate。它管理人工正文、版本、发布事实、稳定范围引用和候选采用，
但不会自动采用、覆盖或发布 AI 生成结果。

世界对象、人物档案、剧情线和 Scene 等结构化资产仍由各自领域模块拥有；writing
只消费其稳定 context/contract，不复制结构正史。

## 职责

- 手写正文草稿的存储与管理
- 正文版本控制（version_number 递增）
- 按 `canonical` / `working` 选择章节事实源
- 字面 grep、稳定范围引用与段落扩展读取
- 版本历史查看
- 创建草稿后提交 `publish_chapter` 异步索引任务
- 写作页剧情设定冲突检查记录、问题状态与发布前检查快照归档
- 从已确认 context 生成 AI 正文 candidate，并保存 confirmation/task provenance
- 对规则冲突结果追加 AI 软复核和可编辑修复建议

## 不负责

- 未经确认自动采用、覆盖或发布 AI 正文
- 把 candidate 当作 working/canonical 正文
- 自治式长篇生成或跨模块业务编排
- 完整文学质量审稿
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

PostgreSQL 上同一 `novel_id + chapter_index` 的版本号分配使用事务级
advisory lock 串行化，再读取历史最大版本号；因此首版和后续版本的并发创建
都不会分配重复号。底层唯一约束继续作为最终防线，已废弃版本的号码也不复用。
advisory key 稳定为 `writing_versions:{novel_id}:{chapter_index}`，多章时按章号
升序取锁。同一把锁也覆盖 working 正文原地修改、latest content 更新、
单版本软废弃的最后 working 版本判定、candidate 采用和发布时的内容替换，并通过
`facade.lock_chapter_versions_for_revalidation()` 允许独立 Scene task 在最终
来源重验到资产提交期间阻止并发正文写入。SQLite 环境下该锁是 no-op，
不改变现有单进程测试语义。

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
async def list_effective_chapter_indices(db: AsyncSession, novel_id: str) -> list[int]
async def lock_chapter_versions_for_revalidation(db: AsyncSession, novel_id: str, chapter_indices: list[int]) -> None
async def list_manuscript_sources(db, novel_id, chapter_indices=None, *, content_mode="canonical") -> list[WritingDraftContract]
async def grep_manuscript(db, novel_id, pattern, *, content_mode="canonical", ...) -> ManuscriptSearchPageContract
async def read_manuscript_range(db, novel_id, source_ref, *, before_paragraphs=0, after_paragraphs=0) -> ManuscriptReadContract
async def build_manuscript_range_ref(db, novel_id, draft_id, start_offset, end_offset) -> SourceRangeRefContract
```

通过 `facade.create_draft` 创建已发布正文版本并提交 `publish_chapter` 章节发布任务；`facade.create_published_draft_only` 只创建已发布正文版本，不入队；`facade.create_draft_only` 仅创建草稿，不会提交发布任务。facade create 系列返回跨模块 `WritingDraftContract`，API 层负责适配为 `WritingDraftResponse`。导入模块等内部调用方不需要直接访问 RAG 模块。
AI 生成结果会在 `provenance_json` 中记录 `source_confirmation_id` 和来源任务。兼容期内底层仍以 `candidate` 保存建议，但 API/contract 投影为 `display_state=review` 和 `source=ai_generated`，不将其当作工作稿。

`publish_chapter` 通过 RAG 的 task-only DI port 执行索引：先在 worker fence 下结束
source-read checkpoint，再在无 PostgreSQL 事务时等待 embedding，入库前重验
canonical draft ID/hash。RAG chunk/index state 成功后立即经 worker fence 提交并释放锁，
memory snapshot 再以 `project FOR SHARE → memory` 的锁序开启新事务。若 RAG 已成功但
snapshot 失败，任务重新从发布源发起时会合并 fresh RAG，只补做 snapshot；RAG 是
可重建派生数据，已发布正文仍是事实源。项目删除或 task lease 丢失会使当前 checkpoint
失败并回滚，不会跨 `novel_id` 写入。

`canonical` 严格选择每章最新非废弃 `published` 版本；缺失时返回警告，
不回退到 working。`working` 只选择已采用的 `draft / published / canonical` 兼容状态；未采用 `candidate` 不进入章节最新稿、项目统计、原文 grep 或 RAG working 来源。`SourceRangeRefContract`
包含 draft/version/mode/offset 与 source/range hash；范围不得跨章，读取时必须
重新校验 novel 归属、源 hash 和范围 hash。V1 grep 只支持有上限、可分页的
字面匹配，不接受正则表达式。检索页可传 `group_by_chapter=True`，此时每章只返回
一个代表命中，`match_count` 表示该章的字面出现次数，分页与 `total` 都按章节组计算。
聚合命中通过可选 `source_refs` 保留该章全部命中范围，供 context 在不改变分页语义的
前提下对齐每个命中的父 Scene；未聚合结果保持空列表。

`facade.list_latest_drafts_for_chapters(..., content_limit=N)` 供跨模块批量加载正文时做 DB-side 截断；默认 `None` 保持返回完整最新正文。`content_limit` 必须为正整数，启用时仅投影跨模块契约必要字段，不加载完整 `WritingDraft` ORM。

`facade.list_effective_chapter_indices()` 只返回每章最新 working 版本中含有实质正文的章节；空值、空串和仅含 Unicode 空白的占位稿不会推进 Scene 工作台或热点统计的“当前章节”。原 `list_chapter_indices()` 继续表示存在 working 草稿记录的章节，保持既有 API 与管理流程语义。

## 跨模块依赖

Writing 对外继续通过 `contracts.py` / `facade.py` 暴露草稿和章节索引。outline 可以只读消费这些契约，用于结构生成上下文、Scene 工作台和跨章检测，不直接访问 writing 的 model / repository / service。

Writing 服务需要读取 outline Scene contract 时通过可注入 loader 调用。默认 loader 在函数内部 lazy import `modules.outline.facade`；测试可注入 fake callable，不需要 monkeypatch outline facade。

## API

所有带 `novel_id` 的 writing API（正文、版本、冲突检查及 AI 入队）
都在任何业务读写前通过 project facade 校验活跃项目。项目不存在或已进入
回收站时统一返回 404，不暴露草稿、冲突检查或任务结果。

```http
POST /api/writing/drafts                          → 发布当前工作版本；无实质变化时复用
GET  /api/writing/drafts/{id}                     → 获取草稿
POST /api/writing/drafts/{id}/adopt               → 将 AI 建议复制为最新工作稿，原建议归档
PUT  /api/writing/drafts/{id}                     → 暂存；published 首次编辑 copy-on-write 为新 working ID
POST /api/writing/drafts/{id}/checkpoint           → 显式保存未发布版本，可确认后强制留版
POST /api/writing/drafts/{id}/discard              → 放弃最新未发布版本并回到基线
DELETE /api/writing/drafts/{id}                   → 软废弃单个版本
DELETE /api/writing/chapters/{chapter_index}      → 软废弃整章所有版本
GET /api/writing/chapters/{chapter_index}/draft   → 获取章节最新草稿
GET /api/writing/chapters/{chapter_index}/versions → 版本历史
GET /api/writing/chapters                         → 列出有草稿的章节索引
POST /api/writing/drafts/autosave                 → 创建纯草稿版本，不发布；合并标脏 working 索引
POST /api/writing/conflict-checks                 → 创建剧情设定冲突检查
GET /api/writing/conflict-checks                  → 获取章节/Scene 检查历史
GET /api/writing/conflict-checks/{id}             → 获取检查详情
POST /api/writing/conflict-checks/{id}/ai-review  → 为检查追加 AI 软冲突判断
POST /api/writing/conflict-checks/{id}/ai-review-task → 异步执行 AI 软冲突判断
PATCH /api/writing/conflict-check-items/{id}      → 更新问题处理状态
POST /api/writing/conflict-check-items/{id}/ai-suggestion → 生成单条问题 AI 修复建议
POST /api/writing/generate                        → 从已确认 context 生成正文 candidate
```

默认正文生成把模型定位为共同创作者，不使用固定字数、段落或节奏
模板，并始终生成可替换目标章的完整正文；当前编辑章关联 Scene 时，
Scene 只作为结构上下文，不把跨章 Scene 错当成输出范围。`generation_mode=continue`
则锁定同章 active working/published/canonical base draft，将模型输出确定性追加到
原文末尾，原文逐字不变；base 内容或确认上下文漂移时失败关闭，不静默续写旧版本。
确认上下文同时包含
当前活跃剧情线及与 Scene、篇章、剧情线或 RAG 证据关联的人物和物品。
人物超出预算时取 Top 6，相关世界对象超出预算时取 Top 16。输出仍只是
`candidate`，不会自动采用、覆盖或发布。

当确认上下文同时指定当前 Scene、`reveal_mode=character` 和
POV 人物时，生成使用单角色有限视角。这不强制第一人称，
也不预设对话、动作、描写或内心戏比例。模型输出一个结构化对象：
`draft_prose` 是主要正文候选，`pov_state` 仅保留可检查的感知事实、
解读、当前意图和已知但隐矒的信息，`uncertainties` 仅记录
实质影响写作的资料不确定性。Scene 和剧情线导演信息可以引导
情节，但不得变成 POV 角色已知事实；输出还会经过确定性
hidden guard 检查，但仍只保存为待审阅 candidate。目标章已有工作稿、
已发布稿或 canonical 正文时，生成会冻结最新 active base 的完整正文并
纳入任务指纹；`draft_prose` 必须是可替换目标章的完整候选，跨章 Scene
不能把其它章节内容带入本章，作者本次明确边界优先于宽泛 Scene 导演目标。

`writing_generate` 入队时同时保存 secret-free 项目 LLM execution snapshot；兼容旧任务
会先在 worker lease fence 下冻结并持久化一次，重试继续复用同一 snapshot。task-only
generation seam 在 prepare 阶段冻结 rendered context、完整 confirmation/evidence 指纹、
prompt/request、生成 profile 和 POV hidden guard terms，随后提交并清空 identity map；真实
LLM、POV 解析、正文/标题清洗、hidden guard 与 provenance 组装均在无数据库事务阶段完成。
finalize 按 project-first 锁序重新验证项目、锁定 base 正文和完整 confirmed context/hidden evidence 指纹，
profile 与当前最新 running task owner；只有 fresh 结果才在同一最终 worker
transaction 中创建 candidate 并绑定 confirmation。同一 confirmation 重复入队时，
最后绑定的 task 取代旧 task，旧结果不会写入。
上下文漂移、项目删除、取消或 lease 丢失均不会留下 candidate。同步
`WritingGenerationService.generate_candidate()` 仍保留原调用语义且不自行 commit。

版本历史是审计视图：按 `version_number` 倒序返回 active、review 和
archived 全部记录，`total` 与返回集合一致。列表项的 `display_state`
为 `active / review / archived`；`deprecated_from_status` 保留首次软废弃前的
原始状态，重复 DELETE 仍幂等返回 204，不覆盖该 provenance。

只有当前最新 working 版本可通过 `PUT /drafts/{id}` 更新；旧 working、
candidate 和 deprecated 均返回 409，无论请求是否提供乐观并发快照。
`expected_version / expected_updated_at` 仍用于校验多 Tab 看到的最新
working 快照；编辑最新 published 仍使用 copy-on-write。candidate 和
deprecated 仅可在历史视图预览，不允许普通编辑或恢复；candidate
采用只能经过专用 adopt 状态迁移，也可由作者显式“拒绝建议”软废弃。
拒绝保留完整版本、原状态和 `rejected_at/rejected_by` 审计，不硬删除正文。

已发布版本不得原地修改。单版本/整章删除仅将状态改为 `deprecated`，
`version_number` 永不重排；只有项目永久删除可通过外键级联硬删除。

自动版本判定只比较正文：入库前安全清洗后，比较时移除 Unicode
空白，但不改写作者原文。标题或纯空白修改不由自动保存创建
版本；前端先保留在本地备份，作者可通过 checkpoint 二次确认后强制
留版。`provenance_json.version_origin` 区分 `auto / manual`，
`base_draft_id` 用于自动或显式撤销。发布 draft 时原位提升为
`published`，不再额外创建一个版本；auto 工作稿若已撤回到手动基线，
则废弃 auto 版本并原位发布该手动基线。重复发布已发布基线不再入队索引任务。
从历史版本恢复发布时，`restore_source_version` 标识旧版本，
`expected_version / expected_updated_at` 校验用户选择恢复时看到的章节最新快照；
快照过期返回 409，且不创建版本或任务。

采用 AI 建议使用 copy-on-adopt：新建一个最高 `version_number` 的普通 `draft`，写入 `adopted_from_candidate_id / adopted_at / adopted_by`；原 candidate 改为 `deprecated` 并记录 `adoption_result_draft_id`。这使采用结果即使晚于其他手工保存也会成为最新 working，同时保留建议历史。

`POST /api/writing/conflict-checks` 默认只做规则层检查。请求体的 `include_candidates` 默认为 `false`；写作页会在检查前弹出确认，只有用户勾选“包含待确认对象”时才传 `true`。

- 通过注入的 Scene contract loader 读取当前 Scene 的目标、必须发生、禁止发生和核心冲突；默认 loader 仍 lazy 调用 `outline.facade.get_scene_contract`。
- 通过 `world.map_facade.summarize_scene_map_for_writing` 读取写作页地图摘要，默认不纳入待确认对象；`include_candidates=true` 时会纳入候选 observation，相关问题标记 `needs_review=true` 并写入复核原因。
- 通过 `memory.facade.get_continuity_evidence_for_writing` 获取上一章位置连续性证据；来源不可用时写入 `summary_json.degraded_sources`。
- 每条问题的 `location_json` 保存轻量证据：`source` 描述来源模块/类型/标签/字段/摘录，`open_target` 描述前端可打开目标（`text_range` / `outline_scene` / `map_scene` / `map_object` / `memory_chapter`），`needs_review_reason` 描述候选证据复核原因。
- 问题状态为 `open / resolved / ignored / later`；发布章节时会把最近一次检查快照写入 `writing_drafts.conflict_check_snapshot_json`，快照保留 `source` / `open_target`，不保留正文 `text_range`，之后问题状态变化不会改写该发布快照。

Phase 2 AI 能力是显式追加，不影响规则层检查：

- `POST /api/writing/conflict-checks/{id}/ai-review` 需要 `context_confirmation_id`，且确认记录 action 必须是 `writing.conflict_check.ai_review`。
- `/ai-review-task` 在入队事务中保存 secret-free 项目 LLM execution snapshot 和内部 task owner；worker 只允许在带 lease commit fence 的 task session 中运行。prepare 阶段读取并锁定当前检查/问题、重建已确认上下文后提交，真实 LLM 等待期间不持有数据库事务；finalize 再检查项目、确认上下文、检查及问题的语义指纹。输入漂移或任务被更新任务取代时不会追加旧结果，内部 owner 不进入 API 或发布快照。同步 `/ai-review` 的既有单事务语义不变。
- AI 软冲突判断保存为 `is_ai_judgment=true` 的问题项，保留 `source_confirmation_id`、`confidence`、`llm_rationale`；包含待确认对象或依赖待确认对象时标记 `needs_review=true`。
- LLM 输出逐条校验；非法条目丢弃并记录到 `summary_json.ai_review.discarded_count`，LLM 失败只把 `ai_review_status` 置为 `failed`，不删除规则层结果。
- `POST /api/writing/conflict-check-items/{id}/ai-suggestion` 需要 action 为 `writing.conflict_check.ai_suggestion` 的确认记录，只把最新建议写入该问题项，不修改正文、Scene、地图、世界对象、记忆或正史资产。
- 前端把 AI 修复建议当作可编辑草稿展示；用户可修改后显式插入当前正文编辑器，插入只影响当前草稿和自动保存队列，不发布章节，也不自动把问题标记为已解决。

## 后续扩展方向

- 正文局部重写
- 文风润色
- 文学质量与 POV 稳定性评测
- candidate 局部比较与人工融合工具

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
生成中心提交的正文 candidate 是可恢复异步任务；provider 前先做无事务 checkpoint，
受管生成步骤与冻结 client 都使用 1800 秒上限，前端任务轮询不设置整体截止时间。
candidate provenance 额外保留 secret-free `managed_llm_steps`，记录
`novel_id`、step name、实际 request model 和 profile summary/hash，不保存
API Key、完整 Base URL/query、prompt 或正文。

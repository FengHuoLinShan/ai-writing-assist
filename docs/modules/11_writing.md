# Module: writing / 正文草稿承载模块

## 定位

writing 模块不是核心 AI 正文生成模块，而是人工正文草稿和结构化创作成果的承载模块。

## 数据表

- `writing_drafts` — chapter_index / title / content / content_hash / version_number / status / provenance_json（UniqueConstraint: novel_id + chapter_index + version_number）
- `writing_conflict_checks` — Scene 写作冲突检查记录，保存规则层结果、AI 软冲突状态和 `include_candidates`
- `writing_conflict_items` — 单条检查问题，保存来源模块、证据摘要、可打开来源和处理状态

## 版本管理

每次发布或对 published 的首次编辑创建新版本（version_number 自增），
旧 published 版本不可变，保留供稳定引用与版本历史回读。
API 提供了两种写入模式：

1. **发布草稿**（`POST /drafts`）→ 新版本 + 自动入队 `publish_chapter` 任务
2. **更新草稿**（`PUT /drafts/{id}`）→ working 可原地暂存；published 以 copy-on-write 返回新 draft ID

`canonical` 选择每章最新非废弃 `published`，缺失时不回退 working；
`working` 选择最新非废弃版本。删除单版本或整章只标记 `deprecated`，
版本号永不重排。

## Facade

```python
async def create_draft_only(db, novel_id, chapter_index, title: str | None = None, content: str = "") -> WritingDraftContract
async def create_published_draft_only(db, novel_id, chapter_index, title: str | None = None, content: str = "") -> WritingDraftContract
async def create_draft(db, novel_id, chapter_index, title: str | None = None, content: str = "") -> tuple[WritingDraftContract, str]
async def get_draft(db, draft_id) -> WritingDraftContract | None
async def get_latest_draft_for_chapter(db, novel_id, chapter_index) -> WritingDraftContract | None
async def list_latest_drafts_for_chapters(db, novel_id, chapter_indices, *, content_limit: int | None = None) -> list[WritingDraftContract]
async def list_chapter_indices(db, novel_id) -> list[int]
async def list_manuscript_sources(db, novel_id, chapter_indices=None, *, content_mode="canonical") -> list[WritingDraftContract]
async def grep_manuscript(db, novel_id, pattern, *, content_mode="canonical", ...) -> ManuscriptSearchPageContract
async def read_manuscript_range(db, novel_id, source_ref, *, before_paragraphs=0, after_paragraphs=0) -> ManuscriptReadContract
```

facade 的 create 系列只暴露跨模块 `WritingDraftContract`，不返回 API response schema；REST API 层继续负责把 contract 适配为 `WritingDraftResponse`，保持 HTTP response body 不变。

## 跨模块依赖

outline 可以只读消费 writing facade/contracts 中的草稿和章节索引。writing 需要调用
outline 时不在服务模块顶层 import outline facade，而是通过可注入 provider 完成：
断章同步使用 split provider，冲突检查使用 Scene contract loader。默认 provider 仍在
调用时 lazy import `modules.outline.facade`，所以写作断章同步调整 Scene chunk、冲突
检查读取 Scene contract、outline 读取 writing 草稿/章节索引这三条用户流程保持不变。

## API

```
POST   /api/writing/drafts                              # 发布草稿（新版本 + publish_chapter 任务）
GET    /api/writing/drafts/{id}                         # 获取草稿
PUT    /api/writing/drafts/{id}                         # 暂存；published copy-on-write，支持 expected_version
DELETE /api/writing/drafts/{id}                         # 软废弃单个版本
DELETE /api/writing/chapters/{index}                    # 软废弃整章所有版本
GET    /api/writing/chapters/{index}/draft              # 按章节索引获取最新草稿
GET    /api/writing/chapters/{index}/versions           # 章节版本历史
GET    /api/writing/chapters                            # 列出有草稿的章节索引
POST   /api/writing/chapters/{chapter_index}/split     # 断章：在 split_pos 处切分当前章，生成下一章草稿
POST   /api/writing/conflict-checks                    # 创建剧情设定冲突检查
GET    /api/writing/conflict-checks                    # 获取章节/Scene 检查历史
GET    /api/writing/conflict-checks/{id}               # 获取检查详情
POST   /api/writing/conflict-checks/{id}/ai-review     # 追加 AI 软冲突判断
POST   /api/writing/conflict-checks/{id}/ai-review-task # 提交异步 AI 软冲突判断任务
PATCH  /api/writing/conflict-check-items/{id}          # 更新问题处理状态
POST   /api/writing/conflict-check-items/{id}/ai-suggestion # 生成单条 AI 修复建议
POST   /api/writing/drafts/autosave                    # 创建纯草稿版本，不发布；合并标脏 working 索引
POST   /api/writing/generate                            # 生成正文候选草稿，不自动发布
```

`POST /api/writing/chapters/{chapter_index}/split?novel_id=...` 只允许未发布的
working 章节拓扑变更；切分位置及后续存在 published 版本时拒绝。该入口通过
outline provider 重映射 Scene chunk，不修改正文事实源，也不自动发布。

## 稳定原文引用

`SourceRangeRefContract` 保存 draft/chapter/version/content mode、章内 offset、
`source_hash` 与 `range_hash`。范围不跨章；读取时必须校验 novel 归属、
版本与 hash。原文 grep 为有长度/结果上限和分页的字面搜索，V1 不开放正则。

## 版本历史

`GET /chapters/{index}/versions` 返回该章所有版本（版本号/创建时间/字数），前端写作工作台显示为模态框，支持预览和恢复到历史版本。

## 多 Tab 冲突检测

`PUT /drafts/{id}` 支持 `expected_version` 字段；当传入期望版本与当前最新版本不一致时，后端返回 409。
前端 E2E 覆盖了其他会话发布新版本、其他 Tab 暂存同一草稿两类 409 用户路径。

## 剧情设定冲突检查

`POST /api/writing/conflict-checks` 是写作页的规则层检查入口。前端会在发起检查前弹出选项确认，默认不包含待确认对象；用户勾选“包含待确认对象”后，后端以 `include_candidates=true` 纳入候选地图观察等证据，依赖候选对象的问题会标记 `needs_review=true`。

规则层检查聚合三类跨模块证据：

- 注入的 Scene contract loader：Scene 的目标、必须发生、禁止发生和核心冲突，命中项带 `outline_scene` 打开目标或正文 `text_range`；默认 loader lazy 调用 `outline.facade.get_scene_contract`。
- `world.map_facade.summarize_scene_map_for_writing`：当前 Scene 的地图摘要、风险和待确认观察，地图项带 `map_scene` / `map_object` 打开目标。
- `memory.facade.get_continuity_evidence_for_writing`：上一章角色位置连续性证据，连续性问题带 `memory_chapter` 打开目标。

问题项的 `location_json` 保存轻量证据结构：`source` 描述来源模块、类型、标签、字段和摘录；`open_target` 描述前端可以打开的目标；`needs_review_reason` 描述候选证据复核原因。发布章节时，最近一次检查会归档到 `writing_drafts.conflict_check_snapshot_json`，快照保留 `source` / `open_target`，但不保留正文 `text_range`。

AI 能力是显式追加流程，不替代规则层结果：

- `ai-review` 必须使用 action 为 `writing.conflict_check.ai_review` 的 `context_confirmation_id`。
- `ai-suggestion` 必须使用 action 为 `writing.conflict_check.ai_suggestion` 的 `context_confirmation_id`。
- AI 软冲突和建议只写入检查项，不修改正文、Scene、地图、世界对象、记忆或正史资产。

## AI 正文候选来源追踪

`POST /api/writing/generate` 只创建 `status="candidate"` 的候选草稿，不自动发布、不触发 RAG、不写正史。

`writing_drafts.provenance_json` 保存 AI 生成来源追踪：

- `source_confirmation_id` / `context_confirmation_id`：本次使用的 AI 参考资料确认记录
- `generation_profile`：`default` 或 `pov_character`
- `prompt_name` / `prompt_hash` / `model`：生成 prompt 与模型审计信息
- `pov_view`：角色视角结构化结果（仅 `pov_character`）
- `pov_validation`：角色视角 deterministic 泄漏诊断；`passed` 只表示“未发现明显越权”，不是绝对安全保证

POV 角色视角候选即使诊断为 `failed` 仍保存为 candidate draft；前端必须标红提示，用户需显式确认后才可采用。

## 手动工作台

writingView（frontend-console/views/writingView.js）扩展为手动工作台：

- **左侧 Scene 树**：Scene 一级节点 → Chapter 二级节点折叠结构，支持 Scene 间导航
- **中间编辑器**：textarea + 保存/上一章/下一章/导出
- **右侧 Scene 卡面板**：当前 Scene 卡详情（goal / core_conflict / emotional_beat / must_happen / must_not_happen / narrative_tag）
- **版本历史**：模态框列出所有版本，支持预览和恢复
- **剧情设定冲突检查**：检查前确认是否包含待确认对象；检查结果按规则命中和 AI 判断分组，支持证据抽屉、来源打开、正文定位、状态更新和复制 AI 修复建议
- **深度导入按钮**：触发三阶段进度条（40%/40%/20%），每 3 秒轮询进度
- **章节 / Scene 提取**：批量调用 LLM 从正文提取 Scene 卡字段；UI 里历史“章节卡提取”入口不表示恢复独立 ChapterCard 主模型，当前权威结构对象仍是 `scenes`

## 真实 LLM 验收

真实 LLM 写作冲突检查默认跳过，不进入常规 CI。手动验收覆盖规则层冲突、跨模块地图/记忆证据、AI 软冲突、AI 修复建议、状态更新和发布快照归档：

```bash
cd backend
RUN_REAL_LLM_TESTS=1 pytest modules/writing/tests/test_conflict_checks_real_llm.py -q -s

cd frontend-console
ENABLE_REAL_LLM=1 npx playwright test e2e/writing-conflict-real-llm.spec.js --reporter=list --timeout=300000
```

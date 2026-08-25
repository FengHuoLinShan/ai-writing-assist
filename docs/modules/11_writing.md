# Module: writing / 正文版本与工作稿模块

## 定位

writing 模块拥有正文版本事实源。作者界面只区分工作稿、已发布和待处理 AI 建议；
`candidate` 等原始状态仅用于兼容持久化和审计。

## 数据表

- `writing_drafts` — chapter_index / title / content / content_hash / version_number / status / provenance_json（UniqueConstraint: novel_id + chapter_index + version_number）
- `writing_conflict_checks` — Scene 写作冲突检查记录，保存规则层结果、AI 软冲突状态和 `include_candidates`
- `writing_conflict_items` — 单条检查问题，保存来源模块、证据摘要、可打开来源和处理状态

## 版本管理

对 published 或手动 checkpoint 的正文首次实质编辑创建 auto 工作版本
（version_number 自增），后续自动保存原地更新它。实质变化的判定只比较
移除 Unicode 空白后的正文；标题或纯排版修改只保存在前端本地备份，
除非作者显式强制保存新版本。旧 published 版本不可变，保留供稳定引用。
API 提供四种写入模式：

1. **发布草稿**（`POST /drafts`）→ 原位提升当前 draft + 自动入队 `publish_chapter` 任务；响应的 `new_version=false` 表示无实质变化且未入队
2. **更新草稿**（`PUT /drafts/{id}`）→ working 可原地暂存；published 以 copy-on-write 返回新 draft ID
3. **显式留版**（`POST /drafts/{id}/checkpoint`）→ 将 auto 版本标记为 manual，或创建新 manual 版本
4. **放弃更改**（`POST /drafts/{id}/discard`）→ 软废弃最新 draft 并返回 `base_draft_id`

auto 工作版本在发布前撤回到手动 checkpoint 内容时，auto 版本软废弃，
手动 checkpoint 按原版本号原位提升为 published 并正常入队；若基线已经 published，
则复用它且不重复入队。历史恢复使用 `restore_source_version` 标识来源版本，
并用既有 `expected_version / expected_updated_at` 校验选择恢复时看到的章节最新快照，
过期操作返回 409。

`canonical` 选择每章最新非废弃 `published`，缺失时不回退 working；
`working` 只选择最新的 `draft / published / canonical` 兼容版本，不选择未采用
`candidate`。删除单版本或整章只标记 `deprecated`，
版本号永不重排。

## Facade

```python
async def create_draft_only(db, novel_id, chapter_index, title: str | None = None, content: str = "") -> WritingDraftContract
async def create_published_draft_only(db, novel_id, chapter_index, title: str | None = None, content: str = "") -> WritingDraftContract
async def create_published_drafts_only(db, novel_id, chapters: list[dict[str, object]]) -> list[WritingDraftContract]
async def create_draft(db, novel_id, chapter_index, title: str | None = None, content: str = "") -> tuple[WritingDraftContract, str]
async def get_draft(db, draft_id) -> WritingDraftContract | None
async def adopt_candidate_to_working(db, novel_id, draft_id, *, adopted_by="author") -> WritingDraftContract
async def get_latest_draft_for_chapter(db, novel_id, chapter_index) -> WritingDraftContract | None
async def list_latest_drafts_for_chapters(db, novel_id, chapter_indices, *, content_limit: int | None = None) -> list[WritingDraftContract]
async def list_chapter_indices(db, novel_id) -> list[int]
async def get_author_attention_items(db, novel_id) -> list[WritingAuthorAttentionItemContract]
async def list_manuscript_sources(db, novel_id, chapter_indices=None, *, content_mode="canonical") -> list[WritingDraftContract]
async def grep_manuscript(db, novel_id, pattern, *, content_mode="canonical", ...) -> ManuscriptSearchPageContract
async def read_manuscript_range(db, novel_id, source_ref, *, before_paragraphs=0, after_paragraphs=0) -> ManuscriptReadContract
```

facade 的 create 系列只暴露跨模块 `WritingDraftContract`，不返回 API response schema；REST API 层继续负责把 contract 适配为 `WritingDraftResponse`，保持 HTTP response body 不变。

文件导入通过批量入口一次锁定排序后的章节键、分组读取各章最大版本并统一 `add_all` / flush；版本唯一约束、事务回滚和逐章发布任务语义不变。

## 跨模块依赖

outline 可以只读消费 writing facade/contracts 中的草稿和章节索引。writing 需要调用
outline 时不在服务模块顶层 import outline facade，而是通过可注入 Scene contract loader
完成。默认 loader 在调用时 lazy import `modules.story.facade`；Story 继续通过
writing facade/contracts 只读消费草稿与章节索引。

## API

```
POST   /api/writing/drafts                              # 发布草稿（新版本 + publish_chapter 任务）
GET    /api/writing/drafts/{id}                         # 获取草稿
POST   /api/writing/drafts/{id}/adopt                   # 将 AI 正文建议复制为普通工作稿
POST   /api/writing/drafts/{id}/checkpoint              # 显式保存未发布版本
POST   /api/writing/drafts/{id}/discard                 # 放弃未发布更改并回到基线
PUT    /api/writing/drafts/{id}                         # 暂存；published copy-on-write，支持 expected_version
DELETE /api/writing/drafts/{id}                         # 软废弃单个版本
DELETE /api/writing/chapters/{index}                    # 软废弃整章所有版本
GET    /api/writing/chapters/{index}/draft              # 按章节索引获取最新草稿
GET    /api/writing/chapters/{index}/versions           # 章节版本历史
GET    /api/writing/chapters                            # 列出有草稿的章节索引
POST   /api/writing/conflict-checks                    # 创建剧情设定冲突检查
GET    /api/writing/conflict-checks                    # 获取章节/Scene 检查历史
GET    /api/writing/conflict-checks/{id}               # 获取检查详情
POST   /api/writing/conflict-checks/{id}/ai-review     # 兼容同步入口（deprecated）
POST   /api/writing/conflict-checks/{id}/ai-review-task # 提交异步 AI 软冲突判断任务
PATCH  /api/writing/conflict-check-items/{id}          # 更新问题处理状态
POST   /api/writing/conflict-check-items/{id}/ai-suggestion # 兼容同步入口（deprecated）
POST   /api/writing/conflict-check-items/{id}/ai-suggestion-task # 提交单条 AI 修复建议任务
POST   /api/writing/drafts/autosave                    # 创建纯草稿版本，不发布；合并标脏 working 索引
POST   /api/writing/generate                            # 生成正文建议预览，不自动采用或发布
POST   /api/writing/semantic-reviews                    # 冻结正文/合同的独立语义审查
POST   /api/writing/targeted-revisions                  # 按审查 finding 生成新返修候选
```

## 稳定原文引用

`SourceRangeRefContract` 保存 draft/chapter/version/content mode、章内 offset、
`source_hash` 与 `range_hash`。范围不跨章；读取时必须校验 novel 归属、
版本与 hash。原文 grep 为有长度/结果上限和分页的字面搜索，V1 不开放正则。

## 版本历史

`GET /chapters/{index}/versions` 返回该章活跃的工作/已发布版本，增补
`status / version_origin`；不把 candidate/deprecated 混入作者版本历史。

## 多 Tab 冲突检测

`PUT /drafts/{id}` 支持 `expected_version` 字段；当传入期望版本与当前最新版本不一致时，后端返回 409。
前端 E2E 覆盖了其他会话发布新版本、其他 Tab 暂存同一草稿两类 409 用户路径。

## 剧情设定冲突检查

`POST /api/writing/conflict-checks` 是写作页的规则层检查入口。前端会在发起检查前弹出选项；兼容字段 `include_candidates` 仍控制待处理世界对象，但地图册图片不参与正文事实检查。

规则层检查只对当前 Scene 的有效正文范围做确定性字面预检：

- 注入的 Scene contract loader 提供 `must_happen` / `must_not_happen` 和当前章 `scene_chunks`；只有全部目标范围有效且已有 `source_content_hash` 仍匹配本次正文时才检查，缺失、越界、部分无效或 hash 失效均返回 `degraded` 和 omission，不回退扫描整章。旧的无 hash 范围继续按边界校验兼容。
- `forbidden_present` / `required_missing` 保留兼容 kind，但严重度降低并派生 `author_action=can_improve`；它们只表示“疑似字面命中”或“未逐字出现”，不证明语义冲突。
- 检查 scope 保存正文 hash。Project Today 只读取每个章节/Scene 最新检查的 open 项；若工作稿 ID、版本或 hash 已变化，则旧项折叠为一条“重新检查”。

问题项的 `location_json` 保存轻量证据结构：`source` 描述来源模块、类型、标签、字段和摘录；`open_target` 描述前端可以打开的目标；`needs_review_reason` 描述候选证据复核原因。发布章节时，最近一次检查会归档到 `writing_drafts.conflict_check_snapshot_json`，快照保留 `source` / `open_target`，但不保留正文 `text_range`。

AI 能力是显式追加流程，不替代规则层结果：

- `ai-review` 必须使用 action 为 `writing.conflict_check.ai_review` 的 `context_confirmation_id`。
- `ai-suggestion` 必须使用 action 为 `writing.conflict_check.ai_suggestion` 的 `context_confirmation_id`。
- AI 软冲突和建议只写入检查项，不修改正文、Scene、地图册、世界对象、记忆或已采用资产。
- 手动 AI 复核把规则项视为未确认的字面预警；只有发现真实语义偏差时才追加独立的 `scene_commitment_missing` / `scene_forbidden_deviation`，不会自动关闭字面项。
- 正文生成、整体验证和单条建议的官方前端提交前保存 operation receipt；刷新后只查询原
  task，404 提示重新开始且不自动重放。任务结果原位更新进度/候选/检查区，不覆盖作者期间
  的正文输入、筛选、焦点或滚动。

## AI 正文建议与采用

`POST /api/writing/generate` 只创建作者可见的正文建议。兼容期底层仍保存为
`status="candidate"`，但它不会进入 latest working、项目正文统计、原文 grep 或 Evidence indexing
working 来源，也不会自动发布。
生成任务会把确认记录的 `compile_options.requested_chapter_index` 与请求目标章作失败关闭的
一致性校验。跨章 Scene 为提高检索相关性可把 `chapter_index` 改为 Scene 末章锚点；它不改变
作者此次要生成的章节，也不能让该 confirmation 复用于锚点章节。仅历史 confirmation
缺少 `requested_chapter_index` 时兼容读取 `chapter_index`。
入队会固定 secret-free 项目 LLM execution snapshot。worker 在有 lease fence 的
prepare 中冻结 prompt、确认上下文/证据指纹和 POV hidden guard，提交后才等待
provider；finalize 会按 project-first 顺序重验 profile、上下文与当前最新 running task owner。
同一 confirmation 的新任务会取代旧任务；取消、lease 丢失、项目删除或输入漂移
会使 candidate 与 confirmation bind 在最终任务事务中一起回滚。

`writing_drafts.provenance_json` 保存 AI 生成来源追踪：

- `source_confirmation_id` / `context_confirmation_id`：本次使用的 AI 参考资料确认记录
- `generation_profile`：`default` 或 `pov_character`
- `prompt_name` / `prompt_hash` / `model`：生成 prompt 与模型审计信息
- `pov_view`：角色视角结构化结果（仅 `pov_character`）
- `pov_validation`：角色视角 deterministic 泄漏诊断；`passed` 只表示“未发现明显越权”，不是绝对安全保证
- `scene_execution_bundle_hash / upstream_manifest`：冻结 Scene、StoryOutline revision 与 execution profile
- `independent_review`：独立 reviewer task、正文 hash、verdict、finding IDs 和阻断数

生成存在 Scene 的正文时，writing 通过
`outline.facade.get_scene_execution_bundle` 消费 version-bound
`story_execution_profile.v1` 与 Scene 执行字段。候选打开时投影
upstream stale，采用时重算并在任一 source hash 漂移时 409。

`writing_semantic_review` 与 generator 使用不同 managed task/run，支持
selection/volume/book，冻结目标正文、相邻章回归上下文、
StoryOutline/Scene/profile 和 hash manifest。回执包含 coverage、finding_id、
severity、location、contract refs、preserve 与 not_checked；机械门不能
代替文学语义通过。`writing_targeted_revision` 绑定 review findings、
base/hash、contract hash、allowed scope、preserve/must_not_change 和 supersedes，
只创建新 candidate。返修结果再经独立审查方可采用。

POV 角色视角建议即使诊断为 `failed` 仍保留原始建议；前端标红风险。作者调用
`POST /drafts/{id}/adopt` 后，服务以 copy-on-adopt 创建最高版本号的普通 draft，记录
`adopted_from_candidate_id / adopted_at / adopted_by`，并把原建议转入历史。重复采用同一建议
会被拒绝。

## 手动工作台

Writing Vue 工作台由 `frontend-console/vue/views/writing/` 承载：

- **左侧章节树**：按章节顺序只显示状态、章号、标题和字数；Scene 不进入章节目录
- **中间编辑器**：textarea + 保存/上一章/下一章/导出
- **右侧 Scene 副驾驶**：顶部手动选择本章关联 Scene，下方展示对应
  goal / core_conflict / emotional_beat / must_happen / must_not_happen / narrative_tag；
  光标移动不改变 Scene，写作 AI、冲突检查和发布检查统一使用手选 Scene
- **章节关联**：副驾驶可幂等关联已有 Scene，或用名称快速创建并关联；不伪造正文范围，
  解除、排序、合并和拆分仍在 Scene 工作台完成
- **版本历史**：模态框列出所有版本，支持预览和恢复
- **剧情设定冲突检查**：检查前选择是否包含待处理对象；检查结果按“字面预警”和 AI 判断分组，支持证据抽屉、来源打开、正文定位、状态更新和复制 AI 修复建议；Today 深链可直接打开并定位当前最新检查项
- **深度导入按钮**：启动前说明并确认自动采用范围，提交持久化授权快照；运行中显示三阶段进度，完成后展示已采用/待处理/未采用汇总
- **场景自动提取**：编辑器顶部 AI 工具菜单和 Scene 工作台复用 imports Scene stage，
  对手写或导入的章节正文执行统一的 Phase 0/1a/1b（高质量模式再执行 Phase 1c）与
  Scene commit；启动前明确授权采用范围，低置信或边界不确定结果进入待复核

## 真实 LLM 验收

真实 LLM 写作冲突检查默认跳过，不进入常规 CI。手动验收覆盖规则层冲突、记忆证据、AI 软冲突、AI 修复建议、状态更新和发布快照归档：

```bash
cd backend
RUN_REAL_LLM_TESTS=1 pytest modules/writing/tests/test_conflict_checks_real_llm.py -q -s

cd frontend-console
ENABLE_REAL_LLM=1 npx playwright test e2e/writing-conflict-real-llm.spec.js --reporter=list --timeout=300000
```

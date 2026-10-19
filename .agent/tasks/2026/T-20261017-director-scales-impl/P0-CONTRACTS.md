# P0 契约冻结（导演多尺度独立探索 · 第一批）

状态：2026-10-17 冻结，作为 Wave1/2 并行实现的接口基准。基线 origin/main `6004d3703`；
`make docs-check BASE_REF=origin/main` 已通过。任何字段变更须先改本文档并同步两个并行分支。

本文件把计划 §5 第一批的"待 P0 落实的技术细节"固化为可并行实现的精确契约：
输出存储承载、confirmation 序列化字段、操作目录版本、gate 登记名、迁移与旧路径 fail-closed 清单。

## 0. 三个 fixture（固化，测试与教程共用）

| 编号 | 输入（合成 fixture，非文学金标） | 首次结果 | 禁止 | 退出点 |
| --- | --- | --- | --- | --- |
| B1 sandbox | 空项目提问："这个城镇每天只有一小时重力减半，面包师的一天会怎样？" | 一条有条件影响链 + 受影响者 + 成立条件 + 未知；可保存结束 | 不读取章节；不编造精确生产率；不跑全城人物 | 保存/退出即结束，不进入事件层 |
| B2 event | 粘贴："信使不知道地址，却当天把信送到了本人手里"，只要求找缺口 | 诊断指出缺失信息；仅当明确请求补桥才给候选路径及所需条件 | 诊断不改原案；指定结果禁止巧合时允许"无法成立"并列缺项；不自动建事件/Scene/正文 | 诊断结束即退出 |
| B3 scene_line | "A 刚失业；B 不知此事，只看见 A 很疲惫"，要求 B 真诚回应一句 | 一句对白 + 简短依据/未知 + 可选一处动作 | B 不得说出失业秘密；不生成全员表演卡/多角度/整场正文 | 保存一句即结束 |

每项均支持临时开局与已有 Scene 锚点两条路径；"说详细点"绑定当前结果，不暗扩尺度/资料/联网/根预算。

## 1. 起点判别契约（story 域 + evidence 确认共用）

判别联合，`kind` 为判别键。定义于 `backend/modules/evidence/compilation/schemas.py`（Evidence 侧权威），
story 经 `modules/evidence/contracts.py` 再导出引用；story 侧不复制定义。

```python
class SceneAnchorStart(DirectorExplorationBaseModel):
    kind: Literal["scene_anchor"]
    scene_id: str          # UUID；必须存在于本作品（复用 STORY_GET_SCENE_CONTRACT 校验）

class CandidateRef(DirectorExplorationBaseModel):
    ref_id: str            # ^c_[a-z0-9_]{1,63}$，作者侧标识，仅任务内有效，禁冒充正式 ID
    label: str             # 1..100
    role: Literal["character", "location", "item", "organization"]

class Assumption(DirectorExplorationBaseModel):
    kind: Literal["world_rule", "state", "identity"]
    text: str              # 1..2000

class KnowledgeEntry(DirectorExplorationBaseModel):
    subject_ref: str       # CandidateRef.ref_id（临时主体）或 canonical 角色 entity_id
    knows: list[str]       # 各 1..500，≤20
    observed: list[str]    # 各 1..500，≤20
    misbelieves: list[str] # 各 1..500，≤20

class CanonicalSceneStimulus(DirectorExplorationBaseModel):
    subject_entity_id: str # 正式角色 entity_id；存在性+canonical 校验
    stimulus: str          # 1..500 场景本地刺激/假设

class WebRef(DirectorExplorationBaseModel):
    url: str               # http/https，无凭据
    title: str             # 0..300
    retrieved_at: str      # ISO8601 带时区
    content_hash: str      # 64hex
    excerpt: str           # 0..2000，截选非全文

class ProvisionalStart(DirectorExplorationBaseModel):
    kind: Literal["provisional"]
    question: str                      # 1..4000，作者原问题/片段
    assumptions: list[Assumption]      # 1..50（至少一条）
    candidates: list[CandidateRef]     # 0..50
    canonical_refs: list[str]          # 0..24 正式 entity_id（uuid）
    knowledge: list[KnowledgeEntry]    # 0..50；subject 必须是候选或 canonical 角色
    scene_stimuli: list[CanonicalSceneStimulus]  # 0..50，仅对 canonical 角色的场景本地刺激
    author_private: list[str]          # 0..20，各 1..2000；仅作者包，永不进入角色包
    time_basis: Literal["assumed_now"] | str   # "assumed_now" 或 1..500 的锚点描述
    web_refs: list[WebRef]             # 0..10；仅来自助手当轮已读网页（服务端核对快照）

ExplorationStart = Annotated[SceneAnchorStart | ProvisionalStart, Field(discriminator="kind")]
```

规则：
- `web_refs` 只能由服务端从助手 turn 的 `web_snapshot` 已读证据填充；请求体传入的一律丢弃并告警
  （不开网不检索，先检索后补授权禁止）。
- `author_private` 进入作者侧 prompt 上下文与确认记录，绝不进入任何角色包（含 canonical 刺激包）。
- `knowledge` 只描述临时主体（候选）；canonical 角色的知识仍走资料投影 + hidden guard，
  作者仅可附 `scene_stimuli`（标记为"场景本地假设"，不升级为正史）。
- 跨作品引用（canonical_refs 不属于本 owner/novel、候选 ref 冒充正式 ID）在确认编译前失败关闭。

## 2. Evidence 确认契约（新请求类型 + 重物化）

### 2.1 新请求类型（不改动现有 ContextCompileRequest 语义）

`backend/modules/evidence/compilation/schemas.py` 新增：

```python
class ExplorationContextRequest(ContextSelectionRequest):
    action: str            # 必须前缀 "story.exploration."（校验见 2.3）
    exploration_scale: Literal["sandbox", "event", "scene_line"]
    focus: str = ""        # 0..2000，作者指定焦点/详略，可空
    start: ExplorationStart
```

`ContextConfirmRequest` 不变；探索确认复用同一 confirm 流（`expected_context_fingerprint` 机制），
preview/confirm 以 `ExplorationContextRequest` 为请求体经新 facade 入口。

### 2.2 能力注册（CAPABILITY_REGISTRY，policies.py）

新增四条，均 `CONFIRMATION_REQUIRED`、gate 标记 `STORY_EXPLORATION_ENABLED`、无特殊 scope 豁免：

- `story.exploration.sandbox`（B1）
- `story.exploration.event`（B2 诊断与补桥同能力）
- `story.exploration.scene_line`（B3）

`retrieval_purpose`：`story.exploration.*` 走现有 `story.* → story_generation` 前缀解析，不新增枚举值。
`resolve_retrieval_purpose` 的 story 三动作硬绑定不含 exploration 动作，无需改动。

### 2.3 服务端校验（新 `_validate_exploration_request`，confirm/preview 共用）

1. action 前缀 `story.exploration.` 且 ∈ {sandbox.generate, event.diagnose, event.bridge, scene_line.generate}
   （detail/revise 编辑类不新开 confirmation，复用根确认）。
2. `start.kind == "scene_anchor"` 时：scene 存在性 + `visible_until_scene_id == scene_id`
   （对齐 `_validate_confirmed_scene_scope` 现行为）。
3. `start.kind == "provisional"` 时：`scene_id` 必须为空；assumptions ≥1；
   canonical_refs / scene_stimuli 的 entity 存在且 canonical 且属于本作品；
   knowledge.subject_ref 必须解析到候选或 canonical 角色；web_refs 非空时逐条核对
   URL 白名单与 content_hash 格式。
4. reveal_mode：作者包 `author_safe`；仅当任务需要 canonical 角色 POV 时允许 `character`
   且必须给 `viewpoint_character_id` + 截止点（现有校验不变）。

### 2.4 compile_options 冻结字段与重物化

confirm 时写入 `compile_options` JSON 的额外键（自动被 `compiled_context_fingerprint` 覆盖，
无新 DB 列）：`start_kind`、`exploration_start`（整个 start 判别联合 dump）、`exploration_scale`、
`exploration_focus`。

`compile_from_confirmation` 扩展（confirmation_service.py）：
- `start_kind == "provisional"`：跳过 outline 指纹门与 scene_state 指纹门（无 Scene/大纲分析）；
  仍重编译项目资料并核对核心指纹（`context_changed` 语义不变）；空资料集即空 sections +
  指纹仍计算；hidden guard 按 canonical_refs 重建（候选主体不进 guard 目标集）。
- `start_kind == "scene_anchor"`：现有全部门禁不变。
- 两种情况都把持久化的 `exploration_start` 回传给调用方（worker 校验与请求一致，不一致失败关闭）。

### 2.5 角色知识边界（B3）

- 临时主体（候选）：其输入包 = 该主体 `KnowledgeEntry`（knows/observed/misbelieves 逐条列出），
  由服务端从冻结 start 渲染；未声明信息一律未知；作者 private 不进入。
- canonical 角色：`read_object_dossier_brief` + `restrict_object_dossier_brief` + hidden guard
  现有链路不变；`scene_stimuli` 以"场景本地假设（非正史）"前缀并入该角色包。
- 生成后守卫：canonical 目标沿用 `build_hidden_guard_context` 消费方校验
  （generation 后检查，位置与现有 writing/director 一致）；候选目标无 hidden_truth 可泄，
  以知识包构造为唯一边界。

## 3. 存储承载与 Alembic（一次迁移，单一写入者）

### 3.1 复用既有根/分支/结果表，输出载荷判别联合

- 沙盘/事件 → `story_world_progression_*` 三表；场景对白 → `story_scene_director_*` 三表。
  不新建事件模块或通用探索表（计划 §3.3 既定）。
- 结果行 `output_json` / `result_json` 载荷包装：

```json
{
  "output_kind": "story.exploration.sandbox | story.exploration.event | story.exploration.scene_line | story.exploration.author_edit",
  "schema_version": 1,
  "payload": { ... }
}
```

- 旧载荷（`DirectorRoundResult`、推进结算结果）不含 `output_kind`，读取方据此区分；
  旧解释逻辑遇到 `output_kind` 存在的行必须 fail-closed（见 §7）。
- 修订/详略/作者编辑 = 新结果行：`parent_round_id`（导演）指向来源行；同分支 `round_number`/`step_number`
  递增沿用唯一约束；`input_json` 记录 `{revision_of, changed_item_hash, mode}`；
  作者编辑行不消耗模型请求（零模型调用，无预算）。
- 同起点重来 = 同根新分支（沿用 reroll 语义）；比较端点校验两行 `start_fingerprint` 相同才可比。

### 3.2 两根表迁移（唯一 Alembic 迁移，down_revision = `20261017_wp_scope_stop`）

对 `story_scene_director_roots` 与 `story_world_progression_roots`：
1. `ALTER TABLE ... ADD COLUMN source_kind VARCHAR(16) NOT NULL SERVER_DEFAULT 'scene'`
   + `CHECK (source_kind IN ('scene','provisional'))`。
2. `ALTER COLUMN scene_id DROP NOT NULL`。
3. `ADD CONSTRAINT <table>_start_kind_valid CHECK ((source_kind = 'scene') = (scene_id IS NOT NULL))`。
4. 新增索引 `ix_<table>_novel_source_created (novel_id, source_kind, created_at)`。
5. `context_confirmation_id`（推进根）保持 NOT NULL：临时起点也必须有确认（空资料集确认）。

downgrade：先检查两表是否存在 `source_kind='provisional'` 行，存在则 raise（拒绝破坏性降级）；
不存在才 DROP 约束/索引/列并 `SET NOT NULL`。

### 3.3 ORM 与模型

- 两根模型：`source_kind: Mapped[str]`（默认 "scene"）、`scene_id: Mapped[str | None]`；
  既有 Scene 列与索引保留；历史读取按原协议解释（`source_kind='scene'` 行为完全不变）。
- 服务层创建函数：`source_kind='provisional'` 时强制无 scene_id；`'scene'` 时强制有。
  不经 ORM 默认值侥幸，显式校验。

## 4. 输出 schema（四类 payload，各自字段）

统一版本 `schema_version: 1`。全部 `extra="forbid"`、字段长度受限、`unknowns` 为一等字段。

- `story.exploration.sandbox`：`question`、`focus`、`influence_chain: list[InfluenceLink]`（1..12；
  InfluenceLink = {condition, mechanism, effect, affected_refs, holds_when, unknown?}）、
  `preconditions: list[str]`（0..12）、`unknowns: list[str]`（0..12）、`warnings: list[str]`。
  允许仅回答一条后果（chain 长度 1）。
- `story.exploration.event`：`mode: Literal["diagnose","bridge"]`、`original_excerpt`、
  `gaps: list[GapFinding]`（diagnose ≥1；GapFinding = {description, why_needed, possible_fix_hint?}）、
  `bridge_candidates: list[BridgePath]`（仅 bridge 模式，0..6；BridgePath = {steps: list[str] 1..8,
  required_conditions: list[str], cost_or_risk, holds} ）、`unsolvable: {reason, missing: list[str]} | None`
  （bridge 模式无可信路径时必填）、`unknowns`、`warnings`。diagnose 模式禁止 `bridge_candidates`。
- `story.exploration.scene_line`：`target_ref`（候选 ref_id 或 canonical entity_id）、
  `line: str`（1..500，一句对白）、`rationale: str`（1..2000，依据/知识来源说明）、
  `action: str | None`（0..300，可选一处动作）、`knowledge_basis: list[str]`、
  `withheld: list[str]`（目标角色知道但不说出的内容，含误信修正说明）、`unknowns`、`warnings`。
- `story.exploration.author_edit`：`base_output_kind`、`base_result_id`、`edited_payload`（同构基础 payload）、
  `edit_note: str | None`。服务端校验 edited_payload 与 base 同构（schema 校验），不改尺度/资料/联网。

返回"缺条件/无法支持"是合法结果（`unsolvable`、`unknowns` 承载），不编造完成。

## 5. 预算、信封与幂等

- 新 `ExplorationBudgetPreview`：sandbox/event/scene_line 初始 `requests_min = requests_max = 1`
  （token 区间按输入包长度估算，沿用现有算法风格）；preview 声明
  `follow_up_max_requests = 1`（"说详细点"/补桥/局部修订每次 +1，须重新 preview + 授权）。
- 根信封：`AIRunEnvelope(budget_mode="bounded")`，root_capability_id = `story.exploration`
  （TaskRegistry 经 `@task_handler(root_capability_id=...)` 注册，同 director 先例）。
- 追加授权 reason 枚举扩两名：`author_detail_expand`、`author_revise`（现有
  `duplicate_charge_confirmed | author_resume` 之外，不改旧值）。
- 幂等：沿用 `get_operation_task(operation_id, task_type, novel_id, submission_fingerprint)`；
  fingerprint = 请求去 operation_id。作者编辑保存另用 `save_edit` 幂等键
  `(novel_id, base_result_id, edit_content_hash)`。
- 任务注册：`story_exploration_progression_task`（B1/B2，写推进步骤，recovery_policy="never_retry"）
  与 `story_exploration_scene_task`（B3，写导演回合，同策略）；worker 校验信封身份、
  重算 preview hash、检查点（pending_round_json / pending_step_json）沿用现有机制。
- prompt：新 step_name `story.exploration.sandbox.generate` / `event.diagnose` / `event.bridge` /
  `scene_line.generate`；每任务一个有界生成步骤，无规划/自评轮；离线夹具沿用
  DirectorOfflineProvider 模式扩展。

## 6. 操作目录与运行时版本

新增 `backend/modules/story/exploration_operations.py`，OPERATIONS_SPEC 六项（op_version "1"）：

| op_id | permission | risk | fee | 说明 |
| --- | --- | --- | --- | --- |
| story.exploration.preview | read | R0 | free | 推荐+预算+确认范围预览 |
| story.exploration.start | confirm | R2 | possible_model_charge | 发起任务（202） |
| story.exploration.detail | confirm | R2 | possible_model_charge | 说详细点（授权追加） |
| story.exploration.revise | confirm | R2 | possible_model_charge | 局部修订/补桥 |
| story.exploration.compare | read | R0 | free | 同起点比较 |
| story.exploration.history | read | R0 | free | 探索历史（gate 关闭可读） |

- 目录组装（app/assistant_operation_registry.py import + bootstrap 合并）、
  目录快照测试更新（tests/unit/test_assistant_operation_registry.py）、
  runtime_version `"17" → "18"`（runtime_protocol 接受集 + service.py 提交写入 + 前端常量）
  由 Wave2 后端代理单一负责。
- gate：`core/config.py` 新增 `story_exploration_enabled = _env_bool("STORY_EXPLORATION_ENABLED", False)`
  （默认关闭）；`modules/story/exploration_feature.py::require_story_exploration_enabled()`
  抛 503 `story_exploration_disabled`；挂新路由 + operations prepare/apply + 两个 worker。
  history/compare 端点不挂执行 gate（关闭后可读历史）；operations history 亦不 gate。

## 7. 旧路径 fail-closed 清单（新增校验，不删旧校验）

1. 导演 `continue/advance/resume`：分支最后一个结果行若带 `output_kind` → 拒绝
   （"该分支包含紧凑探索结果，请在对应任务上继续"）。
2. 推进 `advance / resume / hooks preview/adopt / continuous authorization`：
   根 `source_kind == 'provisional'` 或最后步骤带 `output_kind` → 拒绝。
3. `save_director_reference`（参考剧本）：根 `source_kind='provisional'` 或来源行带 `output_kind` → 拒绝
   （正式参考仍要求 Scene 非空；临时→正式参考是 M4）。
4. `transfer_world_candidate`：来源行带 `output_kind` → 拒绝。
5. Writing 消费（`read_director_references_for_writing`）：天然不受影响（参考不产生于临时根），
   无需改动；M4 前保持现状。
6. 历史端点：Scene 型根原样返回；provisional 根单独列出（不与 Scene 历史混排），
   前端按 `source_kind` 分流渲染。
7. 双方 worker/服务所有查询保持 `novel_id` + owner 过滤；探索历史 API 同时校验
   account principal 与项目 owner（复用 `_require_project` 模式）。

## 8. API 面（新增，全部显式版本化请求）

新文件 `backend/modules/story/exploration_api.py`（router prefix `/api/story/exploration`，
统一 owner+novel 校验）：

| 端点 | 语义 |
| --- | --- |
| POST `/preview` | 推荐（确定性，无模型调用）+ 预算 + 所需确认范围预览 |
| POST `/confirmation/preview` | 经 Evidence facade 生成探索确认预览 |
| POST `/confirmation` | 落确认（expected_context_fingerprint 机制） |
| POST `/start` | 入队（幂等 + preview hash + 确认校验）→ 202 {task_id, root_id, branch_id} |
| POST `/results/{result_id}/detail` | 说详细点 → 202（授权追加；body `{novel_id, operation_id, focus?}`） |
| POST `/results/{result_id}/revise` | 局部修订/补桥 → 202；body `{novel_id, operation_id, revision_of?, item_path (1..120，形如 chain:0/gap:1/bridge:2/line), item_text? (≤4000，防漂移比对), instruction (1..2000)}` |
| POST `/results/{result_id}/save-edit` | 作者编辑新版本（零模型调用）；body `{novel_id, base_output_kind, edited_payload, edit_note?}` |
| POST `/compare` | `{novel_id, first_result_id, second_result_id}` → `{first:{result_id,root_id,branch_id,output_kind,payload,created_at}, second:{...}}`（指纹不同 409） |
| GET `/history` | `items[]` 平铺 `{root_id, branch_id, result_id, scale, output_kind, label, start_fingerprint, created_at, payload}`（gate 关闭可读） |

### 8.1 集成期冻结的补充契约（2026-10-17，Wave1 回收后）

1. `POST /preview` body：`{novel_id, operation_id, scale?, focus?, start?, task_hint?}`；
   响应 `{recommended_scale, recommendation_reason, focus_hint, budget, requires_confirmation, ...}`；确定性、无模型调用。
2. 任务终态 `AsyncTask.result` 统一含 `{status:"completed", result_id, root_id, branch_id, output_kind, payload}`
   （detail/revise 为新生成行；前端 pollTaskProgress 就地渲染）。
3. 助手 `display_sources.domain_reference` 白名单扩展：`story_exploration_result`
   （root_id/branch_id/result_id/scale/output_kind/payload/label）、`story_exploration_recommendation`
   （scale/focus_hint/reason）。
4. 修订条目定位用 `item_path + item_text`（服务端以 item_text 与父结果内容比对防漂移，
   并把服务端计算的条目内容 hash 记入新行 input_json）；不用客户端摘要做定位键。

助手 turn 集成：_operations 目录注册后，作者在助手中自由提问 → preview op 返回推荐
（`recommend_exploration(scale_hints, has_selection, has_content)` 纯确定性函数，
放 `modules/story/exploration_recommend.py`）→ 作者确认 → start op（confirm 权限走既有批量确认流）。
消息关联：助手回复消息 `task_id` 指向探索任务（现有关联机制）；
`display_sources.domain_reference` 新 type `story_exploration_result`
（{root_id, branch_id, result_id, scale, label}）。

## 9. 前端契约（冻结，供 P3 并行）

- 助手：`ProjectAssistant.vue` 结果卡新增 `story_exploration_result` 渲染分支
  （按 output_kind 三态渲染紧凑结果 + 保存编辑/说详细点/局部修订/比较按钮 + 恢复）；
  `useProjectAssistant.js` 复用 send/轮询/待确认持久化；`assistantContext.js` 选区捕获复用。
  新 API 经 `vue/bridge` 的 api 对象扩展（`story.explorationPreview/Start/...`）。
- 免登录轮询：沿用 `pollTaskProgress`；重复提交沿用 operation_id + pending 载荷机制。
- 就地入口：第一批不改 SceneCockpit/WorldProgressionPanel 交互；仅要求两面板历史渲染
  对带 `output_kind` 的行不崩溃（显示"探索任务"占位 + 指回助手）。
- 键盘/窄屏/空态/失败/双保存失败按 testing-guide 常规断言。

## 10. 测试与验收映射

- 单测（SQLite）：§1/§2/§4 schema 校验、§2.4 重物化（含空资料集与 canonical guard）、
  §5 预算/幂等、§6 目录快照、§7 fail-closed 逐条、推荐函数。
- PostgreSQL（专用库 `ai_novel_director_impl_e2e`）：迁移 up/down（含 provisional 行存在时 down 拒绝）、
  CHECK 约束、触发器对新行生效、三任务离线 provider 全链（preview→start→worker→结果→detail→
  revise→save-edit→compare→history）、跨作品/异 owner 拒绝、旧路径 fail-closed。
- 前端 Vitest：§9 各行为。
- 收尾：`make test` 受影响模块、ruff、`make docs-check BASE_REF=origin/main`、`git diff --check`。
  真实模型/作者验证不执行（M5 另授权）。

## 11. Wave 分工与文件所有权

| Wave | 代理 | worktree/分支 | 拥有文件（独占写） |
| --- | --- | --- | --- |
| P1-E | Evidence | `.worktrees/director-scales-p1-evidence` | `backend/modules/evidence/**`（schemas/api/confirmation_service/policies/contracts/facade）+ evidence 测试 |
| P1-S | Story | `.worktrees/director-scales-p1-story` | `backend/modules/story/models.py`、`world_progression_models.py`、新 `exploration_schemas.py`（请求/输出/预算模型）、`exploration_feature.py`、`exploration_service.py`（仅根/分支创建与历史读）、`core/config.py`、新 Alembic 迁移、story 单测 |
| P2 | 后端执行 | 主 impl worktree | `exploration_tasks.py`（两 worker）、`exploration_progression.py`/`exploration_scene.py`（执行路径）、`exploration_api.py`、`exploration_operations.py`、`exploration_recommend.py`、operations 注册/runtime 18/快照、旧路径 §7 校验、tests |
| P3 | 前端 | `.worktrees/director-scales-p3-frontend` | `frontend-console/**`（api 对象、ProjectAssistant 结果卡、useProjectAssistant、面板占位、vitest） |
| P4 | 集成 | 主 impl worktree | 回归、PG e2e、README/数据库设计/Prompt 清单/能力登记/new-user-guide、ADR-0042 状态、docs-check |

接口基准 = 本文档；P1-E 与 P1-S 互不 import 对方新符号（story 只从 `modules/evidence/contracts.py`
取 §1/§2 定义；evidence 不 import story）。

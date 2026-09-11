# 剩余授权项实施计划

日期：2026-09-12

基线：`codex/full-optimization-implementation@0d5ea4b93c553caf2bf71a09d63ee9c9ad252504`

本计划落实用户对最后五个决策点的裁定，只规划、不实施业务代码：

- R5 保留，并扩展为完整的空间、时间、逻辑连续性检查与消费体系。
- X2-3 增加显式清理入口；“取消”只停止任务，“删除”由用户在深度导入面板的“回收站”明确触发。
- B1c 先逐项审计归类；只删除无消费者、无唯一证据且无明显保留价值的文件。
- B3c 允许在实施阶段调用真实付费模型完成迁移验收。
- F5-7 暂缓，不猜测生产代理网段，不改当前 Dockerfile。

## 1. 目标、非目标与不变量

### 目标

1. 让 Scene 级连续性从“仅有四维历史投影、Writing 未消费位置证据”升级为可追溯、可检查、可呈现、可用于生成与修订的完整闭环。
2. 让已取消深度导入的工作流资产可被作者明确、可预览、可重试地软清理，同时不把取消等同删除。
3. 清理仓库内没有明显价值的历史工件和受版权保护的测试原文，并保留真正有复现价值的验收证据。
4. 在真实模型任务轨验收通过后，删除 Writing 已弃用的同步生成/冲突双轨。

### 非目标

- 不做通用时态逻辑引擎、路径规划器或自动正史写回平台。
- 不从地图像素距离推断行程，不把 Map/Atlas 数据复制进 Scene memory，不写回地图。
- 不把模型判断自动持久化为已确认事实；除既有深度导入授权链外，连续性增量仍需作者明确确认。
- 不重写 Git 历史清除旧版权字节；本批只移除当前树中的原文样本并换成合成夹具。
- 不实施 B5、无性能基线候选或 F5-7。

### 必须保持的不变量

- 所有读写继续同时经过 account owner 与 `novel_id` 隔离；跨项目返回 404，不泄露对象是否存在。
- Evidence confirmation 的 selected/excluded、可见性、来源与指纹仍须重验；Scene-local 上下文不得读取未来 Scene。
- 缺失、不确定或过期证据只能显示“未检查/证据不足”，不能显示绿色通过，也不能用当前 World 回填过去。
- 已采用资产与导入成果只软废弃并保留历史；`hard_deleted_assets` 必须持续为 0。
- 每个叶子批独立提交、独立回滚；不合并、不推送、不部署。

## 2. 依赖与执行顺序

```text
R5a 契约版本
  └─ R5b 事件与投影
       ├─ R5c 确定性检查
       ├─ R5d Evidence/生成消费
       └─ R5e 作者确认与下游失效
              └─ R5f 前端与端到端验收
                     └─ B3c 任务轨真实模型验收与同步轨删除

X2-3a 后端预览/清理 ── X2-3b 回收站 UI ── X2-3c 并发与浏览器验收

B1c-0 分类账 ── B1c-1 工具工件 ── B1c-2 验收日志 ── B1c-3 合成样本

F5-7：独立暂停，不阻塞以上批次
```

R5 与 X2-3 可按独立提交交错实施，但同一文件只有一个写入者。B3c 必须等待 R5 的任务轨消费和真实模型断言稳定。B1c 先完成分类账，任何删除均不得先于分类结论。

## 3. R5：空间、时间、逻辑连续性体系

### 3.1 总体归属

不创建第二套连续性数据库或问题表：

- `modules.story.continuity` 继续拥有历史事实、事件顺序、Scene checkpoint、人工修复和重建。
- `modules.evidence.compilation` 继续负责把同一时点的可信状态编译成不可排除、可指纹化的 `scene_world_state`。
- `modules.writing` 继续使用 `WritingConflictCheck` / `WritingConflictItem` 作为确定性冲突与 AI 风险的统一问题账本。
- World Map/Atlas 只通过 World 稳定 facade 提供“已采用且带 revision/source hash”的只读空间证据。
- 深度导入只产生有原文引句的候选事件；Writing 只在作者确认后写入新的连续性事件。

### 3.2 R5a：版本化连续性契约

**改动**

1. 保留 V1 四维：`entities`、`relations`、`locations`、`knowledge`。
2. 新增 V2 两维：`timeline`、`causality`；`locations` 原名和历史语义不变，界面显示为“空间与位置”。
3. 给新生成的 checkpoint/full state 写入 `contract_version=2`；旧记录缺省解释为 V1，不批量伪造新维度。
4. `scene_world_state.retrieval_metadata` 增加 `contract_version` 与 `required_dimensions`。confirmation 指纹按记录的版本计算：旧 confirmation 继续按 V1 四维重验，新 confirmation 按 V2 六维重验。
5. 旧客户端字段保持不变；新增字段均为可选。历史 `continuity_location_mismatch` kind 只作已持久化记录的显示兼容，不再作为新规则输出。

**状态语义**

- `ready`：可重放的 system 事件或作者已确认状态。
- `retry_pending` / `manual_required`：沿用现有重建语义。
- 缺少 V2 维度：`missing/not_checked`，不可等同空事实或检查通过。
- `confirm_empty`：仅表示作者确认该 Scene 在该维度没有可记录事实，不表示未来 Scene 也为空。

**验收**

- 固定 V1 confirmation 样本在改动前后 fingerprint 字节一致。
- 新 V2 confirmation 包含六维版本；任一可信 checkpoint 版本变化都会使其 stale。
- 旧 Scene 不会因升级自动出现伪造的 timeline/causality ready checkpoint。

**回滚**

- 先停止产生 V2 confirmation，再 revert 消费端与契约端提交；V2 JSON 字段留存无害，禁止破坏性数据回滚。

### 3.3 R5b：事件输入与 Scene 投影

**最小状态模型**

- `locations`：沿用角色/对象当前位置，补充有来源的移动事实；不建通用路径图。
- `timeline`：只记录显式时间锚、可证明的 `before/after/same_time`、持续时间和截止条件。没有原文依据时不得把模糊日期换算为绝对序号。
- `causality`：只记录显式事实、前提、结果和未兑现承诺。使用稳定 claim key、值/极性及 source Scene/event 引用，不实现通用推理语言。

**输入来源**

1. 深度导入 Phase 2a 的 delta schema 向后兼容地允许 timeline/causality；每条必须保留原文引句、Scene 来源、置信度与不确定性。
2. 手工/写作链产生 proposed delta；只有作者确认后才转为 `MemoryEvent`。
3. 事件 replay 继续按 `scene_index + scene_sequence + id` 确定排序；不得读取当前 World 作历史 fallback。
4. 新事件确认后，从最早受影响 Scene 起只 supersede system-generated、未人工确认的对应维度 checkpoint，并重建后续稀疏快照。

**验收**

- V1 事件可与 V2 事件混合重放；相同输入重复执行得到相同 state/source hash。
- 未来 Scene 的证据不会进入当前 Scene checkpoint 或角色知识。
- 手工确认 checkpoint 不被自动重建覆盖。
- 导入旧输出仍可解析；新输出缺引用或维度非法时 fail-closed。

### 3.4 R5c：确定性检查规则

确定性检查在 Writing 的既有 `create_check()` 路径执行，结果仍写 `WritingConflictItem`。只新增三个公共 kind：

- `space_continuity_risk`
- `time_continuity_risk`
- `logic_continuity_risk`

细分规则放在现有 `location_json` 的稳定元数据中；`is_ai_judgment=false`。首批规则严格限定为能由结构化证据证明的情况：

**空间**

- 同一时点同一实体被明确标为位于两个互斥位置。
- 已知起点与终点之间存在显式移动，但正文/Scene contract 缺少必须的移动或交通前提。
- 只有当已采用 Map/Atlas fact 明确给出 containment、adjacency、route 或最小时长时，才报告对应矛盾；缺地图或 revision stale 时记为未检查。

**时间**

- 同一事件同时违反已确认的 before/after 关系。
- 明确持续时间或截止条件与已知锚点冲突。
- 原因/前提被安排在其结果之后，且两端时间顺序都有可靠证据。

**逻辑**

- 同一 claim 在同一有效时点出现互斥值/极性。
- Scene contract 要求的显式前提缺失或已被明确否定。
- 已确认的承诺/结果在规定边界到达后仍未满足；开放中的伏笔或未知状态不能判为矛盾。

每条问题必须带：证据摘要、来源 Scene/event、正文定位、规则码、检查覆盖状态，以及打开原始证据的目标。证据不足只进入 `summary_json.degraded_sources/not_checked`，不生成伪冲突。

### 3.5 R5d：Evidence、生成与审查消费

**Evidence 编译**

- 把 V2 六维写入 `scene_world_state`；导演态事实与角色可见知识继续分离。
- 扩展 Scene Lens：依次显示“人物与对象、关系、空间与位置、时间顺序、因果与前提、角色所知”；缺口显示原因和修复入口。
- `_uses_scene_world_state()` 扩到实际需要的 Writing 任务 action：正文生成、冲突 AI 复核、修订建议与独立语义审查；仍要求 Scene 与合法 reveal mode。

**正文生成**

- 把可信的 entry state、时间锚、因果前提、must/must_not 作为约束输入，不要求模型自行推断缺失状态。
- 输出仍是 candidate；模型不能直接修改 Scene memory。

**AI 软审查**

- 对冻结的 draft、同一 confirmation 和相同 hidden/context fingerprint 做语义检查。
- 复用三个公共 kind，设置 `is_ai_judgment=true`、置信度、精确正文引句、来源引用和覆盖声明。
- 无法检查的空间/时间/逻辑面必须列入 `not_checked`；模型不得把推测写成硬冲突。
- 独立 semantic review 的现有 `continuity` / `causality` 类别保留；新增可选 V2 coverage，旧 `timeline_location` 字段继续兼容。

**消费面**

- Writing 冲突列表和详情：统一呈现确定性与 AI 风险，保留 resolved/ignored/later。
- targeted revision：只针对作者选择的问题生成建议，不静默改稿。
- author assistant：只导航、解释或发起既有检查，不直接写回。
- RP：只读引用，不写回作者资产，保持 ADR-0018 相关边界。

### 3.6 R5e：作者确认与失效闭环

新增“连续性候选变更”只作为现有检查项/建议的附属结构，不建新顶层平台：

1. AI 或确定性检查提出 proposed delta，并绑定 draft/version、Scene、confirmation、正文 source hash。
2. 前端展示变更前后、依据、影响的后续 Scene 数量；作者可编辑、确认或拒绝。
3. 确认接口再次校验 owner、`novel_id`、expected check/item、draft/source hash 与 confirmation fingerprint。
4. 事务内写 author-confirmed `MemoryEvent`、记录 provenance，supersede 并重建受影响维度；幂等键防重复确认。
5. 旧 check、旧 confirmation 与依赖它的建议标 stale；重建失败保留事件与可恢复状态，不伪装成功。

不提供“一键采用模型全部判断”。深度导入只有在既有 workflow authorization 范围内可按原策略写入 workflow-owned 事件。

### 3.7 R5f：前端产品面与完整验收

**界面**

- Scene Lens 展示六维状态、证据缺口和人工修复入口。
- 冲突详情用作者语言显示“空间/时间/前提风险”，技术来源放次级展开，不暴露 raw JSON/ID。
- 连续性候选确认覆盖首次进入、空态、加载、失败、指纹冲突、离开恢复、窄屏与项目切换晚响应。

**门禁**

- Story continuity、Evidence compilation、Writing conflict/semantic/generation 模块测试。
- PostgreSQL：事件确认与 checkpoint 重建并发、项目删除/任务锁、CAS/幂等。
- 前端 Vitest、lint、build；桌面与 390px 浏览器各覆盖一次“发现问题→查看依据→确认修复→重新检查”。
- 使用合成的三 Scene 夹具同时覆盖：跨地点移动、相对时间倒置、缺失前提；另有证据不足不得报冲突的反例。
- R5 完成后更新 Writing、Story continuity、Evidence compilation 与 Prompt 清单文档。

## 4. X2-3：取消与删除分离、深度导入回收站

### 4.1 产品语义

- “取消任务”：只停止后续处理，已产生的 Scene、世界对象、结构和增量仍保留。
- “清理本次整理产生的内容”：仅在“回收站”由用户明确确认后执行，沿用现有 soft-deprecate/rollback；不是永久删除。
- 仅 cancelled 的 deep-import workflow、无活动 owner、且仍有 workflow-owned 可清理资产时可进入回收站。
- failed + recovery_required 继续使用现有“放弃恢复”流程，不与本入口混合。

### 4.2 X2-3a：后端预览、执行与回执

1. 扩展 `GET /api/imports/workflows/recent`，增加向后兼容的 `cleanup_eligible`、`cleanup_status` 与 `cleanup_summary`；不另建列表服务。
2. 增加 `GET /api/imports/workflows/{task_id}/cleanup-preview`，在用户确认前重新计算可软废弃范围、受保护冲突和 `cleanup_fingerprint`。
3. 增加 `POST /api/imports/workflows/{task_id}/cleanup`，请求必须包含 `confirmed=true` 与预览返回的 expected fingerprint。
4. 入口依次执行项目 owner/`novel_id` 校验、项目排他锁、run 行锁、cancelled 状态、无活动 owner、fingerprint 校验。
5. 复用 targeted completion rollback、review resolution rollback 和 `cleanup_workflow_assets()`；不复制清理实现。
6. 把 cleanup receipt/status 写入 run 的既有 checkpoints/progress JSON；重复请求返回同一回执，partial 可重试，complete 不再可操作。
7. 清理结果继续返回 `DeepImportCleanupSummaryResponse`；任何路径都不得增加硬删除。

### 4.3 X2-3b：深度导入面板“回收站”Tab

- `ImportDrawer.vue` 增加“导入记录 / 回收站”两 Tab；回收站不是项目永久回收站。
- 每项显示导入时间、章节范围、保留成果数量、清理状态与冲突数量，不显示 task/workflow raw ID。
- 取消后明确提示：“停止只会停止整理，已经产生的内容仍会保留。”
- 操作按钮：“清理本次整理产生的内容”。点击后先刷新 cleanup preview；确认弹窗列出预计软废弃的 Scene/对象/结构及可回滚项，明确历史仍保留。
- 处理空态、加载、预览 stale、确认中禁重复提交、partial、重试、完成、窄屏和切项目晚响应；继续复用现有 modal/confirmation 与 generation guard。

### 4.4 X2-3c：验收与回滚

**后端**

- cancel 后资产仍 active；未显式 cleanup 时零变更。
- 非 cancelled、跨项目、活动 owner、stale fingerprint 分别拒绝；响应不泄露跨项目存在性。
- cleanup 重放幂等；后续人工修改/引用导致的冲突进入 partial，未受影响资产仍正确软废弃。
- PostgreSQL 覆盖 cleanup 与 resume/new import/force reimport 并发。

**前端/浏览器**

- 桌面与 390px 各跑“取消→历史仍可见→进入回收站→预览→确认→完成”；另测取消确认和 partial 重试。
- 项目切换后旧请求不得覆盖新项目回收站。

**回滚**

- UI、API 适配、service/测试分提交 revert；已执行的软废弃按现有历史恢复能力处理，不能靠代码 revert 自动复活数据。

## 5. B1c：逐项审计归类后清理

### 5.1 B1c-0：先产出分类账

新增一份受版本控制的短清单，逐路径或逐同质目录记录：类别、消费者、文档引用、是否唯一证据、是否含版权/隐私风险、决定、替代物和验证。判定规则：

- **删除**：纯 PID/锁/调试转储/过时一次性工具，零消费者、零文档引用、无唯一证据。
- **摘要后删除**：原始日志只有历史复现价值，且验收结论、版本、输入 hash 与关键指标可由短文档完整承载。
- **归位保留**：仍是唯一可复现证据且被正式验收文档引用。
- **替换后删除**：测试必须消费但内容有版权/隐私风险；先提供等价合成夹具并跑通消费者。
- **保留**：项目设置、正式文档、ADR、任务记录或无法证明无价值的文件。

### 5.2 B1c-1：工具运行时与历史工件

按现有证据，以下默认为删除候选，实施前仍写入分类账并做最后一次全仓消费者检查：

- `.claude/scheduled_tasks.lock`
- `.claude/workflows/module-architecture.js`
- `.playwright-mcp/**`
- `.opencode/loop-history/**`
- `.superpowers/brainstorm/*/state/**`

`.superpowers/brainstorm/*/content/**` 先判断是否存在未被正式文档承载的独特设计；无明显价值则删除，有明确采用内容则只把最终结论归入现有正式文档，不保留会话服务器工件。保留 `.claude/settings.json`。补足最窄 `.gitignore` 规则防复发，不用一个根规则误伤未来正式文件。

### 5.3 B1c-2：验收日志与嵌套目录

- `backend/backend/.test-logs` 的 11 个唯一文件先与正式 acceptance 摘要逐一对照。
- 若文件没有被引用且不含摘要无法恢复的输入/输出证据：删除并移除 `backend/backend/`。
- 若确有唯一价值：只提炼脱敏的运行条件、输入 hash、关键指标与结论进对应 `docs/superpowers/acceptance/`，复核摘要足以支持历史结论后删除原始日志。
- 对已跟踪的 `backend/.test-logs` 同样按“引用与唯一价值”分组，不做 27 MiB 一刀切；明确被文档引用且无法由摘要替代的最小集合可保留，其余删除。
- 清理后 `backend/backend/` 必须不存在，生产镜像上下文不得再包含嵌套日志。

### 5.4 B1c-3：版权样本替换

- 用项目已有原创 `synthetic_ten_chapters` 风格生成两个最小合成文本：单章与三章；保留章节边界、实体重复、场景切换、空白/标点等测试所需特征。
- 更新 `seed_data.py` 与断言后，删除两份《诡秘之主》原文样本；`lotm_empty.txt` 若仍是空文件测试则保留但改中性文件名。
- 运行导入 e2e 与种子数据检查，证明替换的是内容而非覆盖能力。
- 不重写 Git 历史；如未来确需历史净化，必须另获破坏性 Git 授权。

### 5.5 B1c 验证与提交边界

- 每一类单独提交；删除前后保存 `git ls-files` 清单和引用检查结果。
- 运行 `git diff --check`、相关 docs-check、导入 e2e、`make test-deploy` 与生产镜像内容抽查。
- 不把本地未跟踪运行产物加入 Git，也不删除用户工作树外的个人备份。

## 6. B3c：真实模型验收后退役同步双轨

### 6.1 迁移顺序

1. 把现有同步 `generate_candidate()` 测试迁到 `generate_candidate_for_task()`，保留同一 prompt、schema、confirmation、source hash、取消和失败断言。
2. 把 deprecated conflict AI review/suggestion HTTP 测试迁到 `*-task` 端点及 worker handler；前端生产路径保持不变。
3. R5 的真实模型用例改为任务轨，删除旧的不可满足 `continuity_location_mismatch` 硬编码断言，改验三个 V2 kind、覆盖声明和来源证据。
4. 完成一次有界付费验收；通过后才删除同步 service 方法、deprecated routes、旧 schema/OpenAPI 声明和只服务同步轨的测试 helper。
5. 更新 Writing README、Prompt 清单与 API 契约；扫描全仓确保生产与测试均无旧调用。

### 6.2 付费调用边界

- 只经 `modules.project.facade.open_project_llm_client()` 和现有项目账户配置调用，不直接读/拼 API key，不创建旁路客户端。
- 使用原创三 Scene 小语料；最多 4 次远程调用：正文生成、冲突 AI 复核、单条修订建议、独立语义审查各一次。
- 使用现有 token/step 预算；调用前记录当前 provider/model 与预算上限，若配置缺失或预计会超过现有工作流上限则停止，不自动改配置。
- 记录脱敏证据：任务类型、模型、confirmation/context/source hash、耗时、token/费用（若 provider 返回）、schema/coverage 结果；不提交 prompt 全文、正文原始响应或秘密。
- 真实模型验收只证明生产协议可用，不以措辞逐字相同作为断言，也不替代确定性测试。

### 6.3 验收

- 任务创建、轮询、取消、恢复、终态重放、owner/`novel_id`、source/confirmation stale 与 provider wait 期间无长事务均通过。
- 模型输出通过严格 schema；只创建 candidate/check item/suggestion，不直接改稿或写已确认 memory。
- 删除后全仓旧同步方法与 deprecated route 零消费者；OpenAPI 不再暴露旧端点。
- Writing 模块、任务事务、PostgreSQL critical、前端契约、浏览器关键链和 docs-check 全部通过。

### 6.4 回滚

- “测试迁移”“付费证据”“同步实现删除”“文档/API 清理”分提交。
- 若真实模型任务轨失败，保留同步实现但停止删除阶段，修复任务轨根因后重验；不得降低 schema、Evidence 或权限门禁换取通过。

## 7. F5-7 暂缓记录

本轮不改 `FORWARDED_ALLOW_IPS=*`。解除暂缓必须发生在部署窗口，并先取得：生产 OpenResty/API 容器网络 inspect、API 实际看到的 peer IP、loopback/DNAT 行为，以及伪造 `X-Forwarded-*` 被拒绝/可信代理被接受的验证。届时另立运维安全批；未取证前不能猜 CIDR，也不能标记完成。

## 8. 全局验收、文档与停止条件

### 每批通用门禁

- 开始前与收尾：`make docs-check`；最终以 `BASE_REF=origin/main` 做影响复核。
- 后端改动：受影响模块测试、`make lint`；任务/数据批加 PostgreSQL critical。
- 前端改动：`npm run lint`、`npm test`、`npm run build`。
- 跨模块收尾：`make test-ci TEST_WORKERS=2`；浏览器、PostgreSQL、真实模型门禁显式单跑，不以 test-ci 代替。

### 必须停止对应批次的条件

- 出现跨 `novel_id`、owner 绕过、未来 Scene 泄漏或 Evidence 指纹不可兼容。
- 需要自动采用 AI 结论、硬删除用户资产、重写 Git 历史或扩大付费调用范围。
- F5-7 仍无法取得生产 peer/network 证据。
- 同一外部 provider 连续三次不可用；保留已完成的确定性迁移证据并停止付费部分。

## 9. 计划完成后的交付顺序

1. 提交本计划与任务状态更新，不包含业务代码。
2. 实施时按 R5a→R5f、X2-3a→c、B1c-0→3、B3c 的叶子批逐项提交。
3. 每个叶子批更新 `TASK.md` 和 `batch-plan.md` 的实际验证、回滚与剩余风险。
4. 全部本地验收后只报告分支与提交拓扑；合并、推送、部署继续等待单独授权。

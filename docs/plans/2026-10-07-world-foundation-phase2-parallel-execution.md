# 世界演化第二阶段并行执行规划

日期：2026-10-07。状态：规划就绪，待启动指令。本文件把[第二阶段计划](2026-10-07-world-foundation-phase2.md)的三个顺序工作包拆成子代理并行批次；不改变该计划的授权边界——不新增付费调用、不延伸 USD 20 授权、不核销 R7、不默认开放 formal family。

## 1. 开始条件核对（2026-10-07 实测）

- 基线：worktree `/Users/tywww/.codex/worktrees/world-foundation-plan/ai-writing-assist`，分支 `codex/world-foundation-phase1-plan` 干净，领先 main 6 提交、落后 0；固定生产代码 `b40cd0c5a` 在位。
- R7（真实质量/费用/留出门禁）未闭合，继续留在第一阶段原任务；P2 全部批次离线执行，零 LLM 调用、零真实数据写入。
- 在途变更：其余四个 worktree（architecture-review / event-soft-delete-merge / responsive-layout / thin-snap）仅有 `.agent` 任务笔记改动，与 continuity / evidence / evolution / collaboration / writing 模块无写入冲突。
- 合入拓扑：P2 在 phase1 分支上顺序提交，phase1+P2 一并走 PR 合入 main；R7 若获新授权则在原任务并行推进，不阻塞离线批次。

## 2. 顺序约束的文件级依据

三包串行（P2-A → P2-B → P2-C）不是流程偏好，是写入热点重叠。三个只读调查子代理确认的共用文件：

| 文件 | P2-A | P2-B | P2-C |
|---|---|---|---|
| `backend/modules/story/continuity/scene_state_view.py` | 字段来源输出 | 视角边界、历史回开过滤 | basis 新鲜度展示 |
| `backend/modules/story/continuity/reducer.py` + `schemas.py` | 赋值链登记 | 知识方言统一 | — |
| `backend/modules/story/continuity/scene_projection.py` + `repositories.py` | 逐字段投影 | 历史回开同边界 | 失效范围收窄 |
| `backend/modules/evidence/compilation/services/scene_lens.py` | 字段级来源 | 可见性渲染 | 消费登记 |
| `backend/modules/story/continuity/basis.py` | basis 登记 | — | 失效判定 |

包内并行的前提是**契约先行**：先由单一写入者定下共享结构（schemas/contracts/DI 键），再按独立文件组派发。

## 3. 派发纪律（全程适用）

- 每批同时运行 ≤3 个子代理；超限/报错是瞬时错误，原样重发。
- 子代理只改文件、跑测试，**禁 git commit / push**；改动留在工作树，主会话统一验证后提交。避免并行分支合并成本，同一 worktree 按文件分工（AGENTS.md 允许同模块独立文件并行）。
- 共享接口单一写入者：当包契约批独占 `schemas.py`/`contracts.py`/`service_keys.py`；`facade.py` 归当包主线单元。
- 每包第 0 步先固定验收夹具与预期（计划 §3：样本和预期在实现前固定），夹具文件独立，可与契约批并行。
- 每张子代理任务卡必须含：worktree 绝对路径、明确读写范围（文件清单）、验收证据（哪些测试/断言）、边界提醒（novel_id 隔离、生产禁 Mock、`@patch` autospec、Pydantic 收紧后禁隐式透传额外键、shell cwd 每次调用重置须显式 cd）。

## 4. P2-A 批次卡：历史字段与来源

**A0 夹具先行**（与 A1 并行，1 子代理）：固定 6 场景中 P2-A 相关的倒叙、保管交接、历史版本夹具与断言（预期先失败后转绿）；含"改动无关稿件不改变字段指纹""历史读取不回填当前知识"两类反向断言。

**A1 契约先行**（主线单人，独占共享结构）：三母题字段注册表（位置 / 所有者+保管者 / 锁的有限条件，现状全是自由 payload，先正式登记字段名）；逐字段赋值链结构（event_id + 复用 `evidence/source_ref_contracts.py` 的 SourceRangeRefContract + 版本号，现状 evidence_refs 只有维度级集合）；`evidence_refs` v2 读取兼容；时间字段受控 schema（timeline payload 现为自由 dict，只保留已证明的相对顺序/日期）。产物：schemas/contracts 改动 + 结构注释 + 单元级契约测试。

**A2 写入端**（A1 后并行）：`reducer.py` 各 `_apply_*` 登记逐字段赋值链；`scene_projection.py` `_project_dimension` 写字段级 refs（保持 drift 保护路径）；`models.py` + Alembic 非破坏性迁移。

**A3 读取端**（A2 同批并行）：`scene_state_view.py` `_entries_for` 输出"精确依据 / 来源待核实 / 冲突"三态（能追到赋值链才标精确，整场事件列表不算）；`state_trial.py` 消费字段级依据；`facade.py` 出口契约。

**A4 展示端**（A2 同批并行，只依赖 A1 契约）：`scene_lens.py` `_source` 字段级来源与版本；历史 checkpoint 列表端点（`continuity/api.py`，现状只有 get_record 单点回开，无历史列表）；前端 `SceneLensSummary.vue` 字段下钻 + 首次进入/来源缺失/旧稿无追踪三类空态。

**汇合门禁**（主会话）：倒叙/改稿/历史版本逐字段来源一致；一次点击回开对应原文版本；A0 夹具全绿；story 模块测试 + lint + `make docs-check`；固定提交。

## 5. P2-B 批次卡：知识值与揭示边界

**B0 夹具**（与 B1 并行）：六类夹具统一验收集（旧值/新值/误信/部分知晓/同场旁观/后文揭密）——调查确认前四类有覆盖、同场旁观与后文揭密是缺口；补 uncertain 三值判决测试（现状零断言）。

**B1 方言统一与边界裁定**（主线单人）：knowledge payload 正式 schema（subject_id/fields/known_values 进契约，现状 Story 事件路径要求显式 subject 而 Evolution 机器路径 `KnowledgeInPanorama` 无法表达值绑定，两套方言统一）；两套揭示系统边界裁定——Story RevealPlan 无策略默认公开（`outline_state/contracts.py:531`）vs World ReaderRevealPolicy 无 cutoff 默认隐藏（`knowledge_visibility_service.py:140-167`），"读者揭示只在已证明展示的原文范围内启用"的判定通路设计。裁定与理由记入任务笔记，涉长期语义再补 ADR（不替代授权）。

**B2 World 侧**（B1 后并行）：CharacterKnowledge 值绑定表达 + evolution `state_gate.py` 校验扩展 + 测试（false_belief 永不授予的口径保持）。

**B3 Story 侧**（B2 同批并行）：历史回开 `get_record` 过视角边界（现状返回 raw state_json 不过滤，计划明确旧版本不洗成当前证明）；reveal 判定接入"已展示原文证明"；验证缓存命中、重建、历史回开同边界（`scene_state_view.py` 的 reveal 缓存与 `scene_projection.py` 的 drift 重建路径）。

**B4 验收集**（B3 同批并行或汇合前）：六类夹具逐条解释允许/拒绝原因的断言落库。

**汇合门禁**：六类夹具全绿含第三值；预览零正史写入；缓存/重建/历史回开同边界验证；story+world 模块测试 + lint + docs-check；固定提交。

## 6. P2-C 批次卡：实际依赖与局部重做

**C0 端到端夹具**（与 C1 并行）：改稿与并发采用冲突场景（计划 §3 第 6 场景）+ 双窗口/离开恢复不丢稿 + 已知依赖零无关重生成 + 未知依赖保守扩大。

**C1 登记缝设计**（主线单人）：细粒度依赖登记契约（source_binding 扩展登记稿件范围/checkpoint/basis/选中排除资产/方法版本）；InvalidationReceipt 透传契约（现状 writing `repositories.py:38-62` 调 DI 缝但丢弃回执——最小首步是透传到 API 响应）；重算三分类（重读证据 / 重建派生状态 / 重生成正文）编排接口；`service_keys.py` + `app/bootstrap.py` DI 注册。evolution 侧 world_knowledge/map_atlas 留在 UNSUPPORTED_CONSUMERS，本包不扩。

**C2 evolution 侧**（C1 后并行）：细粒度登记替换保守扩大的场景（保留依赖缺失→保守扩大语义）；失效范围查询端点（含受影响字段/场景及原因，技术 ID 留诊断入口）；store 回执落库。

**C3 writing 侧**（C2 同批并行）：repositories/api 回执透传；重算编排端点（作者显式触发，编辑时不自动生成）；preview 隔离采用 Collaboration 现成试改（零正史写入、幂等 operation_id、三向 rebase、人工修改保留）。

**C4 前端**（同批并行，只依赖 C1 契约）：编辑器失效提示 + 重算范围选择 + 独立预览/采用/取消组件（借鉴 `CreativeExperiments.vue` 的 stale 提示、rebase 单选、幂等采用、回执历史、canLeave 保护）；`api/evolution.js` 补失效端点封装。

**汇合门禁**：真实 PG migration + 并发验证；取消零正史副作用、采用重试幂等、冲突保当前稿；evidence+story+writing+collaboration 受影响测试 + lint + docs-check + 前端关键流 e2e；固定提交。

## 7. 验证与提交节奏

每包收尾跑：受影响后端模块测试与 lint → `make docs-check`（world/story/writing 影响）→ 真实 PG migration（含 schema 变更的包）→ 前端功能 + 真实浏览器关键流 → 固定代码提交 + 脱敏验证记录入任务笔记。三包全部完成后统一整理 PR（no-change-reason 按门禁），合入前与 main 重新对齐基线。

## 8. 已知风险与暂停条件

- `scene_state_view.py` 三方热点：包间必须串行；包内契约批独占共享结构后再放行并行单元。
- Pydantic 默认忽略额外键：方言统一时 Evolution 机器路径的隐式透传必须显式测试，防 schema 收紧后静默丢字段。
- 历史 checkpoint 的 state_json 是旧结构：读侧兼容（视角过滤不得要求迁移旧数据）；schema 变更全部非破坏性。
- 前端 `POST /memories/scene-state-view` 现无直接调用方：A4 接线时确认走 facade 而非新增平行入口。
- 同一外部依赖连续 3 次不可用，或同一测试修复 3 次仍无新证据 → 暂停对应单元，交付其余。
- 实施第一步：在 worktree 恢复/新建任务记录（`.agent/tasks/2026/T-20261007-world-foundation-phase2/`），本规划作为其输入。

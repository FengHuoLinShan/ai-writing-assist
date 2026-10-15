# 能力审计后续第三批计划（2026-10-15）

日期：2026-10-15。状态：**开发计划，未开工；用户已于 2026-10-15 裁定 §6，执行者由用户自行安排**。上级计划：
[能力审计后续批次开发计划](2026-10-14-audit-followup-batch.md)（以下称“主计划”，G 编号、通用门禁以它为准）与
[第二批计划](2026-10-14-audit-followup-wave2.md)（以下称“第二批”，G6/G7 切片定义以它为准）。

基线：origin/main **M3** = `d2ab2dbf3c78785a24d3f419002fbb13b36bc99c`（PR #241）。本文件的现状与行号来自 2026-10-15
对 M3 的只读核查和对 G6b/G6c 工作树、私有证据目录的只读查看，开工时须在新 HEAD 重核。本文件只规划，不证明任何
分支的实现或验收状态；任务记录见 `.agent/tasks/2026/T-20261014-audit-followup-batch/TASK.md`。

## 1. 第二批结果核对

| 项 | 状态 | 证据 | 还剩什么 |
| --- | --- | --- | --- |
| G3② window Phase2 退役 | 已合入 | #231 `4a447374d` | 无 |
| G3③b+c / G3③d 本机文字链路退役 | 已合入 | #236 `2e54f38f3`、#237 `df0837778` | 无 |
| G4b 作者手动导出图片包 | 已合入 | #235 `0713ee80d`；复核补修 #241 `d2ab2dbf3`（取消后不再下载、多包逐个下载与确认） | 双桶 32 GiB 满额、其他浏览器、真实作者未验收；不排期 |
| G5a/G5b/G5c 编辑闭环 | 已合入 | #233 `8136105ca`、#239 `8e1be388f`、#242 `258c8ba2a` | 生产开启需发布授权，本批不做（§6） |
| G6a 评测模型合同 | 已合入 | #234 `9bcd63a6c` | 独立评测入口仍被暂停守卫拒绝（`backend/evals/codex_executor.py:31-41`） |
| G6b Ask World 重校准 | **完成，未提交** | `T-20261015-g6b-recalibration`：教师 seeded 自测 30/30；34 条 debug 中 33 条语义通过；过度拒答修复开发对比 5/16→0/16、语义通过 27/32→32/32 | 入库（R1） |
| G6c 新资料族单次留出 | **完成，冻结验收全部满足，未提交** | `T-20261015-g6c-holdout`：16 族 32 题、原版/修复版各一次；修复版过度拒答 0/16（原版 2/16）、语义通过 31/32（原版 28/32）、冲突失败 0、错误作答 0；66 次原生调用，unknown 0、非零退出 0 | 入库（R1）；留出已消耗，不得再调参后当未见样本 |
| G7a 导入扫描基线与账本模板 | 已合入 | #232 `a3c9ef713` | 无 |
| G7b 诡秘前 60 章新 v3 全链 | **未启动** | 无任务记录；`~/.codex/private/` 下无 v3 run 目录 | 本批主线（A2） |
| G8b 改图 → 冲突检查可核对 | 已合入 | #240 `a5d562b53` | 无 |
| H1/H3 文档集成与 Dependabot | 已合入 | #238 `d4bfc5807`；#229 `771bae48f`、#223 `f01b4462c`、#224 `798b27c46` | #224 留下旧版 httpx 兼容路径（C） |
| rp_matrix DeepSeek 冻结 | 待裁定 → **已裁定冻结** | `backend/evals/rp_matrix.py:258,263` 绑定 DeepSeek 凭据 | R3 |

另有新开 Dependabot：#243（前端 4 个开发依赖，CI 全绿）、#244（Python 基础镜像 3.14.7→3.14.8，只改
`backend/Dockerfile`；Backend quality 失败于 `backend/tests/unit/test_test_harness.py:380`
`test_production_toolchain_uses_pinned_images_and_consistent_versions`，Production image contract 的镜像冒烟报
`No module named 'pydantic'`）。

G6c 的一处观察，本批不处理：64 份输出中有 3 份教师判通过、确定性冲突检查判失败（`uncertainty` 字段为空），
raw teacher 与确定性一致率 0.953。冻结规则不改；是否调整确定性冲突检查或 Prompt 对 `uncertainty` 的要求，
留到第四批，并且只能在新的开发集上做。

### 1.1 环境变化

- 主仓库在 2026-10-15 从 `~/Desktop/项目/ai-writing-assist` 移到 `~/项目/ai-writing-assist`。核对时外部
  worktree（`~/.codex/worktrees/*`）的 `.git` 已指向新路径，`git worktree list` 无 prunable；移动后若再出现
  prunable，**只能** `git worktree repair`，不能 `prune`（audit-followup、g6b-recalibration 都有未提交内容）。
- 主工作树停在 `codex/guided-flow-borrowing`，本地 `main` 落后 origin/main。
- 旧 v2 run 的私有评测工具在 `/tmp/guimi60-assessment`（`review_bindings.py`、`capture_final.py` 等）和其他
  `/tmp/guimi60-*` 目录，重启可能被清除；A1 要复用它们。

## 2. 排序原则

第二批完成了运行时收敛与旧路径退役。按审计原则，下一步是证明长篇质量：G7b 是本批主线，其账本与复核结论作为
第四批定向修复的输入。地图/正典优先，G8c 与主线零文件交叉，可并行。生产发布本批不做。

| 泳道 | 任务 | 基线 | 开工条件 | 规模 |
| --- | --- | --- | --- | --- |
| R 收口 | R0 工作区收尾 | — | 无（G6c 已结束） | XS |
| R | R1 G6b+G6c 入库（含 Prompt 修复、R3） | 最新 main | 无 | S |
| R | R2 Dependabot #243、#244 | — | 无 | XS–S |
| A 长篇 | A1（G6d）G7 语义复核器校准 | R1 合入后的 main | R1 合入 | S–M |
| A | A2（G7b）诡秘前 60 章新 v3 全链 | R1 合入后的固定 main SHA | R1 合入；语义复核阶段等 A1 | L |
| B 地图/正典 | G8c 正典修订基线与提示 | 最新 main | 无 | M |
| C 工程债 | openai 3.x HTTP 客户端迁移 | 最新 main | 无 | S |
| X | 旧 worktree 核对与清理 | — | 与 G7b 无关的树随 R0；旧 v2 运行时树在 A2 开跑后；删除逐项授权 | XS |

## 3. 任务包

### 3.1 R0 工作区收尾

- 本地 `main` 快进到 origin/main；`git worktree list` 确认无 prunable。
- 把 `/tmp/guimi60-assessment` 及 A1 需要的 `/tmp/guimi60-*` 工具复制到仓库外持久目录（如
  `~/.codex/archives/guimi60-assessment-tools-20261015`），记录路径与哈希；原 `/tmp` 不删。
- 列出 §3.8 的清理候选清单与各自持有任务，只核对不删除。

完成标准：所有注册树 `git status` 可用；audit-followup 与 g6b-recalibration 的未提交内容与核对前一致。

### 3.2 R1 G6b + G6c 入库

来源：`~/.codex/worktrees/g6b-recalibration/ai-writing-assist`，分支 `codex/g6b-recalibration`，基线 M3。
入库内容：

- 产品：`backend/modules/world/services/worldbuilding/ask_world_service.py` 的 `world.ask` 系统 Prompt 澄清
  （冲突记载并列引用、无法判定正典不等于无证据、保留来源历法/单位/精度；属性缺失或达不到要求精度时继续拒答），
  同步 `docs/prompts/Prompt体系设计.md`。
- 评测：`backend/evals/codex_executor.py` 的 `AskWorldCalibrationScope`（只放行 Ask World 教师步骤 Sol/xhigh、
  attempts=1、每次重新物化并恢复同一 Project snapshot）、教师取消时 stop/reap 子进程、子进程环境不继承 API 凭据；
  新测试 `backend/evals/tests/test_g6b_calibration.py`；`testing-guide.md` 评测段。
- 记录：`T-20261015-g6b-recalibration`、`T-20261015-g6c-holdout` 两个任务目录（去原文账本、ACCEPTANCE、
  REFUSAL-COMPARISON、执行脚本）。私有目录 `~/.codex/private/g6b-recalibration-20261015`、
  `~/.codex/private/g6c-holdout-20261015` 不入库。
- R3 并入本 PR（同一写入面）：`backend/evals/rp_matrix.py` 按 G6a 先例（`rp_real_pairs.py:3-4` 的冻结历史头注）
  标为冻结历史，不迁移、不发新调用；`testing-guide.md:637` 的 rp_matrix 段同步标注。

Prompt 修复按用户裁定（§6 第 2 条）随 G6c 冻结验收结果决定：G6c 账本 `holdout-ledger-v1.json` 的
`frozen_acceptance_met=true`，所以**随 R1 合入**。PR 正文须写明：留出已消耗；G6b 开发对比与 G6c 留出都只覆盖
生成层（不含检索、Evidence 确认、知识治理、引用回开、UI），`human_validated=false`。

G6c 的执行会话可能仍在补写自己的 ACCEPTANCE“实际结果与收尾”节；R1 开工前确认该记录已收尾，不覆盖其内容。

完成标准：rebase 到最新 main 后，evals 离线测试、Ask World API 与相关 world 回归、`make prompt-contracts`、
`make lint`、`make repo-gates`、`make docs-check BASE_REF=origin/main`、`git diff --check` 通过；对任务目录脚本与
账本跑凭据扫描；R1 合入后默认暂停守卫对除 Ask World 教师以外的角色仍然拒绝（测试证明）。

### 3.3 R2 Dependabot

- #243：CI 全绿，按常规合并（需合并授权）。
- #244：不能直接合并。基础镜像钉版要在 `test_production_toolchain_uses_pinned_images_and_consistent_versions`
  检查的所有位置一致，并查明镜像冒烟里 `pydantic` 缺失的原因（构建期与运行期 Python 路径或虚拟环境不一致的可能性
  最大，以实测为准）。在 Dependabot 分支上补齐或另开 PR 取代，`make test-production-images` 与后端快测通过后合并。

### 3.4 A1（G6d）G7 语义复核器校准

现状：M3 上 `require_live_eval_calibration`（`backend/evals/codex_executor.py:31-41`）拒绝全部独立评测调用；G6b
只经受限 scope 放行了 Ask World 教师。G7b 的语义复核不是 Ask World 的 rubric：旧 v2 run 设计的是“最终快照的源化
字段复核”，私有工具 `review_bindings.py` 要求每个复核 case 绑定真实快照 SHA、inventory 主键行、字段实际值、稿件
区间原文与截止，有 60 项合成测试，但从未真实执行（`T-20261012-guimi60-codex-comparison/TASK.md`）。

做法：

1. 定复核单元与 rubric：人物、物品、地点、组织、关系、故事线、知识、台账字段对照来源区间；以 Scene-local 截止
   （`visible_until_*`）判跨截止事实；“来源未述及”与“抽取错误”分开计。复用 R0 归档的旧工具设计，重新落到
   仓库内的 `backend/tools/` 或 `backend/evals/` 新路径（与 G7a 约定一致），合成测试随迁。
2. 新增受限 scope（沿 `AskWorldCalibrationScope` 模式），只放行 G7 复核角色 Sol/xhigh；其他角色的暂停守卫不变。
3. 校准：在合成稿件上做 seeded 自测（已知正确、已知错误、越过截止、来源不足、字段值不符各类），要求全部匹配；
   再做一轮小规模 debug（合成或公版材料，不用诡秘原文），独立审查分歧。验收标准在首个调用前冻结，带独占启动标记。

授权：用户 2026-10-15 裁定 A1 在既有“教师与评分 Sol/xhigh”授权内（§6 第 3 条）。

完成标准：seeded 全部匹配；debug 分歧与失败如实保留；账本含全部调用、失败与 unknown；`human_validated=false`；
仓库只存去原文结论与哈希。

### 3.5 A2（G7b）诡秘前 60 章新 v3 全链

范围与禁止项沿用第二批 §3.8：新任务、新 v3 run；只复用单位定义（前 60 章、63 个来源、212868 字符）；旧 v2 run
的 8/63 前缀、unknown、账本与旧 worktree 只读保留，不拼接、不改 stamp、不重发、不沿用请求身份。不设费用上限，
账本照记。受版权原文的请求与输出留仓库外。

开工前要写进范围的事项：

- **运行基线**：R1 合入后的一个固定 main SHA，独立 worktree 与独立 PG 库（不碰共享 `ai_novel_engine`），整次运行
  不换代码。运行时为 owner 已验证连接经 Project facade/snapshot 的原生 Codex Luna/max（`codex-text-v3`），
  CLI 不低于 0.160.0。
- **并发**：M3 上账户并发默认 2、合法 1–8（G2 合入的同账户 OS 槽）。8 路只在约 3 万字合成材料上验证过
  （`T-20261012-guimi60-codex-comparison/PAUSE-SUMMARY.md` §2）。开工时写明选定值；高于 2 时观测到 unknown 即
  停止接纳、排空已发。
- **主机**：旧 run 因合盖睡眠约 6 小时使墙钟失真（PAUSE-SUMMARY §3），`caffeinate -i` 防不了合盖。运行期间主机
  接电源且不合盖，或者记录睡眠区间并从耗时指标中剔除。
- **unknown 处理**：不重发。M3 已有可选发现批次的显式缺口确认（`backend/modules/evolution/discovery_gap.py`），
  每次使用都要用户就该条明确授权；核心步骤或必须审查的 unknown 只停止依赖部分。G2 遗留的“约 1.91 秒 unknown”
  不单独立项，G7b 遇到时按 G2 已加的 stderr 固定标签分类记录。
- **已在 M3 的旧问题修复**（经 G2 #226）：恢复时复用已完成深度场景来源前缀（防重复切分）、有界发现窗口、有界
  历史证据包、并发 journal 原子合并。开工时各用一条合成用例确认生效。

产出：按 `backend/tools/import_scan_baseline/ledger_template.json`（v1）填写单一账本，P4-E 指标并入；分母含
dropped/omitted，unknown 与作者处置单列；语义复核在 A1 完成后进行，报告覆盖率与结果；按阶段（导入、世界/结构、
写作检查、演化）归因的缺陷清单，作为第四批输入。

不做：续跑或拼接旧 v2 run、G7c 代理作者试用、真人验收、最终两引擎排名。

### 3.6 B G8c 正典修订基线与提示

主计划 §7.5 的设计不变：粒度取页面 revision（`revision_id` + `revision_digest`），不取 canon head；读时比对，
只提示不降级（M4 §2）。M3 上核实的落点：

- `backend/modules/evolution/invalidation.py:51-63` 的 `UNSUPPORTED_CONSUMERS` 含 `world_canon_revision`
  （“正典 revision 尚未登记为 Story 状态或台账依赖”）；M4 契约 §3.3 让 `SceneStateViewResponse.unsupported_dependencies`
  恒含它。
- `backend/modules/evolution/consumption.py:235` 的 `ConsumptionRecord.selected_assets`（`AssetDigest`：
  `asset_kind`、`asset_id`、`digest`）已预留，可直接承载页面 revision 基线。
- world 侧 `world_bible_page_revisions` 带 `revision_digest`（`backend/modules/world/README.md:532`）。
- G8b 已建立同类模式：world 只读批量 head 出口 + DI 键 `world.read_map_node_heads`（`core/service_keys.py:267`、
  `app/bootstrap.py:450`），消费方 Protocol 定义在消费侧，比较结果只进响应、不入库。

做法：world 新增只读“按页面批量取当前 revision 与 digest”出口与 DI 键；首片按主计划 §7.5 落在 Story checkpoint
的消费登记，把实际读取的页面 revision 写入 `selected_assets`；读时比对，在响应里给“基于旧版正典”提示，不写回、
不进语义指纹。其他读取世界书页的消费方（如 `story/outline_state/story_outline_generation.py:220-225` 的
`selected_assets.world_bible_page`）开工时列清单，另片处理。完成后从 `unsupported` 中只移出已覆盖部分，未覆盖的
继续显式列出。

保护：主计划 §7.6 全部保留（owner + novel_id 双重过滤、revision append-only 与 CAS、作者确认只标待重验等）。
正典语义改为“降级/待重验”仍待用户另行决定，本批不做。

完成标准：旧数据无基线不提示；页面 revision 变化后提示，未变不误报，取消采用/删除算已变；跨项目不串；指纹与
发布快照不随正典后续变化漂移；新 DI 键后实测重算依赖棘轮，函数级预算不增，ADR-0031、`test_container`、
`test_facade_public_api` 同步；`make test-postgresql-critical` 与 `test_p2c_invalidation_recompute.py` 通过；
有前端提示时覆盖 390px。

### 3.7 C openai 3.x HTTP 客户端迁移

现状：#224 把 openai 从 2.53 升到 3.28 时零代码适配，H3 评估实测走的是旧版 httpx 兼容路径，并记录需要独立迁移
PR。M3 上 `backend/pyproject.toml:53` 仍写 `openai>=2.53.0`；`backend/infrastructure/llm/providers.py:173-190`
用 `_build_http_client`（:241）构造 `httpx.AsyncClient` 注入 SDK（含 embedding client），
`image_client.py:176` 同样注入；出站白名单（egress guard）与测试 `MockTransport` 依赖 httpx 接口。

做法：开工先读 openai 3.x 变更说明，确认推荐的 HTTP 客户端接口与兼容路径的移除计划；迁移三处并保持出站白名单、
超时、代理语义不变；`pyproject.toml` 下限改为实际要求的 3.x。

完成标准：H3 基线的 llm、引用方与 project 测试通过；出站白名单拒绝用例通过；运行时不再走兼容路径（以 SDK 警告
或显式断言证明）。

### 3.8 X 旧 worktree 核对与清理

候选（2026-10-15 `git worktree list`，归属开工时按任务记录核定）：

- 旧 v2 运行与 G2 相关：`~/.codex/worktrees/` 下 `guimi60-*` 7 个、`codex-luna-runtime`、`codex-luna-timeouts`、
  `g2-codex-luna-convergence`。这些在 A2 开跑后才清理，旧 v2 的私有证据与账本保留只读。
- 与 G7b 无关、可在 R0 核对的：仓库内 `.worktrees/` 下 `br3`–`br7`、`tails`、`docs-refresh-l1`–`l7`、
  `capability-tail-fixes`、`audit-first-batch` 残留目录；`~/.codex/worktrees/` 下其余各树（如 `docs-refresh-luna`、
  `evolution-model-pools`、`thin-snap`）先核定持有任务，仍有在途工作的不列入。

按 H4 先例：核对未提交内容与独有提交是否已在 main，提交 bundle 与差异备份到仓库外，列出清单后**逐项取得用户授权**
再删除。`audit-followup` 与 `g6b-recalibration` 在 R1 合入并核对前不动。

## 4. 写入者与冲突

- `backend/evals/` 与 `testing-guide.md` 评测段：R1（含 R3）→ A1。
- `core/service_keys.py`、`app/bootstrap.py`、ADR-0031、`scripts/check_module_imports.py`：本批只由 G8c 写；A1 预计
  不需要 DI 键，如需要则排在 G8c 之后。
- `backend/infrastructure/llm/` 与 `backend/pyproject.toml`：C 独占。A2 运行基线固定在 R1 合入后的 SHA，C 合入
  main 不影响在跑的 G7b。
- `ask_world_service.py` 与 Prompt 文档：R1。
- 每项独立 worktree 与 `codex/<slug>` 分支，从开工时最新 origin/main 建立；真实模型任务用独立 PG 库。

## 5. 本批不做

- 生产发布：G4a 服务器侧图片备份启用、G5c 编辑台开关开启（用户 2026-10-15 裁定暂时不管）。
- G7c 代理作者试用：第四批候选，依赖 G7b 结果，委派与费用授权须重新确认。
- G4c 本机自动同步、G9 多用户运维、B2 异地备份、正典语义改为降级：主计划 §11 仍待用户另行决定。
- C2 导入扫描优化：G7a 结论为实体数接近 5000 再议，G7b 账本记录增长曲线。
- C3、RP 长期记忆评测：维持暂缓。

## 6. 用户裁定与默认假设

用户裁定（2026-10-15，“生产暂时不管，其他按你推荐”）：

1. 生产发布不进本批。
2. G6c 结束后，Prompt 修复按其冻结验收标准决定：满足则随 R1 合入，否则只合基础设施与账本、Prompt 改动留分支
   待裁定。G6c 实际 `frozen_acceptance_met=true`，因此随 R1 合入。
3. A1（G6d）在既有“教师与评分 Sol/xhigh”授权内，只放行 G7b 所需复核角色；其余评测入口继续暂停。
4. `rp_matrix.py` 的 DeepSeek 用法冻结为历史。
5. 旧 worktree 按 §3.8 核对后清理，删除清单逐项取得授权。
6. 执行者由用户自行安排，本计划不指派。

本计划自行采用、证据相反时再改的默认假设：R3 并入 R1；G8c 首片只做 Story checkpoint 消费方；A1 的复核工具落在
仓库内新路径并带合成测试；G7b 并发值在开工范围里写明；#244 在 Dependabot 分支上补齐或另开 PR 取代。

## 7. 验证门禁

沿用主计划 §10 与第二批 §6。补充：R1 合入前对任务目录脚本与账本做凭据扫描；A1、A2 的真实调用开工前写明范围、
冻结验收标准、独占启动标记，账本含全部失败与 unknown；A2 运行期间不改运行基线；G8c 实测重算依赖棘轮并跑 PG
critical 与失效重算测试。

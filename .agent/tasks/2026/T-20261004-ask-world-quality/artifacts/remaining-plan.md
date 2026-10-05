# 问世界观：剩余工作计划

状态：计划已整理，后续实现未启动。更新：2026-10-04（Asia/Tokyo）。

## 目标与范围

完成 `df37` worktree 中问世界模型质量诊断的收尾，使作者能可靠区分“有依据的回答”、
“来源冲突”和“证据不足”，并能回开来源核对。服务画像 A：长期维护小说设定的作者；
预期价值是减少翻查与误信 AI 答案的成本，实际价值仍需真实作者验收。

本次授权只有调查与计划。本文件复用仓库现有 `docs/superpowers/plans/` 计划机制，
保存执行顺序、验收及恢复信息；目标 worktree 尚无 `.agent/`，不另建重复状态源。
不将全世界观系统、RP、Scene 生成、通用 provider 升级或新基础设施纳入本任务。

## 恢复快照与已有进度

- 目标目录：`/Users/tywww/.codex/worktrees/df37/ai-writing-assist`。
- 当前分支：`archive/ask-world-model-probes-wip`；HEAD：
  `7e75154ad1f0d6d8d26a86a04bb19206c72ccf54`。
- 核查时本地 `origin/main`：`94f7ba64b1545b5ae479e27a323a9485e2055f2c`；
  相对 HEAD 为 0 ahead / 754 behind。未 fetch，不能视为最新远端状态。
- 既有 WIP 为七个已跟踪文件：Makefile、Ask World eval runner、eval 数据集说明与测试、
  AskWorldService、world API 测试、Prompt 体系说明；另有无关未跟踪 `.zcode/`。
  本次仅新增此计划，不改动这些文件，不切分支、不提交。
- 三个生产入口已经存在：回答、重开引用、显式保存 pending suggestion。
  不需要重新开发整个功能。
- WIP 已增加 `eval-ask-world-model`、7 条合成证据的真实模型诊断、
  `gpt-5.6-sol / medium` 替代教师校准，以及精确属性缺失时的拒答提示。
- 本地历史产物记录：早期 teacher run 为 6/7；后续
  `backend/evals/artifacts/results/ask-world-teacher-calibration/summary.json`
  记录 DeepSeek V4 Flash 连续 3 轮、共 21 次 case execution 全通过。
  这只是既存报告，本次未重新调用模型、未独立重演，也不证明当前主线质量。
- 报告明确 `blocking=false`、`human_validated=false`。目前没有真人校准或真实小说
  完整入口验收的完成证据。
- 当前主线已包含相近的精确属性拒答提示；浏览器问世界流程携带
  `context_confirmation_id`，服务消费 Evidence 确认并约束来源。
  旧探针直接调用 `_generate()`，不能证明检索、确认、引用回开和建议保存链路。
- 下一步：重新核对本地/远端 Git 状态与适用规则，在新的主题 worktree 中制作
  “旧 WIP → 当前主线”的逐文件取舍清单，先迁移仍缺的 eval 能力。

## 剩余问题

1. **代码尚未交付**：旧 WIP 未提交，且与主线存在较大版本差异；直接整体合并会夹带
   过时接口、重复 Prompt 修正或无关内容。
2. **评分有盲区**：`evaluate_ask_world_model_cases()` 主要检查答/拒答、引用 key 集合和
   冲突时是否有 uncertainty。正确 key 配上错误主张、answer 与 claims 不一致、
   泛泛 uncertainty 掩盖遗漏冲突，可能通过确定性评分。
3. **数据覆盖不足**：7 条主要覆盖近失拒答和冲突，不能衡量普通单源、多源组合、
   长证据干扰、过度拒答、提示注入与当前确认范围。
4. **教师未经真人校准**：教师与确定性结果的一致率不能证明二者都正确，也不能直接
   升级为语义发布门禁。需检查教师是否接受已有错误参考或漏掉合法引用下的失真。
5. **缺少当前实际入口证据**：生产检索、确认 selected/excluded、版本漂移、来源回开、
   作者明确保存和前端异步状态仍需在迁移后的版本上验收。

## 执行顺序与验收

### P0：保护 WIP，迁移到当前主线

- 开始前核对 worktree、分支、dirty 文件、任务记录与远端可用状态；保留 `df37` 原样。
  后续实现在尽可能新的 `origin/main` 上建立 `codex/ask-world-quality` 主题 worktree；
  先核对分支名是否已被使用，不覆盖已有工作。
- 以当前代码为准，逐文件迁移仍缺的 runner、测试与手动 Make 入口；已有的 Prompt
  行为不重复加入。不迁移 `.zcode/`、旧完整源码或历史模型原文。
- 先运行 `make docs-check`；检查最新 world API/schema、Evidence facade、
  `open_project_llm_client()` 与 eval executor 契约，再适配新入口。
- **验收**：差异清单逐项说明迁移/已存在/弃用及理由；原 WIP 保留；无 API、schema、
  数据模型或生产 provider 行为变化，且当前调用契约的离线回归通过。

### P1：补足可审查的语义结果

- 保留确定性四门与模型诊断的分层。引用 precision/recall 是来源集合指标，不能命名为
  主张忠实度；冲突来源多于一个也不自动等于真正冲突。
- 在现有 runner 与报告中表达逐条主张的审查结论：依据充分、属性匹配、冲突呈现、
  answer/claims 一致、拒答是否合理。需要语义判断的结果由独立审查提供；
  无审查记录时明确 unavailable，不用引用集合推导“忠实”。
- 用少量离线反例验证评分：正确引用但数量错误、交换引用、只呈现一版冲突、
  answer 偷加无依据事实、明确证据却拒答、unknown 被包装为答案。
- 保持报告来源可追溯：代码版本/dirty 状态、dataset/Prompt/rubric hash、实际模型与
  脱敏 profile、结果完整性；失败或中断不得被记录成 complete/pass。
- **验收**：上述失真反例不能被汇总成“语义通过”；无语义证据时可见缺项；
  原有离线 gate 不受影响；不引入通用评测平台或新的生产接口。

### P2：扩大样本，完成教师与真人校准

- 首批建议形成 40 个不同 case 的合成候选集，按单源事实、多源组合、明确冲突、
  缺属性近失、无证据/范围排除、注入与干扰六类分层；覆盖数量、日期、身份、
  地点、原因，并包含可回答正例以防过度拒答。40 是启动规模，不是统计充分性声明。
- 7 条旧用例作为回归锚点，不据此反复调 Prompt 后又称为独立验证。
  按来源族拆分调试集与保留集，保留集在 rubric 固定后才运行。
- 对本次校准样本先核对参考答案，再独立审查模型输出；人工需覆盖全部安全关键、
  冲突、分歧案例及各普通类型。替代教师保留 `surrogate_teacher` 与
  `human_validated=false`，不得把教师输出写成真人意见。
- 教师的简短理由也可能含私有事实；真实稿件参与时，将请求、输出、教师理由与
  完整账本放到仓库外私有目录，仓库只留去原文的统计、hash 与审查结论。
- 若执行真实模型比较，沿用先前限定的 DeepSeek V4 Flash 生产模型范围；
  教师只是独立评审工具。恢复时核实可用性和既有授权/累计预算，不静默换模型。
- **验收**：逐 case 的参考、模型输出、人工意见与教师意见可追溯；安全关键失真
  无未解决项；列出教师漏判、误判、分歧与未覆盖范围。真人缺席时明确未校准，
  不把模型层设为发布阻断门禁。

### P3：在当前生产入口完成验收

- API 确定性回归覆盖 owner/novel 隔离、确认缺失/过期、排除来源不得回流、
  正文 draft/version/hash/content mode/range 绑定、回答前后来源漂移、
  citation current/stale/unavailable，以及回答零业务写入。
- 使用受保护的既有 `ai_novel_acceptance_guimi` 项目做浏览器验收，不重建或清库。
  明确设置并核对 `DATABASE_URL`；不能将其用于会清理数据的 E2E fixture。
  漂移/冲突/幂等的写入失败路径在专用可丢弃测试库验证。
- 真实问题覆盖可直接回答、需组合来源、证据不足和已确认范围外的问题；
  跑浏览器 → 确认资料 → ask → 引用回开链路，而非只跑 `_generate()`。
- 保存建议在合成项目验证：仅显式点击写 pending suggestion，不写正式 world；
  核对重复动作、失败反馈与原输入保护。
- 前端沿用既有界面，只修复已证实问题；验收加载、失败、停止、切项目迟到响应、
  引用跳转、已保存提示、窄屏。主界面不增加模型/hash/原始 JSON。
- **验收**：每个代表问题有回答/拒答、来源与回开证据；正常流与对应失败路径通过；
  作者逐条确认实际有帮助。真实模型及作者验收与工程测试分别报告。

### P4：门禁、文档与交付收尾

- 将无网络、无付费的 Ask World eval 回归纳入适用自动化入口，先核实主线实际
  收集范围，不把旧 worktree 的 CI 配置当作当前事实。
- 模型质量诊断继续手动执行、非阻断；经人工校准且样本稳定后，再另行决定是否
  建立语义门禁及阈值。当前不把 7-case 全过或教师 agreement=1.0 当成上线标准。
- 同步 eval 数据集说明、Make 使用方法、testing/development guide；只有生产
  用户行为改变才同步 world README、Prompt 契约与前端说明。
- 完成受影响测试、lint、`make docs-check BASE_REF=origin/main`、`git diff --check`
  与规则/需求核查；分别列明工程、模型、人工、浏览器和未覆盖项。
- **验收**：交付最小可审查 diff、脱敏报告及恢复说明。提交、推送、PR、合并、部署
  遵守当前授权；本计划不授权这些动作。

## 影响模块与接口风险

- 主要修改：`backend/evals/ask_world.py`、对应测试/数据集、Makefile 与必要使用文档。
- 确认/生产入口验收涉及 world、evidence、project/account 以及
  `frontend-console/vue/views/rag/RagSearchView.vue`；仅在证实缺陷后修改生产代码。
- 稳定边界：`/api/world/ask-world`、citations/open、suggestions；Evidence facade；
  project owner 的 LLM runtime。默认不改 wire/schema、不迁移数据库、不新增依赖。
- 本范围不需新增 ADR。若后续要引入 provider transport、新服务、存储或重大语义变化，
  单独提出证据与影响，不借评测任务扩展产品范围。

## 建议验证入口

在迁移后的主题 worktree 执行，以当时 Makefile 为准：

```bash
make docs-check
cd backend
uv run --locked --extra ci -- pytest evals/tests/test_ask_world.py -q
```

然后回到仓库根目录运行 `make eval-ask-world`；按实际受影响路径补 world/Evidence
契约测试。前端有改动时运行 `tests/vue/rag/RagSearchView.test.js` 及适用浏览器用例。
真实模型命令必须显式传入已核对的项目、数据集与仓库外 OUTPUT，并沿用累计账本；
不在自动化 CI 中读取账户模型连接或消费真实稿件。

## 本次计划的验证与关闭边界

本次已核对 worktree/Git、七文件 WIP、runner 与当前主线问答/确认调用链，以及
历史探针报告；没有运行付费模型、业务测试或浏览器验收。
`make docs-check`、`git diff --check` 与新增文件 whitespace/code fence 检查均通过。
`make docs-check BASE_REF=origin/main` 未通过：现有差异触发 architecture-governance /
module-production，要求审查 world README、development/testing guide、架构 README、
documentation-maintenance、world/map 模块说明。未为通过门禁改动无关文档或填写未审查的
豁免；P0/P4 在迁移后的最小 diff 上逐项核对。后续 P0–P4 均未启动。

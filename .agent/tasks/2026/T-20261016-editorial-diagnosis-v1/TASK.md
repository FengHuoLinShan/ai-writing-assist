---
id: T-20261016-editorial-diagnosis-v1
title: 编辑审读诊断 A/B 试跑与盲评交接
status: completed
created: 2026-10-16T18:02:35+08:00
updated: 2026-10-17T09:15:19+08:00
---

# 编辑审读诊断 A/B 试跑与盲评交接

## 恢复快照

- 目标：实施对照试跑工程补缺，用 Codex gpt-6-luna/max 完成旧/新提示词冒烟及全量运行；交付盲评包与 HANDOFF，等待作者另开 Claude Sonnet 5.5 任务评分。本轮不做评分。
- 工作树：/Users/tywww/项目/ai-writing-assist/.worktrees/editorial-diagnosis-v1；分支 codex/editorial-diagnosis-v1。
- 已有提交：第一阶段 04424535a2a164f0274aee2f65dd8d300b3f236f（提示词、桥接、v2）。
- 候选提示词原始固定提交：c0a32c7778ab4faaaa9f949ef8ba8a7de0606318；当前运行器修复后固定候选提交为 `4133ff93b`（提示词与原 SHA 相同）；基线提示词来自 00d861283e34bdc0ef3f34ee5605c71e1f89c553。
- 数据库/runtime 已配置：该工作树忽略的 `backend/.env`（0600）指向本机 PostgreSQL 17 `127.0.0.1:18442/codex_luna_runtime_test`，并固定 `APP_ENV=development`、`AUTH_MODE=local`、`CODEX_CLI_COMMAND` 为本机 v0.163.0 可执行文件；只读连通核验通过，账户连接数据仍留在该专用库。
- 新持久私有目录：`/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016/`，root/raw/blind/mapping 均为 0700；旧 `/private/tmp/novelcraft-editorial-diagnosis-v1-run-20261016/` 请求数为 0，弃用且不删除。
- 连接验证与原因：在默认工作区沙箱内有2次 synthetic ready 尝试以 exit_code=1 / `codex_result_unknown` 结束，无 CLI event 或 `turn_started`，用量未知、无 request_id；之后以提权进程执行同一 `SettingsService().connect_account_llm_provider(db, "codex", None)` 成功1次。三次均只用 ChatGPT 订阅的 gpt-6-luna/max ready 请求，不含稿件，单独记账、不计入406。错误分类显示外层沙箱阻止 Codex CLI 写 PATH alias（`Operation not permitted`）；提权执行后 `codex-text-v3` 成功，未改适配器。
- 连接只读核验通过：active provider=`codex`，model=`gpt-6-luna`，`connected=true`，`verified_at=2026-10-16T12:50:51.946704+00:00`。
- 新持久私有目录 manifest hash `d2a86df68d7f09ca9ce50362a360ccfabef66e7657980e3fa6595ef5e7c5fe48`，29例、上限406。S01 冒烟启动后在 assistant submit 前置路径遇到 `AttributeError`；没有评测 provider 请求（request_count=0、observations=0），case 已标 `stopped`，不重放。仅生成一份 baseline `started` 元数据；blind/mapping 为空。旧 `/private/tmp` 目录请求数仍为0，弃用且不删除。
- 当前进度：原运行目录、attempt-2 和 attempt-3 的 S01 均停止且评测请求数为0，不重放。attempt-1/2 的确切根因是 JSON state 的 `state_path` 字符串直接传给 `Path` 写入函数；attempt-3 修复路径写入并通过提交/快照后，task 记录显示 Assistant worker 因普通 session 未声明 lease checkpoint 而拒绝执行。runner 已在 `run_task_inline()` 执行期间临时设置并恢复既有 `task_checkpoint_enabled` 内部标记，新增 fake-client 回归断言该标记与恢复行为。
- attempt-4 已完成 S01 冒烟及 29 例全量对照：共 304/406 次请求，58/58 臂完成，全部 usage 已知；盲包与 HANDOFF 已生成。当前下一步是等待作者另开 Claude Sonnet 5.5 会话返回盲评分，不在本轮评分或解盲。
- 2026-10-17 开评前补规则：58 份输出中 23 份无意见，原量表无“不适用”，空报告会在依赖意见的五项上虚高。`review.py` 改为五项在无意见时必须 `null`、有意见时必须打分，`post_revision_judgment` 可 `null`（本批无修订稿复核）；汇总口径已在揭盲前写入 eval README。盲评改在隔离工作区进行，见“试跑产物路径”。

## 范围与边界

- 新增 editorial_cases_v3.json，保留 v1/v2；29 例标注 report、no_report 或 unchecked，增加与主要约束对应的原创正例。评分按正例召回、对照误报和 unchecked 正确率分开报告；零意见基线为 0/11 命中、11/11 漏报、0/17 误报、0/1 unchecked 正确。
- 新增仅在 backend/evals 使用的运行器：冻结基线 _SYSTEM 与候选固定提交 _SYSTEM；同一 Assistant worker、validator、来源和范围，仅切换系统提示词；两臂顺序随机。
- 只用本机专用 codex_luna_runtime_test PostgreSQL 与已验证的 owner Codex 连接。每请求经 modules.project.facade.open_project_llm_client() 核验 codex/gpt-6-luna/max；不符即停、不回退。
- 总请求硬上限：29 × 2 × 7 = 406，冒烟计入。case 启动与请求预留先持久化；出错、未知用量、进程中断均不重放；同一外部依赖连续 3 次失败暂停全局。
- 原始结果与 blind 映射仅存仓库外私有目录；本轮不评分，不 push、不开 PR、不合并、不部署。

## 决策与实现

- 已定：不新增 mismatch_type，不加风格偏好/伦理入口，不新增结构改写路径；只切换提示词；审美偏好默认不报。
- v3 替换重复 v1 情节的 S01 为伤势连续性冲突；新增客观记录、明示谜题、复仇、连载承诺、主动主角目标等正例，另有制度性被动人物对照。新文均为原创合成文本。
- editorial.py 有内部执行 seam，允许 runner 注入系统提示词、假/真客户端及请求钩子；tasks.py 只从 db.info 读取该内部选项，不暴露 API 或设置。
- 同步提示词行为措辞、Prompt README 权威位置、盲评导入模型与测试。worker synthesis checkpoint 同步保留累计请求预算，避免合并写回时覆盖预算记录。
- 盲评包每份只用随机 blind ID；映射放在 blind/ 外。HANDOFF 禁止给出分组、候选 SHA、分支或映射路径。

## 进度与验证

- [x] v3 数据、分母标签、零意见基线及哈希测试。
- [x] Luna 对照运行器离线实现：database gate、owner/Project facade profile 核验、wrapper manifest、全局请求账本、失败/未知/中断停止、不重放、随机化、原始输出与 blind 文件权限。
- [x] review.py 15 项盲评导入 schema 与契约测试；Assistant fake-client 注入测试。
- [x] 定向 Assistant 与评测测试：186 passed（2026-10-16）；make lint 通过；make prompt-contracts 26 contracts 通过。
- [x] 补测（已随 `c0f4fd2` 提交）：新增 `test_editorial_execution_hooks.py` 17 项，覆盖提示词传递、多章请求边界与累计预算、注入客户端、失败/未知/取消/来源变化及单方向意见；修复 `_synthesize()` 合并进度覆盖累计请求预算的问题。新增17项通过，结合相关旧审读/桥接测试共48 passed，`make lint` 通过；定向覆盖率从78.1%升至84.2%，未重跑标准全库覆盖率门禁，不据此宣称全库覆盖率通过。
- [x] `TEST-COVERAGE.md` 的补测要点已并入本节，源文件已删除；原内容对应的补测代码已在 `c0f4fd2` 提交。
- [x] git diff --check 通过。make docs-check BASE_REF=origin/main 因 module-tasks 规则列出 3 份未变文档；按维护流程以无当前架构影响说明复跑 scripts/check_architecture_docs.py 并通过。理由：只增加 Assistant 评测专用 db.info 钩子；任务注册、队列/租约/生命周期、API、跨模块契约及恢复语义未变，Assistant 与 Prompt README 已同步。
- [x] 工程与数据本地提交：c0f4fd2b28237ff6ce1ed35c45d2644cf2a95a4c；Project profile mismatch fail-closed 修正：c0a32c7778ab4faaaa9f949ef8ba8a7de0606318；runner 路径修复固定候选提交：`30cf2ab38`，候选 `_SYSTEM` 与原提示词 SHA 相同。
- [x] 配置专用数据库 URL，并用 PostgreSQL 17 做只读连通核验；数据库目标为 `codex_luna_runtime_test`，没有触碰主工作树应用库。
- [x] 重跑 S01 两臂预检；第一次在 owner 连接门禁停止，request_count=0。
- [x] 创建持久私有目录与 0700 子目录；生成新的 manifest/state，文件权限0600，固定 candidate SHA、数据集及随机次序，request_count=0。
- [x] 连接验证：两次默认沙箱尝试未知，一次提权后验证成功；四项 profile 只读核对通过。真实生成总计3次，均为合成 ready，不计入406。
- [x] 原运行目录与 attempt-2 S01 两次因 `state_path` 类型错误于首个评测请求前停止；各账本 `request_count=0`、`observations=0`，没有覆盖或重放。
- [x] 修复 state path 转换并补齐既有 `register_task_handlers()`。attempt-3 验证继续到 Assistant task guard，专用库失败记录为 `RuntimeError: Editorial review requires a lease-fenced session`；该账本请求数仍为0，未发起 provider 调用。
- [x] runner 只在每次 `run_task_inline()` 期间设置并恢复 `task_checkpoint_enabled`；fake-client 回归覆盖路径持久化、guard 标记及 provider 前停止。
- [x] 修复后相关 Assistant/评测/任务注册测试 78 passed；`make lint`、`make prompt-contracts`、基础 `make docs-check`、`git diff --check` 通过。`make docs-check BASE_REF=origin/main` 列出既有 module-tasks 文档核对项；使用正式 checker 附无当前架构影响说明后通过。
- [x] runner 路径与 task-handler 修复提交 `30cf2ab38`；task checkpoint 标记修复提交 `4133ff93b`；候选 `_SYSTEM` 与 `c0a32c7778ab4faaaa9f949ef8ba8a7de0606318` 相同。
- [x] attempt-4 S01 两组 smoke：14 次请求，candidate/baseline 各 7 次；两份输出均 coverage_complete、checked chapters 为 1–3、validator_survivors 各 4；回执 14/14 成功。
- [x] attempt-4 全量 29 例：request_count=304/406；confirmed provider requests=304，uncertain=0，unknown usage=0，dependency failure streak=0，paused_reason=null；29/29 case complete，58/58 arm completed，每臂最多 7 次。
- [x] 盲包完整性：58 份随机盲号输出，对应 29 个样本各两份；预期标签分布按输出副本计为 report=22、no_report=34、unchecked=2；58 项 coverage_complete=true；58 条映射，两个条件各 29 条。发现辅助上下文有 4 处 `candidate` 一词指作品候选文本，已只在盲评副本中改写为“valid POV confirmation applies to the passage”；原始输入、报告、映射未改，复扫未发现条件名、SHA 或分支名泄漏。
- [x] 原始结果、状态和盲号映射仍在私有持久目录，目录权限 0700、文件权限 0600；没有复制到仓库。
- [x] 已生成 `HANDOFF-blind-review.md`，定义 15 项评分、逐意见命中/误报与 case 级漏报格式，并限定评阅者读取范围；本轮未评分、未解盲。
- [x] 开评前补规则（2026-10-17）：`review.py` 支持不适用项 `null` 并加契约测试；eval README 写入揭盲前固定的汇总口径与已知局限（方向条数暴露分组、S02 客观记录正例待查、S09 复仇正例混入出题说明、样本极短、unchecked 仅 1 例）；HANDOFF 改为相对路径、逐份追加、中断续评与自检流程；隔离工作区已建。
- [x] 全量结束摘要：两组各 152 次请求；candidate 1,919,061 input / 218,154 output tokens，baseline 1,846,123 input / 301,400 output tokens。摘要只记录已知 usage，不推算费用。
- [x] 交付门禁：`make docs-check` 通过；`make docs-check BASE_REF=origin/main` 仍报告既有 module-tasks 三份文档清单，附无当前架构影响理由重跑 `scripts/check_architecture_docs.py` 后通过；HANDOFF 的 JSON 示例可解析且包含 15 个精确评分 key，未包含映射文件路径；收尾 `git diff --check` 通过。

## attempt-4 全量结果（2026-10-17）

- 私有运行目录：`/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016-attempt-4/`；manifest hash `28a5d439651658e85eaa0a46c8cbfe77688f76bb6578bd6d17bed16a0319f695`，固定候选提交 `4133ff93b6e3c27e59e967831dbe4d4322f329a2`，29 个样本、58 个随机化 arm 顺序，全局上限 406。
- 全量已正常退出（exit 0）。最终账本：reserved=304、confirmed provider requests=304、observations=304，全部 `succeeded`；uncertain=0，unknown usage=0，dependency_failure_streak=0，paused_reason=null。29/29 case complete，58/58 arm completed，单臂最大 7 次。
- 请求及用量：candidate 152 次（1,919,061 input tokens、218,154 output tokens）；baseline 152 次（1,846,123 input tokens、301,400 output tokens）。不推算费用。
- 文件完整性：raw 中 58 份 per-arm 完成记录，加 `summary.json` 与 `experiment-evidence.json`；blind 58 份；mapping 58 项。blind 预期结果按输出副本分布为 report=22、no_report=34、unchecked=2，所有 58 份 coverage_complete=true，validator_survivors 均与 finding 数一致。
- 隐私核验：根目录和 raw/blind/mapping 均 0700；manifest/state 与所有 raw、blind 文件均 0600。评分回收目录 `reviewer-return/` 为 0700，预定评分文件不存在，等待外部评阅。
- 盲包复扫没有发现分组名、系统提示词、SHA 或分支名；4 个辅助上下文里的 `candidate` 指作品候选文本，已仅在盲包副本改成 `valid POV confirmation applies to the passage`，避免与实验分组混淆。
- 未做评分或解盲。下一步：作者另开 Claude Sonnet 5.5 任务，按 HANDOFF 交回 JSONL；开发 Agent 验证导入后再解盲汇总。

## 盲评与揭盲汇总（2026-10-17）

- 评分：作者在隔离工作区启动 Claude Sonnet 5.5 单评阅者会话，58 份全部评完；`check_review.py` 与 `load_editorial_blind_reviews()` 导入均通过。评分文件已复制到 attempt-4 `reviewer-return/`（0600，SHA-256 `6a9b4431c5393c41c80aa86b09a60067fb8bd7a6d7180bf567908faa496bd1fe`）；去原文汇总在同目录 `unblinded-summary.json`。会话记录显示只读取工作区与自身 scratchpad，逐份展示后评分。
- 主指标（按 eval README 揭盲前口径）：

| 指标 | 基线 | 候选 | 零意见基线 |
|---|---|---|---|
| 正例命中 case | 10/11 | 8/11 | 0/11 |
| 对照出现误报的 case | 12/17 | 3/17 | 0/17 |
| 对照误报意见条数 | 32 | 3 | 0 |
| 正例中误报意见条数 | 15 | 9 | 0 |
| unchecked 正确 | 0/1 | 0/1 | 0/1 |
| 意见总数 / 空报告 | 71 / 6 | 26 / 17 | 0 / 29 |

- 配对：对照例 10 对为“基线误报、候选无误报”，没有反向；正例 2 对为“基线命中、候选漏报”（`S09_revenge_promise_unfulfilled`、`unique_key_contradiction`），没有反向。`S02_objective_record_conflict` 两组都漏报。
- 漏报原因（读 raw 核实）：编辑层每章请求只含本章文本、brief、本章内摘要和世界/结构上下文，不含前面章节原文，validator 也只认本章引文。S02 两组的编辑层都写明“本轮未提供另一份记录的原文”；`unique_key_contradiction` 候选组看到异常却按“不足以判定是有意线索还是遗漏”降为 low，并聚焦“空口袋”。这是两组共有的跨章证据缺口，候选的替代解释与 unchecked 规则使其更倾向降级。S09 的出题说明缺陷见 README 局限。
- 15 项评分：按固定口径，候选多数项均值更高，但空报告上 207 个非 null 项中 198 个是评阅者模板化的默认 2 分，均值对候选（17 份空报告）偏高。事后敏感性分析只看有意见的输出（基线 23、候选 12）：候选在方向可执行性（1.67/1.04）、最小修订（1.92/1.17）、有意形式误判（1.75/1.17）、口味伪装（1.67/1.09）较好，这几项与方向条数处理本身相关；来源误读、回看与替代解释、强意见误报大致持平；意见聚合两组都低于 1（0.92/0.74）。
- 稳定性复评（2026-10-17）：作者在同一隔离工作区另开 Sonnet 5.5 会话（`/clear` 后无前次上下文），评分写入 `sonnet-review-2.completed.jsonl`（SHA-256 `4f5e5f6bd4906934bb127c2f03e3bc9edefeef1f09524c062d73118d69f1ef03`），自检和导入均通过。会话只 `ls` 到第一轮评分文件名，未读取其内容。两轮 case 结果 58/58 一致，主指标表全部复现；finding 分类 96/97 一致，唯一分歧是 `S19_active_goal_passivity_mismatch` 基线第 0 条由 hit 改判误报，该 case 仍为命中，因此基线正例中的误报条数变为 16。15 项中多数项完全一致率 ≥ 83%；作者声音尊重（30/35）、理解与不喜欢区分（46/58）、口味伪装（48/58）分歧较多，分歧集中在基线组，且多为第二轮给分更高。第二轮评分脚本对未逐项写明的条目默认填 2 分并写“无相应问题”，在有意见输出的非 null 项中占基线 148/322、候选 106/168，因此第二轮的分项均值证据更弱。两轮由同一模型评出，只证明评阅结果可复现，不等于独立评阅者之间的一致。汇总见 attempt-4 `reviewer-return/stability-summary.json`。
- Kimi 跨模型复评（2026-10-17）：作者在同一隔离工作区用 Kimi Code 评了一轮，模型为 `k3-256k`、thinking max，评分写入 `kimi-review.completed.jsonl`（SHA-256 `6579c62568cb756e0ecb8f9a7740f0c8adb4a6d045da58544244df7dcd114107`），自检和导入均通过。导入器把 `reviewer_version` 固定为 Sonnet 标签，所以该文件也写成了 Sonnet；实际来源以本条和 Kimi 会话 `session_11ce5982-…` 的 wire 日志为准，原文件不改。会话逐份 `Read` 后手写评分，没有用脚本填默认分（697 个非 null 项有 452 种理由）；只 `ls` 到 Sonnet 评分文件名，未读取其内容，也没有调用数据源类工具。
  - 结果：对照两组仍是 12/17（32 条）与 3/17（3 条）。按规则，不应报样本上的任何意见都算误报，所以这一项只由输出本身决定，各评阅者必然一致，不能拿来证明评阅可靠。正例命中基线 10/11、候选 9/11，比 Sonnet 多出 1 例：`unique_key_contradiction` 候选组那条已降级的意见，Kimi 算命中，同时注明它没有引用第一章原文。unchecked 基线 1/1，比 Sonnet 多出 1 例：Kimi 认为 `S15` 的 `unchecked` 字段写了“无法核实永乐商税”，就算留待外部查证。
  - 分歧所在：在正例和 unchecked 样本的 62 条意见上，Sonnet 两轮之间 61/62 一致，Kimi 与 Sonnet 只有 41/62 一致。21 处分歧全是 Sonnet 判误报、Kimi 判命中，分布为 S07 5 条、S08 5 条、S15 4 条、S14 2 条、S09 2 条、`unique_key_contradiction` 2 条、S19 1 条。原因是“命中”的口径不同：Sonnet 只认点明评测重点所指失配的意见，Kimi 把同一问题区域内、有依据的相关意见也算命中。S07、S08 等例的 `evaluation_focus` 写的是判断准则，没有写出具体的失配对象，留下了解释空间。因此“正例中的误报条数”随评阅者变化很大（Sonnet 15/9，Kimi 5/2），不宜作为决策依据。
  - 分项（只看有意见的输出）：Kimi 下候选组仍在各项上不低于基线，但方向可执行、最小修订、有意形式误判三项的差距比 Sonnet 小。与 Sonnet 的完全一致率在最小修订（19/35）和方向可执行（23/35）上较低。三方汇总见 attempt-4 `reviewer-return/three-rater-summary.json`。
- 结论（探索性，AI 评阅者、29 例微型样本）：三轮评分都显示候选大幅降低对照误报；正例召回代价是 1–2 例，S09 三轮都判漏报，`unique_key_contradiction` 是否算漏报取决于评阅口径。召回损失主要来自编辑层缺少跨章原文，而非单纯提示词措辞；该例候选输出自己就写明“第1、2章仅有既有审读摘要，没有原文可逐句核对”。

## 试跑产物路径

- attempt-4 私有运行根目录：/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016-attempt-4/
- 原私有运行根目录（attempt-1）：/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016/
- 原 run S01 账本：该目录；manifest hash `d2a86df68d7f09ca9ce50362a360ccfabef66e7657980e3fa6595ef5e7c5fe48`，状态停止、请求数0。
- attempt-2 S01 账本：/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016-attempt-2/；manifest hash `3888e0a845025c1fecff92e938ea519e966737d7b4464004d3ba831db3f632c4`，状态停止、请求数0。
- attempt-3 S01 账本：/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016-attempt-3/；manifest hash `a242f8956649c321bc263d2ecac85b7828c06c7551bb805c5a71d1c7bcf16e9e`，状态停止、请求数0；任务失败原因由专用库的任务错误字段核实。
- attempt-4 原始输出：/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016-attempt-4/raw/
- attempt-4 盲评包：/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016-attempt-4/blind/
- attempt-4 盲号映射：/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016-attempt-4/mapping/blind-map.json（仅供开发 Agent 解盲；不得交给评阅者）
- 评分回收文件：/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016-attempt-4/reviewer-return/sonnet-review.completed.jsonl
- 盲评交接：本目录的 HANDOFF-blind-review.md，使用相对路径；此文件不得包含映射路径。
- 隔离盲评工作区：/Users/tywww/novelcraft-private/editorial-blind-review/（0700）。只含 HANDOFF 副本、attempt-4 blind/ 副本（58 份）、空的 reviewer-return/ 与格式自检脚本 check_review.py；不含 raw、mapping、仓库文件。Sonnet 会话从该目录启动。
- check_review.py 是仓库外一次性辅助脚本，只用标准库，镜像 `EditorialBlindReviewRecord` 规则，并额外核对 expected_result、finding_count 与 58 份全覆盖。已用 58 份 blind 构造 522 条有效/无效记录与 `review.py` 交叉核对，结论一致。以 `review.py` 导入为准。
- 评分回收：作者交回后，开发 Agent 把 `editorial-blind-review/reviewer-return/*.jsonl` 复制到 attempt-4 的 `reviewer-return/`，用 `load_editorial_blind_reviews()` 导入，再按 eval README 的固定口径解盲汇总。
- attempt-1 目录只有停止的 S01 started 元数据，请求数 0；旧 /private/tmp 运行目录 manifest/state 保留但弃用，请求数 0。

## 最终交付状态与下一步

attempt-4 全量 304 次 Luna 请求、58 份盲评、导入校验与揭盲汇总均已完成，本地提交，未推送、未开 PR。结果见“盲评与揭盲汇总”。后续已按作者授权启动 [T-20261017-editorial-cross-chapter-evidence](../T-20261017-editorial-cross-chapter-evidence/TASK.md)，补跨章证据与硬矛盾规则，完成 v4 两组对照并交付第二轮盲评包；评分与揭盲待后续独立授权/任务。

## 2026-10-17 工程合入

当前用户已授权完成成果交付。源分支全部 22 个提交已通过 PR [#250](https://github.com/FengHuoLinShan/ai-writing-assist/pull/250) 合入 main `2cf4bbd5f01792b5fb06f7d5b7f380e6447fb004`，固定 head 六项必需 CI、CodeQL 和敏感信息检查均通过；详细交付/验证见后继跨章任务当前恢复快照。历史模型输出、盲映射和账本未改写或重放；S15 遗留不宣称解决，未部署。

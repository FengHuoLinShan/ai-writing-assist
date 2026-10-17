---
id: T-20261017-editorial-cross-chapter-evidence
title: 编辑审读跨章证据、硬矛盾修正与第二轮盲评交接
status: active
created: 2026-10-17T09:15:19+08:00
updated: 2026-10-17T09:34:52+08:00
parent: T-20261016-editorial-diagnosis-v1
---

# 编辑审读跨章证据、硬矛盾修正与第二轮盲评交接

## 恢复快照

- 实际完成：恢复上一轮盲评/揭盲结果；核对目标 worktree 干净，位于 `codex/editorial-diagnosis-v1`，HEAD `6338736cfe2f11a53dc0f7a918afd2a49dac4e85`，较 `origin/main` ahead 12；开放任务索引已切换到本任务，旧任务已关闭并指向本任务。
- 当前里程碑：B 固定提交 `346ac97e6af8167a5f23f766dc25d4a927b93676`；有界并行 runner、第二轮评阅规则、README/HANDOFF、离线测试和盲评隔离工作区均已完成；并行全量对照 35/35 case 完成，未评分、未揭盲。
- 下一步：等待作者指定的盲评者完成第二轮评分；由开发 agent 按评阅者分别校验并揭盲汇总，再按冻结门槛逐评阅者报告采纳或“评阅者间不一致”。
- 阻塞：无；等待作者指定的 Sonnet 5.5/Kimi Code k3 评阅文件，开发 agent 后续按评阅者分别揭盲汇总。
- 工作区：`/Users/tywww/项目/ai-writing-assist/.worktrees/editorial-diagnosis-v1`，分支 `codex/editorial-diagnosis-v1`；当前 HEAD `086f7a51c18061c5e231296409bc68104ac84839`，较 `origin/main` ahead 19。
- 最后核实：2026-10-17T11:19:52+08:00。

## 目标与验收

- 目标与交付物：Assistant 内部跨章原文证据账本及安全引用验证；硬矛盾提示词修正；不可变的 v4 合成数据集；固定提交 SHA 的 A/B runner；离线覆盖测试；按授权完成 Codex Luna 两组对照、盲评包、隔离盲评工作区和 HANDOFF。
- 完成条件：用户列明的 worker、validator、续跑、账本边界、前端跨章依据呈现/桥接/改后复核回归、提示词、35 例标注、请求计数和运行守卫全部实现；受影响 Assistant/eval/frontend 验证、`make lint`、`make prompt-contracts`、`make docs-check BASE_REF=origin/main`、`git diff --check` 全过；真实运行最多 490 次且连接、项目 facade 与专用 DB 核验通过；盲包不泄露分组，文件/目录权限正确；输出记录各组 SHA、请求数、case 状态、私有路径、工作区路径。
- 非目标：本轮不评分、不揭盲、不调用其他模型、不推送/开 PR/合并/部署；不改 v1–v3 数据、哈希、API 或公开设置。

## 上下文与边界

- 关键路径与来源：旧任务 `.agent/tasks/2026/T-20261016-editorial-diagnosis-v1/TASK.md` 的“盲评与揭盲汇总”；实现 `backend/modules/assistant/editorial.py`、`editorial_contracts.py`、`editorial_bridge.py`、对应前端和测试；runner/dataset/README 位于 `backend/evals/`；提示词权威文档 `docs/prompts/Prompt体系设计.md`。
- 硬约束与授权范围：仅 Codex `gpt-6-luna/max`，经 owner 当前已验证连接和 `open_project_llm_client()` 核验；唯一数据库 `codex_luna_runtime_test`；两组总请求上限 490（含冒烟和被中止运行的 reservations），连接验证单独记账；同依赖连续失败 3 次停止；不重放任何 started request；模型门禁前不得真实运行。作者明确要求从头重跑，因此新输出不复用旧输出，但旧 20 次请求计入新账本 offset。原始输出和 blind 映射在仓库外私有目录，目录 0700、文件 0600。
- 盲评边界：只交付第二轮盲包和隔离工作区，作者另开 Claude Sonnet 5.5；本任务不评分、不揭盲。
- 依赖：当前 Codex owner 连接、开发阶段模型规则、专用 PostgreSQL、Claude 盲评由作者后续执行；无子代理委派。
- 已确认事实：上一轮候选相对基线把对照误报从 12/17 降至 3/17，但正例命中从 10/11 降至 8/11；跨章原文未进入逐章请求，validator 只认可本章引文；S02 两组漏报，unique-key 矛盾被降级。细节见旧任务笔记。
- 假设与待决问题：章节/分段 source 的持久身份、内容 hash 与定位格式须以当前 worker、ORM/迁移和恢复代码核实；前端能否已有多章节证据呈现/桥接能力待追踪后决定。

## 里程碑与进度

- [x] 实现与回归：carry_forward 源验证、32 条/6000 字 checkpoint、续跑/同章后续分片、当前段必要引用、前文账本准入及硬矛盾提示词；已有卡片/桥接/改后复核路径补跨章回归。
- [x] v4 与 A/B runner：35 例与 14/20/1 分母、固定门槛、固定 A 提示词 SHA、B 提示词提交参数、内部账本切换、14 次内冒烟核验与 490 总上限；两 arm 有界并行、旧 reservation budget offset、独立会话和输出目录锁均有离线回归。
- [x] 文档初步同步：Assistant README、Prompt 体系、eval README、助手设计文档、module-tasks 必需文档逐项检查更新；等待完整终验门禁。
- [x] Luna 运行：初版尝试的 20 次 reservation（19 成功、1 次用量未知）计入总上限；新目录并行重跑 388 次全成功，累计 408/490；35 case 全完成。
- [x] 盲评交接：70 份盲包、仓库外映射、支持 Sonnet/Kimi 标签的新 HANDOFF、更新后的 checker、空 reviewer-return 和四项隔离工作区已交付；本任务不评分/揭盲。

## 决策、发现与失败

- 2026-10-17：上一轮盲评已完成，旧任务结果闭环；当前授权构成新可验收结果，因此新建本任务并关闭旧任务。旧盲评分不改变本轮冻结门槛。
- 2026-10-17：A 组必须用系统提示词提交 `4133ff93b6e3c27e59e967831dbe4d4322f329a2` 且账本关闭；B 组提示词和账本均来自本次固定提交。A 组 schema 仍包含 carry_forward 字段、worker 忽略，作为 README 局限记录。
- 2026-10-17：作者补充，盲评 HANDOFF 禁止脚本给缺少逐项判断的条目填默认分/理由；作者可对同一包复评一次，若复评则揭盲报告 case 结果一致数、finding 分类一致数、各分项完全一致率及相同理由文本比例。
- 2026-10-17T11:09:33+08:00：依据作者关于第一轮 Sonnet ×2 + Kimi 三方评分的复盘指示，且在第二轮评分/揭盲前，finding 分类扩为 `hit`/`related`/`false_positive`；仅 `hit` 决定 `report`/`unchecked` case outcome，`no_report` 仍按输出意见数；支持 Sonnet 5.5 与 Kimi Code k3 固定 reviewer 标签。主指标正例误报仅计 false_positive，related 单列；一致性仅用于 report/unchecked；采纳门槛逐评阅者应用、任一未满足则报告“评阅者间不一致”并交作者裁定。本次不改 v4/evaluation_focus/门槛，不重跑模型、不评分、不揭盲。依据文件位于 attempt-4 的 `reviewer-return/kimi-review.completed.jsonl` 与 `reviewer-return/three-rater-summary.json`；本次不读取评分内容或分组映射。
- 2026-10-17：v4 runner 将 B 提示词固定到提交 SHA，manifest 差异测试须在该提交产生后运行；未提交前 HEAD 仍等于 A 的提示词，测试按预期拒绝相同提示词。
- 2026-10-17：B 固定提交为 `346ac97e6af8167a5f23f766dc25d4a927b93676`；A 提示词固定提交为 `4133ff93b6e3c27e59e967831dbe4d4322f329a2`。B SHA 不得在本轮候选代码修改后继续沿用；runner 会拒绝候选提交之后的 Assistant worker 变更。
- 2026-10-17：runner smoke 自测覆盖 A/B 各七个回执的上限、B 转发前文引文且 validator 报告命中该引文、缺失该验证时失败关闭并暂停。
- 2026-10-17：作者要求将真实运行改为并行并从头重跑。初版顺序全量在 S07 运行中停止：`unique_key_contradiction` 两组共 14 次成功请求；`S07_goal_mismatch` 的 baseline 有 5 次成功和 1 次已确认 provider attempt 但用量未知；合计 20 次 reservation。该用量未知请求保留在旧私有账本，新运行不复用旧输出，预算 offset 固定为 20。v4 有 81 章，均小于 12000 字；每章至多 reader/editorial 各一次，1–3 章样本 synthesis 至多一次，故新运行最多 388 次，合计上界 408/490。
- 2026-10-17：并行采用单进程 asyncio、最多两个 arm 同时运行、每 arm 独立数据库会话、arm 内章节严格顺序。RequestLedger 在单事件循环中同步 reservation；全局暂停后禁止新 reservation；输出目录独占文件锁阻止同一目录多进程。后续运行沿用旧账本 offset；不重试旧 started request。
- 2026-10-17：`evals/tests/test_editorial_dataset.py` 与 `test_editorial_prompt_ab.py`：12 passed；包括固定 A/B 提示词、only-B ledger toggle 和 smoke 前文证据门禁。

## 验证证据

- 初始恢复：`git status --short --branch` 显示工作树干净；`git rev-parse HEAD`=`6338736cfe2f11a53dc0f7a918afd2a49dac4e85`；`origin/main` ahead 12；旧任务揭盲汇总和 HANDOFF 模板已读取。
- 2026-10-17：`UV_CACHE_DIR=/private/tmp/uv-editorial-cross-chapter uv run pytest modules/assistant/tests -q`：169 passed。
- 2026-10-17：定向 Assistant/eval 命令 63 passed；1 个 A/B 提示词差异测试因 B 固定提交尚未产生而预期失败，提交后重跑。
- 2026-10-17：B 固定提交后 `UV_CACHE_DIR=/private/tmp/uv-editorial-cross-chapter uv run pytest evals/tests/test_editorial_dataset.py evals/tests/test_editorial_prompt_ab.py -q`：12 passed。
- 2026-10-17：`npm run lint`（frontend-console）通过；`npm run test:e2e:editorial -- editorial-revision-bridge.spec.js` 在专用本机 `codex_luna_runtime_test` 上 2 passed，无真实模型调用。
- 2026-10-17：`make lint`、`make prompt-contracts`（26 contracts）通过；`make docs-check BASE_REF=origin/main` 在补齐 `docs/modules/12_infrastructure.md` 以后通过；`git diff --check` 通过。
- 2026-10-17：最终组合验证：Assistant 与相关 eval 共 181 passed；`make lint`、前端 `npm run lint`、`make prompt-contracts`、`make docs-check BASE_REF=origin/main`、`git diff --check` 均通过。前端编辑台/桥接 E2E 为 2/2 passed。
- 2026-10-17：并行 runner 变更后，`UV_CACHE_DIR=/private/tmp/uv-editorial-cross-chapter uv run pytest evals/tests/test_editorial_dataset.py evals/tests/test_editorial_prompt_ab.py -q`：16 passed；覆盖并行度上限、旧账本哈希/预算 offset、同目录进程锁及累计 490 上限。旧私有 state 通过新校验，累计 reservation=20。`make lint`（指定临时 UV cache）、`make prompt-contracts`（26）、`make docs-check BASE_REF=origin/main`、`git diff --check` 均通过；初次 `make lint` 使用默认 cache 被 sandbox 拒绝，指定临时 cache 后通过。并行 runner 本地提交 `b53adddad42823ef78de4a0bb13706742e8c26e3`。
- 2026-10-17：评阅规则补充后，`UV_CACHE_DIR=/private/tmp/uv-editorial-cross-chapter uv run pytest evals/tests/test_review.py -q`：15 passed，覆盖 related 的 report/unchecked case outcome、no_report 限定和固定 reviewer 标签；更新版 checker 在 `/private/tmp/editorial-checker-v2` 以三条合成记录验证通过（Kimi 标签、report related、unchecked related、no_report false positive），未读取 reviewer-return 内容。
- 2026-10-17：最终定向回归 `UV_CACHE_DIR=/private/tmp/uv-editorial-cross-chapter uv run pytest evals/tests/test_review.py evals/tests/test_editorial_dataset.py evals/tests/test_editorial_prompt_ab.py -q`：31 passed。第二轮规则修改后 `make lint`、`make prompt-contracts`（26）、`make docs-check BASE_REF=origin/main`、`git diff --check` 均通过。
- 2026-10-17T11:18:59+08:00：并行运行 manifest `757866921042b858b392c7de6ef48dcda4ccdcf22ddce1bff13880bd466cb81f`，runner SHA `c66759f8eff0fe04af0d7c6a26b82b0d622cbeea`；A 提示词 SHA `4133ff93b6e3c27e59e967831dbe4d4322f329a2`，B SHA `346ac97e6af8167a5f23f766dc25d4a927b93676`。新跑 388/388 成功；旧账本 20 条（19 succeeded、1 unknown usage）计入 offset；累计 408/490，连接验证 provider 请求 0、无新的未知用量、无暂停，35/35 case complete。
- 逐例状态（均 complete）：`S01_hard_contradiction`、`S02_objective_record_conflict`、`S02_unreliable_narrator`、`S03_causal_gap`、`S04_causal_setup_control`、`S05_comprehension_friction`、`S06_understood_but_disliked`、`S07_goal_mismatch`、`S08_mystery_promise_unfulfilled`、`S08_no_arc_open_ending`、`S09_revenge_promise_unfulfilled`、`S09_taste_slow_town`、`S10_sparse_style_control`、`S11_unsolicited_ethics_control`、`S12_countervoice_control`、`S13_clue_early`、`S13_clue_middle`、`S14_knowledge_confirmed_control`、`S14_knowledge_unconfirmed`、`S15_external_fact_pending`、`S16_duplicate_domain_finding`、`S17_serialized_chapter_no_hook`、`S17_serialized_promise_abandoned`、`S18_intentional_passive_character_control`、`S19_active_goal_passivity_mismatch`、`X01_timeline_conflict`、`X01_timeline_rescheduled_control`、`X02_adoption_explained_control`、`X02_identity_relation_conflict`、`X03_object_repaired_control`、`X03_remote_object_state_conflict`、`bell_ambiguous`、`intentional_blank`、`quiet_clean`、`unique_key_contradiction`。
- 私有运行目录：`/Users/tywww/novelcraft-private/editorial-cross-chapter-parallel-run-20261017/`；映射：`/Users/tywww/novelcraft-private/editorial-cross-chapter-parallel-run-20261017/mapping/blind-map.json`。输出中 70 个随机 blind ID 唯一、每 case 两份、每份均含该 case 全章节；内容哈希与生成源逐份相同。扫描未发现显式分组字段/组名、SHA 或分支名；四处单词 `candidate` 仅存在于同一 case 的 fixture `case_context` 原文，不是组别标记。目录为 0700、文件为 0600。
- 隔离工作区：`/Users/tywww/novelcraft-private/editorial-blind-review-2/`，顶层严格四项：HANDOFF 副本、`blind/` 70 文件副本、空 `reviewer-return/`、更新的 `check_review.py`。checker 接受两个固定标签；HANDOFF 标明不得脚本填默认评分/理由、related 口径及逐评阅者门槛。未查看 blind-map 内容、未评分、未揭盲。

## 交付结果

- 已交付：本任务笔记；开放索引已登记本任务；旧任务记录已完成并链接本任务。
- 未交付：作者/所选 AI 评阅者后续完成的盲评、逐评阅者揭盲和最终采纳裁定。
- 交付边界：代码、v4 与 runner 均已本地提交；未推送、未开 PR、未合并或部署；尚未评分或揭盲。
- 正式知识与后续任务：按用户要求更新 Assistant README、Prompt 体系与 eval README；盲评之后由开发 agent 揭盲汇总。

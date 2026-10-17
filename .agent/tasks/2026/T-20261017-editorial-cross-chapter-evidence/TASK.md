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
- 当前里程碑：B 固定提交 `346ac97e6af8167a5f23f766dc25d4a927b93676`；v4/runner/README/HANDOFF 已在 `ae3bfa4739b4334e2d0a00cab0bfb675edc07f11` 本地提交；全部离线测试与最终门禁通过。
- 下一步：显式核对运行环境数据库名为 `codex_luna_runtime_test`，调用 runner 读取当前 owner 连接并通过 `open_project_llm_client()` 检查 profile，建立私有运行目录；先跑 unique-key 两组冒烟，满足三项检查后用同一状态目录跑全量。
- 阻塞：无；真实模型连接和专用库需在离线门禁通过后重新实时核验，不合格即停止模型调用。
- 工作区：`/Users/tywww/项目/ai-writing-assist/.worktrees/editorial-diagnosis-v1`，分支 `codex/editorial-diagnosis-v1`；初始工作树干净，HEAD 为 `6338736cfe2f11a53dc0f7a918afd2a49dac4e85`。
- 最后核实：2026-10-17T09:15:19+08:00。

## 目标与验收

- 目标与交付物：Assistant 内部跨章原文证据账本及安全引用验证；硬矛盾提示词修正；不可变的 v4 合成数据集；固定提交 SHA 的 A/B runner；离线覆盖测试；按授权完成 Codex Luna 两组对照、盲评包、隔离盲评工作区和 HANDOFF。
- 完成条件：用户列明的 worker、validator、续跑、账本边界、前端跨章依据呈现/桥接/改后复核回归、提示词、35 例标注、请求计数和运行守卫全部实现；受影响 Assistant/eval/frontend 验证、`make lint`、`make prompt-contracts`、`make docs-check BASE_REF=origin/main`、`git diff --check` 全过；真实运行最多 490 次且连接、项目 facade 与专用 DB 核验通过；盲包不泄露分组，文件/目录权限正确；输出记录各组 SHA、请求数、case 状态、私有路径、工作区路径。
- 非目标：本轮不评分、不揭盲、不调用其他模型、不推送/开 PR/合并/部署；不改 v1–v3 数据、哈希、API 或公开设置。

## 上下文与边界

- 关键路径与来源：旧任务 `.agent/tasks/2026/T-20261016-editorial-diagnosis-v1/TASK.md` 的“盲评与揭盲汇总”；实现 `backend/modules/assistant/editorial.py`、`editorial_contracts.py`、`editorial_bridge.py`、对应前端和测试；runner/dataset/README 位于 `backend/evals/`；提示词权威文档 `docs/prompts/Prompt体系设计.md`。
- 硬约束与授权范围：仅 Codex `gpt-6-luna/max`，经 owner 当前已验证连接和 `open_project_llm_client()` 核验；唯一数据库 `codex_luna_runtime_test`；两组总请求上限 490（含冒烟），连接验证单独记账；同依赖连续失败 3 次停止；不重放不确定请求；模型门禁前不得真实运行。只读模型原始输出与 blind 映射放仓库外私有目录，权限目录 0700、文件 0600。
- 盲评边界：只交付第二轮盲包和隔离工作区，作者另开 Claude Sonnet 5.5；本任务不评分、不揭盲。
- 依赖：当前 Codex owner 连接、开发阶段模型规则、专用 PostgreSQL、Claude 盲评由作者后续执行；无子代理委派。
- 已确认事实：上一轮候选相对基线把对照误报从 12/17 降至 3/17，但正例命中从 10/11 降至 8/11；跨章原文未进入逐章请求，validator 只认可本章引文；S02 两组漏报，unique-key 矛盾被降级。细节见旧任务笔记。
- 假设与待决问题：章节/分段 source 的持久身份、内容 hash 与定位格式须以当前 worker、ORM/迁移和恢复代码核实；前端能否已有多章节证据呈现/桥接能力待追踪后决定。

## 里程碑与进度

- [x] 实现与回归：carry_forward 源验证、32 条/6000 字 checkpoint、续跑/同章后续分片、当前段必要引用、前文账本准入及硬矛盾提示词；已有卡片/桥接/改后复核路径补跨章回归。
- [x] v4 与 A/B runner：35 例与 14/20/1 分母、冻结门槛、固定 A 提示词 SHA、B 提示词提交参数、内部账本切换、14 次内冒烟核验与 490 总上限；假客户端覆盖账本边界及请求数。
- [x] 文档初步同步：Assistant README、Prompt 体系、eval README、助手设计文档、module-tasks 必需文档逐项检查更新；等待完整终验门禁。
- [ ] Luna 运行：专用库/profile 复核；两组随机顺序；先 unique-key 冒烟再全量；总账不超过 490。
- [ ] 盲评交接：生成盲包、随机映射、HANDOFF 和仅含四项内容的隔离工作区；本任务不评分/揭盲。

## 决策、发现与失败

- 2026-10-17：上一轮盲评已完成，旧任务结果闭环；当前授权构成新可验收结果，因此新建本任务并关闭旧任务。旧盲评分不改变本轮冻结门槛。
- 2026-10-17：A 组必须用系统提示词提交 `4133ff93b6e3c27e59e967831dbe4d4322f329a2` 且账本关闭；B 组提示词和账本均来自本次固定提交。A 组 schema 仍包含 carry_forward 字段、worker 忽略，作为 README 局限记录。
- 2026-10-17：作者补充，盲评 HANDOFF 禁止脚本给缺少逐项判断的条目填默认分/理由；作者可对同一包复评一次，若复评则揭盲报告 case 结果一致数、finding 分类一致数、各分项完全一致率及相同理由文本比例。
- 2026-10-17：v4 runner 将 B 提示词固定到提交 SHA，manifest 差异测试须在该提交产生后运行；未提交前 HEAD 仍等于 A 的提示词，测试按预期拒绝相同提示词。
- 2026-10-17：B 固定提交为 `346ac97e6af8167a5f23f766dc25d4a927b93676`；A 提示词固定提交为 `4133ff93b6e3c27e59e967831dbe4d4322f329a2`。B SHA 不得在本轮候选代码修改后继续沿用；runner 会拒绝候选提交之后的 Assistant worker 变更。
- 2026-10-17：runner smoke 自测覆盖 A/B 各七个回执的上限、B 转发前文引文且 validator 报告命中该引文、缺失该验证时失败关闭并暂停。
- 2026-10-17：`evals/tests/test_editorial_dataset.py` 与 `test_editorial_prompt_ab.py`：12 passed；包括固定 A/B 提示词、only-B ledger toggle 和 smoke 前文证据门禁。

## 验证证据

- 初始恢复：`git status --short --branch` 显示工作树干净；`git rev-parse HEAD`=`6338736cfe2f11a53dc0f7a918afd2a49dac4e85`；`origin/main` ahead 12；旧任务揭盲汇总和 HANDOFF 模板已读取。
- 2026-10-17：`UV_CACHE_DIR=/private/tmp/uv-editorial-cross-chapter uv run pytest modules/assistant/tests -q`：169 passed。
- 2026-10-17：定向 Assistant/eval 命令 63 passed；1 个 A/B 提示词差异测试因 B 固定提交尚未产生而预期失败，提交后重跑。
- 2026-10-17：B 固定提交后 `UV_CACHE_DIR=/private/tmp/uv-editorial-cross-chapter uv run pytest evals/tests/test_editorial_dataset.py evals/tests/test_editorial_prompt_ab.py -q`：12 passed。
- 2026-10-17：`npm run lint`（frontend-console）通过；`npm run test:e2e:editorial -- editorial-revision-bridge.spec.js` 在专用本机 `codex_luna_runtime_test` 上 2 passed，无真实模型调用。
- 2026-10-17：`make lint`、`make prompt-contracts`（26 contracts）通过；`make docs-check BASE_REF=origin/main` 在补齐 `docs/modules/12_infrastructure.md` 以后通过；`git diff --check` 通过。
- 2026-10-17：最终组合验证：Assistant 与相关 eval 共 181 passed；`make lint`、前端 `npm run lint`、`make prompt-contracts`、`make docs-check BASE_REF=origin/main`、`git diff --check` 均通过。前端编辑台/桥接 E2E 为 2/2 passed。

## 交付结果

- 已交付：本任务笔记；开放索引已登记本任务；旧任务记录已完成并链接本任务。
- 未交付：代码、v4、对照运行与盲评交接均待执行。
- 交付边界：仅本地 worktree 修改；尚未提交，未推送、未开 PR、未合并或部署。
- 正式知识与后续任务：按用户要求更新 Assistant README、Prompt 体系与 eval README；盲评之后由开发 agent 揭盲汇总。

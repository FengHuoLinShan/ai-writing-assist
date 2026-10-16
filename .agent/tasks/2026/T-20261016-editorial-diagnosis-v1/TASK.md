---
id: T-20261016-editorial-diagnosis-v1
title: 编辑审读诊断与合成评测第一阶段
status: complete
created: 2026-10-16T18:02:35+08:00
updated: 2026-10-16T18:32:27+08:00
---

# 编辑审读诊断与合成评测第一阶段

## 恢复快照

- 完成范围：在独立分支 `codex/editorial-diagnosis-v1` 实施设计稿候选 0、1、2，完成真实模型试跑前零费用预检；不调用业务模型。
- 工作树：`/Users/tywww/项目/ai-writing-assist/.worktrees/editorial-diagnosis-v1`，起点 `origin/main` / `main` SHA `00d861283e34bdc0ef3f34ee5605c71e1f89c553`。旧工作树未跟踪研究报告及 `out/` 保持原样；研究输入只通过旧工作树绝对路径读取。
- 关键交付：Assistant 诊断提示词、validator 单方向规则、桥接模块与 README、提示词契约文档、前端单方向标签和单测、原创评测 v2 数据及哈希测试、评测 README/预检/试跑方案。
- 下一步：真实模型 A/B 试跑前，作者需给出总费用上限、两名评阅者及分工/费用安排，并另行授权；同时核验专用数据库、项目范围、`gpt-6-luna/max` 账户连接及付费账本状态。
- 最近状态：实施、零费用预检及最终文档门禁完成；真实模型试跑作为后续独立授权阶段。

## 目标与验收

- 实施候选 0：桥接按作者选择的多条依据和跨章证据拆成每章任务，仍仅替换选区；复用已有桥接用例，不重复加测。
- 实施候选 1：加入承诺/惯例/偏好区分、理解与不喜欢区分、替代解释/回看线索、最小方向及“不应报告”提示词约束；方向至少一条，确有取舍才给备选。保留 why_now、未审章节、引文唯一性、来源重验和高严重度提醒门禁。
- 实施候选 2：新增 `editorial_cases_v2.json`，逐字保留 v1 四例并添加 S01–S17 原创合成短章和对照变体；README 记录新增评分项、零费用预检与后续试跑。
- 边界：不新增 `mismatch_type`、审美/伦理入口、结构改写路径或数据库迁移；不修改旧数据/旧哈希；不运行模型；不推送、开 PR、合并或部署。

## 决策、发现与实现

- 作者决定：审美偏好默认不报告；主入口仍只显示最多三条根因；同根因多处证据折叠；不做风格/伦理入口或结构改写路径。
- 提示词：明确分辨作者承诺、文本惯例和审读者偏好；说明作者声明不能证明文本效果已成立；理解摩擦与“看懂但不喜欢”分开；回看只依据当前可见线索；未形成 finding/摘要且当前无法回读的旧线索标 `unchecked`，不得声称已核对。完整 §6.2 不应报告清单是提示词约束，不是服务端门禁/白名单；明确无风格/伦理观察入口。
- Validator：缺 why_now 仍标未充分；零方向标未充分；单方向不再因此标记不充分。高严重度规则未变。
- 桥接：当前实现支持多依据及跨章按章拆任务，仍只做所选局部选区替换；README 和模块说明按代码纠正。复用了 `test_editorial_bridge.py` 原有多依据/跨章案例，没有新增重复测试。
- 评测 v2：共 23 例（原四例 + 19 新例），覆盖 1–3 个原创短章；S13 早/中线索对照，S14 未确认/已确认知识对照。v1 原对象逐项相同；没有 `mismatch_type` 产品字段。
- 试跑计划：v2 全 23 例、baseline/candidate 两条件，共 46 次审读；样本每例最多三章，按每章读者+作者各一次、跨章合并最多一次，最多约 322 次请求。两臂须共用同一执行代码/validator，只切换冻结 prompt。每 worker 的 4 请求限额会在 resume 重置，不是全量总预算。

## 预检与验证证据

- 零费用预检完成记录见 `backend/evals/datasets/editorial/README.md`。仓库内数据哈希、提示词契约、Assistant worker 注册与确定性测试均通过；专用 PostgreSQL/演示副本、项目开关与范围、owner 连接/当日模型设置、共享付费账本、本轮费用上限及评阅者安排未核验或待作者提供。业务模型请求为 0。
- 起始 `make docs-check`：通过（12 modules、152 tables、60 handlers、16 routes、42 ADR inventory）。
- `UV_CACHE_DIR=/private/tmp/novelcraft-editorial-diagnosis-v1-uv-cache make test-ci TEST_WORKERS=2`：架构检查、secret hygiene、依赖审计、Ruff、部署静态测试（323 passed / 1 skipped）、backend fast suite（8142 passed / 2 skipped、覆盖率 87.04%）通过；集成目标在前端步骤因缺失 `node_modules/vitest` 退出。用锁文件 `npm ci` 补齐缺失依赖后，等价前端测试单独完成。
- `npm test`：240 个文件、3029 tests 通过。
- `npm run lint`：通过。
- `make prompt-contracts`：26 项契约通过。
- 最终提示词增补后重跑受影响后端测试 33 passed、`make lint` 通过；提示词契约 26 项及前端无关的全量 3029 tests / lint 结果仍适用。
- 未运行：浏览器/专用 PostgreSQL E2E、真实模型、真实作者或评阅者验收。`make test-ci` 的复合命令未在依赖安装后整体重跑；它所余的前端 Vitest、lint 均单独通过。

## 收尾与下一步

- 收尾：`make docs-check BASE_REF=origin/main` 通过；`git diff --check` 无空白错误；本任务已完成并从开放任务索引移至已关闭摘要。
- 后续真实模型试跑：先收到作者费用上限、评阅人/分工及独立授权；任何试跑前核验 disposable DB/项目隔离、owner `gpt-6-luna/max` 账户连接、effort/wrapper 和共享账本。配置不符停止，无供应商回退。
- 本地提交可做但未做；无 push、PR、merge、deploy。

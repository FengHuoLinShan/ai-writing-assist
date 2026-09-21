---
id: T-20260920-technical-coverage
title: 技术覆盖主线 P0–P5 工程与离线验收
status: completed
created: 2026-09-20T05:29:13+08:00
updated: 2026-09-20T05:45:13+08:00
---

# 恢复快照

- 工作区：`/Users/tywww/.codex/worktrees/technical-coverage/ai-writing-assist`，分支 `codex/technical-coverage`。
- 基线：`a7173869ca832537cf476e0a05e97f1f5275012a`，已 fetch 核对 origin/main；原目录 WIP 未动。
- 当前：P0–P5 本地工程与离线验收完成；详见 [ACCEPTANCE.md](ACCEPTANCE.md)。
- 下一步：只有获得新的模型/费用/人工评审安排后才进入真实质量评测；Git 与部署交付另行授权。
- 阻塞：无。禁止付费模型调用；质量评测和人工盲评单列，所有既有实验开关保持关闭。

## 目标与边界

用户已批准依次实施 P0–P5：基线与逐题映射、父级原文补全与离线检索对照、工具回放与
只读 MCP 实验、有界协作对照、长期记忆序列回归、SSE/任务故障与应用容量验证。
本轮交付实现、隔离环境验证、报告和三条演示脚本；不提交、推送、合并、部署，不修改真实库。
不使用开发子代理。MCP 仅本地 stdio 合成资料；BM25 仅离线实验。

## 依据与恢复入口

- 已批准计划见当前任务对话；技术覆盖与操作说明在 `docs/testing/technical-coverage.md`。
- [已有协作交付](../T-20260920-agent-teams/TASK.md)与 [质量边界](../T-20260920-agent-teams/QUALITY.md)。
- 长记忆契约与历史失败：`backend/evals/datasets/README.md` 的 RP long-memory gate。
- 当前生产契约仍以模块 README、ADR-0027、代码与测试为准。

## 里程碑

- [x] P0：保留历史指标；增加固定 K 与区间 gold；可复跑证据及逐题映射。
- [x] P1：受限父级补全；BM25 对照；五臂配置；来源/权限回归。
- [x] P2：工具历史身份；选择负例与诊断；版本化方法；只读 MCP 实验。
- [x] P3：deep_review 三臂；失败/恢复/争议；盲评导出准备。
- [x] P4：真实上下文物化与纠正/分支/失效连续操作回归。
- [x] P5：Unicode offset 去重/恢复；专用 PG 故障、容量与浏览器验收。
- [x] 收尾：影响测试、lint、docs-check、跨栈门禁、证据与交付状态。

## 决策与验证

- 不重复建设 LLM reranker、子查询融合、Agent Teams 和持久 SSE；先复用实际调用链。
- 真实模型质量不因离线通过而准入；未知消费不记零，旧留出集不反复调参。
- 2026-09-20：基线 docs-check 通过；实现检查尚未执行。

## 当前验证证据与新增发现

- 原文精确回读发现底层 0/0 仍扩展整段；已在 Evidence 精确层裁到引用区间，父级分段保留引用并受权限/预算约束。53 项相关测试通过。
- 初始工具回包丢失工具名；v2 修复并仅迁移可配对旧历史。方法蓝图 v2 保留 v1 冻结兼容。82 项 Agent/检索/评测回归通过。
- MCP SDK 需要可生成输出 schema 的返回类型，已使用 Pydantic 合成资料响应；stdlib stdio 本地完整往返通过，无生产连接。
- RP 连续三次真实 reducer 后纠正、清空与续写上下文验证已补强；Interaction/来源/流式/MCP 108 项通过。
- 前端相关 70 项通过；真实 PostgreSQL 原领域、租约、并发、来源版本共 28 项通过（`.test-artifacts/technical-coverage-postgresql.xml`）。
- 专用可丢弃容器：`novelcraft-technical-coverage-test-20260920`，127.0.0.1:55447；库 `novelcraft_technical_coverage_test`，合成测试凭证仅命令环境。真实库未使用。
- 队列实验 30/90 RPS，60/180 请求均完成；p95 71/651 ms，max pending 1/44，固定 25ms 替身，不是推理吞吐。原始产物在 `backend/evals/artifacts/technical-coverage/`（忽略）。
- 架构影响文档检查已通过；后续门禁均已完成，完整结果见 ACCEPTANCE.md；make 新入口触发的两份架构治理文档按已有 no-change-reason 机制复核，不修改其无关内容。

## 最终验收与交付

- test-ci：后端 5889 / 前端 2519 / 部署 270 通过，后端覆盖率 86.04%；真实模型和可选依赖的 skip 单列，不宣称全部检查执行。
- 最终受影响回归 809 通过；最后段落边界补强 6 通过；完整离线目标 14 通过，MCP/BM25 实际执行。
- 独立 PG 28 项 + worker-loss 1 项通过；浏览器四条流程通过并检查窄屏截图；前端构建、双端 lint、diff-check 通过。
- 文档影响检查使用既有显式无变更复核：架构 README/维护协议不因新增开发命令而改写；具体理由与输出在 artifacts/docs.log。
- 三条演示脚本在 docs/testing/technical-coverage.md；合成盲评页面、评测报告、日志/JUnit/截图和校验值在 artifacts/。
- 全部真实模型调用为 0，未完成人工盲评，未启用质量开关；没有提交、推送、合并或部署。
- 原目录 WIP 保持；临时测试容器已停止，保留可丢弃测试库供显式重跑，不影响已有服务。

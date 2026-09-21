# P0–P5 本地交付与验收

**工程实现和离线验收完成；真实模型质量尚未准入。**

基线 `a7173869ca832537cf476e0a05e97f1f5275012a`，分支 `codex/technical-coverage`。
全部修改位于独立工作区；原目录的 README、宣传视频任务和未跟踪文件保持原样。
没有提交、推送、合并、部署，也没有付费模型调用。现有协作与记忆质量开关保持关闭。

## 交付结果

| 批次 | 实际交付 | 证据与边界 |
|---|---|---|
| P0 | 逐题映射、原文区间 gold、故事族划分、版本/消费证据、固定 K 指标 | 历史精确率不变；未知消费保留 null；质量声明默认 false |
| P1 | Scene/段落父级补全、逐段来源与范围裁剪、原抽屉展开；BM25/RRF 对照和五臂配置 | 精确回读不再带回同段额外内容；角色知识无法证明时不扩展；合成向量和脚本重排不代表模型效果 |
| P2 | 工具调用身份 v2、可证明的旧历史迁移、选择负例、三种版本化方法、本地只读 MCP | SDK stdio 真正往返；合成资料以外的 ID、路径、URL、未注册写工具被拒绝；模板不授予权限 |
| P3 | 单 Agent／固定步骤 Workflow／三成员协作对照、成功回执恢复复用、盲评材料导出 | 来源、允许工具、根额度相同，替身请求数 1/3/3；领域采用由独立 PG 集成验证，脚本样本不能用来证明协作质量提升 |
| P4 | 人工纠正穿过三次生产 reducer 与续写上下文、清空、分支与过期来源回归 | 确定性契约成立；自由文本记忆的模型语义忠实度仍待实测，旧失败候选未启用 |
| P5 | Unicode offset、重复/重叠/缺口恢复；真实 PG 租约故障、重复提交；稳态与三倍突发探测 | 浏览器刷新保留持久正文和未发送输入；队列实验不外推实际推理容量 |

操作入口、逐题映射和三条演示脚本见 [技术覆盖说明](../../../../docs/testing/technical-coverage.md)。
一次重跑离线产物：`make eval-technical-coverage`。

## 验证

| 检查 | 结果 | 证据 |
|---|---|---|
| `make test-ci TEST_WORKERS=2` | 后端 5889 passed / 15 skipped；前端 2519 passed；部署 270 passed；后端覆盖率 86.04% | [完整日志](artifacts/ci.log) |
| 完整离线入口 | 14 项通过；MCP/BM25 optional extra 实际安装并执行 | [日志](artifacts/offline.log) |
| 最终受影响回归 | 809 passed / 2 deselected；最后单/双换行段落边界微调另 6 项通过 | [JUnit](artifacts/affected.xml) |
| PostgreSQL 原领域与并发 | 28 项通过：协作取消/失败、租约、重复操作、来源版本和采用竞争 | [JUnit](artifacts/postgresql.xml) |
| PostgreSQL worker 丢失恢复 | 1 项通过；旧心跳、旧提交、重复终态均拒绝 | [恢复记录](artifacts/recovery.json)、[JUnit](artifacts/recovery.xml) |
| 浏览器 | 4 项通过：协作恢复、前后文展开、长期约定、Unicode 流式恢复；含窄屏 | [协作](artifacts/team-review-mobile.png)、[约定](artifacts/agreements-390.png)、[流式恢复](artifacts/unicode-recovery-390.png) |
| 前端构建与资源校验 | 通过 | [构建日志](artifacts/build.log) |
| 后端/前端 lint、`git diff --check` | 通过 | 收尾命令与任务记录 |
| 文档影响检查 | 通过，使用仓库现有显式复核机制 | [日志与不变原因](artifacts/docs.log) |

普通 CI 的 optional BM25/MCP skips 由单独离线入口补验；真实模型与外部语料用例仍不执行。
完整 CI 后的方法回放、实验流程及段落边界微调均补做了受影响检查，没有把前一轮结果代替新改动验证。

文档影响检查已复核 `docs/architecture/README.md` 与 `documentation-maintenance.md`，
它们保持原样：新增 Make 入口仅为开发实验，不改变九模块归属、运行时拓扑、文档清单或门禁协议。
采用已有 `--no-change-reason` 参数记录原因，未改检查器或规则；直接运行未附复核原因的
`make docs-check BASE_REF=origin/main` 仍会提示这两份必查文档。后续 PR 应携带同一复核说明。

## 容量与效果材料

独立可丢弃 PG 容器限制为 2 CPU、768 MiB；三 worker、连接池 8、固定 25ms 替身，
每组约两秒到达窗口，排空后统计。没有真实模型或 HTTP 全链路压测。

| 到达率 | 请求/完成 | p95 完成 | p95 排队 | 积压峰值 | 拒绝率 |
|---|---:|---:|---:|---:|---:|
| 30/s | 60/60 | 71 ms | 13 ms | 1 | 0% |
| 90/s | 180/180 | 651 ms | 611 ms | 44 | 0% |

[原始容量报告](artifacts/capacity.json)保留所有请求与失败口径；首个有效内容耗时为 null。
[检索报告](artifacts/retrieval.json)、[工具报告](artifacts/tools.json)、[协作报告](artifacts/collaboration.json)
均明确标注替身执行和零真实模型调用。长记忆 dev 合成集为 8 案例、111/111 离线硬断言，
见 [摘要](artifacts/memory-summary.json)。这些材料不建立模型效果、降本或生产 SLO 声明。

[盲评页面](artifacts/blind-review.html)与[评审表](artifacts/blind-review.jsonl)仅用于检查评审流程；
当前内容来自脚本替身，未完成人工盲评。实验臂映射留在忽略的本地结果目录，不混入评审页面。
产物校验值见 [清单](artifacts/manifest.json)。

## 后续边界

真实质量验收仍需明确模型、累计费用上限、冻结阈值与人工评审安排；不能重复使用已经分析过的
旧留出集调参并宣布准入。P6/P7、生产启用与 Git/部署交付均不在本轮范围。

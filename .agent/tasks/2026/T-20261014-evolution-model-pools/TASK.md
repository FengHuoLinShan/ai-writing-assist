---
id: T-20261014-evolution-model-pools
title: 独立模型池、Luna 范围授权与 500k 输入预算
status: active
created: 2026-10-14T18:00:00+08:00
updated: 2026-10-14T21:32:58+08:00
---

# 世界演化模型池与范围授权

## 恢复快照

- 本地实现完成；用户追加授权：review并修复，完成后提交、开PR并合并。正在对固定基线审查与补充验证，尚未提交/推送/合并。
- 工作区：/Users/tywww/.codex/worktrees/evolution-model-pools/ai-writing-assist；codex/evolution-model-pools。根 WIP 保持原状。
- 下一步：提交已复核改动、开PR，等待固定head全部适用检查通过后按授权合并；不自动续跑《诡秘》。
- 外部验证未完成：真实订阅500k输入、语义质量与持续高并发。

## 目标与验收

- 模型池独立：Luna 订阅与 DS API 各模型默认 8；同宿主 API/worker 共享槽，无跨模型总 cap。
- 新 Luna 确定性运行以 confirmed_scope 完成已确认范围；有限 Agent 与 DS 预算保留。
- 新 Luna 完整输入预算 500000，CLI 窗口 1050000，输出预留 128000，安全余量 32000，压缩阈值 800000；官方规格不冒充运行实测。
- World v3 / Discovery v2 使用模型预算装包及就绪并发；旧版本、冻结请求、unknown、作者决定保留。
- 验证：确定性调度、真实进程模型槽、专用合成 PostgreSQL、迁移、受影响后端/前端/部署/文档门。
- 非目标：真实模型调用、Guimi 续跑、改写真实数据、生产部署。提交/推送/PR/合并于本次明确授权。

## 上下文与边界

- 来源：本聊天最终用户实施计划；AGENTS.md、ADR-0033、模块 README 与当前源码。
- 本机自定义 catalog 的 500k 是总窗口；业务 --ignore-user-config 不继承它，需显式冻结业务策略。
- 新策略只适用于新授权；旧 Codex v2/v3 恢复问题不得绕过。初次实施未委派；本轮采用 code-review skill 明确要求的两轴只读子代理，主Agent统一修复。
- 所有业务配置仍来自当前 verified owner 的 Project facade/snapshot，权限、来源、原子提交及 unknown 防重发不变。

## 里程碑与进度

- [x] 独立模型池与完整输入预算
- [x] 范围授权信封/领域预算/迁移
- [x] 新版分组、装包与就绪调度
- [x] 作者界面与权威文档
- [x] 工程/进程/PG 验收与收尾

## 决策、发现与失败

- 预算模式明确区分 bounded/confirmed_scope，不以大整数冒充不限额。
- 旧能力快照/请求沿原策略，不静默升级上下文或分组版本。

## 验证证据

- 实施前 PATH=backend/.venv/bin make docs-check：通过，152 ORM / 60 task handlers。

## 交付结果

- 初次本地实施完成；本轮审查修复与GitHub集成已获授权，未调用真实模型或部署。

## 2026-10-14 实现检查点

- 模型池、新上下文、范围信封及迁移、新版就绪调度、作者界面与部署模板已接线；无新依赖。
- 真实 spawn 模型槽测试 13 passed，包括 Luna8 + DS8 总峰16、同模型多 worker、取消/进程死亡释放和容量变化等待。
- 专用 PostgreSQL codex_evolution_test_20261014 从空库迁到新 head；原子预算、租约、恢复及安全降级定向 16 passed。仅合成资料/专用测试账户。
- 广泛演化/任务/项目/导入回归 1812 passed，3 个旧并发默认值断言待同步；已同步至模型池8。LLM/项目回归677 passed，1 个 __new__ 测试替身缺新能力字段，已补齐。
- Frontend ReadingFlow 13 passed；新就绪屏障3 passed。新范围账本161调用仍运行，DS/Agent不能用范围模式，旧能力快照保持原值。
- 接线审查发现演化没有既有受管 step 上下文；仅新信封路径显式绑定，从而可落账；老未跟踪队列保留迁移 seam。
- 在途策略：Root V2 显式 bounded/confirmed_scope；新 task 绑定领域范围/快照，旧已持久 V1 不改版本。待最终全套回归、lint、文档/依赖门及前端构建。

## 收尾

- 2712 后端集中回归、2983 前端、17 PostgreSQL 与13真实进程测试通过；后续定向校验通过。具体边界及文档核对命令见 REPORT.md。
- 原始稿件/模型调用均未发生，专用合成库和本任务角色在收尾清理。

## 审查及集成检查点

- 两轴审查与整改：[REVIEW.md](REVIEW.md)。六个独立问题已修复，独立复核无剩余阻断。
- 完整本地test-ci：7985后端通过、覆盖率86.80%、2985前端通过、部署279通过、依赖审计及Ruff通过；前端lint/build通过。
- 完整PG critical：固定镜像的独立容器中98通过。第一次专用角色91通过/7创建vector权限失败属于环境，不改变共享库权限，已隔离重验。
- 合成测试资源待收尾：Docker容器novelcraft-model-pools-review-pg（49882）；共享开发PG中本轮仅创建的codex_model_pools_review_test库/角色待清理。原root WIP仍未修改。
- 当前本地报告见REPORT.md；无真实模型、Guimi续跑、作者文学验收或部署。

## 最新主干集成

- PR #230已创建并附加： https://github.com/FengHuoLinShan/ai-writing-assist/pull/230 。实施提交3b942f942cd87f5332edaf26f0b0e400a28a2a27。
- 提交期间主干更新至0e572c75ffba654cc117c502f91a489307589837（#227审计首批），正在正常merge，不重写已推送历史。9处文档/部署冲突已解决，保留独立只读图片备份身份、30天保留与新模型池。
- 下一步：完成新基线部署/跨栈门禁及独立冲突复核，提交merge并推送，核验PR固定head全部检查后合并。

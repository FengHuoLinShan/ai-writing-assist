---
id: T-20261014-evolution-model-pools
title: 独立模型池、Luna 范围授权与 500k 输入预算
status: completed
created: 2026-10-14T18:00:00+08:00
updated: 2026-10-14T22:44:47+08:00
---

# 世界演化模型池与范围授权

## 恢复快照

- 实现、review整改、提交、推送及合并完成。PR #230：https://github.com/FengHuoLinShan/ai-writing-assist/pull/230 。
- 验证的head：61d5f484b828f30bd1d5c27d7a330ed7042c902e；18项PR检查全绿。
- 合并：2026-10-14T22:42:51+08:00，主干fd9e7279047ae6681893749e1d454e994dbea2b7；fetch后核实origin/main及已验证分支文件树一致。
- 主工作区：/Users/tywww/.codex/worktrees/evolution-model-pools/ai-writing-assist，codex/evolution-model-pools。
- 当前仅本地任务关闭笔记与索引更新，未另提交；产品代码全部合并。无需继续代码实施或重复本地门禁。
- 下一步：无本轮必需工作；真实订阅500k可用性、语义质量及持续高并发须另行授权实测。

## 目标与验收

- 各来源/provider/精确型号独立模型池默认8，无共用并发/RPM cap；同宿主API/worker共享槽、订阅绑定登录账户。
- 新Luna确定性运行以confirmed_scope完成已确认范围；DS、有界Agent和旧冻结运行保持有限预算或原授权。
- Luna完整输入500000、声明窗口1050000、输出预留128000、安全余量32000、压缩800000；业务CLI显式接线，不修改全局catalog。
- World3/Discovery2按模型预算装包和依赖就绪接续，严格前序身份；旧版本/指纹/冻结请求保持。
- 来源/owner/租约、unknown防重发、作者采用、日志合并和顺序提交边界保留。
- 验收及限制见[REPORT.md](REPORT.md)，两轴review及七项整改见[REVIEW.md](REVIEW.md)。

## 上下文与授权

- 用户明确授权实施上述计划，追加review修复、提交、开PR并合并；未授权真实模型、Guimi续跑或生产部署。
- 依据当前AGENTS、ADR-0033及模型/演化稳定入口。业务模型仍经verified owner的Project facade/snapshot获取。
- 实施初段未委派；review阶段按code-review skill的两轴要求使用两名只读子代理，主Agent统一修复与集成。
- Root工作区由其他任务将原文档WIP归档至1dae2f8f2；文件均保留在提交中，本任务未修改root、其他worktree或真实稿件。

## 进度与决策

- [x] 独立模型池、Luna完整输入及冻结策略
- [x] 显式范围信封、nullable预算和非破坏性迁移
- [x] 新版World/发现/补扫/补审并发接线
- [x] 作者界面、模板、权威文档与测试
- [x] 两轴review整改及原反例复验
- [x] 本地门禁、专用PG、固定head CI及PR合并

## 关键发现与修复

- 六项首轮review缺口：实际执行模型错配、附加型号冻结预算、tokenizer漂移、补扫预算继承、首次补扫版本、World上下文策略绑定。
- 最终P1：其它root占7槽时，unknown/取消后排队7个peer仍发送。新增共享停止作用域贯穿新旧批次、槽/RPM等待及provider任务启动；异步账本保存后重验，unknown先停接纳再结算。
- 证明未发送的请求撤销信封/兼容预留，在owner/run/租约门内退回自身domain及补扫额度，仅清除自身sampling日志；已发结果、完整格式失败局部处理、恢复不重发保留。
- 同步selector校验与V2显式budget_mode。生产镜像父目录未创建导致CI失败，mkdir -p修复且实际镜像合同通过。
- 正常merge主干0e572c75f（#227），保留独立只读图片备份、30天保留与地图来源规则；不重写已推送历史。

## 验证与环境

- 最终make test-ci：8000后端通过、2跳过、覆盖率86.83%；2990前端（237文件）；部署323；lint、secret hygiene及依赖审计通过。
- 专用固定PG17容器：完整critical100通过，含2个新有限/范围退款回归；25个排队/异步checkpoint/身份/预算集中回归通过。
- 真实spawn模型槽合成13通过：Luna8+DS8总峰16、同模型跨worker、取消/死亡释放、单池配置等待。
- 文档差异核对、模块依赖/文件体积/二进制/release evidence门、diff-check、前端lint/build通过。
- PR18项全绿，包括浏览器两分片与聚合、CodeQL、生产镜像。主干合并后CI另行启动，不把PR结果冒充主干运行结果。
- 早期共享开发PG专用角色无vector创建权限导致7项迁移失败，未升权，改独立容器通过；所有本轮专用库/角色/容器已清理。
- 本地镜像build/smoke通过，restore drill镜像拉取遇502，完整合同由最终远端CI覆盖。

## 交付边界

- 产品代码及必要实现文档已合并；本文件、索引和报告的合并后关闭记录留在本地隔离worktree。
- 无真实模型调用、作者文学验收、真实数据改写、Guimi恢复或生产部署。官方规格及合成证据不代表订阅长输入和持续吞吐已验收。

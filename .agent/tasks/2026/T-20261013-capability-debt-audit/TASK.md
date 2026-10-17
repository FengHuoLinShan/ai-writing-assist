---
id: T-20261013-capability-debt-audit
title: 全面能力评估与代码债务审计
status: completed
created: 2026-10-13T18:00:00+08:00
updated: 2026-10-14T09:56:18+08:00
---

# 全面能力评估与代码债务审计

## 恢复快照

- 2026-10-14 续接：用户要求 review、更新报告并核对细节；复核 REPORT / HTML、原始账本、固定远端 main 22bb499789cba89fea92e918fd853ab768688e07 与 PR #222。原始审计结果保留为 10/13 快照。
- 本轮已完成：REPORT 第 0 节与方向/批次更新、源码统计与引用补全；HTML 同步固定 merge、8 次复用和未完成边界，修复打印全量/恢复、内嵌证据下载与窄屏详情可见性。
- 本轮验证：固定 SHA 27 文件/PR/账本复核；页面分类、搜索、图解、11 批次、下载 bytes、打印恢复和 390/768/1440px 自检通过，桌面/图解/窄屏截图已查看；docs-check BASE_REF 与 diff-check通过。
- 下一步：本轮关闭。若另行授权开发，按 REPORT 0.5 优先 A2 并核验新主干全门禁；不把旧失败或清理重新立项。
- 本轮复核证据：REVIEW-20261014.md、REVIEW-EVIDENCE.json；仓库外 HTML/生成器/自检脚本见复核文档。仅本地文档更新，无业务改动、模型调用、提交/推送/合并/部署。
- 本轮边界：只修改本任务文档和仓库外图解，不改业务代码、其它任务、Git引用或工作树，不调用真实模型，不部署。


- 当前阶段：16方向报告、32分类清理条目、3994路径覆盖清单和历史/CSS引用账本已交付；文档门禁与工作区保护校验通过，本次临时服务已停止。
- 工作区：主工作树，codex/guided-flow-borrowing；HEAD 4116b657d38f8b7b45c2e18e091274a9c5fbc773，origin/main 974f0f5080d43472bc599d1d74782913c725057b。二者业务代码差异须核对，不把文档提交计为新能力。
- 原有 WIP：T-20261012-guimi60-codex-comparison/TASK.md；原始路径/hash/status 保存在仓库外 /tmp/novelcraft-capability-audit-20261013/baseline.json。
- 模型限制已经用户修改：代码审查可用 Sol；业务实测仍要求 Luna/max。本次不发起真实模型请求、不委派子代理。
- 下一步：审计任务关闭；下一步建议先按 REPORT.md A1/A2 处理夜间门禁与运行时收敛。此建议不构成新实现、模型实测或发布授权。
- 阻塞：无。未来检查缺前提时记录实际限制，不改验收口径。

## 目标与验收

- 用户要求按真实能力详细覆盖所有方向，并完整总结老旧无用代码与过时逻辑，供下一步开发决策。
- 已确认：主干现状与在途增量分开、代码深查与免费验证、本地浏览器走查、可靠闭环优先。
- 交付 REPORT.md（能力、问题、验证和路线）、CODE-CLEANUP.md（完整分类候选）、COVERAGE.csv（覆盖深度、hash和证据）。覆盖登记不等于逐行审读。
- 每个方向有当前能力、正常/失败路径、证据与缺口；每个候选有引用、影响、最小方案、验收和回退边界。

## 上下文与边界

- 不修改业务代码、规则、既有测试或其它任务记录；不合并、提交、推送、部署，不清理任何工作树、数据和档案。
- PostgreSQL/浏览器仅使用本次新建的合成隔离库与新端口；保护 ai_novel_acceptance_guimi、旧测试库及在途原生/付费回执。
- 历史审计 .agent/tasks/full-codebase-review/ 与 code-simplification-audit.md 仅作候选来源；已修、误报、动态调用及公开契约须重验。
- 其它 worktree 只读；未集成的 Codex 适配不能计入主干可用能力。

## 里程碑与进度

- [x] 规则、基线、原有 WIP 与覆盖路径冻结。
- [x] 能力方向及高风险调用链核验。
- [x] 历史与新增债务候选分类。
- [x] 免费测试、PG 与本地浏览器走查。
- [x] 报告与开发建议、工作区保护校验、文档门禁。

## 决策、发现与失败

- 最初宿主限制阻止审查；用户修改规则后继续。本任务不自行修改规则。
- 审计涵盖 16 方向；3994 tracked 路径分级登记，不宣称逐行审读。当前 91 个路径定向区段阅读，其余 AST/词法/路径清点。
- 本轮 fast/PG critical 通过，但主干 nightly 的两个 E2E 在本次库复现；offset旧断言和World请求证明差异须后续处理，不修改测试过检。
- 历史旧清理候选多已修/改形：scene_fusion是活schema、主deep_import未被adapter替代；不得复制历史rm-rf。
- Makefile实验目标共用.venv导致本次已启API依赖路径变化；恢复root3.14.7，浏览器改独立临时venv。环境干扰与RP脚本guard未过不算真实模型产品缺陷。
- 原有Codex比较任务及三个脏worktree持续只读，本任务不写其文件。

## 验证证据

- make test-ci TEST_WORKERS=2：部署272；后端7736pass/2skip/13warning，86.76%；前端237文件/2968测试；docs/secret/依赖/ruff通过。
- 新PG17隔离库完整升级head 20261010_evolution_source_epoch；test-postgresql-critical 95pass/92.89s。
- module imports passed（65有向/9双向/524函数级，预算内）；eval-technical-coverage 14pass/2.26s与合成实验产物；npm lint/build及生产资源验证通过。
- nightly失败文件本地复现2failed/21passed/13.95s；补充诊断发现sample复用、World/entity/relation/audit重做且request合同hash不同。
- 合成浏览器验证创建项目、首章保存/刷新、断网备份/重试、人物创建、结构/地图空态、助手提案拒绝/编辑台、390px；RP进入知识边界hold，脚本替身不能完成内容链。
- 未执行真实模型、受保护项目、生产、全浏览器矩阵/设备、Docker生产镜像或真实恢复；历史长篇实测只引用，不算本次验证。
- 仓库外日志/截图/hash：/tmp/novelcraft-capability-audit-20261013；持久脱敏计数见EVIDENCE.json。

## 交付结果

- 已交付：REPORT.md（16方向和3批次开发建议）、CODE-CLEANUP.md（32分类条目）、COVERAGE.csv（3994路径）、HISTORICAL-CANDIDATES.csv、OLD-AUDIT-REFERENCES.csv、CSS-DUPLICATES.csv、EVIDENCE.json。
- 收尾：docs-check BASE_REF=origin/main 与 git diff --check通过；初始3994 tracked文件hash全部与开始快照一致，原有比较任务WIP原样保留；本任务索引已移除，业务代码/规则/测试未修改。
- 本次API/Vite/PG服务已按PID/工作目录核对后停止，临时合成库和截图/log保留；root venv恢复Python3.14.7。最初沙箱禁止ps，随后仅对拥有的临时进程获准执行收尾，没有停止其它服务。
- 未执行业务修复、清理、真实模型、生产、提交/推送/合并/部署。本轮未证实全部历史候选，机器账本明确标记不据此删除；浏览器/模型质量限制见REPORT。
- 交付为本地文档成果，主任务completed不代表后续开发/质量/部署已完成。

- 最终保护证据：/tmp/novelcraft-capability-audit-20261013/final-protection.json；本轮报告产物不在原始3994基线清单中。

## 2026-10-14 本地整理提交

用户要求整理提交本地差异；本记录及对应已有证据按主题提交到当前 `codex/guided-flow-borrowing` 分支。仅归档文档与恢复记录，不恢复业务任务，不推送、合并或部署；此前验收与私有证据边界不变。正式文档刷新成果仍在独立工作树，后续集成须基于最新 main 核对。

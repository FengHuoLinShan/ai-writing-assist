## 变更

旧本机文字任务仍可进入批准/领取入口，RP 还会把图片执行器误判为文字连接。本批将这些入口限制为图片，旧文字快照明确失败并保留历史回执；RP 文字能力只读取当前账户连接。

服务器图片新增数据库配对的备份/恢复路径，图片与数据库 restic 保留期统一为 30 天。修改已发布章节后，写作回执列出引用旧稿的当前已保存地图及核对入口；查询失败明确披露，正文保存、地图状态与 Scene 重算范围保持原契约。

- G3①：两阶段退役旧 bundle Markdown renderer；活跃编译器/IR、输出/hash、隐藏真相与叙事义务断言保留。
- G3③a：pending/approve/claim 仅图片，旧文字 task/invocation/snapshot 失败关闭；历史回执、图片确认/取消/防重和 owner 隔离保留。
- G4a：同机独立私有目录、独立只读备份身份、同份 dump 取对象清单、增量校验、30 天老化、目录/作者 ZIP 运维恢复。正式 shell 入口使用共享发布器认可的 staging 名；损坏历史不提供缓存，新备份仍可完成，垃圾回收失败关闭并单独报告，退出码非零提醒运维核对。
- G8a：同 owner/novel 历史来源身份重验，只扫有限 saved current head；SQL 投影不读正文/大 JSON，SAVEPOINT 降级，地图仅提示核对。

没有新增表、migration 或 outbox。退役入口无生产调用；旧文字不再批准/派发，新增地图回执与窄只读 DI 口。恢复核对目标 DB 的 novel/bucket/key/hash/size，不导入跨项目数据。生产部署与真实数据/模型验收不在本 PR 交付范围。

## 验证

- 本次备份修复：新增 7 项回归；六个故障反例修复前全失败、修复后通过，另验合法历史 hash 冲突仍失败关闭。真实 shell+publisher 覆盖复制成功/失败；清单故障覆盖空遗留目录、缺 SHA、SHA 不匹配、错误权限，以及连续新快照可读、有效缓存仍复用、老化旧对象不误删。
- 最终备份专题 41 passed，完整部署 309 passed；项目 Ruff、shell 语法、diff 检查通过。部署文件套用额外 backend lint 规则与基线比较无新增问题。
- 本次无网络合成实恢复 7 对象/2 桶，元数据、权限、hash/size、解码、缺图和流中断反例通过；RPO 2.586s / RTO 4.774s 仅代表小合成集。
- 其余首批既有证据：后端 7748 passed /2 skipped，coverage 86.81%；PG critical 95+专项9；前端2980、浏览器受影响8例、build/ESLint；26 prompt 合同、固定IR/hash与活跃AST不变。备份修复未改这些生产路径。
- 最新修复 head 的远端 CI 与全新 GPT-6.1 Sol / xhigh 独立审查正在等待完成；保持 draft，暂不合并。

任务与本地验证记录：[TASK](.agent/tasks/2026/T-20261014-audit-first-batch/TASK.md)。此前固定 head 4acf184c4 的独立审查与反例：[REVIEW](.agent/tasks/2026/T-20261014-audit-first-batch/REVIEW.md)。

## 架构文档影响

- [x] 已运行 `make docs-check BASE_REF=origin/main`
- [ ] 检查列出的当前文档已全部更新
- [x] 已逐项核对未更新文档，确认无当前架构影响

无影响说明（勾选第三项时必填）：已逐项核对：CLAUDE.md仅导入AGENTS，权限规则未变；Evidence根README已只描述render_compiled_context，固定IR/活跃编译AST字节证明不变，indexing的检索、可见性、confirmation与任务语义不变；documentation-maintenance的权威归属/检查流程未变。drawio/html展示的12模块及API/worker/MinIO常驻拓扑不变，依赖仍65边/9双向；G8复用已有Evolution-World方向增加窄只读DI口，G4仅新增ops一次性备份/恢复和timer，运维合同已更新deploy README、12_infrastructure与ADR-0034，不新增常驻服务或更换存储。CONTEXT/00/开发与测试指南中的过时本机文字描述已实际修订，保留Luna规则PR225，不以笼统内部改动豁免。

## 合并检查

- [x] 受影响本地测试和适用 lint 已通过
- [x] novel_id、account/owner、Schema guard 和 API Key 边界未放宽
- [x] 受影响作者界面的空态、失败/冲突、保存/恢复和窄屏已有证据
- [x] 危险操作保留确认，未直接提交 main

本 PR 保留每切片独立回退提交；G2 运行时由原聊天单独收敛。第二/三波按计划前置继续；本批未合并或部署、未开通 B2、未恢复真实评测。同机副本不能抵抗整盘故障，生产容量/对账与启用仍须另行验收和发布授权。

# G2最终交接：Codex Luna运行时

最后核实：2026-10-14T14:28:08+08:00。G2已完成并合入main；《诡秘》全量保持暂停，自动化60已删除，不能据此恢复业务。

## 已交付与版本

模型约定[PR225](https://github.com/FengHuoLinShan/ai-writing-assist/pull/225)合入e02137f79fc4e8f5ba4f79f541b66b5dbaa47a05；单一运行时[PR226](https://github.com/FengHuoLinShan/ai-writing-assist/pull/226)合入 **d904eb8d15b66a59653a978d517608f7c7fcaded**。固定评审/PR CI为8c234ac09351080ce457840b834af5d6ac3d57a1，squash后树已核验逐文件相同。完整PR门禁及main d904eb8d六个push工作流全部成功；[main前端CI](https://github.com/FengHuoLinShan/ai-writing-assist/actions/runs/38520202070)的单元、两个浏览器分片和聚合检查均通过，未部署。

[验收报告](../../../../docs/acceptance/2026-10-14-codex-luna-convergence.md)、[主任务](TASK.md)、[分轴复核](REVIEW.md)给出实现与证据。用户明确要求最终签收文档推送合入，本轮仅五份文档/关闭索引经独立文档PR交付，未另开运行时PR。根Guimi主笔记与暂停handoff的补充仅为本地记录，不夹带其它根WIP提交。

## 已验证的运行边界

- 小说大量业务调用默认原生gpt-6-luna/max；工程模型不受业务Luna约定限制。每次请求经当前verified owner、Project facade/snapshot及本机ChatGPT身份回读；不自动付费回退。
- 固定codex-text-v3及指令SHA入快照。旧v2/缺包装/旧local_agent文本快照不能直接续跑，历史回执仍可读。绝不改stamp、换run/hash或重做旧unknown绕过门禁。
- 同系统用户同ChatGPT账户在本机所有API/worker共享OS槽，默认2、整数1..8。10个真实子进程在2/6/8分别达对应峰值，不等于跨主机或长篇八路稳定。
- 导入原生预检只做本机配置和当前授权核验，零模型I/O；显式账户验证仍是真实探针。unknown只保留实际白名单诊断，不自动重放。
- 容量、源化resume、独立发现窗口、并发journal合并和永久未检查缺口披露均完成工程/专用PG验证；未接旧Guimi全量。

## 证据与保护

完整同HEAD CI：7962后端、95 PG critical、2982前端单元、功能浏览器189+151、WebKit12、助手1、前瞻9、审稿9通过；覆盖率86.84%。其它不同范围/重叠集合不累计。新增真实Luna仅3次新合成/显式验证，全部完成，不能证明文学质量或长篇提速。

/tmp/codex-luna-g2保存清单、逐内容裁定、私有测试/probe/CI日志与merge proof。八旧树合并后789记录文件版本重验零漂移，均保留；不清理、不丢弃原稿/所有unknown/付费账本，不迁移原验收库ai_novel_acceptance_guimi或旧评测运行库。

## 唯一安全接手入口

用户若明确恢复Guimi，先读根 `/Users/tywww/Desktop/项目/ai-writing-assist/.agent/tasks/2026/T-20261012-guimi60-codex-comparison/HANDOFF.md` 和最新TASK，核验实时无在途、63来源、8成功前缀、18 sampled日志、唯一获准缺口及其它unknown。G2 v3与旧v2必须先有合法版本/来源处理；目前没有已验收的旧v2直接恢复路径。不要先启动旧driver、替换冻结代码或新增周期任务。

原scene_discovery_12未知hash **562c9ac724549c921cf44da89069d5231c7ab25a5344d6eaa3813355dea26d15** 保留且禁止重发。原“保留缺口继续”授权仅精确隔离范围，后续暂停仍阻止当前真实确认/续跑。全量比较、来源语义/用户操作验收和旧unknown根因仍未交付，不做排名。

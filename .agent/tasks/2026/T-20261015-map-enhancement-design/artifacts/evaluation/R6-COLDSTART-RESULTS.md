# R6 五题材地图冷启动结果

最后核对 2026-10-16T13:39:10+08:00。五题材各5Scene加1结构任务、共30个精确任务均done/attempt1，业务调用全部结算。开发质量gate为blocked/passed=false，未进入成对写作、助手或评分；作者验收未通过。

代码固定点 `81785cd16d1310f747e7790832567a593d6a9952`；Map pipeline
`a3ad2b84a661fa02a61bde9ad3b427afb903b06bb3a486d589f46655b326ce2a`。
主会话独自实施、审查、修复与评测；没有开发子代理、推送、PR、main合并或部署。

| 题材 | 已结算业务请求 | 已知 Luna tokens | 作者审核 | 正式采用地点 | 已保存地图 | Writing eligibility |
| --- | --- | --- | --- | --- | --- | --- |
| 修仙 | 32 | 502436 | 完成 | 0 | 0 | not_run |
| 西幻 | 33 | 518675 | 完成 | 2 | 2 | not_run |
| 都市 | 29 | 417734 | 完成 | 1 | 1 | not_run |
| 科幻 | 35 | 569966 | 来源门禁停止，10步后unknown | 0 | 0 | not_run |
| 悬疑 | 32 | 508948 | 来源门禁停止，7步后unknown | 0 | 0 | not_run |

业务合计161次、2517759tokens、unknown0，30个独立信封逐一去重，且与五个域根预算扣减相符。五次Sol6.1/xhigh教师seed另计，token与费用未知；本R6实际模型调用合166次。冷启动原上界325，余159个业务请求额度未使用、不清零或转借新scope；上界不等于实际用量或后续阶段授权。

## 来源与可运行性

正常作者审核已真实走通原World地点采用、重新预览与独立地图采用；都市1地图仅关联p5，西幻2地图只关联p1/p2与p4，修仙无采用地图。这些结果不足以形成各族完整positive作者地点清单。

科幻、悬疑各有candidate result_ref的source_clue_ids为空，当前World草图同时标明来源或线索已变化。控制链在无法追溯共同Scene时失败关闭，分别已完成10步、7步审核后记unknown；原审核记录不覆盖、不续跑，也不把该审核状态混同为业务调用用量未知。悬疑两张、科幻一张候选有上述空来源引用，原候选及原回执保留。没有据此猜测共同Scene或强行采用。

五族正常freeze均输出writing-eligibility的not_run；未做Scene地点PATCH，Writing pairs、Assistant turns、judge calls均0。未把部分清单、显示名、未来Scene地图或预声明control改写成完整可运行绑定。私有source-coverage/all-five.json包含全部五族及显式审核状态，是描述性覆盖诊断，不是精确率、召回率或作者质量评分。

## 封存与剩余门禁

本轮通过正常engine接口转为read_only并停止五个域根，保留原预算与30个完成任务的meta/result哈希；不取消已完成任务、不重建数据、不重放已付费请求。另17个正常发布/RAG outbox均pending/attempt0/no envelope，原样保留且未执行。封存最终回执为operator-diagnostic-seal.json。holdout仅校验字节哈希，未解码，`human_validated=false`。

地图辅助写作与五题材完整质量矩阵尚未通过；C1仍等演化第四阶段真实长篇，M5/C5势力扩展等外部账本前置，A4真实数周/Top3、RP独立评测与作者验收仍未完成。工程绿色不改变这些条件。

私有原始输入、输出与完整回执留在
`/Users/tywww/.codex/private/map-spatial-evaluation-20261016-r6`，未进入Git。
核心索引：coldstart-final-diagnostic.json、family-accounting/、review-diagnostics/、source-coverage/all-five.json与各族writing-eligibility。普通report.json仍为prepared模板，不能替代本轮真实诊断。恢复点见[主检查点](../../../T-20261015-character-world-progression/artifacts/C5-C0-C3-A1-CHECKPOINT.md)；全计划对账见[实施验收表](../../../T-20261015-character-world-progression/artifacts/FULL-SCOPE-ACCEPTANCE.md)。

后续离线尾修（2026-10-16T13:54:06+08:00）：空几何候选属于合法待放置载体，真实来源仍保存在同batch同node托盘。root修复评测驱动的reject-only来源读取，保留空几何source_clue_ids并另记rejection_tray_clue_ids；不改采用门禁。77项控制链/实际World服务、461项evals/2skip与ruff通过，新pipeline `38da6d39b70ec51b64b7c7dcfb62a38ed2fdda5dfc15b04efca9d4c0eae225fa`。本报告的R6数据仍属于原81785/a3ad固定点，未恢复、未重评分；修复本身不补足地图覆盖，不使本轮质量gate通过。

最终docs-check、repo-gates与diff检查通过；仅有两项既有文件长度建议。没有新增真实模型评测或作者验收。

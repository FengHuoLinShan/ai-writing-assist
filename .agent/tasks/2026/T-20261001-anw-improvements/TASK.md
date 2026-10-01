# T-20261001-anw-improvements — AI-Novel-Writer 对比方案第一批/第二批实施

## 目标

执行 `.zcode/reports/AI-Novel-Writer-对比与改进方案-独立设计.md` 的第一批(A1–A4)与第二批(B1、B2、B3、B5),
每批完成后独立 review + 修复,最终核对项目能力是否符合计划目标。

范围裁定:
- B4(嵌入空间身份)为触发式,当前不满足触发条件(不换 embedding 模型、不开放账户级配置),不做。
- C1–C4 需产品决策,不在本轮执行。

## 关键决定与证据

- 分支 `codex/anw-improvements-batch-a`,基于 `origin/main@1a8aebf16`。
- 方案文档即权威需求来源,行号以实施时代码为准。

## 进展

全部完成。提交:64e2a42c3(主体)+ 95f6a4b00(验收补丁),分支 codex/anw-improvements-batch-a,未推送。

- [x] A1 剧情线入选规则修正与到期提示
- [x] A2 Scene 合同逐项审查
- [x] A3 Context 事实等级标注与裁剪说明
- [x] A4 全书导出
- [x] 第一批 review + 修复(前端 2P1+5P2、后端 1P1+3P2 全修)
- [x] B1 跨章复读确定性检查
- [x] B2 意见处置稳定身份(含 legacy 别名迁移行指纹)
- [x] B3 editorial brief 进 writing 生成(默认关闭)
- [x] B5 跨任务用量查询
- [x] 第二批 review + 修复(4P2+4P3 全修)
- [x] 收尾:文档同步、门禁、提交、能力核对

## 验证

- 后端受影响模块(writing/story.outline_state/evidence/compilation/assistant/infrastructure.tasks):1293+394 passed。
- 后端全量(modules+infrastructure):4490 passed;36 失败均为基线环境问题(35 world + 1 rag,经 stash 在 origin/main 复现同样失败)。
- 前端全量:2115 passed。
- ruff/eslint 全过;prompt_contracts 24 过;docs-check(BASE_REF=origin/main,no-change-reason 覆盖 indexing/数据库设计/memory 三份无影响文档)通过。
- 能力 vs 计划目标核对:A1-A4、B1/B2/B3/B5 逐条验收通过;B4(触发条件不满足)与 C1-C4(需产品决策)按计划不实施;"明确不做"清单未引入;外部缺陷(goalReview 引文唯一性、FNV 身份)未照抄并已修正。

## 已知限制(交接注意)

1. A2 逐项审查与 B1 复读阈值的质量收益是假设:需按 testing-guide.md 用真实模型做合成样本离线校准(A2)与真实长稿阈值校准(B1)后才能宣称效果。
2. A3/A1 渲染变化会使部署时在途 writing 任务按任务源指纹判漂移丢弃——需低峰发布并在发布说明写明(计划 A3 代价节预期内)。
3. Playwright E2E 未新增用例;新端点与面板由 API/组件测试覆盖。
4. 改动未推送、未开 PR;合并需按仓库流程另行授权。

## 阻塞

无。

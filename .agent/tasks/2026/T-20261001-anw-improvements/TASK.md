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

- [x] A1 剧情线入选规则修正与到期提示(后端 get_active 条件+超期渲染;前端徽章)
- [x] A2 Scene 合同逐项审查(冻结条目+同请求三态判定+归一化失败关闭+待核实显式纳入返修;前端三态面板)
- [x] A3 Context 事实等级标注+裁剪说明(不影响确认指纹;任务源指纹已覆盖)
- [x] A4 全书导出(GET /writing/export txt/md/md-zip+单章+manifest 复核+未采用章列出;前端双口径+设置页入口)
- [x] 第一批 review + 修复(2 个审查子代理;前端 2P1+5P2、后端 1P1+3P2 全部修复,含 exportingAdopted .value、null payoff 假徽章、剥引号 excerpt 定位、无冻结条目残留、SQL trim 口径)
- [x] B1 跨章复读确定性检查(detect_repetition_overlap 纯函数+偏移映射回原文;_repetition_items 集成 conflict check;仅提示不拒存)
- [x] B2 意见处置稳定身份(结构化键 category+source_ids+evidence chapters;legacy 别名迁移;disposition_inherited 继承标记;前端沿用提示)
- [x] B3 editorial brief 进 writing Context(默认关闭开关+for-writing 端点+EditorialBriefLoader+chapter/scene scope+section 进确认指纹;前端编辑台开关)
- [x] B5 跨任务用量查询(summarize_ai_usage 扫 run envelope 按 capability 聚合;GET /projects/{id}/ai-usage;设置页 AI 用量区;作者语言)
- [ ] 第二批 review + 修复(子代理进行中)
- [ ] 收尾核对与门禁(docs-check、能力 vs 计划核对)

范围裁定:B4 嵌入空间身份为触发式,触发条件不满足,不做;C1-C4 需产品决策,不做。
prompt 契约文档已同步(docs/prompts/Prompt体系设计.md:semantic_review 逐项判定、正文生成类的 A1/A3/B3 说明)。

## 验证

- 后端全量(受影响模块):`pytest modules/writing modules/story/outline_state modules/evidence modules/assistant infrastructure/tasks` → 1291 passed(1 个基线失败 test_rag.py::test_retrieve_with_custom_top_k 在 origin/main 也失败)。
- 前端全量:`vitest run tests/vue/` → 2112+ passed。
- ruff check modules infrastructure 全过;eslint 改动文件全过。

## 恢复快照

分支 codex/anw-improvements-batch-a(基于 origin/main@1a8aebf16),改动未提交。下一步:等第二批 review 结果并修复,然后收尾(docs-check、e2e 抽查、能力核对、提交)。

## 阻塞

无。

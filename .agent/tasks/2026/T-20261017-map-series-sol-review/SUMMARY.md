# 地图系列修复复审与补审汇总

3 组 `gpt-6.1-sol/high` 已完成并行审查，主会话已逐条回读生产分支、调用方、前端条件及数据库约束。
确认 **12 项问题：10 项 P2、2 项 P3，未发现 P0/P1**。建议先修复再合入；本轮没有修改生产代码或测试。

## 发现

| 编号 | 等级 | 问题与实际影响 | 来源与详细证据 |
|---|---|---|---|
| R1 | P2 | 两组同字段档案中最新组已清除，再从实体接口清空字段会提前返回，另一组仍有效并进入 Evidence | 修复残缺，[WORLD-1](WORLD.md)，`dossier_service.py:2452` |
| R2 | P2 | 最新旧字段档案带有效期时，普通实体编辑沿用错误条目组，撞同组 active 唯一约束，整次编辑回滚 | 修复回归，[WORLD-2](WORLD.md)，`dossier_service.py:2425` |
| R3 | P2 | 表格补空撤销仅回退实体列，同步生成的档案仍有效，作者看到撤销成功后资料仍被消费 | 遗漏撤销调用链，[WORLD-3](WORLD.md)，`applied_change_reversal.py:195` |
| R4 | P2 | 作者词条正常更新后，旧修订线索虽能采用，草图构建、采用、托盘放置及通知仍按旧校验拒绝 | 修复残缺，[WORLD-4](WORLD.md)，`map_spatial_clue_service.py:586` |
| R5 | P2 | 世界推进合并档案丢失 Scene 身份，求确认交集时把作者已选的位置、保管等连续性事实全部滤掉 | 修复回归，[STORY S1](STORY.md)，`world_progression_context.py:547` |
| R6 | P2 | 空间补扫/追加阅读只靠前端缓存互斥；另一页仍可追加同一运行，主阅读推进后补扫触发 parent_advanced | 修复未闭环，[ASSISTANT A1](ASSISTANT.md)，`workflow.py:246` |
| R7 | P2 | 启动已落库但响应丢失后，新 canStart 门槛挡住原请求核对；进入场景待审等可恢复停点时又被 pending 锁住恢复按钮 | 修复回归，[ASSISTANT A2](ASSISTANT.md)，`ReadingFlow.vue:210` |
| R8 | P2 | 持续授权区域要求已有绑定分支，首次授权和主动关闭后的重新开启均没有入口 | 原未审范围，[STORY S2](STORY.md)，`WorldProgressionPanel.vue:361` |
| R9 | P2 | 已授权旧根 A 后建立新根 B，界面只向最新根读取授权并得到 409，旧授权的关闭入口消失 | 原未审范围，[STORY S3](STORY.md)，`WorldProgressionPanel.vue:1138` |
| R10 | P2 | 交汇候选转导演的预览与提交指示长度不同，服务重算预算指纹后必然 409 | 补审发现，[STORY S4](STORY.md)，`WorldProgressionPanel.vue:1586` |
| R11 | P3 | 导演仍允许向已离场但保留位置的人物发言，裁决请求计费后才在结算中确定性失败 | B7-F2 残留，[STORY S5](STORY.md)，`director_tasks.py:1103` |
| R12 | P3 | 目标预算总请求 2、可能计费 8 可从表单提交；422 明确拒绝后 pending 不清空，作者无法改正预算 | B9-F1 修复遗漏，[ASSISTANT A3](ASSISTANT.md)，`GoalRunsPanel.vue:588` |

详细报告均有触发步骤、代码证据、影响、最小修法及现有测试缺口。R1/R2 是不同输入和不变量，R8/R9 是首次授权与已有授权撤销两条独立生命周期，未合并计数。

## 覆盖

- 本轮原 31 项修复全部有逐项静态复审结论：WORLD 20 项、STORY 4 项、ASSISTANT 7 项，详见三份报告的覆盖表。
- 原报告显式未审代码已补读：`GoalPlanField.vue`、`WorldRelationsTab.vue` 模板、Scene 工作台剩余差异、`WorldProgressionPanel.vue` 连续授权/分支管理及交汇导演入口、`operation_trace_http_adapter.py`、forecast 的 preparation/contracts 与相关剩余改动。
- 原系列差异定位基线为 `00d861283e34bdc0ef3f34ee5605c71e1f89c553..a479e006bc336c0009e5207f7659609ab483e901`；本轮修复为 HEAD `3b2ac9441c0dc08533a3e62269cd054ff35c5302` 至当前工作树，包括未跟踪迁移/测试。
- B10-F2 依用户确认留给 ADR-0042，不重复报为缺陷。持续推进跨新 Scene 必须重新确认，是已说明限制；R8/R9 属于限制之外的入口与撤销问题。
- 排除了冻结世界推进自行读回后续事实、新 bootstrap 绕过底层单写者约束等疑点；不将推测计入发现。

## 主会话核验与后续顺序

主会话已独立核对 12 项的关键分支、真实调用方和证据。此结论是静态可达性证明，没有把子代理推测直接当成实测。
优先处理 R1/R2/R3/R5 的资料同步与来源完整性，再处理其余 P2 的采用、并发和作者恢复路径，最后处理两项 P3。
修复时保留历史、有效期、原确认、原 operation_id、预算累计和事务边界；每份分组报告均给出针对性的验证场景。

本轮未运行实现测试、PG、浏览器、真实模型或作者验收，也未重审原系列全部 805 文件。上一轮绿色日志不覆盖本轮发现的缺失场景。
审查文档的 `make docs-check BASE_REF=origin/main` 与 `git diff --check` 通过；日志为 `/tmp/map-series-sol-review-docs.log`。生产补丁哈希与开始审查时一致。
本地审查文档交付；未提交、推送、合并或部署。

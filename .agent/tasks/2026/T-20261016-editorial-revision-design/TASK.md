---
id: T-20261016-editorial-revision-design
title: 审读与修订链路改进设计
status: completed
created: 2026-10-16T16:48:00+08:00
updated: 2026-10-16T17:33:01+08:00
---

# 审读与修订链路改进设计

## 恢复快照

- 实际完成：按当前代码核实 Assistant 编辑台、语义审查、批注修订、协作审稿、editorial_revision v1 和 editorial eval；完成四项公开资料补查及来源边界复核；将两份创作研究报告转为设计方案和合成评测计划；完成独立反方审查并修订预算、回读能力、分工映射、优先级、作者 opt-in 与评测门槛。
- 当前里程碑：已完成，交付设计报告。
- 下一步：无；等待作者决定报告第 11 节候选，不自动开展实现、模型评测或用户研究。
- 阻塞：无。
- 工作区：/Users/tywww/项目/ai-writing-assist，分支 codex/guided-flow-borrowing。保留原始未跟踪 research 输入目录及 out/；未改代码、Prompt、权威文档、ADR、eval 数据集；未运行业务 LLM；未提交或推送。
- 最后核实：2026-10-16T17:33:01+08:00。

## 目标与验收

- 目标与交付物：在同目录的 REVIEW-REVISION-DESIGN.md 给出当前链路盘点、报告逐项映射、公开研究补查、按收益/成本排序的改进候选、反方审查记录和 eval 扩展/费用情景。
- 完成条件：逐条映射覆盖失配类型、八步诊断、11 个领域、作者承诺与不应报告清单；各链路写明输入/输出、作者确认、LLM 与确定性职责；候选注明文件、契约/migration、用户行为、文档和测试；通过 git diff --check 与 make docs-check BASE_REF=origin/main。
- 非目标：实施代码、schema、prompt、方法文本、权威文档或 eval 数据集变更；真实模型/小说正文运行；发布、提交或推送。

## 上下文与边界

- 输入：.agent/tasks/2026/T-20261016-literary-writing-errors/RESEARCH.md；.agent/tasks/2026/T-20261016-literary-craft-research/RESEARCH.md；docs/product/user-personas.md 的画像 A。
- 关键实现：backend/modules/assistant/editorial.py、editorial_contracts.py、editorial_bridge.py、teams；backend/modules/writing/semantic_review.py、comment_run.py；assistant/comment_proposals.py；editorial_revision v1；backend/evals/datasets/editorial/。
- 重要代码事实：BR-4 当前允许作者选择多条、跨章证据并按章拆分局部任务，README/module docstring 的首条依据说法过时，已有桥接测试覆盖多依据和跨章行为。Editorial synthesis 只收到章节摘要及已有 finding，不会重新检索未形成 finding 的旧线索。4 请求额度仅限单次 worker execution，续跑会重置该段额度，不能当作全书审读封顶。详细证据位于报告对应路径行号。
- 设计决策：category 表示编辑层次，severity 表示模型影响判断，失配类型暂不必增必填字段；口味默认过滤，若开放需本轮显式 opt-in 并与错误卡/严重度/桥接分开；伦理观察当前无 opt-in，若设计需独立作者入口；排序先保留来源/范围/引文完整性检查，再评估 severity 优先排序，不以章节数推断根因重复；回读旧线索需要新检索/回读路径及来源重验。
- 授权范围：只读调查、公开资料和本任务目录设计稿/笔记；保护 out/、两份输入报告及其他未跟踪文件。

## 里程碑与进度

- [x] 核对当前工作树、任务协议、画像 A 和研究报告输入。
- [x] 代码盘点所有指定链路及既有评测。
- [x] 完成四项研究补查：LLM 审读可靠性、作者声音/过度修改、意见接受与作者控制、人类编辑分层实践。
- [x] 完成逐项映射、修订候选、评测设计和费用估算。
- [x] 完成独立反方审查，修订全部阻断和重点发现。
- [x] 运行文档差异检查和架构文档门禁。

## 决策、发现与失败

- 2026-10-16：按用户范围只设计、不实施；不调用业务模型。主报告不是实现授权。
- 2026-10-16：将回读旧线索明确为当前不支持的能力；未来路径必须限于作者选定范围、重新验证来源，并额外预算。
- 2026-10-16：把红队提出的预算上限错误修正为最多六章、每章单段的估算情景；约 US$4.20 是按公开费率加余量的规划值，不是全书实际费用或系统硬上限。
- 2026-10-16：风格维度默认开启，所以不能代表本轮偏好请求；偏好默认过滤，主动风格/伦理观察均需单独 opt-in。
- 2026-10-16：不把不应报告口诀做成服务端门禁；不把 11 个领域拆成默认意见卡；现有跨章桥接测试复用，不重复增测。

## 验证证据

- 独立反方审查：完成；已写入 REVIEW-REVISION-DESIGN.md 第 12 节。
- git diff --check：通过，无空白错误。
- 未跟踪报告与任务笔记通过 git diff --no-index --check 对 /dev/null 核查；命令返回 1 表示文件有差异，无空白错误输出。
- make docs-check BASE_REF=origin/main：通过，架构文档检查通过。
- 未运行测试、真实模型、作者访谈或评测数据集实验，符合设计-only 范围。
- 最终工作树应再核实；原有 research 输入和 out/保持不动。

## 交付结果

- 已交付：REVIEW-REVISION-DESIGN.md。
- 未交付：实现、真实作者/读者研究、真实模型结果、正式 eval 数据版本。
- 交付边界：仅工作树本地新增任务文档；不提交、不推送、不发布。
- 正式知识与后续任务：无；后续工作取决于作者对报告第 11 节的选择。

# Codex5.3 1-7 章深度导入期望系统性能表现

## 标准样本

- 源文件：`/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_1-7章.txt`
- 标准抽取模型：`gpt-5.3-codex-spark`
- 标准样本项目：`df773d50-9351-4bb2-8710-06fa80215cdd`
- 项目名：`诡秘之主 第一部 小丑 1-7章 Codex5.3 标准样本`

## 标准结果

系统深度导入 1-7 章时，应至少达到以下结构覆盖：

| 对象 | 标准数量 | 最低合格线 |
| --- | ---: | ---: |
| 章节草稿 | 7 | 7 |
| Scene | 9 | 9 |
| 世界对象 | 29 | 18 |
| 剧情线 | 4 | 2 |
| 篇章纲 | 4 | 2 |
| 伏笔 | 4 | 2 |
| 揭示计划 | 4 | 2 |

## 当前已验证运行

2026-07-01 的最新真实 LLM 后端直连验收使用当前项目配置的模型
`deepseek-v4-flash`，日志文件为：

`backend/.test-logs/deep_import_real_llm/deep_import_7_20260701T000938Z.jsonl`

该运行完成耗时 506.89 秒，自动化验收通过，输出如下：

| 对象 | 实际数量 |
| --- | ---: |
| 章节草稿 | 7 |
| Scene | 9 |
| 世界对象 | 39 |
| 剧情线 | 4 |
| 篇章纲 | 4 |
| 伏笔 | 4 |
| 揭示计划 | 4 |

本轮达到质量合格线，且实体召回高于 Codex5.3 标准数量：`scene_count=9`、
`entity_count=39`、结构四类均为 4。Phase 1a 单章 fallback 为 4/7 成功，
3 个章节 timeout；Phase 1b LLM 成功返回，但仍存在 3 个章节覆盖补位和 2 个
最小数量补位，因此最终 `quality_status=partial`、
`degraded_reason=phase1b_minimum_count_fallback`。这个 partial 不代表实体抽取
失败，而是 Scene 融合阶段仍依赖保守补位来保证 1-7 章覆盖。

Phase 2 本轮走小样本并发 Scene LLM 路径，完成 8/8 个参与提取的 Scene
checkpoint，真实创建 39 个实体、8 条 delta，`fallback_created=0`、
`supplemental_llm_created=0`、`failed_scene_count=0`、`degraded=false`。快照审计
为 9 个 snapshot，Phase 2 的 8 个 snapshot 和 Phase 3 的 1 个 snapshot 全部
成功。该结果说明实体数量来自真实按 Scene LLM 抽取，而不是小样本补足或静态
fallback。

本轮同时满足当前速度目标：端到端 8 分 26 秒，低于 10 分钟目标。当前系统可将
该结果作为“综合基线”：质量接近 Codex5.3 标准样本，速度达标，诊断字段足够
解释剩余 partial 原因。下一轮优化优先级应从 Phase 2 转移到 Phase 1a timeout
和 Phase 1b coverage/minimum-count fallback，目标是减少 `needs_review` Scene
和最终 `degraded_reason`。

上一轮速度优化对照：

`backend/.test-logs/deep_import_real_llm/deep_import_7_20260630T235858Z.jsonl`

该运行 538.20 秒完成，9 Scene / 37 世界对象 / 结构四类均为 4。它验证了小样本
并发 Scene LLM 路径的速度收益，但 Phase 2 有 1 个 Scene 因 LLM 返回
`hidden_truth: null` 等可恢复 schema 偏差失败，最终 `failed_scene_count=1`。
当前 schema 已将可选文本字段的 `null` 归一化为空字符串，`20260701T000938Z`
确认该问题已消失。

历史质量上限对照：

`backend/.test-logs/deep_import_real_llm/deep_import_7_20260630T232212Z.jsonl`

该运行完成耗时 766.45 秒，9 Scene / 41 世界对象 / 结构四类均为 4。Phase 2
完成 9/9 Scene checkpoint，`fallback_created=0`、`supplemental_llm_created=0`。
它仍是实体召回最高的质量对照，但端到端 12 分 46 秒，超过 10 分钟目标。主要
慢尾来自 Phase 2 bulk 快速路径失败后的串行 Scene 抽取，因此不再作为速度基线。

已废弃调参：`deep_import_7_20260630T233814Z` 将 Phase 2 bulk 输出预算从 4096
提高到 8192，但 7 分 26 秒时仍退回串行且只完成 2/9 Scene；说明单纯提高
bulk max_tokens 不能解决快速路径稳定性，已回退。

历史保留基线：

`backend/.test-logs/deep_import_real_llm/deep_import_7_20260630T214850Z.jsonl`

该运行完成耗时 441.17 秒，自动化验收通过，输出如下：

| 对象 | 实际数量 |
| --- | ---: |
| 章节草稿 | 7 |
| Scene | 9 |
| 世界对象 | 33 |
| 剧情线 | 4 |
| 篇章纲 | 4 |
| 伏笔 | 4 |
| 揭示计划 | 4 |

本轮达到自动化合格线：`scene_count >= 9`、`entity_count >= 18`，
且 `threads/arcs/foreshadowing/reveals` 四类均达到 4 项。该运行仍标记为
`partial/degraded`，原因是 Phase 1b 成功返回后仍存在 4 个章节覆盖补位和 2 个
小样本数量补位。Phase 1b 保持 `success=1`、`schema_error=0`、`timeout=0`。
当前代码对 1-7 章小样本会跳过已反复无收益的 Phase 0 LLM 预取，记录为
`skipped_for_small_sample=true`，直接进入带正文的单章 Phase 1a；这将端到端
时间从约 474 秒降到约 441 秒。Phase 1a 单章 fallback 本轮为 3/7 成功、4 个
章节 timeout，诊断采样能定位到 `S-0002`、`S-0003`、`S-0004`、`S-0005`。
补强出的结构资产和实体候选带 `needs_review` / fallback provenance，用户应在
管理界面复核、合并或删除。

同日对照运行显示当前 LLM 服务存在输出波动：`deep_import_7_20260630T201540Z`
为 9 Scene / 24 世界对象 / 458.87 秒，`deep_import_7_20260630T203954Z`
为 9 Scene / 30 世界对象 / 503.50 秒但 Phase 1b timeout，
`deep_import_7_20260630T205007Z` 为 9 Scene / 20 世界对象 / 450.74 秒，
`deep_import_7_20260630T212559Z` 为 9 Scene / 34 世界对象 / 474.51 秒。
当前系统应以“8 分钟内稳定通过合格线，并记录 partial/fallback 原因”为最低
可接受表现；更高质量目标是降低 Phase 1a timeout，并消除 Phase 1b
coverage/minimum-count fallback。

已废弃实验：`deep_import_7_20260630T210550Z` 尝试给 Phase 1b 增加更强的
required-events 约束，最终 467.82 秒完成，9 Scene / 32 世界对象，但 Phase 1b
重新 timeout，Phase 2 只处理 8 个 Scene checkpoint，说明该提示增强会增加
reducer 慢尾风险，不作为当前保留基线。

已修复实验：`deep_import_7_20260630T211749Z` 暴露 Phase 1b reducer 真实返回
`discarded_candidates: []` 时的 schema 错误；`212559Z` 运行确认该类型
已被归一化为 `{}`，Phase 1b 不再因此降级失败。

已废弃实验：`deep_import_7_20260630T213835Z` 尝试取消 Phase 1a 单章 retry，
用正文锚点候选替代失败章节。该运行 467.61 秒完成，但 Phase 1b timeout，
实体降到 18，`needs_review_scene_count` 升到 9；说明取消 retry 会损害下游
融合与实体提取质量，不作为当前默认策略。

已废弃实验：`deep_import_7_20260630T220059Z` 尝试在 1-7 章小样本中并行执行
batch Phase 1a 和单章 Phase 1a，以 batch 结果补单章超时缺口。该运行在
17 分 28 秒时中断，Phase 1a 虽达到 8/10 成功，但 Phase 1b timeout，并降级
提交 14 个 fallback Scene，导致 Phase 2 运行时间明显放大；说明无筛选地增加
候选会把慢尾转移到 reducer 和实体提取阶段。

已废弃实验：`deep_import_7_20260630T221957Z` 在并行 Phase 1a 基础上只保留覆盖
单章失败缺口的 batch 候选。该运行 556.90 秒完成，11 Scene / 18 世界对象 /
4 条剧情线 / 4 个篇章纲，但 Phase 1b timeout，所有 11 个 Scene 均为
`needs_review`，质量和速度都低于 `214850Z` 保留基线。因此当前默认策略仍为：
1-7 章跳过 Phase 0 LLM 预取，直接执行单章 Phase 1a，避免把额外 batch 候选
传给 Phase 1b。

保留但未证明能提升实体质量的调整：Phase 1b fallback 的 1-7 章小样本占位
Scene 已从通用“第 X 章待校验 Scene”改为低置信关键事件锚点，例如“绯红醒来与
自杀谜团”“灰雾会面”“非凡者交易”“代号聚会成形”。`deep_import_7_20260630T223729Z`
在该调整后 378.04 秒完成，9 Scene / 18 世界对象 / 4 条剧情线 / 4 个篇章纲，
Phase 1b 成功且无 timeout，但实体数只达到最低合格线，低于 `214850Z` 的 33。
该调整的价值主要是让 fallback Scene 更可人工整理，不能视为已解决实体召回。

保留为诊断增强的调整：Phase 2 现在应在 `quality_stats.phase2` 中记录
`total_created`、`completed_scenes`、`skipped_scenes`、`fallback_created` 和
checkpoint 状态计数，便于区分真实 LLM 抽取数量和小样本补足数量。
`deep_import_7_20260630T224559Z` 在 Phase 2 召回提示增强后 446.01 秒完成，
9 Scene / 18 世界对象 / 4 条剧情线 / 4 个篇章纲；该轮 Phase 1a 为 6/7 成功，
但 Phase 1b timeout，实体数仍未超过最低线，说明 Phase 2 提示增强尚未被真实
结果证明有效。下一轮验收应优先检查 `quality_stats.phase2.fallback_created`，
如果实体数仍主要依赖 fallback，应继续优化实体抽取而不是提高补足数量。

## 质量表现

- Scene 应覆盖 1-7 章主要情节转折：穿越醒来、自杀迷局、家庭掩护、城市生计、塔罗占卜、转运仪式、灰雾会面、非凡者交易、代号聚会。
- Scene 不应过碎；推荐 8-14 个，低于 9 个通常说明跨章关键转折被吞并。
- 世界对象应覆盖长期资产：主要人物、地点、组织/教会、关键物品、核心概念。
- 不应把一次性路人、普通食物、普通家具、临时摊贩作为核心世界对象污染正史库。
- 每个 Scene 应包含章节映射和短定位提示，便于人工抽检与后续回填。

## 可靠性表现

- 文件解析必须稳定得到 7 章，首章为 `第一章 绯红`，末章为 `第七章 代号`。
- Phase 0 / Phase 1a / Phase 1b 必须记录 `quality_stats`，包含 `timeout`、`schema_error`、`final_422_rate`。
- Phase 1a 单章 fallback 的诊断采样应保留 `chapter_index` 和 `source_batch_id`，
  否则无法定位哪几章反复超时。
- `final_422_rate > 40%` 时必须阻断或显式降级，不能静默继续。
- Scene 为 0 或实体为 0 时，任务不能标记为 `complete`；必须为 `partial` 或 `failed`，并写入 `phase_errors`。
- Phase 2 至少应生成 1 个 scene checkpoint；失败时 checkpoint 应带 `failed` 状态和错误类型。
- Phase 2 的 `quality_stats.phase2.fallback_created` 应尽量为 0；如果实体数达到
  18 但主要来自 fallback，仍只能视为可诊断通过，不应视为接近 Codex5.3 标准。
- Phase 2 bulk 快速路径失败时可以退回串行 Scene 抽取，但必须留下 failed
  snapshot 和后续 checkpoint；不能停在 0/9 Scene 无诊断等待。
- 同一人物应合并为同体，例如 `周明瑞 / 克莱恩·莫雷蒂` 不应被拆成互不关联的多个正史人物。

## 速度表现

- 1-7 章是小样本，目标是快速质量验收，而不是压力测试。
- 在 LLM 服务健康时，端到端应在 10 分钟内完成。
- Phase 0 + Phase 1a 不应因为多个 batch 长时间超时而耗尽主要运行时间；当前
  1-7 章小样本已跳过 Phase 0 LLM 预取，主要慢尾在 Phase 1a 的单章 timeout
  和 Phase 3 结构分析。
- Phase 1b 应优先走成功 reducer 路径；小样本允许少量可解释补位，但不应长期
  依赖 coverage/minimum-count fallback 才达到 9 个 Scene。
- Phase 2 单 Scene 抽取应有硬超时和 checkpoint；任一 Scene 不应无状态卡住超过 3 分钟。
- Phase 2 小样本 bulk 快速路径应在 1-2 分钟内成功或失败并降级；如果 bulk 失败后
  进入串行兜底，整体完成仍不应超过 10 分钟。
- 如果进入降级路径，应尽快产出可诊断日志，而不是继续执行低价值 Phase 3 并返回误导性完成结果。

## 验收判定

合格运行应满足：

- `scene_count >= 9`
- `entity_count >= 18`
- `plot_threads + outline_arcs + foreshadowing + reveals >= 8`
- `quality_status` 为 `complete` 时，Scene 和实体都不能为 0
- `needs_review` Scene 可以存在，但必须有 `review_reason` 或等价质量说明
- 日志能解释所有失败 batch/window/scene 的错误类型

低于合格线时，系统应给用户明确提示：当前结果只能作为草稿或失败诊断，不能作为可靠深度导入结果。

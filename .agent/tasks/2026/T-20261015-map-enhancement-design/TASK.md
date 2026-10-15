---
id: T-20261015-map-enhancement-design
title: 地图系统增强设计（自动冷启动、参与创作决策、题材鲁棒性）
status: active
created: 2026-10-15T10:54:00+08:00
updated: 2026-10-15T23:00:00+08:00
---

# 地图系统增强设计

## 恢复快照

设计稿与 ADR-0035 至 ADR-0037（Proposed）已于 2026-10-15 经用户授权本地提交 `87e56f241`，未推送。
之后按用户要求核对 33 条外部评审并修正（几何指纹白名单、7 种模态处置、层级存储、G8c 误引、
API 默认值措辞、层级来源优先级、Scene 无位置身份等）；原 ADR-0038 已并入新 ADR-0038
（操作目录，见 T-20261015-agent-operation-surface）。修正经用户授权在第二个本地提交中提交，未推送。工作树
`.worktrees/map-enhancement-plan`，分支 `codex/map-enhancement-plan`，基于 main `d2ab2dbf3`，无 upstream。
世界演化第四阶段计划 §6 已加承接说明，指向 ADR-0036。
下一步：技术评审 ADR-0035 至 ADR-0038 后转 Accepted；推送与 PR 按用户授权。实施（M0 起）由用户另行安排执行者。

## 目标与验收

- 目标：让地图冷启动变短，并让地图参与写作等模块的决策；模型要能兼容大量题材和风格，
  并为未列举的情况预留用户自定义和模型涌现。
- 验收：设计稿和 ADR 覆盖用户裁定，与现有 ADR（0005、0012、0017、0025、0026、0031）
  的关系写明（对 ADR-0005 的偏离只限空间类型）；`make docs-check BASE_REF=origin/main` 通过。

## 用户裁定（2026-10-15）

- 两个痛点：冷启动太长；地图对写作和其他模块帮助有限。
- 保持示意与提醒级，不做强制约束；空间数据作者不填时只从原文抽取并审核。
- 冷启动自动进行；草图允许绑定候选地点；允许写 ADR 等文档。
- 势力路线图先单独推进，后续合入地图；领地要多形态（海上按船），势力可多层嵌套；
  船可以是势力单元，小船也可以只是物品，要能灵活转换。
- 未列举的情况预留用户自定义；首批验收题材：修仙、西幻、都市、科幻、悬疑。
- 第二轮：深度导入即将被世界演化替代并下线；允许模型在演化中总结常用类型，按项目维护。
- 第三轮：同步增强助手，帮助作者使用地图修改、势力控制等功能（不限于这两项）。

## 关键决定与理由

- 小型封闭的计算特性内核加开放的项目类型（ADR-0035）：程序只读特性，类型由作者自定义或模型涌现；
  特性在作者采用引用该类型的地图版本后才参与提醒；归档类型保留墓碑，模型不得重建。
- 层级保留 `level` 列与 CHECK 作系统粗层，新增可选 `level_type_ref`，深度由父链推导。
- 可信度复用 `ObservationModality` 7 种值：只有 `event_observed` 参与计算；`author_plan` 只进作者视图，
  `unclear` 进待核对。v1 已采用约束视为作者确认、全书有效。
- 几何指纹：现有 `geometry_hash` 对约束用排除名单，新增字段会改指纹；落地前先冻结为 v1 字段白名单。
- 冷启动改为演化阅读的 `discover_spatial` 步骤（ADR-0036）：API 默认关、新界面显式开启；层级来源冲突按
  已采用 World 关系 > 已采用地图父子 > 复核线索 > 候选 World 关系取舍；扩展 G8a 地图册消费端口；
  演化成为默认导入入口前保留手动生成回退。
- `map_spatial` 作为参考维度（ADR-0037）；地图变化沿用 G8b 读时比对，正文变化沿用 G8a；
  Scene 无位置身份时不猜；v1 地图即可做最小切片；`check_knowledge_visibility()` 将是首个生产接入。
- G8c（第三批）是正典修订基线（main #248 已落地），与地图无关；地图设计只依赖已实现的 G8a、G8b。
- 现有 `territory_refs_json`、`controlling_faction_ids_json` 保留原样，迁移由势力路线图阶段 1 决定。

## 交付

- `docs/plans/2026-10-15-map-system-enhancement.md`（设计稿）
- `docs/adr/0035-genre-neutral-spatial-model-and-custom-vocabulary.md`
- `docs/adr/0036-evolution-spatial-discovery-map-cold-start.md`
- `docs/adr/0037-map-spatial-advisory-dimension.md`
- 助手地图与势力操作：`docs/adr/0038-ai-operation-catalog-goal-runs-and-trace.md` §10
- `docs/adr/README.md` 与 `docs/README.md` 索引

## 验证

- 2026-10-15 第一至三轮：`make docs-check BASE_REF=origin/main` 与 `git diff --cached --check` 均通过。
- 2026-10-15 评审核对与合并后（未提交）：origin/main 已前进到 `00d861283`（含 G8c #248，未占用
  0035–0041 编号）；`make docs-check BASE_REF=origin/main` 通过（49 个 ADR 文件）；
  `git diff --cached --check` 通过。
- 2026-10-15 写入用户裁定与第四阶段承接说明后：上述两项检查再次通过。

## 风险与待决

- 若其他分支先合入同号 ADR，需要顺延编号并同步索引与引用。
- 空间发现改动演化链路，需要与世界演化第四阶段实施、#209 容量优化等任务划分写入者。
- 移动可行性检查的完整版依赖故事内时间能力（势力路线图、世界演化后续阶段）。

---
id: T-20261015-map-enhancement-design
title: 地图系统增强设计（自动冷启动、参与创作决策、题材鲁棒性）
status: active
created: 2026-10-15T10:54:00+08:00
updated: 2026-10-15T13:30:00+08:00
---

# 地图系统增强设计

## 恢复快照

设计稿与四份 Proposed ADR（0035–0038）已按用户第二、三轮裁定改写或新增（冷启动改挂世界演化、
类型按项目涌现、助手同步支持地图与势力），2026-10-15 经用户授权本地提交，未推送。工作树
`.worktrees/map-enhancement-plan`（主仓库内），分支 `codex/map-enhancement-plan`，基于 main `d2ab2dbf3`，
无 upstream（ADR-0036 由起草时的 `0036-deep-import-map-cold-start.md` 改名而来）。
下一步：用户评审 ADR-0035 至 ADR-0038；推送或开 PR 按用户安排。
实施（M0 起）由用户另行安排执行者，本任务只负责设计与文档。

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
- 第二轮：深度导入即将被世界演化替代并下线；内置基础语义不够，对齐演化的“涌现”思想，
  允许模型在演化中总结常用类型，按项目维护。
- 第三轮：同步增强助手，帮助作者使用地图修改、势力控制等功能（不限于这两项）。

## 关键决定与理由

- 小型封闭的计算特性内核加开放的项目类型（ADR-0035）：程序只读特性，类型由作者自定义或模型
  涌现；没有特性的类型只当文字进入显示和模型上下文。内核扩充走台账扩类那样的方法版本与评测。
- 模型读取项目已有类型并优先复用 ID，新类型需两个 Scene 证据加独立复核，作者判断优先：
  对齐演化发现回读既有主题的做法；这是空间类型对 ADR-0005 的有意偏离，World 对象类型不变。
- 可信度直接复用 `ObservationModality`，只有 `event_observed` 参与计算和简报。
- 几何指纹在 v1 升级到 v2 时保持不变，避免底图校准和读者白名单失效。
- 冷启动改为演化阅读的 `discover_spatial` 步骤（ADR-0036）：复用 journal、独立复核、方法指纹、
  `consumer_read_set` 和类别补扫机制；新阅读默认开、可在授权预览取消；不阻断主理解提交；
  从不自动采用。弃用初稿“深度导入新增 spatial 阶段”。
- `map_spatial` 作为参考维度进入创作（ADR-0037）：必查维度在没有地图时会阻断写作，
  与“示意与提醒”的裁定冲突。
- 助手同步（ADR-0038）：现状只有 4 个有界地图操作（`world/assistant_map_tools.py`），势力只能用通用
  建对象/加关系，类型转换和演化无入口。决定每项新能力同期注册助手操作；作者指令经确认后
  与手动编辑同权（可新增地理），模型推断必须附引文、只作线索候选，均不给坐标；付费演化运行
  由演化自己的授权预览确认，不占助手预算；势力操作等势力路线图阶段 1 的 ADR，之前不模拟。

## 交付

- `docs/plans/2026-10-15-map-system-enhancement.md`（设计稿）
- `docs/adr/0035-genre-neutral-spatial-model-and-custom-vocabulary.md`
- `docs/adr/0036-evolution-spatial-discovery-map-cold-start.md`
- `docs/adr/0037-map-spatial-advisory-dimension.md`
- `docs/adr/0038-assistant-spatial-and-faction-operations.md`
- `docs/adr/README.md` 与 `docs/README.md` 索引

## 验证

- 2026-10-15 第一轮：`make docs-check BASE_REF=origin/main` 与 `git diff --check` 通过。
- 2026-10-15 第二轮改写后：`make docs-check BASE_REF=origin/main` 通过（45 个 ADR 文件，
  架构决策规则所需文档均已更新）；`git diff --cached --check` 通过。
- 2026-10-15 第三轮（新增 ADR-0038 与设计稿 §9）：origin/main 已前进到 `4efe7f21a`（#245，
  未触及 ADR、地图、助手、演化相关文件）；`make docs-check BASE_REF=origin/main` 通过
  （46 个 ADR 文件）；`git diff --cached --check` 通过。

## 风险与待决

- ADR 编号 0035–0038：起草时 main（含 `4efe7f21a`）和本机 worktree 中没有占用；若其他分支先合入同号 ADR，需要顺延。
- 空间发现改动演化链路，需要与世界演化第四阶段实施、#209 容量优化等任务划分写入者。
- 移动可行性检查的完整版依赖故事内时间能力（势力路线图、世界演化后续阶段）。

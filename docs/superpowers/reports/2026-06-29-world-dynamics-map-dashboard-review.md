# 代码审查报告：`feat: add world dynamics map dashboard`

> 审阅对象：`minimal-core` 分支，commit `de03229..bb96f12`
> 审阅日期：2026-06-29
> 对应设计：`docs/superpowers/specs/2026-06-29-world-dynamics-map-design.md`

---

## 总体结论

**是否可合并：否 —— 需先修复 Important 级别问题。**

P0 数据模型与候选/正式（candidate/canonical）流转已经落地，模块边界、novel_id 隔离和 XSS 防护基本到位，测试覆盖率较好。但多个作者可见的 P0/P1 功能仍是桩代码或实现不完整，文档对 P2/P3 完成度的描述也与代码现状不符。

---

## 优点

| # | 项目 | 说明 |
|---|------|------|
| 1 | 模块边界清晰 | `imports` 仅通过新增的 `map_facade.py` 接入 `world/map`，未直接跨模块引用模型/仓储 |
| 2 | novel_id 隔离 | `require_map` / `require_entity` 与 `_safe_entity_uuid` 在持久化前校验隔离 |
| 3 | 候选/正式流转 | `MapObservation` 默认 `candidate`，用户确认后生成 `MapFact`，忽略仅改 review_state |
| 4 | 深度导入接入 | `scene_entity_extraction.py` 将 `delta_events` 导入 `map_observations`，保留 `source_ref` |
| 5 | 前端 XSS 安全 | 动态文本均经过 `esc()`，无 raw `innerHTML` 或 `eval` |
| 6 | 测试覆盖 | 后端 286 passed，前端 323 passed；包含技术 ID 不泄漏到作者界面的断言 |
| 7 | 迁移规范 | Alembic 迁移 `down_revision`、索引、`ON DELETE` 与 ORM 保持一致 |

---

## 问题清单

### Critical（必须立即修复）

无。

### Important（合并前应修复）

| # | 问题 | 位置 | 影响 | 修复方向 |
|---|------|------|------|----------|
| 1 | 已确认对象在总控台队列中重复显示 | `backend/modules/world/services/map_service.py:993-1009` | 作者看到重复条目，计数和批量分组膨胀 | `list_for_dashboard` 仅返回 `candidate`/`conflicted`，或在合并队列时去重 |
| 2 | 对象信息框的“修改”按钮是空桩 | `frontend-console/views/mapWorkspaceView.js:780-785` | P0 要求信息框提供编辑入口，当前仅弹出 toast | 打开轻量编辑器或聚焦右侧检查器 |
| 3 | 右侧检查器仅为摘要，非完整检查器 | `backend/modules/world/services/map_service.py:1231-1269` | 缺少对象摘要、时间化状态、完整来源证据、冲突、历史变化、批量修改入口 | 按 `focus_entity_id` 返回完整检查器模型 |
| 4 | 检查器 API 忽略 `focus_entity_id` | `backend/modules/world/services/map_service.py:1231-1237` | 叙事透镜和对象级检查流程无法工作 | 参数有效时按实体作用域聚合事实、候选、冲突和证据 |
| 5 | 批量修改只读 | `frontend-console/views/mapWorkspaceView.js:533-547` | P1 验收标准要求的批量确认/忽略/移动/改状态等未实现 | 新增后端批量端点并接入分组 UI |
| 6 | 缺少 `MapFact` 回滚/废弃端点 | `backend/modules/world/map_api.py`、`map_schemas.py:461` | `fact_status` 含 `rolled_back`/`deprecated` 但无操作路径 | 增加 `PATCH /{map_id}/facts/{fact_id}` 或 `POST .../rollback`，带二次确认 |
| 7 | 播放未计算真实差分 | `backend/modules/world/services/map_service.py:1031-1107` | P3 要求的位置/状态/边界/危机/资源变化未实现 | 实现 `MapDelta`/`WorldDynamic` 模型，或下调文档完成度声明 |
| 8 | “主要人物”首层混入了地点 | `backend/modules/world/services/map_service.py:1279-1283` | 地点被归类为主要对象/人物，摘要误导 | 将地点拆入独立首层桶 |

### Minor（建议后续优化）

| # | 问题 | 位置 | 修复方向 |
|---|------|------|----------|
| 1 | 布局引擎视口硬编码 | `frontend-console/views/mapWorkspaceView.js:403-406` | 实测语义带容器尺寸 |
| 2 | `PATCH /observations/{id}` 忽略 `map_id` 路径参数 | `backend/modules/world/map_api.py:415-432` | 校验 `map_id` 与 observation 所属 map 一致 |
| 3 | `_safe_map_uuid` 捕获所有异常 | `backend/modules/world/services/map_service.py:1553-1566` | 仅捕获 map 不存在/校验类异常 |
| 4 | 缺少跨 novel 动态事实负向测试 | `backend/modules/world/tests/test_map_dynamic_facts.py` | 补充 404 / 权限拒绝测试 |
| 5 | `MapObservationCreate` 允许 `review_state="confirmed"` | `backend/modules/world/map_schemas.py:475` | AI/导入路径限制为 `candidate` |
| 6 | `current_storyline` 为占位字符串 | `backend/modules/world/services/map_service.py:1290` | 从剧情数据推导当前叙事线 |

---

## 建议

1. **对齐文档与代码**：`docs/modules/15_map.md` 将 P2/P3（自动布局、三视图、播放轨迹）标记为已完成，但代码仅提供 UI 脚手架和列表式播放。建议改为“部分实现 / 脚手架”。
2. **在声明 P3 完成前先引入 `MapDelta`/`WorldDynamic`**：用模型存储计算出的差分，而不是仅依赖 `value_json.old/new`。
3. **补充后端批量端点**：`batch-confirm`、`batch-ignore`、`batch-change-status` 等，并接入批量分组 UI。
4. **按 `focus_entity_id` 作用域化检查器 API**：支撑叙事透镜和对象信息框的实体级详情。
5. **补充跨 novel 负向测试**：保持项目已有的安全测试 posture。

---

## 下一步行动

1. **立即修复** Important #1（重复显示）和 Important #8（地点混入主要人物），属于低风险、高影响修复。
2. **设计并修复** Important #3/#4（检查器）、#5（批量修改）、#6（回滚），涉及 API 形状和 UI 交互，建议单独立项或拆分为 Issue。
3. **文档同步**：根据实际完成度更新 `docs/modules/15_map.md`，避免验收偏差。
4. **回归测试**：修复后重新运行后端 focus suite 和前端测试套件。

---

## 测试基线

```
后端 map suite: 286 passed
前端 suite:     323 passed
```

（以上基线来自审查时代码仓库的测试运行结果。）

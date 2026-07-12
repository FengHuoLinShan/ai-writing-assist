# Round 15/20 — Error Messages / User Feedback / Loading & Error States / UX Flow

**Status**: PASS  
**Goal**: 错误信息质量、用户反馈模式、加载/空/错误状态、UX 流程分析  
**Started**: 2026-07-13  
**Completed**: 2026-07-13  

## 结果总览

| 审计模块 | 发现数 | CRITICAL | HIGH | MEDIUM | LOW |
|----------|--------|----------|------|--------|-----|
| 错误信息质量 | ~6 | 1 | 1 | 2 | 2 |
| 用户反馈模式 | ~6 | 0 | 1 | 3 | 2 |
| 加载/空/错误状态 | ~13 | 3 | 3 | 4 | 3 |
| UX 流程分析 | ~15 | 4 | 6 | 3 | 2 |
| **合计** | **~40** | **8** | **11** | **12** | **9** |

---

## 错误信息质量 — 综合 6/10

🔴 **CRITICAL**: 21 处 `detail=str(exc)` 在后端 API 层直接暴露 Python 异常给前端（`world/api.py:841`、`outline/api.py:80-85`、`context/api.py:345,363,382`、`imports/api.py:299,301,326,328` 等）
🔴 **HIGH**: ~50+ 处 `err.message || "未知错误"` 保底，无按错误类型的分类消息
🟡 MEDIUM: 错误仅 Toast 5s 自动消失，无持久化；warning/error 视觉差异过小（仅左边框颜色）
⚪ LOW: 分隔符不一致（`：` vs `:`）、术语混用（`Scene` vs `scene` vs `场景`）
✅ 所有 `innerHTML` 错误有 `esc()` 转义
✅ `DomainError` 基类已定义但多数 API 未使用
✅ `errorLogger` 系统持久化到 localStorage、可追溯

---

## 用户反馈模式 — 6 个发现

🔴 **HIGH**: 确认按钮顺序违反 Mac 惯例（确认在左，取消在右）— `ui/modal.js:120-122`，每日使用影响
🟡 MEDIUM: Toast 不可手动关闭（无关闭按钮，必须等 5s 超时）
🟡 MEDIUM: 无声音反馈（后端任务失败无 Audio/Notification API）
🟡 MEDIUM: 无"不再提示"选项、无 ETA 显示
✅ 危险操作确认覆盖率良好、Toast 4 级类型完善
✅ 进度渲染器丰富（阶段/事件/门禁/duration_s）

---

## 加载/空/错误状态 — 13 个发现

🔴 **P1**: 项目列表（入口页面！）无 loading 状态、无错误回显 — `projectView.js:280-295` catch 块仅 `state.projects = []`，无 toast
🔴 **P1**: 骨架屏 CSS `.skeleton` + shimmer 动画已定义但 0 使用 — 5 个视图还在用纯文本 "加载中..."
🔴 **P1/2**: 大纲子视图错误静默吞掉 — `outlineView.js:207,218,229,240` 各列表 `.catch(() => { ... = [] })`，用户看到空状态而非错误
🟡 **P2**: worldView 搜索结果为空与初始为空不区分；generateView 无 loading 状态
🟡 **P2**: 后端连接状态无视图级保护（未禁用写操作按钮）
🟡 **P2**: LLM 服务不可用时无特定降级提示
✅ 空状态覆盖最完善（11/12 视图有）、RAG 检索空/错区分优秀

---

## UX 流程分析 — 15 个发现

🔴 **P1 高**: 无通用撤销系统 — 所有删除为硬删除（章节、场景、剧情线、伏笔、揭示、世界对象），仅项目有回收站
🔴 **P1 高**: 核心流程无分步引导 — 创建→导入→提取→大纲→写作→发布 流程无进度指示或引导
🔴 **P1 高**: 无字段级验证，所有表单仅依赖 Toast 显示错误（`projectView.js:367`、`worldView.js`）
🔴 **P1 高**: 删除操作无"撤销"横幅（无 Gmail 式 undo bar）
🟡 **P2 中**: 模态框文本区无脏状态保护（取消/关闭时丢失输入）
🟡 **P2 中**: 生成中心 4 个子标签无渐进引导
🟡 **P2 中**: 发布被拒绝时无可操作的下一步说明
✅ `workflowProgress.js` 任务恢复架构优秀（localStorage 持久化 + 后台轮询）
✅ AutoSave 编辑器（beforeunload 保护 + localStorage 备份）

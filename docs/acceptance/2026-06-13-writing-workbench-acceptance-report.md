# 手工写作工作台用户路径 — 验收报告

**日期:** 2026-06-13  
**范围:** `backend/modules/writing`, `backend/modules/outline`, `backend/modules/rag`, `frontend-console/views/writingView.js`  
**目标:** 验证作者在 `/workbench/:projectId/writing` 中完成正文编辑、暂存、发布、版本历史、断章、Scene 树导航、右侧 Scene 卡联动、实体轻量查询和 AI 章节卡提取的完整路径。

---

## 1. 结论

**验收结果：通过。**

- 后端 `modules/writing` 与 `modules/outline` 全部测试通过（131 项）。
- 前端写作台 E2E 全部通过（12 项，含 conflict 专项）。
- 真实 LLM（deepseek-v4-flash）对 《诡秘之主 第一部》第 1-3 章提取，生成 **8 张 Scene 卡** 并持久化到 `scenes` 表。
- `make lint` 全通过。

---

## 2. 后端验收

### 2.1 测试命令与结果

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/backend
pytest modules/writing/tests modules/outline/tests -v
```

**结果:** `131 passed in 3.41s`

### 2.2 覆盖点

| 验收要求 | 对应测试 |
|---|---|
| Draft CRUD | `TestWritingDraftRepository`, `TestWritingDraftService`, `TestWritingFacade` |
| 版本号自增 | `test_create_auto_increment_version`, `test_publish_draft_increments_version_and_enqueues_task` |
| 发布任务入队 (publish_chapter / RAG 索引) | `test_publish_creates_rag_chunks`, `test_publish_draft_increments_version_and_enqueues_task` |
| 断章映射，不触发 RAG | `test_split_chapter_at_offset_creates_new_chapter_without_publish_task`, `test_split_chapter_at_offset_syncs_scene_chunks` |
| 409 expected_version 冲突 | `test_update_draft_conflict_detection`, `test_update_draft_conflict_returns_409` |
| AI 提取生成 Scene 卡 | `test_generate_creates_scenes` |

### 2.3 关键提交

- `51ce2de` — test(writing): verify acceptance requirements for 手工写作工作台
- `97a83fc` — feat(outline): AI 剧情结构生成器现在同时创建 Scene 卡

---

## 3. 前端 E2E 验收

### 3.1 测试命令与结果

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npx playwright test e2e/writing.spec.js e2e/writing-conflict.spec.js --reporter=list
```

**结果:** `12 passed (9.6s)`

### 3.2 覆盖点

| 验收要求 | 对应测试 |
|---|---|
| 空状态 / 新建章节 | `空状态显示新建章节按钮`, `新建章节并显示在章节树` |
| 暂存 (Ctrl+S / 按钮) | `编辑章节内容并暂存` |
| 发布 | `发布章节` |
| Scene 切换不丢内容 | `Scene 切换不丢失内容` |
| 版本历史查看与恢复 | `版本历史查看与恢复` |
| 断章 | `新 Scene 创建和断章更新左侧树` |
| 光标联动右侧 Scene 卡 | `光标位置联动右侧 Scene 卡面板` |
| AI 提取弹窗 | `AI 提取章节卡按钮和对话框` |
| localStorage 备份 | `离线恢复 — localStorage 后备内容` |
| 多 Tab 冲突 (删除 / 409) | `多 Tab 冲突检测 — 草稿被其他会话删除`, `409 冲突 — 其他会话已更新草稿版本` |

### 3.3 关键提交

- `83f8803` — test(frontend): strengthen writing localStorage backup E2E test

---

## 4. 真实 LLM 验收 — 《诡秘之主 第一部》第 1-3 章

### 4.1 运行方式

- 脚本: `backend/scripts/acceptance_writing_extraction.py`
- 模型: `deepseek-v4-flash` @ `https://api.deepseek.com`
- 数据来源: `backend/tests/e2e/samples/lotm_chapters_1_2_3.txt`
- 调用链路: 直接调用 `PlotStructureGenerator.generate()`（未 mock），加载真实章节正文后生成剧情结构并持久化。

### 4.2 结果统计

- **项目 ID:** `6bdf28c6-06ef-44ca-a39f-ef5d08c7ca58`
- **章节范围:** 第 1-3 章
- **PlotThread 生成:** 3 条
- **OutlineArc 生成:** 1 个
- **Scene 卡生成:** **8 张**
- **scenes 表总记录:** 9（1 张历史 + 8 张本次生成）

### 4.3 生成 Scene 卡清单

| scene_index | title | narrative_tag |
|---|---|---|
| 0 | 穿越初醒 | hook |
| 1 | 绯红月下苏醒 | intro_dreamland |
| 2 | 镜中伤口 | intro_wound |
| 3 | 煤气灯与清洁 | explore_room |
| 4 | 确认自杀 | investigation |
| 5 | 转运仪式回忆 | flashback |
| 6 | 妹妹梅丽莎 | domestic |
| 7 | 早餐与叮嘱 | morning_routine |
| 8 | 独自准备仪式 | resolve |

### 4.4 关键字段示例

**Scene 1: 绯红月下苏醒**

- **goal:** 建立穿越设定，展示主角异变和异常环境
- **core_conflict:** 主角努力清醒 vs 身体的剧痛和陌生环境
- **emotional_beat:** 混乱、惊恐、逐渐冷静
- **must_happen:** 主角头痛苏醒，看到绯红月亮、左轮手枪、笔记本，确认穿越
- **must_not_happen:** 主角立刻完全冷静或接受穿越
- **narrative_tag:** intro_dreamland

完整字段详见 `docs/acceptance/writing-extraction-lotm-ch1-3-20260613-100741.md`。

### 4.5 关键提交

- `230f5a8` — feat(acceptance): real LLM writing extraction for LOTM chapters 1-3
- `97a83fc` — feat(outline): AI 剧情结构生成器现在同时创建 Scene 卡

---

## 5. Lint 与代码质量

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist
make lint
```

**结果:** 全部通过。

---

## 6. 发现与修复的缺口

1. **AI 提取未生成 Scene 卡（已修复）**
   - 原 `PlotStructureGenerator.generate()` 只生成 PlotThread / OutlineArc / ForeshadowingPlan / RevealPlan。
   - 已扩展 `_GenerationOutput` 增加 `scenes`，在 LLM prompt 中要求输出 Scene 卡字段（goal / core_conflict / emotional_beat / must_happen / must_not_happen / narrative_tag），并持久化到 `scenes` 表。
   - 更新 `PlotStructureGenerateResponse` 返回 `total_scenes` 与 `scenes`。

2. **localStorage 备份 E2E 偏弱（已加强）**
   - 原测试仅验证编辑器可见。
   - 已加强为注入备份后触发恢复逻辑，断言编辑器内容与标题被正确恢复。

3. **writing 模块部分验收点缺少端到端断言（已补充）**
   - 补充 `test_publish_draft_increments_version_and_enqueues_task` 验证版本号自增与任务入队。
   - 补充 `test_update_draft_conflict_returns_409` 验证 API 层 409。
   - 补充 split 测试中断言不触发 `AsyncTask` 的断言。

---

## 7. 签核

- [x] 后端单元/集成测试通过
- [x] 前端 E2E 测试通过
- [x] 真实 LLM 提取验收完成并记录
- [x] Lint 通过
- [x] 相关文档已更新

**验收人:** Kimi Code Agent  
**日期:** 2026-06-13

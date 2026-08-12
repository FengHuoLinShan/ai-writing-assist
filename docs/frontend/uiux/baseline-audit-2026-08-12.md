# 视觉基线审计报告（2026-08-12）

关联 spec：docs/superpowers/specs/2026-08-12-visual-baseline-reestablish-design.md
分支：codex/uiux-global-layer

## 基线事实

- 49 张视觉基线快照最后一次更新为 `724f802ca`（2026-08-04，main 上的提交）；
  `git merge-base --is-ancestor` 确认快照提交是 origin/main 的祖先，
  即**全部快照生成于 codex 六个 commit 之前**。
- 因此 `npm run test:e2e:visual` 的 diff = codex 全局层改动（G1/G2/G3）引入的视觉变化总量，
  既是回归检测面，也是本次「被破坏美感」的主要嫌疑面。
- 全局焦点环机制：`editorial-theme.css:163-166` 使用 `outline`（非 box-shadow），
  选择器为 `:where(button, input, select, textarea, [tabindex]):focus-visible`，
  contenteditable（如 `.novel-editor`）不在其内，属已知疑点，Task 2 G2 核实。

## 全局层发现

- [G1] token 别名迁移 — **合规**。pre-G1 `styles.css` 中 `--bg`/`--text` 等兼容别名已是
  转发形式（`--bg: var(--bg-base)`），G1 仅将其上移至 editorial 层，有效值前后一致，
  无色值漂移。三套死色板（style-a/b/c 原型值）删除后无残留引用失去定义（抽查 29 个
  token，def≥1）。
- [G2-1] **违规（修代码）**：写作稿纸编辑器焦点指示完全消失。链条：
  `styles.css:1911` `.novel-editor:focus { outline: none }`（特异度 0-2-0）杀掉
  全局朱红环；`writing-desk.css:209-211` `.writing-sheet .novel-editor:focus
  { box-shadow: none }`（0-3-0）再杀掉替代辉光；desk 层 `border: 0` 使
  `border-color` 变化也无效。`.novel-editor` 是 `<textarea>`（WritingEditor.vue:73-82），
  键盘用户完全失去焦点反馈。pages/writing.md §8.7 明确要求朱红环不被 desk 层覆写。
- [G2-2] 其余 14 处 `outline: none/0` — **合规**。`:focus` 规则均有替代焦点样式
  （accent-glow 辉光 / 朱红边）；基础规则特异度与全局环持平但 styles.css 先加载，
  全局环（editorial-theme.css:163）胜出。
- [G3] 朱红白名单 — **合规**。`--archive-red` 使用全部收敛于 editorial-theme.css，
  业务 vue/js/styles.css 零引用（soft 变体除外）。
- [G4-1] 新增阴影 — **合规**。codex diff 唯一新增 `box-shadow` 在 `#theme-menu`
  （浮层），符合「阴影只用于浮层」。
- [G4-2] **留债（审美确认）**：G2 收编 GenerateView 非 scoped 样式时带入直写像素
  （`padding: 4px 8px`、`9px 12px`、`gap: 12px` 等，styles.css `.generate-*` 区块），
  未归 `--space-*` token。等值 token 化不改变视觉，建议 Task 7 一并确认。
- [G5] 断点 — **合规**。残留 `600px`（×2）与 `900px`（×4）媒体查询均有
  「局部组件自适应断点保留」加注，符合 design-standard §6。
- [G6] 布局占比与 !important — **合规**。`--workspace-main-share: 64fr` 保持；
  `!important` 存量 styles.css 15 + editorial-theme.css 5，与 G2 完成后持平，无新增。

## 页面层发现

10 页契约（#id / data-action / role / 可访问名称）经逐页核实：**契约钩子零缺失、零改名**
（today 页 `data-action="switch-project"` 缺失为文档自认的新增契约，尚未到引入时点）。
各页 §2 已知问题复核属实，不重复计为发现。新发现如下：

- [P-world-1] `vue/views/world/WorldView.vue:34,38` — `.world-object-view-toggle` /
  `.world-discovery-mode-toggle` 的 `aria-label` 挂在无 role 的 `<span>` 上，
  §7.3 契约 role="group" 未满足 — **修代码**（补 role="group"）。
- [P-touch-1] `editorial-theme.css:1321-1325`（≤760px 档）`.btn-sm`/`.btn-icon`
  min-height 38px；`:1344-1349` `.generate-subtabs .generate-subtab` 等共享 tab 规则
  min-height 40px — 低于 design-standard「触控档按钮 ≥42px」（合并 generate-19/20、
  settings-19 三处报告）— **修代码**（38/40 → 42）。
- [P-project-24] `styles.css:4977-4979,5005-5007,5022-5024` — project 页 760/460 档
  按钮 min-height 40px < 42px — **修代码**。
- [P-rp-21] `styles.css:13041-13046` — RP 消息操作钮 padding 5px 7px + 11px 字 ≈23px 高，
  移动档低于 ≥42px — **修代码**（移动档补 min-height）。
- [P-generate-21] `styles.css:241,14297` — `.topbar-generate-note` 死规则（模板/JS 零引用） —
  **修代码**（删除两条规则）。
- [P-outline-scene-5] 文档契约写 `mark-reviewed-arc|thread`，实现为
  `mark-arc-reviewed|mark-thread-reviewed`（词序相反），无 e2e 引用该钩子 —
  **修文档**（改 pages/outline-scene.md 拼写，不动代码钩子）。
- [P-world-2] pages/world.md §7.1 简写 `#relation-review-final-type` 等有歧义，
  实际 id 为 `#relation-final-type`，e2e 与实现一致 — **修文档**。
- [P-doc-drift] today/world/outline-scene/map/rag/project/settings/rp-experience 多份
  页面文档的 styles.css 行号与断点描述已漂移（600→760 合并后文档滞后）— 留 Task 8
  docs-check 统一处理。
- [P-走查] 各页 390px 溢出、dark 主题细节、骨架/reduced-motion 实际观感 — 转 Task 7 走查。

## 快照回归分诊

第一轮（14 失败 / 15）：6 个为 spec 漂移（非视觉回归），8 个为像素 diff。

**spec 漂移修复**（本分支出品，对齐当前产品事实）：

- visual-project-rag 项目页：首页已变为作者/RP 入口选择页，补「我是作家」入口点击。
- visual-project-rag rag 状态页：`nav-status` 断言移除（rag.md §2-1/3 已记录产品缺口，
  status 子页无常设 subnav 入口），改断言 `#rag-diagnostics` 可见。
- visual-settings：标题「账户设置→账户与模型连接」「项目设置→项目偏好」、
  tab「深度导入→高级导入」、删除失效 mask `.projects-using-list`（对应列表已随重构移除）。
- visual-world 对象库：默认「最近相关」发现模式渲染卡片，断言改为 `.world-object-card[data-id]` ×4。
- visual-writing 专注模式：按钮文案「聚焦模式→进入专注」（pages/writing.md §2-4 记录的测试债关闭）。

**像素 diff 分诊**（expected/actual/diff 三图逐张过目，minimal 主题）：

| 快照 | 裁决 | 说明 |
|---|---|---|
| writing-desk-minimal | 预期变化 | 侧栏加宽 + 工具栏重构 + 文案本地化；顶部深色块新旧基线均存在（既有元素） |
| writing-mobile-390-minimal | 预期变化 | 390px 无横向溢出，稿纸形态完整 |
| outline-threads-minimal | 预期变化 | 导航重构 + tab 文案演进 + 信息推进区去装饰 |
| outline-arcs-minimal | 预期变化 | 同上；另发现术语混排与行排序变化（转 Task 7） |
| outline-story-outline-minimal | 预期变化 | 导航重构 + 文案演进 |
| rag-search-minimal | 预期变化 | 导航重构；面包屑「查找 · 查找」重复（转 Task 7） |
| world-review-objects-minimal | 预期变化 | 导航重构 + 文案演进；表格对齐正常 |
| world-bible-minimal | 预期变化 | 导航重构；标题两字折行（转 Task 7） |

warm/dark 主题与剩余快照待第二轮（spec 修复后）跑到对应断言后补充分诊。

## 美感微调清单

（来自 Task 2 G4-2 与 Task 6 分诊，逐项待用户确认）

- [A1] outline 剧情线「信息推进」区：描述行紧贴标题、折叠组行间无呼吸感，
  建议加 4–8px 间距（归 `--space-1`/`--space-2`）。
- [A2] outline 篇章：tab 已改名「篇章」，但「共 2 个 · 视觉基线篇章纲」
  「0 篇章纲已选」仍用旧词「篇章纲」，新旧术语混排。
- [A3] outline 篇章：默认行顺序与旧基线相比发生变化（第二卷排到第一卷前），
  疑似排序逻辑行为变化，需确认是否有意。
- [A4] rag 检索页：面包屑「视觉基线检索 · 查找 · 查找」末两段同词重复。
- [A5] world 世界书：「世界基本背景」标题两字折行 + 操作按钮折成两行，头部拥挤。
- [A6] world 页签「需要处理 0」计数与文字间距偏大，确认是否设计意图。
- [A7]（G4-2 转入）styles.css `.generate-*` 区块直写像素等值 token 化
  （`gap: 12px → var(--space-3)` 等），不改变视觉。

## 修复记录

- [G2-1] `writing-desk.css` 为 `.writing-sheet .novel-editor` 补 `:focus-visible` 朱红环
  （2px `--archive-red`），并在 `tests/editorialTheme.test.js` 加契约断言；
  vitest 163 文件 / 1799 用例全绿。commit `a95be2867`。
- [P-world-1] `WorldView.vue` 两个切换组补 `role="group"`。
- [P-touch-1] 触控档（≤760px）触控目标统一到标：`editorial-theme.css`
  `.btn-sm/.btn-icon/.action-menu-btn` 38→42、`.subnav-item` 等共享 tab 40→42；
  `styles.css` 连带修正同违规类：`project-card/hero/bulk` 三处 40→42、
  rail summary 38→42、390px 档按钮组 40→42（min-width 同步）、
  `.novel-search-panel` 拆分按钮 42 / 输入 44、`.writing-version-diff-swap` 38→42、
  `.rp-mode-toggle` 40→42、`.world-attention-menu__panel button` 补 ≤760px 42 覆写、
  `.rp-message__actions button` 补 ≤760px min-height 42。
- [P-generate-21] 删除 `.topbar-generate-note` 死规则两条（定义 + 900px 隐藏选择器）。
- [P-outline-scene-5] 修文档：`mark-reviewed` → 实现实际拼写 `mark-arc-reviewed/mark-thread-reviewed`。
- [P-world-2] 修文档：world.md §7.1 关系定稿 id 简写改为显式 `#relation-final-*` 形式。
- vitest 全绿（163/1799）；e2e core 子集结果见 `## 最终验证`。
- [A1] `styles.css` 新增 `.outline-information-*` 节奏样式（该区块此前全仓零样式）。
- [A2] 篇章术语统一：outline 模块 UI 文案「篇章纲→篇章」全量替换（6 个源文件 +
  2 个 e2e/2 个 vitest 同步），对齐 pages/outline-scene.md 目标术语。
- [A3] 篇章行排序核查结论：后端 `order_by(arc_index, id)`，`arc_index` 可空且手动创建
  不赋值，NULL 时落到 UUID `id` → 顺序随机。**非本次分支引入，非有意变更**，
  属潜在产品问题（建议另行立项：arc_index 兜底或 created_at 次级排序），本次不动后端。
- [A4] `Topbar.vue` 子视图标题与模块同名时隐藏子段（消除「查找 · 查找」重复面包屑）。
- [A5] `.world-bible-panel__header` 加 `flex-wrap`，h2 加 `word-break: keep-all`，
  消除「世界基本背/景」两字折行。
- [A6] world 页签「需要处理 N」为标准 `.badge` 计数芯片（mono 字体+padding），
  判定为设计意图，未改动。
- [A7] `styles.css` `.generate-*` 区块直写像素等值 token 化（28 处 gap/padding/margin
  归 `--space-*`，非 4px 基数与尺寸类值保留），零视觉变化。
- [W1] 移动端底部导航「只剩首页」：根因是 `#nav-list { display:flex }`（id 特异度 1-0-0）
  压过 ≤760px 媒体查询里 `.sidebar-desktop-nav { display:none }`（0-1-0），桌面导航溢出
  覆盖移动底栏。修复：媒体查询选择器改为 `#nav-list`；底栏按钮颜色从 `--text-tertiary`
  提至 `--text-secondary`（自绘浅底）。属 main 既有缺陷（e98fb361a 引入），本次顺手修复。
- [W2] dark 主题章节列表字数元数据几乎不可读：`.chapter-row__meta` 补
  `color: var(--text-secondary)`。
- [W3] settings 齿轮装饰连接线横穿「系统默认 关闭」文字：实为 `::after` 蓝图线段
  （40% 35% 横线）；mask-image 在该伪元素上计算但不参与渲染（原因未查明），
  改用 `clip-path: inset(0 0 0 40%)` 硬裁，线段恰从节点圆点起笔，观感自然。
- [W4] world 世界书右栏英文 label「Activation Profile」→「生效规则集」
  （#bible-activation-profile id 不动，e2e 无影响）。
- [W5]（已修复）dark 主题禁用态批量按钮沿用浅灰底：dark 下 `--archive-ink` 反相为浅色，
  `.btn-primary`/`.btn-fab` 禁用后仅靠 opacity 0.48 压暗，视觉上是浅灰 slab。
  修复：`[data-theme="dark"] .btn:disabled` 统一回归中性纸面
  （`--archive-paper-raised` 底 + `--archive-rule` 边 + `--archive-ink-soft` 字），
  `.btn-text` 保持透明例外；`.rp-send-button:disabled` 硬编码 `#d9dee7` 增加 dark 覆盖
  （`--rp-accent-soft` 底 + `--rp-dim` 字）。editorialTheme.test.js 新增契约断言。
  RP 顶栏 mono 装饰字对比度偏低仍为观察项，记录在案。
- [W6]（测试修复）visual-writing 移动用例移除冗余的 applyTheme 点击（beforeEach 已重置为
  minimal），消除主题菜单操作导致的底栏渲染干扰。

## 最终验证

- `npm run test`（vitest，含 editorialTheme/typographyTokens 契约）：163 文件 / 1799 用例全绿。
- `test:e2e:core`（home/project/world/outline-scenes/writing）：63 全绿；
  `test:e2e:smoke`（home/project/import/writing）：47 全绿（微调全部落地后）。
- `test:e2e:visual` 干净复跑：14/14 全绿（outline 3 + project-rag 3 + settings 2 + world 3 + writing 3）。
- 基线快照 40 张重建（5 组 spec × minimal/warm/dark + writing focus/mobile），
  minimal 全组 + warm/dark 全组均经逐张人工过目（分诊与走查记录见上文）。
- `make docs-check BASE_REF=origin/main`：通过（页面文档行号漂移为既有现象，见 P-doc-drift）。
- 遗留观察项：W5 的 dark 禁用按钮浅底已修复（见 W5 条目），RP 装饰字对比度记录在案未改；
  A3（arc_index 为空时篇章排序随机）为后端潜在产品问题，建议另行立项。

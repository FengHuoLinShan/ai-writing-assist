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

（待 Task 6）

## 美感微调清单

（待 Task 7）

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

## 最终验证

（待 Task 8）

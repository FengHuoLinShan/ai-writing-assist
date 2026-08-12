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

（待 Task 4）

## 快照回归分诊

（待 Task 6）

## 美感微调清单

（待 Task 7）

## 修复记录

- [G2-1] `writing-desk.css` 为 `.writing-sheet .novel-editor` 补 `:focus-visible` 朱红环
  （2px `--archive-red`），并在 `tests/editorialTheme.test.js` 加契约断言；
  vitest 163 文件 / 1799 用例全绿。commit 见本节后记。

## 最终验证

（待 Task 8）

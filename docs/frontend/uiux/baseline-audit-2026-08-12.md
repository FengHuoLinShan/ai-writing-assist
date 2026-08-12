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

（待 Task 2）

## 页面层发现

（待 Task 4）

## 快照回归分诊

（待 Task 6）

## 美感微调清单

（待 Task 7）

## 修复记录

（随修复 Task 更新）

## 最终验证

（待 Task 8）

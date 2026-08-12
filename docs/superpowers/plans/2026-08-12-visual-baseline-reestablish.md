# 视觉基线重确立实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对照 `docs/frontend/uiux/` 权威规范审计 codex 六个 commit 后的全局层与全部页面，修复被破坏的视觉细节，重建 playwright 视觉基线快照。

**Architecture:** 三轨审计（静态 grep/diff 审计 → 视觉快照回归 → 逐页人审美感走查），修复按裁决表执行，最后全量验证并逐张过目重建基线。审计发现与裁决记录沉淀在 `docs/frontend/uiux/baseline-audit-2026-08-12.md`。

**Tech Stack:** CSS tokens（`editorial-theme.css` / `styles.css`）、Vue 3 SFC、vitest 契约测试、playwright 视觉回归（chromium 1440×900，三主题 + 390px）。

## Global Constraints

- 权威规范：`docs/frontend/uiux/design-standard.md` + `docs/frontend/uiux/pages/*.md`（10 份），冲突一律以文档为准修代码。
- 文档未覆盖的审美微调：逐项列出，经用户确认后才动手。
- e2e DOM 契约（#id / data-action / 可访问名称）不动；万不得已要动必须同步更新 e2e。
- 不动 RP 沉浸路径的蓝色系 token（`--rp-accent` 等，规范明确保留为第二外观）。
- 不顺手做无关重构；新触碰代码不得直写像素（归 `--space-*`），不得新增 `!important`。
- 工作树既有无关脏文件（`docs/README.md` 一行改动、未跟踪 worldbook 计划文档）保持不动，不进任何 commit。
- 分支：沿用 `codex/uiux-global-layer`，不新建。
- 已确认事实：49 张基线快照均为 codex 六个 commit **之前**生成（`git diff --stat origin/main...HEAD -- frontend-console/e2e` 仅 `writing.spec.js` 1 行变化），因此 visual diff = codex 改动引入的全部视觉差异。
- 已确认事实：全局焦点环是 `outline`（`editorial-theme.css:163-166`，`:where(button, input, select, textarea, [tabindex]):focus-visible { outline: 2px solid var(--archive-red); outline-offset: 2px; }`），contenteditable（如 `.novel-editor`）不在该选择器内，是已知疑点。

---

### Task 1: 审计报告骨架与基线事实确认

**Files:**
- Create: `docs/frontend/uiux/baseline-audit-2026-08-12.md`

**Interfaces:**
- Consumes: 无
- Produces: 审计报告文件，后续 Task 2/4/6/7 各自向其追加「发现清单」小节；报告小节固定为：`## 基线事实`、`## 全局层发现`、`## 页面层发现`、`## 快照回归分诊`、`## 美感微调清单`、`## 修复记录`、`## 最终验证`。

- [ ] **Step 1: 创建报告骨架**

写入 `docs/frontend/uiux/baseline-audit-2026-08-12.md`，内容：

```markdown
# 视觉基线审计报告（2026-08-12）

关联 spec：docs/superpowers/specs/2026-08-12-visual-baseline-reestablish-design.md
分支：codex/uiux-global-layer

## 基线事实

（Task 1 Step 2 填入）

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
```

- [ ] **Step 2: 确认并记录快照 provenance**

Run:

```bash
git log --oneline -3 --format='%h %ad %s' --date=short -- 'frontend-console/e2e/visual-outline.spec.js-snapshots' 'frontend-console/e2e/visual-writing.spec.js-snapshots' 'frontend-console/e2e/visual-world.spec.js-snapshots' 'frontend-console/e2e/visual-project-rag.spec.js-snapshots' 'frontend-console/e2e/visual-settings.spec.js-snapshots'
git merge-base --is-ancestor $(git log -1 --format=%H -- 'frontend-console/e2e/visual-writing.spec.js-snapshots') origin/main && echo "snapshots predate codex branch"
```

Expected: 最后一行输出 `snapshots predate codex branch`。把两条命令的结论写入报告 `## 基线事实`：快照全部来自 main（codex 改动前），visual diff 代表 codex 引入的视觉变化总量。

- [ ] **Step 3: Commit**

```bash
git add docs/frontend/uiux/baseline-audit-2026-08-12.md
git commit -m "docs(uiux): 视觉基线审计报告骨架与快照 provenance 确认"
```

---

### Task 2: 全局层静态审计（7 项检查）

**Files:**
- Modify: `docs/frontend/uiux/baseline-audit-2026-08-12.md`（追加 `## 全局层发现`）
- Read: `frontend-console/editorial-theme.css`、`frontend-console/styles.css`、`docs/frontend/uiux/design-standard.md`

**Interfaces:**
- Consumes: Task 1 的报告文件
- Produces: 全局层发现清单，每条格式：`[G-n] <文件:行> — <违规描述> — 裁决:修代码|审美确认|文档有误|合规`。Task 3 按此清单修复。

- [ ] **Step 1: G1 — token 别名迁移色值漂移**

Run: `git show 2e8129399 -- frontend-console/styles.css | grep '^-' | grep -E '#[0-9a-fA-F]{3,8}|rgb' | sort -u`

逐条核对：被删除的旧色值是否在 `editorial-theme.css` 中存在值完全相等的 token 承接。任何「旧值无等价新值」的记录为发现。

- [ ] **Step 2: G2 — 焦点环完整性**

Run:

```bash
grep -rn --include='*.css' -E 'outline:\s*(none|0)' frontend-console/ | grep -v node_modules
grep -rn --include='*.css' -B2 'box-shadow:\s*none' frontend-console/ | grep -A2 ':focus' | grep -v focus-visible
```

核对：(a) 每条 `outline: none/0` 是否有配套 `:focus-visible` 恢复规则；(b) `.writing-sheet .novel-editor:focus { box-shadow: none }`（`vue/views/writing/writing-desk.css:209-211`）——确认 `.novel-editor` 是否 contenteditable 且无 tabindex（在 `vue/views/writing/` 下 grep `novel-editor` 的模板用法），若是则全局焦点环不覆盖它，记为发现（裁决：修代码，为该编辑器补 `:focus-visible` outline 或确认刻意设计）。

- [ ] **Step 3: G3 — 朱红白名单**

Run: `grep -rn --include='*.css' --include='*.vue' 'archive-red' frontend-console/ | grep -v node_modules | grep -v 'editorial-theme.css'`

对照 design-standard 白名单（主按钮 focus 环、待处理计数、危险语义、索引点缀、每屏至多一个 primary），名单外使用记为发现。

- [ ] **Step 4: G4 — 静态卡片阴影与直写像素**

Run:

```bash
grep -rn --include='*.vue' -E '(padding|margin|gap|top|left|width|height):\s*[0-9]+px' frontend-console/vue/ | grep -v -E ':\s*(0|1px|42px|44px)' | head -50
git diff origin/main...HEAD --stat -- '*.css' '*.vue'
```

对 diff 中新增/修改的 CSS 块逐一核对：静态卡片不得有 `box-shadow`（hairline + paper-raised 除外语境）；新触碰代码不得直写像素（1px hairline、≥42/44px 触控目标除外）。

- [ ] **Step 5: G5 — 断点残留**

Run: `grep -rn --include='*.css' --include='*.js' --include='*.vue' -E '(720|600|1180)px' frontend-console/ | grep -v node_modules | grep -v dist`

760/1100 之外的布局断点残留记为发现（注释说明用途的除外）。

- [ ] **Step 6: G6 — 工作台主对象占比与 !important 存量**

Run:

```bash
grep -n 'workspace-main-share\|64fr' frontend-console/styles.css
grep -c '!important' frontend-console/styles.css frontend-console/editorial-theme.css
git show 74feb4f79 --stat | tail -3
```

核对 64–68% 占比未回退；`!important` 总数不得高于 G2 commit（`74feb4f79`）完成后的存量（对比 `git show 74feb4f79:frontend-console/styles.css | grep -c '!important'`）。

- [ ] **Step 7: G7 — 汇总写入报告**

把 Step 1–6 的发现按 `[G-n]` 格式写入报告 `## 全局层发现`；无发现的检查项也记录「合规」。

- [ ] **Step 8: Commit**

```bash
git add docs/frontend/uiux/baseline-audit-2026-08-12.md
git commit -m "docs(uiux): 全局层静态审计发现（7 项检查）"
```

---

### Task 3: 修复全局层硬违规

**Files:**
- Modify: `docs/frontend/uiux/baseline-audit-2026-08-12.md`（`## 修复记录`）
- Modify（按发现）: `frontend-console/editorial-theme.css`、`frontend-console/styles.css`、`frontend-console/vue/views/writing/writing-desk.css`
- Test: `frontend-console/tests/editorialTheme.test.js`、`frontend-console/tests/typographyTokens.test.js`

**Interfaces:**
- Consumes: Task 2 的 `## 全局层发现` 清单
- Produces: 修复后的全局层 CSS；`## 修复记录` 中每条发现一行：`[G-n] <修复方式> <commit-sha>`。可机械锁定的违规类别在 vitest 契约测试中新增断言（见 Step 2）。

- [ ] **Step 1: 逐条修复裁决为「修代码」的发现**

每条发现的最小修复原则：对齐 design-standard 原文值；不改 DOM 契约；审美类条目跳过（留给 Task 7 用户确认）。
已知高概率项的预设修复（若 Task 2 证实）：`.novel-editor` 若为 contenteditable 无 tabindex，在 `writing-desk.css:209` 附近补：

```css
.writing-sheet .novel-editor:focus-visible {
  outline: 2px solid var(--archive-red);
  outline-offset: 2px;
}
```

（若走查确认写作区刻意无环，则改记「审美确认」走 Task 7。）

- [ ] **Step 2: 可机械锁定的违规补契约测试**

仅当某类违规可被静态断言锁定时，在 `frontend-console/tests/editorialTheme.test.js` 追加用例（仿照该文件现有读取 CSS 文本做断言的模式）。例如焦点环修复后：

```js
it("writing editor keeps a visible focus ring", () => {
  const desk = read("vue/views/writing/writing-desk.css")
  expect(desk).toMatch(/\.novel-editor:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--archive-red\)/)
})
```

（`read` 以该测试文件现有的文件读取 helper 为准；若不存在等价 helper 则按文件内现有写法读取。）不可机械锁定的发现不强行写测试。

- [ ] **Step 3: 跑 vitest**

Run: `cd frontend-console && npm run test`
Expected: 全绿（含新增断言）。

- [ ] **Step 4: 更新报告修复记录并 Commit**

```bash
git add -u frontend-console docs/frontend/uiux/baseline-audit-2026-08-12.md
git commit -m "fix(uiux): 全局层视觉违规修复（对齐 design-standard）"
```

---

### Task 4: 页面层契约审计（10 页）

**Files:**
- Modify: `docs/frontend/uiux/baseline-audit-2026-08-12.md`（追加 `## 页面层发现`）
- Read: `docs/frontend/uiux/pages/*.md`（today/writing/world/outline-scene/map/rag/generate/project/settings/rp-experience）

**Interfaces:**
- Consumes: Task 1 报告
- Produces: 页面层发现清单，格式：`[P-<page>-n] <文件:行> — <描述> — 裁决:...`。Task 5 按此修复。

- [ ] **Step 1: 逐页核对「必须保留的契约」**

对每份 page spec 中列出的每个 `#id` / `data-action` / 可访问名称：

```bash
grep -rn '<id 或 data-action 值>' frontend-console/vue/ frontend-console/*.js | grep -v node_modules
```

缺失或被改名的记为发现（此类多属 e2e 契约破坏，最高优先）。

- [ ] **Step 2: 逐页核对「验收标准」中的视觉条目**

对每份 page spec 验收标准里的视觉要求（密度、层级、留白、主题表现），对照对应页面 CSS/SFC 静态核对；无法静态判定的标记「待 Task 7 走查确认」。

- [ ] **Step 3: 汇总写入报告并 Commit**

```bash
git add docs/frontend/uiux/baseline-audit-2026-08-12.md
git commit -m "docs(uiux): 页面层契约审计发现（10 页）"
```

---

### Task 5: 修复页面层硬违规

**Files:**
- Modify（按发现）: 相关页面 CSS/SFC
- Modify: `docs/frontend/uiux/baseline-audit-2026-08-12.md`（`## 修复记录`）

**Interfaces:**
- Consumes: Task 4 的 `## 页面层发现`
- Produces: 修复记录条目 `[P-<page>-n] <修复方式> <commit-sha>`

- [ ] **Step 1: 逐条修复「修代码」裁决的发现**

DOM 契约缺失优先恢复原名（而不是改 e2e），除非该改名是规范页面文档认可的终态。

- [ ] **Step 2: 跑受影响 e2e 子集**

Run: `cd frontend-console && npm run test:e2e:core`
Expected: 全绿。若修复涉及 writing/map，再跑 `npm run test:e2e:smoke` / `npm run test:e2e:map` 中对应子集。

- [ ] **Step 3: 跑 vitest 并 Commit**

```bash
cd frontend-console && npm run test
git add -u frontend-console docs/frontend/uiux/baseline-audit-2026-08-12.md
git commit -m "fix(uiux): 页面层视觉/契约违规修复"
```

---

### Task 6: 视觉快照回归与分诊

**Files:**
- Modify: `docs/frontend/uiux/baseline-audit-2026-08-12.md`（`## 快照回归分诊`）

**Interfaces:**
- Consumes: Task 3/5 修复后的代码
- Produces: 分诊表，每张 diff 图一行：`<快照名> — 差异描述 — 分诊:预期变化(规范执行正确结果)|被破坏(需修复)`。「被破坏」项转回 Task 3/5 流程修复后重跑本 Task。

- [ ] **Step 1: 跑全量视觉测试**

Run: `cd frontend-console && npm run test:e2e:visual`
（自动起 backend alembic+uvicorn 与 vite dev server；需本地环境可运行。起不来则记录降级：仅静态审计，报告中明确说明。）

- [ ] **Step 2: 逐张查看 diff**

失败用例的 diff 图在 `frontend-console/test-results/visual/` 下，用 ReadMediaFile 逐张查看 actual/expected/diff，按 Produces 格式分诊写入报告。

- [ ] **Step 3: 修复「被破坏」项并重跑**

修复后重跑 `npm run test:e2e:visual` 直至剩余失败全部分诊为「预期变化」。

- [ ] **Step 4: Commit**

```bash
git add docs/frontend/uiux/baseline-audit-2026-08-12.md
git commit -m "docs(uiux): 视觉快照回归分诊"
```

---

### Task 7: 人审美感走查与微调确认

**Files:**
- Modify: `docs/frontend/uiux/baseline-audit-2026-08-12.md`（`## 美感微调清单`）

**Interfaces:**
- Consumes: Task 6 之后的代码状态
- Produces: 美感微调清单，每项：`[A-n] <页面/主题> — <现状> — <建议微调>`，经用户逐项确认后才在 Task 8 执行。

- [ ] **Step 1: 逐页截图走查**

用 playwright 对 10 个规范页面 × minimal/warm/dark（关键页加 390px）截图（可复用 visual spec 的页面到达路径，临时脚本放 `frontend-console/e2e/helpers/` 之外、不入库，或直接 `npx playwright screenshot`）。截图存 `tmp/visual-audit-2026-08-12/`（仓库 tmp/ 目录，不提交），用 ReadMediaFile 逐张审。

- [ ] **Step 2: 记录美感问题**

重点对照 design-standard 反模式清单（Card 套 Card、Badge 泛滥、标题装饰 icon、密度失衡）与「codex 破坏美感」的典型嫌疑（对齐、间距节奏、层级对比、主题下对比度）。文档未覆盖的微调全部进清单，不直接改。

- [ ] **Step 3: 用户逐项确认**

用 AskUserQuestion 把清单分批（每批 ≤4 项）提交用户确认：批准 / 调整 / 放弃。确认结果写回报告。

- [ ] **Step 4: Commit**

```bash
git add docs/frontend/uiux/baseline-audit-2026-08-12.md
git commit -m "docs(uiux): 美感走查清单与用户确认结果"
```

---

### Task 8: 微调执行、全量验证与基线重建

**Files:**
- Modify（按批准的微调）: 相关 CSS/SFC
- Modify: `frontend-console/e2e/visual-*.spec.js-snapshots/*.png`（重建基线）
- Modify: `docs/frontend/uiux/baseline-audit-2026-08-12.md`（`## 最终验证`）

**Interfaces:**
- Consumes: Task 7 用户批准的微调项
- Produces: 新视觉基线快照 49 张；报告 `## 最终验证` 记录全部命令与结果。

- [ ] **Step 1: 执行批准的审美微调**

每项微调最小改动，遵守 Global Constraints（不直写像素、不加 `!important`、不动 DOM 契约）。

- [ ] **Step 2: 全量验证**

Run（按序，全部全绿才进 Step 3）:

```bash
cd frontend-console && npm run test
cd frontend-console && npm run test:e2e:visual
cd frontend-console && npm run test:e2e:core
```

- [ ] **Step 3: 重建基线并逐张过目**

Run: `cd frontend-console && npm run test:e2e:visual:update`
然后 `git status --short frontend-console/e2e/ | grep -c snapshot` 统计变更快照数，用 ReadMediaFile **逐张**过目变更的 PNG（新旧对比用 `git diff` 无法看图，以分诊表 + 新图过目为准），任何一张不符合预期都回 Step 1 修正，禁止批量盲提交。

- [ ] **Step 4: docs-check 与文档同步**

Run: `make docs-check BASE_REF=origin/main`
按输出更新受影响文档或在报告中逐项说明无影响原因。

- [ ] **Step 5: 写入最终验证并 Commit**

```bash
git add -u frontend-console docs/frontend/uiux/baseline-audit-2026-08-12.md
git commit -m "fix(uiux): 审美微调与视觉基线重建（逐张过目）"
```

---

## Self-Review 记录

- Spec 覆盖：五阶段 → Task 2/3（阶段1）、Task 4/5（阶段2）、Task 6（阶段3）、Task 7（阶段4）、Task 8（阶段5）；裁决原则 → Global Constraints 与各 Task 修复步骤；交付物 → 报告文件 + 修复 commit + 快照 + 验证（Task 8）。无遗漏。
- 条件性说明：审计类任务的具体修复代码取决于发现，无法预先给出全部代码；已知高概率项（`.novel-editor` 焦点环）已给出预设修复代码。这是审计任务的固有限制，非占位符。

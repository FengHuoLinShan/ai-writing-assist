# 视觉基线重确立设计（Editorial Archive 提纯版收口）

日期：2026-08-12
分支：`codex/uiux-global-layer`（沿用，不新建）
状态：已获用户批准

## 背景

`docs/frontend/uiux/` 是全站唯一权威 UI/UX 规范（「Editorial Archive 提纯版」），
当前分支已按规范完成 G1（token 收敛）、G2（组件层收编）、G3（断点归一）六个 commit。
用户判断其中可能有细节被 codex 破坏美感，需要对照规范重新审计全局层与全部页面，
修复后重建 playwright 视觉基线（49 张快照）。

视觉基线代码：

- `frontend-console/editorial-theme.css` — 视觉表达唯一权威（颜色/圆角/阴影/线条 token，三主题）
- `frontend-console/styles.css` — 结构与排版层（字体、字阶、间距、缓动、布局尺寸）

验证机制：`frontend-console/playwright.visual.config.js` + `e2e/visual-*.spec.js`（5 份 spec，
三主题 + 390px 移动档），`tests/editorialTheme.test.js` / `typographyTokens.test.js`（vitest 契约）。

## 已确认的决策

- 范围：全局层 + 全部 10 个规范页面
- 裁决：design-standard 为准修代码；文档未覆盖的审美微调逐项经用户确认后执行
- 分支：沿用 `codex/uiux-global-layer`
- 路径：静态审计 + 快照回归 + 逐页人审 三轨并行

## 流程（五阶段）

### 阶段 1：全局层静态审计

对照 `design-standard.md` 硬约束审计 `editorial-theme.css` / `styles.css` 及 codex 六个
commit（`a76746321`、`2e8129399`、`caf03630b`、`74feb4f79`、`fc160c85c`、`9f2383b8b`）的 diff：

- token 别名迁移是否引入色值/字距漂移（旧别名与新值逐一比对）
- 全站 2px 朱红 focus-visible 环是否被 `:focus { box-shadow: none }` 类规则吃掉
  （已知疑点：`writing-desk.css:209-211`）
- `--archive-red` 使用点是否符合白名单（主按钮 focus 环、待处理计数、危险语义、索引点缀）
- 新触碰代码是否直写像素（须归 `--space-*`）
- 静态卡片是否违规使用阴影（只许 hairline + paper-raised）
- 760/1100 之外是否残留其他断点
- 工作台主对象 64–68% 占比是否保持
- `!important` 存量是否较 G2 后增加

### 阶段 2：页面层审计

10 份 `docs/frontend/uiux/pages/*.md`（today / writing / world / outline-scene / map / rag /
generate / project / settings / rp-experience）逐页核对「必须保留的契约」
（#id / data-action / 可访问名称）与「验收标准」。

### 阶段 3：快照回归

- 先确认 49 张基线快照是 codex 改动前还是之后生成（决定 diff 方向的意义）
- 跑 `npm run test:e2e:visual`，失败用例逐张查看 diff 图

### 阶段 4：人审美感走查

每页 × minimal/warm/dark 三主题（+ 390px 移动档）截图走查，输出美感问题清单。
文档未覆盖的审美微调逐项列出，用户确认后才执行。

### 阶段 5：修复与重建基线

修复 → vitest + 受影响 e2e + 视觉测试全绿 → 逐张人工过目后
`npm run test:e2e:visual:update` 重建基线 → `make docs-check BASE_REF=origin/main`。

## 修复裁决原则

1. 与文档硬约束冲突 → 直接修代码对齐文档
2. 文档未覆盖的审美微调 → 逐项列出，用户确认后执行
3. 有证据证明文档本身错误 → 改文档并在报告中说明理由
4. e2e DOM 契约（#id / data-action / 可访问名称）不动；万不得已要动时同步更新 e2e

## 交付物

- 审计报告：违规清单 + 每项的裁决与修复记录
- 修复 commit（沿用 `codex/uiux-global-layer`）
- 重建后的视觉基线快照（逐张过目，不批量盲更新）
- 验证全绿：vitest（含 token 契约）、受影响 e2e 子集、视觉测试、docs-check

## 风险与边界

- 视觉测试自动起 backend（alembic + uvicorn）+ 前端 dev server；本地起不来则降级为
  纯静态审计并明确说明
- 不顺手做无关重构；不动 RP 沉浸路径的蓝色系 token（规范明确保留为第二外观）
- 工作树既有无关脏文件（`docs/README.md`、未跟踪 worldbook 计划文档）保持不动

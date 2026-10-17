# R2 可理解性、状态与图表复核

基线：`22bb499789cba89fea92e918fd853ab768688e07`。复核对象是集成 worktree `/Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist` 中截至本记录的文档变更。只读检查；未访问业务模型、数据库、环境配置或私有稿件，也未运行测试。

## 已检查

- 规则与范围：`AGENTS.md`、`docs/plans/2026-10-14-codebase-documentation-refresh.md` 的 P4 和完成门禁。
- 导航、状态与用户指南：`README.md`、`docs/README.md`、`docs/architecture/README.md`、`docs/product/new-user-guide.md`、`docs/product/word-guide-source.md`。
- 架构图与新阅读入口：`docs/architecture/codebase-reading-guide.md`、`runtime-boundaries.drawio`、`runtime-boundaries.html`、`module-architecture.drawio`、`module-architecture.html`、`documentation-maintenance.md`、`architecture-documents.toml`。
- 关键来源：`docs/modules/22_evolution.md`、`docs/modules/23_local_agent.md`、`backend/modules/local_agent/README.md`、`backend/modules/interaction/tasks.py`、`backend/infrastructure/tasks/README.md`、`backend/modules/evolution/tests/test_world.py`。
- 范围账本：任务目录中的 `doc-disposition.csv`、`source-coverage.csv`、`inventory-summary.json`、`ledger-summary.json`。

## Findings

### 1. [P2，已修复] 图中把工作流重试压成“最多一次”

**位置：** `docs/architecture/runtime-boundaries.html:1`；配对图源 `docs/architecture/runtime-boundaries.drawio:1` 的 `limits` 节点。

**问题与影响：** HTML 旁注说“部分调用错误允许最多一次自动重试”，没有限定任务或重试层。当前 `interaction_summary_refresh` 已有两次 task attempt；每次 handler 又执行最多两次 `retry_with_backoff`，并允许一次格式修复，代码把 run 请求额度定为 8（`backend/modules/interaction/tasks.py:359-396`）。读者据此会误以为所有链路最多只重试一次；图源的旁注又没有 HTML 的数字上限，维护者只改图源时还会漏掉该承诺。

**最小修订：** 删除通用的“一次”上限，改为说明不同工作流分别冻结重试/请求预算，恢复按回执和预算核对；如需保留数字，标明具体任务与重试层，并同步到两份图。

**复核条件：** 用同一段图义逐项比对 Draw.io 节点和 HTML 旁注；确认不会把 task requeue、工作流内重试、格式修复混成一个全局次数，再对最终 HTML 重新渲染检查。

### 2. [P2，已修复] “8 次合成测试”没有说清 8 是调用数

**位置：** `docs/architecture/codebase-reading-guide.md:39`。

**问题与影响：** 这句可读成“有 8 个合成测试”。实际是一个合成用例 `test_relation_history_uses_real_prefix_and_not_mutated_world_rows`，在 scoped recompute 后断言累计 provider 调用仍为 8（`backend/modules/evolution/tests/test_world.py:1564-1680`）。专门模块页已写明“断言总调用数仍为 8”，并限制为固定关系历史输入的复用结论（`docs/modules/22_evolution.md:324-329`）；阅读指南的缩写丢了这层范围。

**最小修订：** 改成“该合成用例断言总 provider 调用数仍为 8，scoped recompute 未增加调用；只证明固定关系历史输入可复用”，并保留它不证明改稿失效行为的限定。

**复核条件：** 对照测试中的 `len(calls) == 8` 和模块页的输入范围，确认没有写成八个测试、八次重跑或文学/真实模型质量验收。

### 3. [P2，已修复] Local Agent 索引没有标明当前仅图片入口

**位置：** `docs/README.md:82`。

**问题与影响：** 目录把模块概括为“作者 Mac 本机 CLI 的项目配对、逐任务权限与回执边界”，没有表明当前新建业务入口仅图片，也没有提醒旧文字兼容分支仍保留。读者从索引不能分辨当前能力和历史实现，容易按旧的通用本机 Agent 心智理解；根 `README.md:127` 已将该边界写清。

**最小修订：** 将摘要收窄为“本机图片 CLI 配对、逐任务权限与历史文字 job 兼容边界”。权威来源明确写了图片范围及旧 claim/执行分支（`backend/modules/local_agent/README.md:11-21`、`docs/modules/23_local_agent.md:1-13`）。

**复核条件：** 从 `docs/README.md` 摘要能看出图片是当前入口、文字仅属历史兼容；不得因此暗示所有历史 job 都已在服务端拒绝或数据库中没有待领取记录。

## 已核实但未发现问题的边界

- 当前指南 `docs/product/new-user-guide.md` 是唯一当前指南内容源；`docs/product/word-guide-source.md` 明确为历史源稿。`docs/README.md` 说明现存 DOCX 对应旧 Word 源稿、未随本轮刷新，不把 DOCX 说成当前指南或新导出。未发现需要生成或更新 DOCX 的证据。
- 当前入口、显式开关、生产状态和验收层有分界：演示入口仅在部署启用配置时出现，自动连续阅读是可选且首次开启需确认，Alpha/线上状态另有说明；没有从代码存在或静态测试推导生产/作者验收。
- `ledger-summary.json` 中的 26 是“updated” claim 决定数，不是 26 项契约测试或文学质量证据。`inventory-summary.json` 的 679 是文档路径清点；源覆盖账本另列 1,381 个源码路径，其中 152 个定向阅读、1,229 个仅路径清点，并明确不是全库逐行审计。相关数字未被文档改写成全库理解或质量通过。
- Draw.io 与 HTML 当前标题和四条五步链的标签经静态抽取一致；模块图的 local_agent 图片入口、旧 job、双租约与 cwd 非沙箱说明也在配对 HTML 中出现。

## 未验证项

- **初次复核时的历史限制，已由下方最终图形复验更新。** 我当时用 `mcp__cua_repl.js` 打开 `file:///Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist/docs/architecture/runtime-boundaries.html` 被策略拒绝（仅允许 HTTP/HTTPS），并按要求停止；之后主代理通过支持的 Codex 内置浏览器 localhost HTTP 路径生成了最终验证材料，不曾换浏览器、CDP 或间接绕过。
- 初次查看的 `runtime-390.png`、`runtime-768.png`、`runtime-1440.png` 仍是旧标签，不作为最终证据；它们已由下方 `final-qa/` 中的新截图取代。
- 主代理此前在最后节点/旁注修改前做过的 shell Playwright 检查仍是旧证据；最终 HTML 的截图和浏览器检查在下方单独记录。我未亲自操作浏览器。

## 修正及定向复核（2026-10-14）

- **第 1 条已关闭。** 最终 `docs/architecture/runtime-boundaries.html:1` 已删通用“最多一次”数字，改为各流程重试层级和上限不同、不能承诺无重复费用；`runtime-boundaries.drawio` 的 `limits` 节点保留未知用量非零和自动重试可能重复费用的提醒。HTML 比图源多解释了重试层级，不再有相互矛盾的全局次数承诺。
- **第 2 条已关闭。** `docs/architecture/codebase-reading-guide.md:39-40` 明确是“一个合成用例”，8 指模型调用总数，且限定于固定冻结前缀的复用场景；同处注明只读了测试源码、未运行用例，也不证明所有改稿都没有额外调用。符合测试 `test_relation_history_uses_real_prefix_and_not_mutated_world_rows` 的断言范围。
- **第 3 条已关闭。** 最终 `docs/README.md:82` 改为“本机图片 CLI”及“历史文字 job 兼容边界”；与 `README.md:130`、`backend/modules/local_agent/README.md:11-21`、`docs/modules/23_local_agent.md:1-13` 的当前入口/兼容范围一致，不声称所有历史 job 都已被拒绝或不存在待领取记录。
- 定向静态核对得到 runtime 图源与 HTML 的 20 个流程节点标签完全一致。Local Agent 模块图两份表达均保留本机图片设备、项目/双租约与逐任务授权、旧文字 job 兼容及 cwd 非沙箱边界。静态核对不替代最终浏览器渲染。
- 当前指南、历史 Word 源稿和旧 DOCX 的身份仍清晰：`docs/README.md:144-145` 将 `new-user-guide.md` 标为唯一当前内容源，并说明现存 DOCX 对应旧源稿、未随本轮刷新；`word-guide-source.md:5` 也声明只作历史追溯。未发现需为本轮生成新 DOCX 的理由。
- 以上三项修订后未发现新的 R2 语义阻断。状态/范围数字仍按时间点清点与定向读取表述：72 条 claim、679 个 tracked 文档路径、1,381 个源码路径（152 定向片段、1,229 仅路径清点）；账本明确非全库逐行审计，26 是 claim 决策数而不是契约测试或文学验收。

## 定向复核的验证边界

- 未运行业务测试、`make docs-check` 或 `git diff --check`；本次新增的独立验证仅为静态对照图源/HTML 标签。8 调用用例仍只检查源码断言，没有在本轮执行。
- 该定向复核结束时，我未独立访问最终浏览器页面；当时 `file://` 尝试被策略拒绝并按要求停止。之后最终 localhost HTTP 浏览器验证及截图由主代理完成，当前结论与证据见下方“最终图形复验”。我在该后续回合仍未调用浏览器。
- `runtime-390.png`、`runtime-768.png`、`runtime-1440.png` 是最终节点/旁注语义标签改动前的旧截图；主代理更早的 shell Playwright 记录也早于最后修改。这些旧材料仍不能证明最终标签渲染；最终版材料已在下方“最终图形复验”单列。

## 最终图形复验（2026-10-14）

- **视觉验收可关闭（限最终 HTML 图与浏览器布局/键盘行为）。** 我只读查看了 `/Users/tywww/.codex/visualizations/2026/10/13/01a13598-6feb-7f70-b06e-5bea303588dc/docs-refresh/final-qa/` 的 `runtime-1440-final.jpg`、`runtime-768-final.jpg`、`runtime-390-final.jpg`、`module-1440-final.jpg`、`module-768-final.jpg`、`module-390-final.jpg`、`module-390-collapsed-final.jpg`，以及两张图源辅助图。Runtime 四条链在桌面宽度横向阅读、窄屏纵向阅读；各步骤、箭头、限制说明没有可见裁切或重叠。模块图在桌面可整体查看，在 768/390 下被明确提示为图内横向滚动；390 展开与折叠两态的标题、工具栏和页面均未发生竖排挤压或页面宽度溢出。
- `browser-checks.json` 记录了最终 localhost HTTP 浏览器检查：两份 HTML 在 1440/768/390 尺寸下 pageWidth 与 viewport 相同；窄图键盘聚焦有可见 outline，方向键将 `scrollLeft` 从 0 推进至 40，展开工具栏时 `aria-expanded=true`，折叠时为 `false`。这是主代理执行的浏览器证据；我按本轮指示未调用浏览器，仅独立检查其 JSON、最终截图与当前源指纹。
- 对 `source-manifest.json` 的 6 个源文件逐一重算 SHA-256，均完全匹配：两份 HTML、两份 Draw.io XML、`codebase-reading-guide.md` 和架构 README。当前源码与最终复验包中的指纹一致；manifest 没有记录截图哈希，因此截图与源码之间的对应关系来自本次提供的 `final-qa/` 文件组及其浏览器检查记录，而不是截图级密码学绑定。
- 两张 `*-source-final.jpg` 是 XML 几何辅助预览，画面无明显节点裁切；它们不是原生 Draw.io 导出。`browser-checks.json` 也注明未测试 HTML 的 Copy/PNG/PDF 导出按钮。故本次关闭的是最终 HTML 视觉与浏览器布局/键盘验收，以及当前 HTML/XML 内容配对核对；原生 Draw.io 应用渲染和可选导出文件本身仍未验证，不作通过声明。

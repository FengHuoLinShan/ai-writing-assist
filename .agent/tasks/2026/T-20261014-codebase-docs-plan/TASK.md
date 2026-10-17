---
id: T-20261014-codebase-docs-plan
title: 代码理解与文档体系更新
status: completed
created: 2026-10-14T10:05:06+08:00
updated: 2026-10-14T11:30:33+08:00
---

# 代码理解与文档体系更新

## 恢复快照

- 已完成：7名Luna/max领域理解和修订、72条结论账本、现有文档校准、新阅读指南/图源/HTML、两路Sol/high最终独立复核和返修。
- 最终视觉：两HTML在1440/768/390下通过；390模块图工具栏展开/收起无页面溢出，方向键图内滚动和焦点正常；4标题、20节点、16有向连接与源图一致。
- 状态：本地文档验收关闭，无剩余必需工作。此结果不代表真实模型、作者、业务或生产验收。
- 工作区：正式交付为 `/Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist`，分支`codex/docs-refresh-luna`，固定代码B=`22bb499789cba89fea92e918fd853ab768688e07`。唯一主TASK是本文件，集成树只存结果/证据快照。
- 下一步：无自动执行项；后续提交/推送/合并/部署须另获授权。

## 目标与验收

- 用户要求按计划完成多代理codebase理解、文档体系更新、必要表格/图解及最后独立复核；最新明确review使用Sol/high，已采用`gpt-6.1-sol/high`，领域角色仍`gpt-6-luna/max`。
- 不改业务代码、测试、运行配置、权限、Prompt、数据库或用户数据；不发业务模型调用；不提交/发布。原主树Guimi任务及其它WIP保留。
- 清点和定向阅读分开；实现事实绑定B，默认开关、历史、未知、工程证明和作者/生产验收分开。

## 里程碑

- [x] P0 固定B、WIP保护、文档清点、隔离工作区及起始门禁。
- [x] P1 七领域研究/72claims，测试源码与已执行静态门禁分开。
- [x] P2 主代理代码重核及文档裁定；运行时接线未知和关系历史反例覆盖缺口保留。
- [x] P3 29份既有文件、3份新当前登记件和执行计划；CSV承担筛选表格，旧Word/DOCX标为历史。
- [x] P4 Sol/high契约与视觉复核、返修、最终浏览器和静态门禁，本地验收关闭。

## 决策、发现和修正

- Writing同键采用回原稿；Story facade/SceneWorkbench拆分边界校准。
- Local Agent正常新入口仅图片；旧claim/companion文字分支仍在，未查DB旧pending，不能扩大snapshot拒绝保证。
- RP仅visible_text可partial；停止清可恢复模型消息，私有hold仍留审计，不API返回。
- Canon preview与admit拒绝层级区分；五formal family禁用，Map/Canon消费者缺口及单盘图片无外部备份保留。
- Sol发现Account内部runtime profile含瞬态Key，secret-free只指公开/持久投影；4份相关文档及最终CSV已修。原L1 raw研究作为历史保留，CSV附Sol校正来源。
- 浏览器曾因file协议失败停止。后核正式浏览器local-web-development文档，使用同一内置浏览器支持的localhost HTTP完成最终复验，未改安全设置或切换浏览器/CDP。
- 实测修复390工具栏展开导致463px页面宽和竖排标题；图源3处高度余量不足，移开相邻说明；补图区域键盘滚动和展开状态。

## 验证和证据

- 起始docs-check及收尾`make docs-check BASE_REF=origin/main`通过；diff/CSV/JSON/XML/4标题20节点16连接检查通过。L6执行Prompt静态26合约通过，无模型或DB。
- 两HTML三宽度/工具栏/焦点/方向键实测记录及9截图指纹见visual-verification.json；当前6源SHA与截图包一致。
- 最终审核：[Sol契约](research/SOL-CONTRACT-REVIEW.md)、[Sol视觉](research/SOL-VISUAL-REVIEW.md)；旧Luna R1/R2仅历史，不混淆最终审核身份。
- 679基线文档路径、57当前登记件、1381生产路径（152为L1–L7 claim-linked定向节读取）是清点/覆盖身份，不是全库逐行审计或质量分数。
- 不跑业务pytest/CI、真实模型/DB、生产、备份恢复或作者验收；原生Draw.io与可选Copy/PNG/PDF/打印未实测。辅助几何图不是原生导出。

## 交付

- [RESULT.md](RESULT.md)、[视觉验收](VISUAL-ACCEPTANCE.md)、最终Sol报告、72条claims/文档处置/源码分级CSV、文件快照和验证JSON。
- 截图在仓库外`/Users/tywww/.codex/visualizations/2026/10/13/01a13598-6feb-7f70-b06e-5bea303588dc/docs-refresh/final-qa/`；临时预览仅回环地址18785。
- 原主树正式文档未被批量覆盖，只同步本任务计划及该计划原索引条目；领域writer树保留。未提交、推送、合并或部署。

## 2026-10-14 本地整理提交

用户要求整理提交本地差异；本记录及对应已有证据按主题提交到当前 `codex/guided-flow-borrowing` 分支。仅归档文档与恢复记录，不恢复业务任务，不推送、合并或部署；此前验收与私有证据边界不变。正式文档刷新成果仍在独立工作树，后续集成须基于最新 main 核对。

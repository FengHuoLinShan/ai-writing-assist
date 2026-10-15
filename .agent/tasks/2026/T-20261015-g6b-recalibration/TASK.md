---
id: T-20261015-g6b-recalibration
title: G6b Ask World 真实模型首轮重校准
status: completed
created: 2026-10-15T08:32:19+08:00
updated: 2026-10-15T09:38:31+08:00
---

# G6b Ask World 首轮重校准

## 恢复快照

本轮明确范围已完成：教师 seeded 自测 30/30 匹配；Luna/max 34 条 debug 全部生成并由
Sol/xhigh 独立审查，33 条语义通过、1 条过度拒答失败。校准完成不等于业务质量全通过。
默认 evaluator 仍暂停，其他 reviewer/scene-gold、G6c holdout、G7b 和真人验收均未因此解禁。

主记录在本 worktree，分支 `codex/g6b-recalibration`，基线
`d2ab2dbf3c78785a24d3f419002fbb13b36bc99c`。仅本地未提交、未推送、未部署。
本轮用户续接的最小 Prompt 修复与冻结对比也已完成：新资料族过拒答 5→0，语义通过 27/32→32/32，
未观察到幻觉增加；原失败题新复验 0/2→2/2。详见 [REFUSAL-COMPARISON.md](REFUSAL-COMPARISON.md)。
首轮原始结果与旧账本全部保留。当前无须继续模型调用；如后续开展独立留出，另按 G6c 边界冻结，
不要重复运行已有 .started 标记的阶段，不把本轮开发对比当独立留出集。

## 目标、验收与授权

- 原请求：先查任务与边界、核验 Codex owner 连接及 Luna/max；不符时停止模型并做离线准备。
- 续接请求已明确授权修复 CLI、建立独立开发库/校准项目并真实连接验证；随后继续 G6b，教师与评分用 Sol/xhigh，不改共享库或旧账本。
- 首轮范围在开工前固定：30 条既有教师 seeded 自测，v3 全部 34 条 debug 的真实 Luna 生成与 Sol 评分。
  自测应 30/30 匹配；debug 须完整生成、逐项评分并如实处理分歧/失败，不能以确定性指标替代语义审查。
- 非目标：修改共享账户/共享库、真实稿件、旧 holdout、G6c 新 family、G7b、全局解除 evaluator 暂停、生产发布。
- `human_validated=false`、`blocking=false`，不继承旧模型的真人收据，不直接比较历史分数。

## 上下文与来源

第二批计划 §3.7（本地计划提交 `db1b3ba6d`）及聚合任务在原计划树保存，未覆盖其 WIP。
主仓库当前回到 `/Users/tywww/Desktop/项目/ai-writing-assist`（执行中曾临时移入 iCloud Desktop）；
计划文件为其 `.worktrees/audit-followup/docs/plans/2026-10-14-audit-followup-wave2.md`。
当前代码含 G6a #234 合同；已复用既有 teacher-selftest.py、v3 数据集、AskWorldService._generate、
Project facade 和语义审查器。旧脚本、数据集及所有旧账本未改。

## 决策与执行

1. 初次预检：旧默认 CLI 0.144.6 不能读取较新模型目录；主工作区配置库缺少已验证 Codex 连接，
   Project snapshot 解析为 DeepSeek。已停止调用；旧 `preflight-ledger.json`、`offline-manifest.json` 保持原样。
2. 使用本机现有 CLI 0.160.0 即可读取模型目录并识别 ChatGPT 登录；校准环境显式固定该版本，
   未拼造 base_instructions、未改有效 500K 目录或全局模型指令。
3. 创建独占容器 `g6b-calibration-pg-20261015`，127.0.0.1:65195，专用库
   `agent_e2e_g6b_calibration` 从空库迁移至 `20261014_model_scope_budget`。
   环境仅存本树 ignored backend/.env，没有写共享库、复制稿件或迁移共享环境。
4. 经正常 SettingsService.connect_account_llm_provider 真实验证 native ready，创建合成作者项目。
   Project facade 构建/恢复 snapshot、open_project_llm_client 确认 Codex/Luna/max、已验证指纹及 codex-text-v3。
5. native-capture.py 只转发真实 0.160.0 的参数和 stdin/stdout/stderr，不替换传输或返回。
   先持久 pending+请求再启动模型，完整原始材料留私有目录。连接指纹绑定该入口并真实验证。
6. AskWorldCalibrationScope 每次教师调用重新物化并恢复同一 Project snapshot，限定 Sol/xhigh 的 Ask World 教师步骤、attempts=1。
   默认暂停和其他角色不变。run-calibration.py 的源码/Prompt/rubric/dataset/seeded hash 及独占阶段标记防止误重发。
7. 实测完成后修复原教师取消流程遗漏的 stop/reap，并限制子进程环境不继承 API 凭据。
   校准成功路径未重发：原运行源码另存 live/frozen-sources，与 run-freeze.json 哈希逐一匹配；
   收尾代码变化及最终哈希单列在新脱敏账本，不能冒称所有真实结果来自收尾源码。
8. 捕获器格式整理改变文件指纹后正常重验连接。第一次 native 验证成功，但独立脚本漏注册 ORM 模型，
   事务报 NoReferencedTableError 并回滚；保留失败日志与成功 native 回执。注册正常模型后新一次验证及提交成功。
   最终 facade/snapshot 核验通过，旧 setup-result/freeze 不覆盖。
9. 用户移动主仓库后，通过 Git worktree repair 修复断裂的 Git 路径引用；Git 同时修复其他已注册外部树的 .git 指针。
   仅路径元信息修复，没有覆盖其他工作树文件、WIP、分支或数据。收尾检测到主仓库回到原 Desktop 位置后再次正常修复，最终 Git/文档/差异检查已通过。

## 结果与验证

- [验收结论](ACCEPTANCE.md)；[脱敏新账本](artifacts/live-ledger.json)。
- 39 笔真实原生调用：3 次连接验证、1 次 30-case 教师自测、34 次 debug 生成、1 次 34-case 教师评分。
  native 失败 0、unknown 0、自动重发 0；额外 1 次数据库事务失败如上单列，不冒充 native 失败或隐去。
- seeded 30/30，debug 34/34 审查覆盖、33/34 语义通过、参考接受率 100%、ambiguous=0。
  唯一失败 ask-probe-treaty-date-conflict 保留，不改标签或 Prompt 追认通过。
- 最终相关回归 354 passed、2 skipped（可选 rank_bm25/mcp），Ask World API 9 passed；离线门禁 23 case ready=true。
  取消回收回归修复前红、修复后绿；Ruff 检查/格式检查、docs-check 和 diff 检查结果见最终账本。
- 私有根 `/Users/tywww/.codex/private/g6b-recalibration-20261015/live`：目录 0700、文件 0600。
  仓库仅保存去原文的指标、状态、哈希、审查结论与执行脚本，不保存请求/模型原文。

## 交付边界

已交付本轮 Ask World 校准、独立环境、连接核验、受限入口与取消修复、脱敏证据及恢复说明。
保留独立库/容器与私有证据供复核。首轮未修改产品 Prompt，续接按冻结方案完成最小 Prompt 修复；未做独立留出、真人作者或完整 UI 流程验收，
未校准其他 evaluator 角色，也未做提交、推送、合并或部署。

## 2026-10-15 最小过度拒答修复（用户明确续接）

保留首轮 33/34、原失败与所有旧账本。新增记录独立于首轮验收，不追认首轮全通过。
已冻结 8 个新资料族、16 条正反开发样本（各 8 条）；与 v3 的 family 和正文均不重合。
每版本两次重复，加原失败题每版两次，共预定 68 次生成、2 批混合匿名 Sol/xhigh 审查。
只允许一个预先冻结的 Prompt 候选，不根据结果改标签、评分或再次调参。
冻结清单见 artifacts/refusal-freeze-v1.json；原文、期望和 Prompt 位于仓库外私有 refusal-v1。
验收：过拒答减少；负例错误作答、不支持主张、答案矛盾、冲突选版/遗漏均不增加；
参考全部接受、无歧义，语义通过总数不下降。若基线零过拒答则明确无法证明降低，不扩大结论。
本轮仍是生成层开发对比，不是 G6c 留出、完整 UI 或真人验收；不改共享库。
当前 owner/Project Luna/max 核验通过；baseline 34/34 与 candidate 34/34 均完成，68 笔生成均为正常 native exit，实参核验 Luna/max。
离线评测 243 passed/2 skipped、Ask World API 9 passed、相关 world 回归 97 passed、26 项 Prompt 合同通过。
方法与后续结果见 [REFUSAL-COMPARISON.md](REFUSAL-COMPARISON.md)。两批匿名混合 Sol/xhigh 评分已完成。新正例过拒答 5/16→0/16，语义通过 27/32→32/32；
两版各 16 次负例均未错误作答，未发现不支持主张或答案矛盾。全部参考接受、无歧义；
原失败题单列 0/2→2/2。70 笔调用退出 0、unknown 0，全部旧记录哈希一致。
冻结验收全部通过，保留最小候选；新账本 artifacts/refusal-comparison-v1.json，不覆盖任何旧账本。
任务关闭；无剩余已授权模型阶段。独立留出/作者验收未做，不将本轮开发对比扩为业务全面通过。

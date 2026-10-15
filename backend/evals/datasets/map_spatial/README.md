# 地图空间题材评测

`matrix.json` 冻结了五题材的 10 个独立资料族：修仙、西幻、都市、科幻、悬疑各有 5 个开发案例和 5 个单次留出案例。正文与期望只保存在仓库外的私有目录 `/Users/tywww/.codex/private/map-spatial-evaluation-20261015/`，目录权限为 `0700`、文件为 `0600`；仓库只记录 SHA-256、冻结状态和指标定义。任何复核或评分仍是 `not_run`，代理结果始终 `human_validated=false`。

每个资料族独立原创，分别覆盖矩阵列出的五种压力现象。私有 `source.json` 含逐字原文、Scene 写作要求和助手自然语言指令；私有 `expected.json` 含逐字证据目标、未知/拒绝边界和四组评分规则。矩阵哈希只证明材料版本，不代表题材质量或作者接受。

四组指标须按题材单独报告：

- **冷启动**：线索精确率/召回率、非客观线索误收、层级正确率、待核对比例、作者审核步数/耗时和总费用。
- **类型涌现**：已有类型复用、重复类型、特性准确率、作者采用后启用比例、改名/合并/归档次数。未采用的类型不得计为 active。
- **写作配对**：空间一致性、正文质量和空间提醒误报；同一个已冻结 Project、Scene、来源、Writing 指令和 Luna/max snapshot，只切换 `writing.generate` 的空间简报能力。
- **助手**：目标解析、预览意图、越权或猜测坐标拒绝、unknown 正确率。

不能观测的调用量或费用写 `unknown`/`null`，不能填零。所有比例同时报告分子、分母；不同题材不合并成一个分数。正文质量与空间一致性分开评分，避免地图变准掩盖正文退化。

## 离线材料检查

在 backend 使用已锁定 Python 环境，不同步或替换共享 `.venv`：

```bash
cd backend
.venv/bin/python -m evals.map_spatial verify
.venv/bin/python -m evals.map_spatial report \
  --output /Users/tywww/.codex/private/map-spatial-evaluation-20261015/reports/map-spatial-template.json
```

`verify` 只输出数量和状态，不输出正文。`report` 写五题材、四指标组的空白报告到私有目录；未运行的值保留为 `null`/`unknown`。

## 产品写作配对

配对脚本走产品真实入口：`modules.world.facade.read_map_spatial_brief` 核对采用地图和版本；`modules.evidence.facade.confirm_context` 与 `prepare_confirmed_ai_action` 生成同一 Scene 的两份确认；`WritingGenerationService.submit_generation` 提交真实 `writing.generate`；`TaskWorker.run_once` 执行正式 `writing_generate` handler。生成候选不会采用。两臂在入队前核对来源 hash、Project Luna/max snapshot、Scene hash、地图版本 hash、prompt hash 和非地图 context fingerprint；任一不等即停止。第一臂生成后重读 Project/Scene/map 指纹，漂移即停止。

每次只运行一个案例，且使用该资料族专用合成作者项目。需要满足：

1. 已在本任务专用 PostgreSQL `map_spatial_eval_20261015` 建立本地 synthetic project；项目标题以 `MAP-EVAL:<family-id>:` 开头，题材与冻结分组一致。不得使用真实作品、旧 holdout、共享业务库或旧 G6/G7 账本。
2. 按正常产品流程导入这一个私有合成资料族，建立 Scene 和采用地图。冻结原文必须逐字出现在 Scene 与 Writing 实际确认上下文；地图版本和空间类型也须由产品流程产生，不直接写表伪造结果。
3. 在数据库中已有已验证的 Project owner Codex 连接。预检只通过 Project facade 读取 secret-free snapshot 并校验 `provider_id=codex`、`model=gpt-6-luna`、`connection_verified=true`、`reasoning_effort=max`；不会通过连接测试请求核验凭据。
4. Sol/xhigh 受限评分角色及其真实 seeded calibration ledger、开发报告与 gate 已实现并通过独立 review。当前这项前置尚未完成，不能用手写 `approved` 或 `passed` 布尔文件代替。

`pair-writing` 的产品调用路径已编写，但目前硬拒绝 live；即使下面示例中的显式开关也会返回 `not_ready_for_live`。Sol 直接完成受限 scope 与账本验证审查后，再决定是否开放：

```bash
cd backend
AUTH_MODE=local \
DATABASE_URL='<仅本地map_spatial_eval_20261015的PostgreSQL URL>' \
MAP_SPATIAL_EVAL_ALLOW_LIVE=1 \
.venv/bin/python -m evals.map_spatial pair-writing \
  --execute \
  --family-id map-xianxia-development-v1 \
  --case-id map-xianxia-development-v1-p1 \
  --novel-id '<该family专用项目ID>' \
  --scene-id '<该项目Scene ID>' \
  --chapter-index 2
```

此脚本不执行 Evolution 抽取、类型采用、助手回合或教师评分；这些步骤须分别经产品工作流完成并按下面入口记录，不能用拼出的 LLM 问题代替产品行为：

- 冷启动和线索/类型涌现：Evolution `/api/evolution/reading/preview`、`POST /api/evolution/reading`，以及该 `run_key` 的 `/spatial-rescan-preview` 与 `/spatial-rescan`；只在专用合成项目中由 owner 确认。
- 地图读取与空间类型复核：World `read_spatial_discovery_context`、`read_map_spatial_brief` 和现有地图候选逐项审核/采用工作流。
- 助手：正常 `POST /api/assistant/sessions/{session_id}/turns`，使用 `assistant.turn` 的只读 `map_spatial_brief`；不得直接调用函数后冒充用户回合。
- 写作配对：上面的 `evals.map_spatial pair-writing`；结果只保存私有候选和账本。

实时独立教师/评分仍被 `require_live_eval_calibration` 拒绝。计划需要新的受限地图评分角色及 seeded 校准；本目录不绕过该守卫，也不借用 Ask World 或 G7 scope。评测结果、真实请求和输出的 hash/状态可脱敏归档，原文和评分输出始终留在私有目录。费用未从真实产品回执读到时保持 `unknown`。

单次留出在五个开发题材都经 Sol/xhigh gate 前不会占用；案例一旦写入账本的 `started`、`pending`、`unknown` 或 `completed` 状态，不自动重发。未知或中断须保留原任务/回执并人工调查，不能重置账本后继续使用同一留出。

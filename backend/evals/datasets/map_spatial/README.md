# 地图空间题材评测

`matrix.json` 冻结五题材（修仙、西幻、都市、科幻、悬疑）的 10 个独立资料族，每族 5 个案例，共 25 个开发案例与 25 个单次留出案例。正文、期望、请求和输出仅在仓库外私有目录 `/Users/tywww/.codex/private/map-spatial-evaluation-20261015/`，目录 `0700`、文件 `0600`。仓库只保留材料哈希与合同；教师/评分均为 `not_run`，`human_validated=false`。

当前是**工程准备稿，`not_ready_for_live`**。已有真实 Writing 配对执行路径和独立地图 seeded 校准角色；冷启动、类型涌现、助手的正式证据适配/自动执行器，以及作者审核计时/费用观测仍未实现。四组完整 judge 和开发 gate 因此明确失败关闭，留出不能冻结、不能触发业务或评分。工程测试、Sol/high 代码 review 和空报告都不代表 Sol/xhigh 评分或作者验收。

## 四组指标及实际覆盖

| 指标组 | 指标 | 当前实际覆盖 |
| --- | --- | --- |
| 冷启动 | 线索精确率/召回率、非客观误收、层级准确率、待核对比例、审核步数/耗时/费用 | 仅矩阵与产品调用清单；没有 driver 或正式回执适配 |
| 类型涌现 | 类型复用/重复、特性准确率、采用后启用比例、改名/合并/归档次数 | 仅矩阵与产品调用清单；不能把候选计为 active |
| 写作配对 | 空间一致性、正文质量、提醒误报 | 实际 Evidence 确认 → Writing 入队 → 精确 `TaskWorker.run_once(task_id, novel_id)`；不采用候选 |
| 助手 | 目标解析、预览意图、越权/猜测坐标拒绝、unknown 正确率 | 仅矩阵与产品调用清单；不能把 helper 调用当正常助手回合 |

比例必须报告分子与分母，题材分别报告，未知用量/费用/评分保留 `unknown`/`null`。冻结 rubric 在 `evals.map_spatial_guard.rubric()`：精确率/层级/特性/助手准确率 ≥0.95，召回率/类型复用 ≥0.90，非客观误收=0，重复类型/提醒误报 ≤0.05，待核对比例 ≤0.25，越权/猜测坐标拒绝=1；空间一致性须逐题材改善，正文质量不得下降。作者操作和费用必须实际观测，不能由裁判估算。完整四组 gate 校验尚待正式证据适配批交付；现有命令一律拒绝冻结 gate。

## 离线检查

在 `backend` 使用已锁定 Python；不 `uv sync`，不替换运行环境：

```bash
.venv/bin/python -m evals.map_spatial verify
.venv/bin/python -m evals.map_spatial report \
  --output /Users/tywww/.codex/private/map-spatial-evaluation-20261015/reports/template.json
```

`verify` 只输出数量、哈希检查状态；对留出仅检查权限和文件哈希，不解码正文/期望。`report` 只生成五题材四组空模板，不能作为真实成绩。

## 隔离绑定与受限角色

所有访问数据库的执行命令默认关闭，必须同时显式 `--execute` 与 `MAP_SPATIAL_EVAL_ALLOW_LIVE=1`。只接受 loopback PostgreSQL `map_spatial_eval_20261015`、`AUTH_MODE=local`、正常 active owner 的该族专用作者项目（标题 `MAP-EVAL:<family-id>:`）。配置 URL 与实际 engine URL 的主机、端口、数据库及用户名必须相同。不得使用共享业务库、真实作品、旧 G6/G7 私有账本，也不写生产 flags。

`freeze-binding --family-id ... --scopes <私有JSON> --execute` 通过真实 Project facade 核验 owner 已验证的 Codex Luna/max secret-free snapshot，冻结 manifest/source/expected/rubric/业务 prompt 管线、逐案例 Scene 精确 canonical 来源及采用地图的哈希。一个族只用一个项目，五个案例各用不同 Scene；scopes JSON 的键必须是该族五个 case_id，值只能含 `novel_id`、`scene_id`、`chapter_index`。绑定不可覆盖；缺连接或来源漂移失败关闭，不自行连接验证。

此绑定依赖已采用地图，**仅适用于 Writing 配对准备**，不能充当完整冷启动起点。后续批必须分阶段冻结共同 owner/source/Scene 基线 → seeded 校准 → 从空地图执行冷启动/类型候选 → 真实作者合成审核 → 冻结 pair map 版本 → 两臂。不得把手工预置地图当冷启动成果；该阶段绑定链尚未实现，完整流程保持未就绪。

`score --phase teacher_calibration --case-id seeded-v1` 使用专用 `MapSpatialEvaluationScope`，仅放行 `eval.map_spatial.teacher_calibration`；每族开发绑定一个四题固定 seed 请求，固定 `gpt-6.1-sol/xhigh`、`attempts=1`。校准只由代码核对真实原始输出的四个标签与输入、schema、executor/model/effort 哈希，不接受 `passed`/`approved` 文件。每次调用前重读实际 owner/Project snapshot 并 rollback 释放读事务。

同一 scope 的 `eval.map_spatial.judge` 只接受精确地图 schema 和正式产品证据构成的完整 prompt，不能借 Ask World/G7 scope。当前 `product_evidence()` 明确拒绝未实现的冷启动/类型/助手适配，因此 `development_judge`、`holdout_judge` 仍不可执行。无 scope 的 `require_live_eval_calibration()` 全局暂停保持原样。

每个评分请求在调用前原子占用并记录完整私有输入；原始返回按字节留存并核哈希。`started/pending/unknown/completed` 都不能覆盖或自动重发；中断/无效响应为 unknown。校准错答为已完成但不通过，也不重发同一请求。案例占用用文件锁防止并发双用；未知案例不重置为 started。

## Writing 配对

`pair-writing --family-id ... --case-id ... --novel-id ... --scene-id ... --chapter-index ... --execute` 须先有该族不可变绑定和真实 seeded 校准。两臂先全部冻结 Evidence confirmation 和任务，再执行第一臂；source、Project、Scene、地图、写作指令和非地图 core context fingerprint 必须相同，只改变进程内 `writing.generate` 地图能力。开关用环境与 Settings cache 的有界 context manager，正常/异常/取消均恢复；不修改冻结 Settings 或数据库 flags。

Scene 原文通过 Story 的精确 span → Writing range ref → Evidence 的 reader/Scene 截止回读验证，不能检查 Scene 元数据字符串来冒充原文。每臂执行前重验 owner/snapshot，完成后重验完整预检指纹，候选保持未采用。仅 claim 指定 task，不 drain 其他队列；隔离环境不能另起自动 worker。

具体隔离 setup、命令、调用预算和下一批接口见任务产物 [MAP-SPATIAL-LIVE-PREFLIGHT.md](../../../../.agent/tasks/2026/T-20261015-map-enhancement-design/artifacts/evaluation/MAP-SPATIAL-LIVE-PREFLIGHT.md)。本准备批没有真实模型、教师、连接验证或业务数据库调用。

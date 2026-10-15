# 地图空间题材评测

`matrix.json` 冻结五题材（修仙、西幻、都市、科幻、悬疑）的 10 个资料族，每族 5 个案例，开发集与单次留出各 25 案例。正文、期望、请求和输出仅在仓库外私有目录 `/Users/tywww/.codex/private/map-spatial-evaluation-20261015/`，目录 `0700`、文件 `0600`。仓库只保留材料哈希、合同和脱敏结论；当前所有实际状态仍是 `not_run`，`human_validated=false`。

产品驱动与四组证据适配现已进入工程 review。下面的命令用于 root 在 Sol/high review 与集成完成后执行一个开发族的五 Scene pilot；本批未启动 API、连接账户、真实模型或数据库任务。工程测试和代理作者审核不能替代 Sol/xhigh 实测或人类作者验收。助手的正常回合上下文、开发 gate 的 unknown 成本/零机会聚合仍有 Sol review 项，修复合入前不得将该 pilot 标为完整通过或开放留出。

## 指标与证据边界

四组指标按题材分别报告，比例带真实分子和分母。评分读取正式领域回执：Evolution 的 run/range/Scene receipts、空间线索与类型谱系；World 的真实草图、候选及审核版本；Writing 的两臂 Evidence confirmation、精确任务及候选正文；Assistant 的真实 run、request context、answer、plan、action batch 和拒绝/unknown 结果。Assistant 的工具调用日志在产品中未持久化，必须保留 `tool_invocations_status=unknown`；不能从工具目录或回答文字推断曾调用某工具。Writing 与 Assistant task 的 metadata 结构不同，driver 只按各自 facade 读取真实 Scene 范围。

| 指标组 | 指标 | 证据来源 |
| --- | --- | --- |
| 冷启动 | 线索精确率/召回率、非客观误收、层级准确率、待核对比例、代理作者审核步数/耗时、费用 | Evolution/World 实际输出与独立审核回执；费用仅接受产品真实货币回执，缺失为 unknown |
| 类型涌现 | 已有类型复用、重复类型、特性准确率、启用比例、作者改名/合并/归档次数 | Scene 候选与持久项目词表 lineage；跨 Scene 类型去重 |
| 写作配对 | 空间一致性、正文质量、提醒误报 | 同一 source/Scene/Project 与非地图上下文下的有/无地图 Evidence→Writing 两臂；第一候选不采用 |
| 助手 | 目标解析、预览意图、越权/猜坐标拒绝、unknown 回答正确率 | 正常助手 run 的实际用户答复、计划/预览/拒绝回执与范围来源；不虚构缺失工具日志 |

缺失、截断、来源漂移或无法核验为 `unknown`，不得当作 0 成功；某指标在单个 case 确无观察机会可标 `not_applicable`，分子/分母为 0。开发 gate 必须重新计算全部五题材的 25 个实际开发 case 与全部冻结质量阈值。作者/费用可观测性本身不得被填零；若存在需要 Sol 澄清的 gate 实现差异，应先修正而不是伪造数值。冻结 rubric 在 `evals.map_spatial_guard.rubric()`。

## 隔离与私有材料

所有访问隔离产品库或发起产品模型工作的命令默认关闭，必须同时显式 `--execute` 与 `MAP_SPATIAL_EVAL_ALLOW_LIVE=1`。只接受 loopback PostgreSQL `map_spatial_eval_20261015`、`AUTH_MODE=local`、正常 active owner 的族专用合成作者项目（标题前缀 `MAP-EVAL:<family-id>:`）；每次请求前重验 owner 和当前 Project snapshot，并释放读事务。配置 URL 与实际 engine URL 的主机、端口、库名、用户名必须一致。禁止共享业务库、真实作品、旧 G6/G7 账本，以及任何私自写表的“完成”任务/回执。

正常 `setup-family` API 会创建一个项目、应用题材空间词表预设、发布该族五段原创合成资料，并创建五个不同 Scene 和精确 canonical 来源区间。`freeze-common` 先核验同一 owner/Project snapshot、五个 source span、Scene 身份和空地图；Evolution 的正常 Scene 摘要/enrichment 可在之后变化，不得误报为作者源变化。原文 draft/range hash 与 offsets 仍严格冻结。共同基线后才可跑独立 Sol/xhigh seeded 校准；真实 Evolution 冷启动和类型候选随后来自正常 Luna/max 产品路径，禁止手工 seed/adopt 地图冒充冷启动。

评测阶段按不可覆盖链运行：共同 source/Scene 基线 → seeded 校准 → Evolution 正常授权 reading → 检查真实 clue/type/cold-start 输出及可选阶段回执 → 在隔离合成项目上通过正常 World API 做明确代理作者 review（仍 `human_validated=false`）→ 冻结实际 map/head → 每 case 的 Writing 有/无地图两臂与 Assistant 正常回合 → 每 case 独立 Sol/xhigh judge。Evolution 主 reading attempt 与 operation 的关系未持久化，报告保留 `operation_attempt_membership=unknown`；新的可选阶段需同 attempt 完成并读取 details/spatial stage、coverage 和真实 gaps。任何 `pending`/`unknown`、旧 snapshot、跨项目、错误来源/Scene、quota gap 或 pipeline fingerprint 漂移都阻止相应评测继续；started/pending/unknown/completed 永不覆盖或自动重发。

## 离线检查

在 `backend` 使用锁定 Python；不 `uv sync`，不改运行环境。`verify` 对留出材料只核权限和文件哈希，不解码语义内容；`report` 只生成 unknown 模板。

```bash
.venv/bin/python -m evals.map_spatial verify
.venv/bin/python -m evals.map_spatial report \
  --output /Users/tywww/.codex/private/map-spatial-evaluation-20261015/reports/template.json
```

## 单开发族 pilot 命令

root 已准备专用容器 `map-spatial-eval-20261015`、loopback `65302`、数据库 `map_spatial_eval_20261015` 和私有环境文件 `/tmp/map-spatial-eval-runtime-20261015/app.env0600`。以下只给出 review 之后可执行的流程，不表示本批已授权或已运行；环境文件不能打印或提交。先在隔离终端以 `AUTH_MODE=local`、`APP_ENV=development` 加载环境、升级当前 migration head，并仅启动 `127.0.0.1:65303` API，不启动共享 worker/自动 drain。确认 owner 使用正常账户流程并验证 Codex `gpt-6-luna/max`；不得手写 verified 标记或提供 Key 给评测脚本。

```bash
cd backend
set -a
source /tmp/map-spatial-eval-runtime-20261015/app.env0600
set +a
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m evals.map_spatial verify
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 65303
```

在另一终端，仅为一个开发族设置执行开关并准备项目。示例以修仙族为例；root pilot 时先选定实际开发族，不要并行创建五个族。

```bash
cd backend
set -a
source /tmp/map-spatial-eval-runtime-20261015/app.env0600
set +a
export MAP_SPATIAL_EVAL_ALLOW_LIVE=1
.venv/bin/python -m evals.map_spatial setup-family \
  --family-id map-xianxia-development-v1 --execute
.venv/bin/python -m evals.map_spatial freeze-common \
  --family-id map-xianxia-development-v1 --execute
.venv/bin/python -m evals.map_spatial score \
  --family-id map-xianxia-development-v1 \
  --phase teacher_calibration --case-id seeded-v1 --execute
```

先通过真实产品 preview 读到 mandatory reserve `M` 和五 Scene 的完整空间 child quota `Q`。如果 preview 上限高于 `M+Q`，不要启动这个 operation；用 `request_limit=M+Q` 再做一个只读 preview、重新查看 fingerprint 与数字，然后只对该新的 operation id 启动。若预算不足、quota 不完整、Scene 数不是 5 或输出 unknown，停止，不把它伪装成完整 pilot。

```bash
.venv/bin/python -m evals.map_spatial preview-evolution \
  --family-id map-xianxia-development-v1 --request-limit 30 --execute
# 检查返回的 mandatory_request_reserve 与 spatial_quota；精确 cap 为二者之和。
# 如果新 preview 已用精确 cap，请由 root 检查其 operation_id/fingerprint 后启动：
.venv/bin/python -m evals.map_spatial start-evolution \
  --family-id map-xianxia-development-v1 --operation-id '<root检查过的UUID>' --execute
.venv/bin/python -m evals.map_spatial run-evolution \
  --family-id map-xianxia-development-v1 --max-tasks 2 --timeout-seconds 900 --execute
```

重复 `run-evolution` 命令只允许读取并执行账本中精确的 pending Scene task，每次最多 2 个串行 task、每 task 最多 900 秒；状态非 pending/running/completed、Task 状态不确定或超时后停止，不重新发送该任务。请求 root cap 取 preview 的 `M+Q`；spatial `Q` 必须覆盖五 Scene 的实际提取/复核子 quota。原生使用量/货币费用没有回执时保持 unknown。

Evolution 与可选空间步骤全部完成后，按 `review-map --max-actions 20 --timeout-seconds 30` 通过正常 World API 处理至多 20 个明确 clue/map candidate 决定；每次继续前查看剩余队列与持久回执。每项 map revision adoption 还需正常 preview/CAS，不能通过直接写表或跳过来源检查。该隔离代理审核不是人类验收。最终执行：

```bash
.venv/bin/python -m evals.map_spatial review-map \
  --family-id map-xianxia-development-v1 --max-actions 20 --timeout-seconds 30 --execute
.venv/bin/python -m evals.map_spatial freeze-binding \
  --family-id map-xianxia-development-v1 \
  --scopes /Users/tywww/.codex/private/map-spatial-evaluation-20261015/scopes/map-xianxia-development-v1.json \
  --execute
```

之后每个 case 要单独执行两条 Writing arms、一个 Assistant 正常回合和一个 judge；每族最多 10 个 Writing task、5 个 Assistant turn、5 个 Sol/xhigh judge 请求。仅当 Sol 修正 Assistant turn capability/context 与 development gate review 项并集成后，才可运行以下回合和 judge 命令；每次都只传一个 case_id，未知/超时不重发。

```bash
.venv/bin/python -m evals.map_spatial pair-writing \
  --family-id map-xianxia-development-v1 --case-id map-xianxia-development-v1-p1 \
  --novel-id '<setup返回的专用项目ID>' --scene-id '<scope对应Scene ID>' \
  --chapter-index '<scope中的章节号>' --execute
.venv/bin/python -m evals.map_spatial assistant-turn \
  --family-id map-xianxia-development-v1 --case-id map-xianxia-development-v1-p1 --execute
.venv/bin/python -m evals.map_spatial score \
  --family-id map-xianxia-development-v1 --phase development_judge \
  --case-id map-xianxia-development-v1-p1 --execute
```

该 pilot 的已知上限：每族 1 个 Sol/xhigh seeded request（4 seed，attempts=1，executor timeout 300 秒）、Evolution root request limit `M+Q`、最多 5 个 `evolution_scene_step_v2` task 串行执行、代理 review 每次最多 20 个决定（HTTP timeout 30 秒）、两臂共 10 个 Writing task、5 个 Assistant turn（各精确 worker timeout 900 秒）、5 个独立 Sol/xhigh judge request（每个 attempts=1、timeout 300 秒）。Writing driver 目前没有 task worker timeout 参数，Assistant 正常提交/worker能力与 case task_hint 仍待 Sol 直接修；因此这两项不得按表面 task 数声称具备可靠的请求/超时门禁。Codex/产品不提供可靠货币回执时费用为 unknown；不估算为零。

一个五 Scene pilot 通过不解锁 holdout。完整开发 gate 只在五个开发题材族、25 个 case 的四组产品运行、原始输出、逐题材分母及所有质量门槛全部实际完成并通过后才能冻结；留出材料此前只核哈希，永不覆盖、不重试、不续发。

## Writing 配对约束

`pair-writing` 先冻结两个真实 Evidence confirmation 和 Writing task，然后仅执行精确 `TaskWorker.run_once(task_id, novel_id)`。每 arm 必须绑定相同 owner/Project snapshot、Scene ID、source span/content hash、地图实际 head、写作指令和非地图 core context fingerprint；仅地图参考开关变化。原文必须经 Story 精确 span → Writing range ref → Evidence Scene 截止回读验证。候选保持未采用；冻结设置只在进程内临时覆盖并在异常/取消后恢复。

任何正式 task 未完成、receipt 缺失、request/hash 漂移、Context/Scene/Project/source stale 或候选已采用都导致该 case unknown/blocked。不得往生产 task metadata 写 `result.eval_observations`，不得用手填指标或 `passed`/`approved` 布尔值代替原始请求、输出和领域事实。

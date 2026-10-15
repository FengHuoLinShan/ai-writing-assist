# 地图评测隔离预检与交接

状态仍为 `not_ready_for_live`：本批没有连接隔离 PostgreSQL、启动产品 API、验证账户连接或调用业务/教师模型。产品 setup、共同基线、Evolution / World / Writing / Assistant driver、真实领域 evidence adapter 和完整开发 gate 已实现待审，但 Sol/high 与 root 尚未审修并集成。本地行为测试不代表产品运行成功，代理作者审核保持 `human_validated=false`。

Holdout 在 25 个开发 case 的四组实际产品 evidence 和逐题材 gate 全部完成并通过前始终关闭。留出资料只核哈希/权限，不解码、不导入、不执行、不评分。Git 只记录 hash 与脱敏结论；私有原文、期望、prompt、输出和 request journal 留在仓库外 `0700/0600` 目录。

## 当前隔离环境

root 已准备专用容器 `map-spatial-eval-20261015`，loopback PostgreSQL 端口 `65302`，数据库 `map_spatial_eval_20261015`，migration head 为 `head_map_auto_drafts`。环境文件 `/tmp/map-spatial-eval-runtime-20261015/app.env0600` 权限 `0600`，不得输出、提交或复制其内容。空库不等于已创建账户/项目，也不等于 verified Codex 连接。禁止连接工程测试库 `65202`、G6/G7 或真实作品数据库。

仅在 root 审过代码和执行范围后，可在本地私有终端加载环境并运行迁移、材料哈希校验和 API。不要启动后台 worker 或共享 queue drain；API 由隔离 driver 通过正式 facade/HTTP 与精确 `TaskWorker.run_once(task_id, novel_id)` 调用。

```bash
cd backend
set -a
source /tmp/map-spatial-eval-runtime-20261015/app.env0600
set +a
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m evals.map_spatial verify
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 65303
```

进程必须显式 `AUTH_MODE=local`、`APP_ENV=development`。driver 同时验证环境及实际 engine 的本机地址、端口、数据库、用户名。只有正常 active owner 的 `author` Project 可进入执行；标题必须以 `MAP-EVAL:<family-id>:` 开头，题材符合冻结矩阵。owner 必须在正常 Project facade 下使用已验证 Codex `gpt-6-luna/max`；需要新连接时只走产品账户设置流程，不能直接写 verified 标记、创建自建 client/provider/profile 或提供 Key 给 driver。未验证/模型不符停止，不自动回退。

## 正常 setup 和共同基线

`setup-family` 通过正常产品 HTTP API 建一个该族专用项目、应用题材空间词表预设、发布五段冻结开发合成文本并建立五个彼此不同 Scene 和精确 canonical span。它不会写数据库表、地图 clue、adopted map、任务状态或 fake receipt。期望和材料哈希不进入 Project 或业务 prompt。一个 pilot 只选一个 development family，不能平行批跑五题材。

共同基线顺序是 setup → `freeze-common` → seeded calibration。`freeze-common` 验 owner、当前 Project snapshot、五个 Scene identity、正文精确 source draft/content/range hashes 与空地图事实；后续 Evolution 正常 enrichment 可改变 Scene card/summary，不因此判源漂移。Scene 身份、canonical span、source hash 和 offsets 仍严格比较。共同 baseline 不要求 adopted map，因此支持 cold start。

```bash
export MAP_SPATIAL_EVAL_ALLOW_LIVE=1
.venv/bin/python -m evals.map_spatial setup-family \
  --family-id map-xianxia-development-v1 --execute
.venv/bin/python -m evals.map_spatial freeze-common \
  --family-id map-xianxia-development-v1 --execute
.venv/bin/python -m evals.map_spatial score \
  --family-id map-xianxia-development-v1 \
  --phase teacher_calibration --case-id seeded-v1 --execute
```

`setup-family` 正常产品 HTTP timeout 为 30 秒；创建上限是 1 Project、1 正文 draft 和 5 Scene。项目创建/API失败后 setup 状态不会被覆盖重建。seed 是每 family 一条 Sol/xhigh request、固定 4 个代码 seed、`attempts=1`、executor timeout 300 秒；错答为完成但校准失败，timeout/unknown 不自动重发。teacher scope 和 judge scope 独立，不借 Ask World/G7 权限。

## Evolution 冷启动和完整空间子额度

必须先用只读产品 preview 查明 `mandatory_request_reserve=M`、五个 Scene 的 `spatial_quota=Q` 与 fingerprint。`preview-evolution` 本身不创建 run/Task、不调用模型；它将每个 operation id 和 response hash 写进不可覆盖 preview journal。要求 `Q=per_scene_limit×5` 且为未使用完整额度；预算不足只留 `budget_insufficient` preview。root 应使用精确 root 上限 `M+Q` 建立一个新的 preview，再查看 response/fingerprint 后，只启动该 operation id。不能给到只有 mandatory reserve 的 root quota，随后把全部 spatial quota gap 报成 pilot 完成。

```bash
# provisional bounded preview，用于读取真实 M、Q；例如暂定 cap 30，不会启动 run。
.venv/bin/python -m evals.map_spatial preview-evolution \
  --family-id map-xianxia-development-v1 --request-limit 30 --execute
# root 读取 M+Q 后，用精确 request_limit 再做 preview；若 30 已恰好等于 M+Q 可直接用其 operation_id。
.venv/bin/python -m evals.map_spatial preview-evolution \
  --family-id map-xianxia-development-v1 --request-limit '<M+Q整数>' --execute
# root 检查精确 preview 与 operation id 后，单次启动。
.venv/bin/python -m evals.map_spatial start-evolution \
  --family-id map-xianxia-development-v1 --operation-id '<精确preview的UUID>' --execute
```

启动前重新向正式 preview endpoint 查询同一 request 并比较完整 response hash/fingerprint；任何变化停止，不发 start。start API timeout 30 秒；request id/operation id 不复用。worker 只查该 Project 的精确 pending 且 `attempt=0` 的 `evolution_scene_step_v2`，逐项运行 `run_once(task_id, novel_id)`，不 drain queue。每次命令 `--max-tasks` 上限 2、每 task timeout 最大 900 秒，串行；最多 5 个 Scene task。连续调用只处理持久回执指出的下一精确任务。非 pending/running/completed，owner/source/runtime 漂移或 timeout 后一律停止，unknown 不重发。

Evolution 请求根额度必须覆盖 preview 的 mandatory reserve 与完整空间 child quota；child quota 当前由产品 preview 给出，driver 不把 task 数当模型请求数。每次精确 task 的真实 request/usage/cost 以实际持久回执为准；无法观察的 usage/cost 保留 unknown。正式读口明确 `operation_attempt_membership=unknown`，driver 不造 attempt→operation 关系。完成主理解后还必须等同一 task 的可选空间阶段收尾，再查 `optional_scene_stage`、`optional_step_coverage`、`spatial_discovery_result`、`spatial_stage_result` 与所有 gaps；`complete` 不等于没有 gap 或真人已验收。

## 代理作者审核与 map/head 冻结

`review-map` 读取同 run 的正式 Evolution 和 World facade，只通过正常 clue review、auto-draft build/resume、candidate preview 与 CAS review API 做隔离项目的明确代理作者决定。不会手写 clue、草图、adopted map、version head 或 task receipt。每次最多 `--max-actions 20` 个 clue/revision 决定，普通产品 API timeout 30 秒；候选 adoption 的 review preview+review 仍需真实 API。超出上限且状态可验证为 pending 时，root 先检查待办再显式继续；unknown/stale/source conflict 不重试或手工补状态。费用不从请求数猜测。

```bash
.venv/bin/python -m evals.map_spatial review-map \
  --family-id map-xianxia-development-v1 --max-actions 20 \
  --timeout-seconds 30 --execute
.venv/bin/python -m evals.map_spatial freeze-binding \
  --family-id map-xianxia-development-v1 \
  --scopes /Users/tywww/.codex/private/map-spatial-evaluation-20261015/scopes/map-xianxia-development-v1.json \
  --execute
```

`review-map` 只是测试用代理作者，不是人类审核。最终绑定冻结实际 post-Evolution Scene/card、地图 head/revision、Project snapshot、exact source span、词表状态和方法/管线 fingerprints。source drift、旧 snapshot、方法或 prompt/code/schema 变化失败关闭。pair 阶段用它重验实际 map/head；不要回写 common baseline，也不得将预置 adopted map 当 cold-start 成果。

## Writing、Assistant、Judge 与 gate

每 case Writing 通过正式 Evidence 确认与 WritingGenerationService 入队两臂，再只对精确 `writing_generate` task 调 `run_once(task_id, novel_id)`；source/Scene/Project/non-map context 必须一致，第一候选保持不采用。每 development family 最多 10 个 Writing task。当前 driver 尚无 Writing worker timeout 参数，需 Sol 直接补齐前，不得声称 stage timeout 有界或启动真实 Writing pilot。

Assistant 每 case 最多一条正常 `assistant_turn` task、等待上限 900 秒。当前正式 run facade 持久保存的仅有 answer/actions/evidence refs 等，不含工具调用历史，实际答复指标不得从 tool catalog 推断。另当前 driver 尚需 Sol 修正提交和 worker 两进程 `assistant.turn` 临时 capability、恢复隔离，以及按冻结 case 设置准确 task context（不能统一硬编码 `task_hint=retrieve`）；修复/审查前禁止把助手回合计为有效评分证据。

每 case 独立运行一个 Sol/xhigh judge request；只读相应正式产品 receipts，并冻结原始 prompt/response/hash。judge `attempts=1`、默认 timeout 300 秒；题材分别报告分子/分母，task IDs 只能引用真实同组 task。找不到实际 cost 时必须 `unknown`，不得估 0。每族单独请求的上限为 1 seeded teacher + M+Q Evolution root cap + 10 Writing task + 5 Assistant turn + 5 judge request；其中 Writing/Assistant 的内部模型请求数和费用目前没有统一可观测上限，必须以产品真实回执为准，不能将 task 数等同模型 request。代理 review 最多 20 个决定/调用，不能把它写成零成本。

现 gate 实现仍待 Sol review：未知货币费用不应成为计划外的质量准入阈值；单 case 无观察机会的 `not_applicable` 应参与题材聚合，但若整题材缺必要 coverage 或质量 metric unknown，不能当作通过。不要把 unknown 填成 0 求绿。review item 修复并集成后，仍需所有五个开发族、25 case 的四组实际输出和所有原定题材阈值真实通过，方可一次性冻结 development gate。该五 Scene pilot 仅验证一个开发族，不会解锁留出。

所有原始文章、期望、模型输入输出、费用与审阅明细留在仓库外私有目录；Git 只保留 hashes 和脱敏结果。任何 started/pending/unknown/completed ledger、task id、run id、case id 或 holdout material 不可覆盖、重试或续发。

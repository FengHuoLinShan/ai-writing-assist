# 地图评测隔离预检与执行交接

Sol 工程审修使用受控替身/SQLite/ASGI，不连接评测 PG、不验证账户、不调用真实模型。实际 pilot 由 root 在最终集成版本上执行；当前没有任何质量通过或作者验收结论。`human_validated=false`，holdout 在五开发族 25 case 质量门通过前只核权限/hash。

## 环境和正常账户连接

root 独占专用容器 `map-spatial-eval-20261015`、loopback PostgreSQL 65302、数据库 `map_spatial_eval_20261015`。root 已正常升级至 `20261015_map_node_merge`；正常 bootstrap owner 和已验证连接存在。旧 d8 诊断项目已通过正常引擎 API 停止，原私有目录只保留诊断，不能复用。新运行固定 `/Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2`，仅逐字节复制冻结 source/expected；不复制 binding、seed、请求或账本，截至本次交接尚无 r2 Project/模型请求。每条命令必须显式传该 `--private-root`。私有环境文件实际为 `/tmp/map-spatial-eval-runtime-20261015/app.env`（0600）；不要打印、提交或复制内容。禁止连接工程 65202、真实作品、Guimi 或其他运行账本。

所有 API 通过同进程真实 app + ASGITransport，配置/实际 manager 在首写前校验。**不启动 uvicorn、lifespan、embedding、后台 worker 或 drain**。任何网络 `--api-base-url` 会被拒绝。CLI 正常 import composition 后才调用 facade，避免先注册 DI 再 import app 的 duplicate。不同 CLI 进程都重新绑定同一环境的隔离 DB。

```bash
cd backend
set -a
source /tmp/map-spatial-eval-runtime-20261015/app.env
set +a
export APP_ENV=test AUTH_MODE=local MAP_SPATIAL_EVAL_ALLOW_LIVE=1
export ASSISTANT_ENABLED=true
export LLM_MODEL_LIMITS_JSON='{"subscription/codex/gpt-6-luna":{"concurrency":2}}'
.venv/bin/python -m evals.map_spatial verify --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2
```

root 仅在明确开始 pilot 后，通过正常 `PUT /api/account/settings/llm-connections/codex`（JSON `{}`，无需 API Key）连接并验证当前本地 Codex。使用 `evals.map_spatial_control._product_client("http://map-spatial-eval.internal", 30)`，请求包一层 `asyncio.wait_for(..., timeout=60)`；保存私有结果/hash，只输出 connected/verified 状态。该步骤是独立 **1 次实际验证请求**，先检查现有正常连接，已 verified 时不重复验证。任何 unknown/失败停止，不手写 verified 标记，不回退别的 provider。Project facade / snapshot 必须验证 active owner、Codex `gpt-6-luna/max`，后续每个 task 前重验并释放读事务。`ASSISTANT_ENABLED=true` 与 Codex 并发≤2
只设在该隔离进程，common freeze 在首个教师/业务模型调用前检查两者，禁止改全局生产默认。

## 一个开发族，五 Scene

用同一终端环境运行；不要并行创建其他族。

`setup-family` 创建 Project 后通过正常 GET `/api/evolution/reading` 读取 epoch、确认没有 run，再 POST `/api/evolution/engine`（`engine=evolution`、读取的 `expected_epoch`、`stop_active=false`、`authorization_confirmed=true`），保存真实切换回执。不会停止已有流程。该步骤不调用模型；源文、LLM snapshot 与地图未改变。随后才创建 canonical 正文与五 Scene，并冻结 common。

```bash
.venv/bin/python -m evals.map_spatial setup-family --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 --execute
.venv/bin/python -m evals.map_spatial freeze-common --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 --execute
.venv/bin/python -m evals.map_spatial score --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 \
  --phase teacher_calibration --case-id seeded-v1 --execute
# 只读 preview，先获得实际 mandatory reserve M 与完整空间 quota Q。
.venv/bin/python -m evals.map_spatial preview-evolution --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 \
  --request-limit 30 --execute
# 若 30 != M+Q，使用精确整数重新 preview；start 拒绝超出/不足 M+Q 的版本。
.venv/bin/python -m evals.map_spatial preview-evolution --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 \
  --request-limit '<M+Q>' --execute
# root 检查实际 response/fingerprint 和总请求硬上界 297+M+Q 后只启动该 operation。
.venv/bin/python -m evals.map_spatial start-evolution --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 \
  --operation-id '<精确preview UUID>' --execute
.venv/bin/python -m evals.map_spatial run-evolution --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 --max-tasks 2 --execute
.venv/bin/python -m evals.map_spatial run-evolution --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 --max-tasks 2 --execute
.venv/bin/python -m evals.map_spatial run-evolution --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 --max-tasks 2 --execute
.venv/bin/python -m evals.map_spatial review-map --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 --max-actions 20 --execute
.venv/bin/python -m evals.map_spatial freeze-binding --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 \
  --scopes /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2/scopes/map-xianxia-development-v1.json --execute
```

共同基线必须空地图、同章五个独立 Scene/真实 canonical spans。正常 Evolution enrichment 允许，源身份/精确 offsets/hash 不能变。完成必须同 task 的可选阶段收尾；details disabled 及 spatial coverage/gaps 如实报告。attempt→operation 关系缺持久证明仍为 unknown，不造已知。每次只执行正式回执指出的同项目 `pending/attempt=0` 精确 task；全族最多五个 Scene task 加一个正式结构 task（共六个），unknown/超时不重发。World 代理作者最多 20 个决定/批，地点采用走原 promote/source-hash/source-prefix 校验，地图另外 preview/CAS；0 模型请求。pending 续批先由 root 检查并显式计入额外 wall 预算，unknown/stale 不重试。

每个 case 从 setup scopes 读真实 novel_id、scene_id、chapter_index，分别运行下面三个命令；p1 至 p5 串行，不采用任何 Writing 候选：

```bash
.venv/bin/python -m evals.map_spatial pair-writing --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 \
  --case-id map-xianxia-development-v1-p1 --novel-id '<setup ID>' --scene-id '<scope ID>' \
  --chapter-index 1 --timeout-seconds 900 --execute
.venv/bin/python -m evals.map_spatial assistant-turn --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 \
  --case-id map-xianxia-development-v1-p1 --timeout-seconds 900 --execute
.venv/bin/python -m evals.map_spatial score --private-root /Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2 --family-id map-xianxia-development-v1 \
  --phase development_judge --case-id map-xianxia-development-v1-p1 --execute
```

Writing 两臂共同通过正常 Evidence `pinned_refs` 选择 preflight 已验证的同一 canonical `source_range`，不扩大区间；保留原文进入 rendered 及非地图 context 相同断言，再精确执行。每臂 root registry ≤14（K≤64），不足/超出在模型前停止。Assistant 提交与 worker 同时临时启用 `assistant.turn`，只传真实原请求、Scene 位置与 task_hint=unknown，退出恢复默认。工具历史 unknown 是辅助限制，答复/计划/action/权限实际证据必须保留。

## 冻结预算与门禁

含首次验证的模型调用上界 **297+M+Q**：验证 1、seed 1、judge 5、Evolution M+Q、Writing 10×14、Assistant 5×30。现有生产运行信封计入 initial、agent/tool 子调用与重试；不将 task 数当模型请求数。并发 ≤2，任务串行；所有精确 task timeout 900s；教师/裁判固定 Sol/xhigh、attempts=1、模型 timeout 300s。World review/auto-draft 经源码确认是确定性查询、来源验证、几何布局，0 模型调用。

CLI 整命令 deadline 包含数据库及准备：setup300、共同/最终freeze各120、preview60、start90、Evolution每批`max_tasks×900+120`、review1440、Writingpair1920、Assistant1020、score360（秒）。上述一次 setup、两 preview、2/2/2 Evolution、一次 review 和五 case 总 **24810s**；正常验证另60s，合计 **24870s / 6h54m30s**，额外 review 续批每次另1440s。取消清理及进程启动另计，unknown 不续发。

实际 snapshot context ceiling、hard input、输出 target 和每 task registry 限额进入私有账本。Codex `output_token_limit_enforced=False`，硬 token budget unsupported、token_limit=null；不伪造硬 token 限额或费用。`total_cost=unknown` 仍报告，不作为无计划阈值的质量准入；单 case 0机会可 n/a，整题材质量缺 coverage/unknown 仍失败。完整 25 开发 case 通过后才可冻结 gate 并单次独立 holdout。

生产代码/方法/schema 在 root 集成后才冻结，后续漂移停止。原始输入/输出只留私有目录；Git 仅 hash 与去原文结果。本工程审修不代表真实 Codex 可用、五题材质量或真人作者验收。

Writing 可达性仍须实际核对：setup 的 manual canonical Scene 只有来源 spans，没有 location metadata，也不会自动语义 enrichment。采用地图不等于该 Scene 已有可用地图参考；只有原正式来源支持的 Scene 地点、在场/位置事实满足正常 Brief/Evidence 门，才能形成带地图 baseline。缺可信位置时产品诚实省略，当前 eval 的 present/baseline 条件停止该 case；不得猜地点、补填 location ID 或把省略冒称为地图增强质量通过。

## Sol 工程审修证据

- 已修实际失败：错网络 API 可首写错误库；fresh-process DI 重复/未初始化；Assistant submit/worker 能力未同时启用及错误 retrieve hint；Writing 无 task timeout；五个不同 source spans 被误当全族同值；Evolution 最后 task 完成未在同次收尾；费用 unknown 额外硬阻断与配对分母权重。
- 增补正式 World promote 与独立地图重新预览/CAS，费用、工具历史与 token 硬限保持诚实。生产默认开关未改。
- 最终本地 `evals/tests`：373 passed / 2 skipped；其中地图相关 59 项。Ruff check/format、docs impact（七份既有 authority 逐项说明 no-change）、`git diff --check`、模块导入门均通过；导入棘轮61/9/0/517不增长。
- SQLite/真实 ASGI 验证 Project/draft/五 Scene spans，以及 clue review→auto-draft→candidate-location 原 promote（hash stale/跨项目/缺理解来源拒绝）→独立地图重新 preview→旧 head CAS 拒绝→正常保存。模型入口在该链被显式禁止；仅产生正常 pending 派生任务，没有伪造 done Task。
- 新增正常 ASGI preview/start→持久 run→五 Scene 加一个结构 task 的精确 TaskWorker 回归，provider 边界使用受控响应。独立会话在采样前看到原授权方法/阶段版本，正式读取 facade 与完整 Evolution 产品证据 guard 校验真实 attempt、主回执、可选收尾、两 journal 和当前 canonical 切片；不手造 done task。旧诊断 pilot 的阶段版本/方法遗漏、5-task 上限和两种 range hash 错比属于实际链发现的缺陷，旧账本不补写；修复后的真实评测使用新 private root/Project/请求身份。
- fresh Python 进程验证正常 app composition 和 ASGI 只读路由，禁止真实数据库连接且不启动 lifespan。控制器测试另覆盖 exact task IDs、2/2/2 Evolution、timeout/已尝试 task 拒绝、unknown 禁止重发、能力恢复、未校准/无权限/错误 owner 和冻结指纹漂移。
- 未运行：真实 PG 并发/CAS、真实四域 TaskWorker 的整链与 Codex/teacher/judge。工程 orchestration 的 task 替身只证明调度边界；真实模型产物、语义质量、费用、真实 owner 连接和人类作者验收仍须 root pilot，不能以本节工程绿色替代。

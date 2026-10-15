# 地图评测隔离预检与交接

状态：`not_ready_for_live`，教师/业务/评分未运行，`human_validated=false`。本批只实现专用 seeded teacher scope、Writing 配对修复、私有原始请求账本及原子防重。冷启动/类型涌现/助手的正式证据适配与 driver 尚缺，四组 judge、开发 gate 和留出继续失败关闭。不要用空报告、Sol/high 工程 review、手写 `approved`/`passed` 代替真实 Sol/xhigh 校准与评分。

## 隔离 setup（由 root 审查后执行，本批未执行）

root 已准备容器 `map-spatial-eval-20261015`、loopback 端口 `65302`、库 `map_spatial_eval_20261015`，环境文件 `/tmp/map-spatial-eval-runtime-20261015/app.env` 权限 `0600`。环境文件不得输出或提交。该空库不等于已建立账户、项目或 verified 连接。禁止连接共享库、真实作品或既有 G6/G7 账本。

```bash
cd backend
set -a
source /tmp/map-spatial-eval-runtime-20261015/app.env
set +a
# root 确认环境只指向上述容器后；upgrade 不创建业务成果。
.venv/bin/python -m alembic upgrade head
# 本命令只做私有材料权限/哈希检查，不访问数据库或模型。
.venv/bin/python -m evals.map_spatial verify
# 仅启动隔离 API，不启动后台 worker 或自动流水线。
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 65303
```

独立运行时必须显式 `AUTH_MODE=local`、`APP_ENV=development`，Project owner 正常可用；程序同时检查环境和实际 engine 的库名、端口、用户名。连接验证只能走正常账户流程：先 `GET /api/account/settings/llm-connections` 查看状态；确需新验证且 root 授权后，`PUT /api/account/settings/llm-connections/codex`、body `{}`（无 Key）才会触发连接验证。不要直接写 verified 标记；未连接、非 Codex、非 Luna/max 或 owner 不匹配都停止。runner 不会自行验证连接或换 provider。

每个开发族经正常 `POST /api/projects` 建一个项目（标题 `MAP-EVAL:<family-id>:<说明>`、题材匹配），正常产品流程导入该族合成资料，建立五个不同 Scene/精确 canonical 来源与作者采用地图。每个案例只绑定自己的 Scene；不把五个案例塞进同一个 Scene。期望只供独立评分，不导入业务项目或 Writing prompt。此 setup 尚无自动脚本；不得靠写表捏造 candidate/adoption、任务 done 或观测值。留出正文/期望在完整开发 gate 前不得导入、解码或执行；离线 verify 只核其权限/哈希。

## 可审查的一次性命令

以下命令展示后续执行入口，不构成本批真实调用授权。用实际隔离 Project/Scene ID 在私有目录创建 `scopes/<family-id>.json`（`0600`），键为五个 case_id，值结构为 `{"novel_id":"...","scene_id":"...","chapter_index":2}`。项目共用、Scene 分离；不含正文/期望。

```bash
# --execute + 地图专用环境开关是同时必须的，缺一即在DB读取前拒绝。
export MAP_SPATIAL_EVAL_ALLOW_LIVE=1
.venv/bin/python -m evals.map_spatial freeze-binding --execute \
  --family-id map-xianxia-development-v1 \
  --scopes /Users/tywww/.codex/private/map-spatial-evaluation-20261015/scopes/map-xianxia-development-v1.json
# 仅在 root 再决定实际执行后；一个族仅一个四题 fixed seed 请求。
.venv/bin/python -m evals.map_spatial score --execute \
  --family-id map-xianxia-development-v1 \
  --phase teacher_calibration --case-id seeded-v1
# 有真实校准后，精确运行一个Writing两臂，第一候选不采用。
.venv/bin/python -m evals.map_spatial pair-writing --execute \
  --family-id map-xianxia-development-v1 \
  --case-id map-xianxia-development-v1-p1 \
  --novel-id '<专用项目ID>' --scene-id '<该案例Scene ID>' --chapter-index 2
```

`freeze-binding` 本身只读真实 owner/Project/Scene/map 并写私有哈希绑定；不会创建业务资产。**现有绑定要求已采用地图，仅是 Writing-pair 准备，不能作为完整 cold_start 起点。** 不得把该预置地图当冷启动产物。校准输入固定为四个代码 seed；scope 只允许 `eval.map_spatial.teacher_calibration` / `eval.map_spatial.judge`、Sol/xhigh、attempts=1，且每次调用前经正常 owner/Project facade 重验 verified Luna/max snapshot，释放读事务。无 scope 仍全局暂停；不借 Ask World 或 G7 scope。

请求原始输入、原始返回、schema/prompt/executor/model/effort、绑定与输出哈希保存在私有请求账本；只有真实四标签正确的原始返回才算校准通过。invalid/cancel/timeout 保留 unknown，错答 completed 但校准失败；两者均不覆盖重发。Writing 配对在第一臂前冻结两个 confirmation/task，只精确执行这两个 task；源/Scene/地图/Project/核心上下文漂移即停。

下列命令入口已提供，但当前会返回 `not_ready_for_live`，不会调用 judge 或消耗留出：

```bash
.venv/bin/python -m evals.map_spatial score --execute \
  --family-id map-xianxia-development-v1 \
  --phase development_judge --case-id map-xianxia-development-v1-p1
.venv/bin/python -m evals.map_spatial freeze-development-gate
```

## 调用预算与停机边界

| 阶段 | 本批实际请求 | 后续完整一次运行的任务/独立评分上限 | 业务模型请求/费用 |
| --- | --- | --- | --- |
| 离线 verify/report/freeze-binding | 0 | 0 个模型请求；冻结最多 10 族，留出须先有 gate | 无模型费用 |
| 正常 owner 连接验证 | 0 | 隔离 owner 仅需 1 次新验证；已 verified 不重验 | 实际次数/费用由原生回执确认，不猜零 |
| seeded teacher | 0 | 5 个开发族 ×1 请求，每请求4 seed；attempts=1 | Sol/xhigh 最多5次，费用未知 |
| Writing 开发配对 | 0 | 25 案例 ×2 task=50 个精确任务 | 每 task 可能有审查/返修子步，不能把50 task当50模型请求；总上限/费用尚未冻结 |
| 开发完整 judge | 0 | 25 案例 ×1=25 请求，当前因缺适配禁止 | Sol/xhigh 最多25次；费用未知 |
| 单次留出 | 0 | 开发真实齐全且过 gate 后，50 Writing task +25 judge；当前禁止 | 业务内部请求上限/费用尚未冻结 |
| Evolution/类型/助手 | 0 | driver、每案例任务数量、工作流预算尚未实现，当前禁止自动执行 | 上限未知；不得据此批准全量运行 |

独立 teacher+judge 的完整计划上限为 **55 次**（5+25+25），业务 Writing 为 **100 个 task**，不包含连接验证、Evolution/Assistant，也不等于100个模型请求。任何内部请求数/总费用预算未冻结前，不得声称完整矩阵具备成本门禁或允许批量执行。所有 started/pending/unknown/completed 都消费唯一请求或案例身份，不自动重发；中断先调查原始回执，不重置账本。

## 下一批 Luna/max 的精确接口与待办

1. 先拆分冻结阶段：共同 owner/source/Scene 基线 → seeded → 空地图 cold_start/type 候选 → 真实作者合成审核 → pair map 版本冻结 → Writing 两臂。现有 `freeze-binding/preflight_project` 要求 adopted map，只能复用到 pair 阶段，不能直接用于冷启动；共同基线到 pair 的版本链需新增合同，owner/源漂移继续失败关闭。
2. `backend/evals/map_spatial_guard.py:product_evidence()` 当前显式拒绝 `cold_start/type_emergence/assistant`。补实际领域只读回执适配：Evolution 从 reading run、range/Scene span、spatial rescan 回执追溯真实 clues/类型/审核采用；Assistant 的 `assistant_turn` task 只有 `meta.run_id`，须经 Assistant facade 读取 run、confirmation、tool receipts、candidate 及来源，不能通吃 `task.meta.scene_id`。
3. `read_writing_evidence()` 已按同项目 done `writing_generate` task、真实 `meta.scene_id`、未采用 candidate 和私有原始配对输出哈希校验。四组完整 prompt 在 `judge_prompt()`；不得拼新 LLM题目替代 Evolution、冷启动或正常助手回合。需补真实产品执行器，不能只添 task type 白名单。
4. `evaluate_development()` 当前明确失败关闭。真实适配完成后，逐题材核25个开发案例四组所有指标、分子/分母/unknown及冻结阈值、空间改善与正文不下降，再冻结不可覆盖 gate。作者步数/耗时、采用/改名/合并/归档及费用需真实观测来源；生产 task 没有 `eval_observations`，禁止伪造此字段。
5. 25个留出案例在 gate 前只查哈希；之后按新隔离族绑定、单次冻结、精确任务与一次judge执行。补真实失败/漂移/复用与领域回执适配测试；`test_map_spatial_guard.py` 的 orchestration doubles 不等于这三组真实产品集成或质量验收。
6. `build_report()` 当前只生成 unknown 模板；需从真实原始账本逐题材汇总指标和调用/费用，保留 unknown、人类验收=false。补冻结总业务内部请求与费用预算后再由 Sol/high 审修，root决定是否实际运行。

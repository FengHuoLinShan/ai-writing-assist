# 地图评测真实运行预检与交接

状态：`not_ready_for_live`。合成正文和期望在 `/Users/tywww/.codex/private/map-spatial-evaluation-20261015/`；本文件与矩阵只保留流程和哈希引用。当前没有地图 teacher/judge calibration scope；`evals.map_spatial pair-writing` 即使给出 `--execute` 和 `MAP_SPATIAL_EVAL_ALLOW_LIVE=1` 也会在数据库读取或任何模型请求前拒绝。不要创建一个 `{status: "approved"}` 文件绕过此状态。

## 运行前预检清单

1. 确认使用独占本地 PostgreSQL `map_spatial_eval_20261015`，主机仅为 loopback；`AUTH_MODE=local`。不得指向共享开发库或任何真实作品数据库。
2. 在隔离库中用正常 owner 工作流建立一个合成作者项目，标题以 `MAP-EVAL:<family-id>:` 开头，项目题材匹配矩阵。每个真实运行只使用该资料族的合成 Project。
3. owner 在产品账户设置中完成 Codex 连接验证。评测 runner 只应通过 Project facade 读取并复核 secret-free runtime snapshot：`provider_id=codex`、`model=gpt-6-luna`、`connection_verified=true`、`reasoning_effort=max`。脚本不得自行发连接测试请求、读写 Key 或更换 provider。
4. 通过 Evolution、World、地图审核工作流建立源资料、Scene、空间候选与作者采用版本。脚本预检要求冻结原文同时存在于目标 Scene 与 Writing 实际确认上下文，且 World `read_map_spatial_brief` 能读出采用版本。不得直接写数据库表或另造一个 prompt 来代替这些路径。
5. 运行写作配对前冻结同一 Scene、Project snapshot、空间 revision、正文指令和非地图 context fingerprint。两 arm 仅改变 `writing.generate` 是否加载空间简报。第一候选保持未采用；第一臂完成后重读所有 hash，漂移就终止第二臂。
6. 完成真实 SUT 输出后才允许Sol/xhigh独立评分。teacher/judge scope、seeded calibration ledger、报告和开发 gate 尚未交付；校准资料必须引用真实请求和输出 hash，并绑定 manifest、prompt、rubric、owner Project snapshot 和 seeded 结果。reviewer identity或手写布尔标记不够。
7. 每次请求前写 `started`，排队后写 `pending`。中断、重试回队或结果不可确认都记 `unknown`，不可自动再次提交。`holdout` 要等五个题材的开发集四组指标均通过后再单次占用；未知、失败或空分不能当作通过。

## 当前产品调用清单

这些是接入点，实际运行仍须等上述 scope 和审查完成：

- **Evolution 冷启动/类型涌现（Luna/max）**：`POST /api/evolution/reading/preview`、`POST /api/evolution/reading`；每个 `run_key` 使用 `/spatial-rescan-preview` 与 `/spatial-rescan`。只读开发/留出对应原文的锚定范围，候选和类型由作者通过现有审核界面逐项确认。
- **World 地图发现和 brief（确定性读取）**：`modules.world.facade.read_spatial_discovery_context`、`read_map_spatial_brief`。记录地图 revision、source 和 geometry hashes；不把候选视为 adopted map。
- **Writing 配对（Luna/max）**：`evals.map_spatial` 里的真实确认、生成队列和 TaskWorker 路径；目前硬拒绝 live，等待 Sol 审查后补齐窄评分角色/ledger 校验。
- **Assistant 回合（Luna/max）**：通过正常 `POST /api/assistant/sessions/{session_id}/turns` 运行；仅在隔离进程/项目上打开 `assistant.turn`，由真实只读 `map_spatial_brief` 工具回答，保留助手 run 与 source receipt。
- **教师与评分（Sol/xhigh）**：须由新受限角色执行，不能调用当前默认拒绝的 executor，也不能复用/伪装成 Ask World 或 G7 scope。

## 交给 Sol 的受限角色建议

仅建议，不授权本 Luna 波次实现：增加单独 `MapSpatialEvaluationScope`，只放行 `eval.map_spatial.teacher_calibration` 和 `eval.map_spatial.judge`，固定 `gpt-6.1-sol/xhigh`、`attempts=1`；无 scope 时继续由 `require_live_eval_calibration` 默认拒绝。校准 scope 只能看冻结开发资料并写入逐 case raw request/output/decision SHA 与 seeded 结果。评分 scope 每次绑定一个已完成的项目 Luna/max 输出及其 hash，并绑定同一份 matrix、prompt、rubric 和 Project snapshot；holdout 必须等完整开发 gate，结果不得续跑或覆盖。

校准账本应能复核：manifest/source/expected hashes、prompt 和 rubric hash、Project owner 的 verified Luna/max snapshot hash、seeded case ID 与其原始输出/评分文件的 hash。开发 gate 应引用完整报告和原始 SUT 账本 hash，逐题材证明四组指标有实际分母并通过；不能仅凭文件里写有 `passed` 就打开留出。运行费用不明时始终写 `unknown`。评分仍标 `human_validated=false`。

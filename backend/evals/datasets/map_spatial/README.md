# 地图空间题材评测

冻结矩阵覆盖修仙、西幻、都市、科幻、悬疑：10 资料族、每族 5 case，development / holdout 各 25 case。正文、gold、prompt、输出及操作账本仅保存在仓库外私有目录 `/Users/tywww/.codex/private/map-spatial-evaluation-20261015/`（目录 0700，文件 0600）。Git 仅保留 hash、契约和脱敏结果；`human_validated=false`。

## 证据与质量门

四组实际证据分别来自正式领域 facade：Evolution 的 run、exact source、同 attempt 可选阶段和类型谱系；World 的 clue、auto-draft、候选与作者审核；Writing 的两臂确认、task 与未采用候选；Assistant 的正常 run、answer、plan、actions 和来源。禁止假 task / `eval_observations` / 手填通过文件。Assistant 工具历史未持久化，`tool_invocations_status=unknown`；指标只评实际答复、计划、预览/拒绝与权限证据，不从目录猜工具调用。

比例按题材累加真实分子/分母；单 case 没有机会可为 0/0 `not_applicable`，整题材无必要 coverage 或质量证据未知仍阻断。写作空间一致性必须严格优于无地图，正文质量不降低；阈值见 `evals.map_spatial_guard.BOUNDS`。作者审核步数/耗时/类型改动次数和费用是报告度量，不凭空新增质量阈值。无实际货币遥测时费用保持 `unknown`，不填零、不从 token 猜价。缺真实产品证据仍阻断，不因辅助度量不阻断而放行。

Holdout 在五开发族 25 case 的全部原始评分与质量门实际通过前，只核权限与 hash，不解码、不导入、不执行、不评分。一个五 Scene pilot 不解锁 holdout。

## 隔离与正常执行

执行同时需要 `--execute`、`MAP_SPATIAL_EVAL_ALLOW_LIVE=1`、`APP_ENV=test`、`AUTH_MODE=local` 与专用 loopback PostgreSQL `map_spatial_eval_20261015`。实际 manager 的主机、端口、库名、用户名须与环境一致。所有产品 API 都由同进程 `ASGITransport` 调真实 FastAPI app，唯一 base 为 `http://map-spatial-eval.internal`；网络 API 地址在首个写入之前拒绝。正常 composition 最先 import 一次；不启动 lifespan、embedding、后台 worker 或 queue drain，不增公开配置端点。

owner 必须正常 active，Project 标题以 `MAP-EVAL:<family-id>:` 开头，使用正常账户 verified Codex `gpt-6-luna/max` facade / snapshot。连接验证单列一次模型调用；失败/unknown 不自动回退或重试。生产地图能力默认关闭；Writing 两臂及 Assistant 提交/worker 的能力覆盖只在评测进程内生效，退出或失败后恢复。Assistant `task_hint=unknown`，只传原请求和真实 Scene 位置，不注入 gold/目标。

`setup-family` 经 Project、词表预设、Writing draft 与 Scene API 建立一个项目、一个 canonical draft、同章五个不同 Scene 与精确 spans。创建 Project 后先正常 GET `/api/evolution/reading` 读取 epoch、确认没有 run，再 POST `/api/evolution/engine` 切到 Evolution（`expected_epoch`、`stop_active=false`、`authorization_confirmed=true`）；私有 setup 保存实际切换回执，已有流程或不符回执直接停止。`freeze-common` 冻结空地图、owner、snapshot、Scene 身份与来源，随后每族一次四 seed Sol/xhigh 校准。Evolution 正常 enrichment 可以改变 Scene card，不得改变来源。演化完成后，代理作者只通过原 clue review、World promote（正式 can_adopt/source hash/来源前缀门）、auto-draft 与独立地图 preview/CAS 做合成项目决定。World 地点采用与地图采用分别记账，不采用真实作者数据。

最终 `freeze-binding` 冻结 post-Evolution Scene/card 和地图 head。Writing 两臂先同时入队并固定相同 source、Project、Scene、指令和非地图 context，再各运行精确 task，候选不采用。每次只接管 `pending/attempt=0` 的同项目 task，不 drain 队列；started/unknown/已执行 task 永不重发。方法 fingerprint 覆盖实际 Evolution、auto-draft、Assistant prompt/tool schema 和 Writing/Evidence；项目动态词表按状态冻结，不混入方法 hash。

管线 hash 也覆盖实际 Scene pipeline/task、主提交后的 optional stage、World 候选物化、最终结构 task 与可选额度实现。attempt 保存原计划授权的空间方法指纹；证据读取重新验证 canonical 切片。Writing 的 `range_hash` 是原文切片 hash，Evolution 的可选同名字段是整稿 hash 与 offsets 的身份 hash，两者按正式契约分别验证；draft、章节、整稿 hash、精确 offsets 和 content mode 必须全部一致。

## 命令

完整环境、正常账户连接、逐阶段命令、预算及停止条件见 [预检交接](../../../../.agent/tasks/2026/T-20261015-map-enhancement-design/artifacts/evaluation/MAP-SPATIAL-LIVE-PREFLIGHT.md)。以下为离线准备，不调用模型：

```bash
# backend，使用现有锁定 Python，不 uv sync。
.venv/bin/python -m evals.map_spatial verify
.venv/bin/python -m evals.map_spatial report \
  --output /Users/tywww/.codex/private/map-spatial-evaluation-20261015/reports/template.json
```

所有 live 命令只运行一个选定 development family。顺序：setup → freeze-common → seeded score → preview（先读 M、Q，再冻结精确 M+Q）→ root 检查后 start → run-evolution（2、2、2 个串行 task）→ review-map → freeze-binding → 五 case 各 pair-writing / assistant-turn / judge。五个 Scene 完成后只接管同 run/operation 正式回执返回的一个结构 task；该 task 完成后同次读取正式完成状态。

单族包括正常连接验证的调用硬上界为 **297+M+Q**：1 验证 + 1 seeded + 5 judge + Evolution 的 M+Q + 10 Writing task 各至多 14 + 5 Assistant task 各至多 30。Writing 上限按真实 registry `6*ceil(K/64)+8` 解析，超过 14 在模型前停止；不把 task 数当请求数。World review / auto-draft 是确定性 DB、来源验证及几何代码，0 模型请求。隔离进程必须显式 `ASSISTANT_ENABLED=true`，业务模型并发≤2；common freeze 先检查两者，driver 串行处理任务。各 task 900 秒；教师/裁判单次 300 秒、attempts=1。

CLI 另有包含 DB/准备的整阶段 deadline：setup 300s、common/final freeze 各 120s、preview 60s、start 90s、Evolution `max_tasks*900+120s`、review-map 1440s、Writing pair 1920s、Assistant 1020s、score 360s。一次 setup、两次 preview、一次 start、2/2/2 Evolution、一次 review、五 Writing pairs/Assistant/judge 的 deadline 总和 **24810s**；额外已检查的 review 续批每次另加 1440s。账户验证的产品 60s timeout 另计，总 **24870s（6h54m30s）**。这是取消式 wall deadline，取消清理和进程启动耗时另计；unknown 不重发。

账本冻结 snapshot context ceiling、输入上限、输出 target 和 registry 调用上限。Codex 明确 `output_token_limit_enforced=False`；无硬 token budget，报告 `unsupported` / `token_limit=null`，不得把输出 target 写成硬额度。费用和实际 token 缺失保持 unknown。工程测试不代表真实模型质量或作者验收；实际 pilot 由 root 在最终生产集成版本上执行。

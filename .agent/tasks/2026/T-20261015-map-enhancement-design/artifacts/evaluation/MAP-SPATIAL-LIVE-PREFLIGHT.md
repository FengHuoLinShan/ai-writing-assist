# 地图评测隔离预检与执行交接

Sol 工程审修使用受控替身/SQLite/ASGI，不连接评测 PG、不验证账户、不调用真实模型。实际 pilot 由 root 在最终集成版本上执行；当前没有任何质量通过或作者验收结论。`human_validated=false`，holdout 在五开发族 25 case 质量门通过前只核权限/hash。

## 环境和正常账户连接

root 独占专用容器 `map-spatial-eval-20261015`、loopback PostgreSQL 65302、数据库 `map_spatial_eval_20261015`。root 已正常升级至 `20261015_map_node_merge`；正常 bootstrap owner 和已验证连接存在。旧 d8 与 R2 都已由 root 正常停止并封存诊断：R2 两个 task done，停止1run、取消第三个未尝试task，主回执不变。旧私有目录/绑定/seed/请求/账本不可改写或复用。本次管线修改后的未来运行须由 root 指定新的私有目录、Project和请求身份，仅逐字节复制原冻结 source/expected；下列模板每条显式传 `--private-root "$MAP_EVAL_PRIVATE_ROOT"`，不指定新目录时停止，不默认继续 R2。私有环境文件实际为 `/tmp/map-spatial-eval-runtime-20261015/app.env`（0600）；不要打印、提交或复制内容。禁止连接工程 65202、真实作品、Guimi 或其他运行账本。

所有 API 通过同进程真实 app + ASGITransport，配置/实际 manager 在首写前校验。**不启动 uvicorn、lifespan、embedding、后台 worker 或 drain**。任何网络 `--api-base-url` 会被拒绝。CLI 正常 import composition 后才调用 facade，避免先注册 DI 再 import app 的 duplicate。不同 CLI 进程都重新绑定同一环境的隔离 DB。

```bash
cd backend
: "${MAP_EVAL_PRIVATE_ROOT:?请先由root指定新的私有目录，不可复用R1/R2}"
set -a
source /tmp/map-spatial-eval-runtime-20261015/app.env
set +a
export APP_ENV=test AUTH_MODE=local MAP_SPATIAL_EVAL_ALLOW_LIVE=1
export ASSISTANT_ENABLED=true
export LLM_MODEL_LIMITS_JSON='{"subscription/codex/gpt-6-luna":{"concurrency":2}}'
.venv/bin/python -m evals.map_spatial verify --private-root "$MAP_EVAL_PRIVATE_ROOT"
```

root 仅在明确开始 pilot 后，通过正常 `PUT /api/account/settings/llm-connections/codex`（JSON `{}`，无需 API Key）连接并验证当前本地 Codex。使用 `evals.map_spatial_control._product_client("http://map-spatial-eval.internal", 30)`，请求包一层 `asyncio.wait_for(..., timeout=60)`；保存私有结果/hash，只输出 connected/verified 状态。该步骤是独立 **1 次实际验证请求**，先检查现有正常连接，已 verified 时不重复验证。任何 unknown/失败停止，不手写 verified 标记，不回退别的 provider。Project facade / snapshot 必须验证 active owner、Codex `gpt-6-luna/max`，后续每个 task 前重验并释放读事务。`ASSISTANT_ENABLED=true` 与 Codex 并发≤2
只设在该隔离进程，common freeze 在首个教师/业务模型调用前检查两者，禁止改全局生产默认。

## 一个开发族，五 Scene

用同一终端环境运行；不要并行创建其他族。

`setup-family` 创建 Project 后通过正常 GET `/api/evolution/reading` 读取 epoch、确认没有 run，再 POST `/api/evolution/engine`（`engine=evolution`、读取的 `expected_epoch`、`stop_active=false`、`authorization_confirmed=true`），保存真实切换回执。不会停止已有流程。该步骤不调用模型；源文、LLM snapshot 与地图未改变。随后才创建 canonical 正文与五 Scene，并冻结 common。

```bash
.venv/bin/python -m evals.map_spatial setup-family --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 --execute
.venv/bin/python -m evals.map_spatial freeze-common --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 \
  --writing-roles "$MAP_EVAL_PRIVATE_ROOT/roles/map-xianxia-development-v1.json" --execute
.venv/bin/python -m evals.map_spatial score --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 \
  --phase teacher_calibration --case-id seeded-v1 --execute
# 只读 preview，先获得实际 mandatory reserve M 与完整空间 quota Q。
.venv/bin/python -m evals.map_spatial preview-evolution --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 \
  --request-limit 30 --execute
# M是静态minimum，Q是空间子额度maximum；操作者可显式保留有限headroom。
.venv/bin/python -m evals.map_spatial preview-evolution --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 \
  --request-limit '<有限root_limit，至少M+Q>' --execute
# root 检查实际 response/fingerprint 和实际有限headroom和总请求硬上界296+root_limit（若验证则297+root_limit） 后只启动该 operation。
.venv/bin/python -m evals.map_spatial start-evolution --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 \
  --operation-id '<精确preview UUID>' --execute
.venv/bin/python -m evals.map_spatial run-evolution --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 --max-tasks 2 --execute
.venv/bin/python -m evals.map_spatial run-evolution --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 --max-tasks 2 --execute
.venv/bin/python -m evals.map_spatial run-evolution --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 --max-tasks 2 --execute
.venv/bin/python -m evals.map_spatial review-map --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 --max-actions 20 --execute
# 可选author-assisted变体：root逐例提供全部positive case显式决定（未声明roles时为5个）；未提供则保持source-only评测。
# manifest canonical digest用 evals.map_spatial_guard.digest(原JSON)，文件0600且在本private-root。
.venv/bin/python -m evals.map_spatial apply-scene-locations --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 \
  --decisions "$MAP_EVAL_PRIVATE_ROOT/decisions/map-xianxia-development-v1.json" \
  --manifest-sha256 '<root明确冻结的canonical digest>' --execute
.venv/bin/python -m evals.map_spatial freeze-binding --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 \
  --scopes "$MAP_EVAL_PRIVATE_ROOT/scopes/map-xianxia-development-v1.json" --execute
```

共同基线必须空地图、同章五个独立 Scene/真实 canonical spans。正常 Evolution enrichment 允许，源身份/精确 offsets/hash 不能变。完成必须同 task 的可选阶段收尾；details disabled 及 spatial coverage/gaps 如实报告。attempt→operation 关系缺持久证明仍为 unknown，不造已知。每次只执行正式回执指出的同项目 `pending/attempt=0` 精确 task；全族最多五个 Scene task 加一个正式结构 task（共六个），unknown/超时不重发。World 代理作者最多 20 个决定/批，地点采用走原 promote/source-hash/source-prefix 校验，地图另外 preview/CAS；0 模型请求。pending 续批先由 root 检查并显式计入额外 wall 预算，unknown/stale 不重试。

每个 case 从 setup scopes 读真实 novel_id、scene_id、chapter_index，分别运行下面三个命令；p1 至 p5 串行，不采用任何 Writing 候选：

```bash
.venv/bin/python -m evals.map_spatial pair-writing --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 \
  --case-id map-xianxia-development-v1-p1 --novel-id '<setup ID>' --scene-id '<scope ID>' \
  --chapter-index 1 --timeout-seconds 900 --execute
.venv/bin/python -m evals.map_spatial assistant-turn --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 \
  --case-id map-xianxia-development-v1-p1 --timeout-seconds 900 --execute
.venv/bin/python -m evals.map_spatial score --private-root "$MAP_EVAL_PRIVATE_ROOT" --family-id map-xianxia-development-v1 \
  --phase development_judge --case-id map-xianxia-development-v1-p1 --execute
```

Writing 两臂共同通过正常 Evidence `pinned_refs` 选择 preflight 已验证的同一 canonical `source_range`，不扩大区间；保留原文进入 rendered 及非地图 context 相同断言，再精确执行。每臂 root registry ≤14（K≤64），不足/超出在模型前停止。Assistant 提交与 worker 同时临时启用 `assistant.turn`，只传真实原请求、Scene 位置与 task_hint=unknown，退出恢复默认。工具历史 unknown 是辅助限制，答复/计划/action/权限实际证据必须保留。

## 冻结预算与门禁

模型调用硬上界为 **296+root_limit**：seed 1、judge 5、Evolution 实际授权 root_limit、Writing 10×14、Assistant 5×30；独立连接验证另加1，为 **297+root_limit**。M为静态minimum，未包含后续World动态审查组；Q为child maximum。显式有限root_limit≥M+Q，额外headroom独立记录；即使有headroom也无完成保证，动态mandatory可能使可选空间留gap或主流程needs_budget。start固定原preview请求和quota，不给已启动run自动topup。现有生产运行信封计入 initial、agent/tool 子调用与重试；不将 task 数当模型请求数。并发 ≤2，任务串行；所有精确 task timeout 900s；教师/裁判固定 Sol/xhigh、attempts=1、模型 timeout 300s。代理作者 `review-map`/auto-draft 经源码确认是确定性查询、来源验证、几何布局，0 模型调用；Evolution World独立审查组计入root_limit。

CLI 整命令 deadline 包含数据库及准备：setup300、共同/最终freeze各120、preview60、start90、Evolution每批`max_tasks×900+120`、review1440、Writingpair1920、Assistant1020、score360（秒）。上述一次 setup、两 preview、2/2/2 Evolution、一次 review 和五 case 总 **24810s**；正常验证另60s，合计 **24870s / 6h54m30s**，额外 review 续批每次另1440s。可选 `apply-scene-locations` 整命令deadline600s、0模型，选用时总wall上界加600s，即无验证25410s/含验证25470s（7h4m30s）。取消清理及进程启动另计，unknown 不续发。

实际 snapshot context ceiling、hard input、输出 target 和每 task registry 限额进入私有账本。Codex `output_token_limit_enforced=False`，硬 token budget unsupported、token_limit=null；不伪造硬 token 限额或费用。`total_cost=unknown` 仍报告，不作为无计划阈值的质量准入；单 case 0机会可 n/a，整题材质量缺 coverage/unknown 仍失败。完整 25 开发 case 通过后才可冻结 gate 并单次独立 holdout。

生产代码/方法/schema 在 root 集成后才冻结，后续漂移停止。原始输入/输出只留私有目录；Git 仅 hash 与去原文结果。本工程审修不代表真实 Codex 可用、五题材质量或真人作者验收。

Writing eligibility已显式报告：setup 的 manual canonical Scene 只有来源 spans，没有 location metadata，也不会自动语义 enrichment。采用地图不等于该 Scene 已有可用地图参考；只有原正式来源支持的 Scene 地点、在场/位置事实满足正常 Brief/Evidence 门，才能形成带地图 baseline。缺可信位置且实际brief为空时记录 `unavailable/scene_location_unavailable`（有地点但无brief为 `no_usable_map_brief`）。任一case不可达时只生成私有 `bindings/<family>-writing-eligibility.json`，Writing pair=`not_run`，不生成可执行最终binding/任何两臂任务；report与开发gate记录覆盖阻断，不能把not_run当质量下降。正常开臂baseline非空与core相等守卫仍保留；不得猜地点、补填 location ID 或把省略冒称为地图增强质量通过。

可选author-assisted条件另有5个明确 `author_added_scene_setting`，固定agent_simulated/human_validated=false，未声称原文自动推得Scene地点。root先冻结作者意图，之后仅用明确UUID，不按名称/alias/gold代选。normal GET canonical location和adopted/saved map node/head、actual review receipt与Brief当前地点必须对齐；完整Scene hash和exact source均验证，两location key已有任一值拒绝覆盖。正常Scene PATCH整meta无CAS；只增location_entity_id且再GET核对其余字段/source未变。记录私有独立manifest/request/response/pre-post hash、计数、耗时，至多5 PATCH。未知/漂移不重发、不推进模型；final binding/reader固定这些hash。允许保留pending/attempt0的publish_chapter和rag_index_chapter索引任务，逐例ledger记录其ID/状态，不运行/取消/排空；其他写者停止。索引执行可embedding并重锚SceneSpan来源，允许保留依据为隔离进程无后台worker及精确task执行，不能声称handler无来源副作用。一般mover-only合法Brief不受该实验焦点限制。完整manifest字段见dataset README。

Writing role文件须在common首次冻结时通过`--writing-roles`提供，早于seed/Evolution/pair，schema见dataset README。完整五case按原source.json hash及逐source_excerpt UTF-8 hash绑定，role只可positive或omission_control，文件hash/digest和Scene/source身份进入common，后改拒绝。positive须真实非空地图；omission须无Scene地点且实际无Brief（mover-only也拒），不加地点输入并保存原卡hash。所有case仍各跑2正式Writing task；omission开臂baseline为空且两臂非Map core相同，judge仍评正文/空间错误，不能由role强制0/0、正收益或跳过。全genre严格改善、prose不降低、全N/A失败及BOUNDS不变；没有角色预声明保留旧严格路径。此项只改变实验设计，不改变ADR或产品默认行为。

## Sol 工程审修证据

本次 author-assisted 小批只新增 eval helper、CLI/绑定接线、测试及本文/README；未改生产API、ADR、gold或质量阈值。完整eval加真实optional worker、World冷启动和Writing产品链联合为425 passed / 2 skipped，其中新helper SQLite/ASGI 9项覆盖正常五次PATCH、exact source/完整meta保留、同名异UUID/跨作品/candidate拒绝、来源/卡漂移、已有地点、所选UUID未进入同node/head当前地点，以及unknown不重发。Evolution完成前提在helper测试中为明确HTTP替身，World/map采用资产为受控fixture；不声称这9项重跑了完整Evolution/作者审核链。原始PATCH回执与hash保留，仅updated_at按同一时间值容忍SQLite序列化差异；非目标字段/source仍精确检查。相关Ruff/format、docs显式七份authority no-change复核、import61/9/0/517、diff检查通过。没有真实PG、owner连接、私有语料或模型请求；工程绿色不替代R3质量验收。

本次 R2 后小批仅改 eval/测试/本文与 README：`make eval-fast` 393 passed / 2 skipped；加上真实 optional TaskWorker、World 冷启动和 Writing 产品链共414 passed / 2 skipped。新增覆盖显式有限headroom、低于minimum拒绝、已启动不再请求、实际source-only setup eligibility、not_run不创建binding/任务及report/gate阻断。相关Ruff/format、docs impact、导入61/9/0/517和diff检查通过。无现存DB、真实模型、owner连接或私有材料访问；下述历史工程证据保留原受测HEAD。

- 已修实际失败：错网络 API 可首写错误库；fresh-process DI 重复/未初始化；Assistant submit/worker 能力未同时启用及错误 retrieve hint；Writing 无 task timeout；五个不同 source spans 被误当全族同值；Evolution 最后 task 完成未在同次收尾；费用 unknown 额外硬阻断与配对分母权重。
- 增补正式 World promote 与独立地图重新预览/CAS，费用、工具历史与 token 硬限保持诚实。生产默认开关未改。
- 联合代码 HEAD `abe911c3594564cdabcfb4139ff939956feada39` 的 `make eval-fast`：386 passed / 2 skipped；其中地图评测四文件 72 项。本次相关文件 Ruff check/format、docs impact（七份既有 authority 逐项说明 no-change）、`git diff --check`、模块导入门均通过；导入棘轮61/9/0/517不增长。
- SQLite/真实 ASGI 验证 Project/draft/五 Scene spans，以及 clue review→auto-draft→candidate-location 原 promote（hash stale/跨项目/缺理解来源拒绝）→独立地图重新 preview→旧 head CAS 拒绝→正常保存。模型入口在该链被显式禁止；仅产生正常 pending 派生任务，没有伪造 done Task。
- 同一 HEAD 的完整 Evolution、eval、World 冷启动/合并历史/助手层级/brief/advisory、Story 空间提示与 Writing 产品链联合回归：1061 passed / 2 skipped / 1 deselected（83.81s），均为 SQLite/受控 provider，无真实模型或 PG。Writing 正向地图消费测试使用明确可信 Scene 地点；source-only Scene 对照如实省略地图，未冒称 setup 四域整链全部可达。
- 新增正常 ASGI preview/start→持久 run→五 Scene 加一个结构 task 的精确 TaskWorker 回归，provider 边界使用受控响应。独立会话在采样前看到原授权方法/阶段版本，正式读取 facade 与完整 Evolution 产品证据 guard 校验真实 attempt、主回执、可选收尾、两 journal 和当前 canonical 切片；不手造 done task。旧诊断 pilot 的阶段版本/方法遗漏、5-task 上限和两种 range hash 错比属于实际链发现的缺陷，旧账本不补写；修复后的真实评测使用新 private root/Project/请求身份。
- fresh Python 进程验证正常 app composition 和 ASGI 只读路由，禁止真实数据库连接且不启动 lifespan。控制器测试另覆盖 exact task IDs、2/2/2 Evolution、timeout/已尝试 task 拒绝、unknown 禁止重发、能力恢复、未校准/无权限/错误 owner 和冻结指纹漂移。
- 全 eval Ruff check 通过；扩大到整个 eval 目录的 format 检查发现四份本次未改动文件已有格式漂移（`rp_source_families.py`、`test_editorial_dataset.py`、`test_rp_matrix.py`、`world_design_review.py`），未扩大改动。
- 未运行：真实 PG 并发/CAS、真实四域 TaskWorker 的整链与 Codex/teacher/judge。工程 orchestration 的 task 替身只证明调度边界；真实模型产物、语义质量、费用、真实 owner 连接和人类作者验收仍须 root pilot，不能以本节工程绿色替代。


2026-10-16 主会话补充：代理作者流程中，自动草图仅含“部分地点尚未采用，地图草图保留候选身份绑定”时可以进入正式World候选采用预览；每个地点仍须can_adopt、同Scene精确原文、正式source hash和原promote接口，随后重新预览并单独确认地图。来源失效/融合/冲突或任何其他警告仍拒绝；这不将候选直接视为canonical。R5两族65请求/1006437tokens/unknown0和五seed已封存诊断，另三族未尝试即停止，未进行Writing/Assistant/judge。修复改变pipeline，旧校准/绑定不能改绑或续跑；后续使用全新身份，先核验一个题材完整链。holdout与真人门禁不变。

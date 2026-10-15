# 能力审计后续批次开发计划（2026-10-14）

日期：2026-10-14。状态：**开发计划；G4 备份目标/形态/保留期、第三波优先级、G2 执行者与首批范围均已由用户裁定**。
基线为 origin/main `22bb499789cba89fea92e918fd853ab768688e07`（PR #222 合入后）。输入是能力审计
`T-20261013-capability-debt-audit` 的 REPORT（10/13 快照 + 10/14 复核）与同名图解页，以及本轮对 G3、G4、G8
的三份只读代码调查。行号以该基线为准，实施时须在新 HEAD 重核。本文件只规划，不证明任何分支的实现或
验收状态。任务记录见 `.agent/tasks/2026/T-20261014-audit-followup-batch/TASK.md`。

**进度（2026-10-14 下午至晚间核对）：** G1 完成；G2 已经 PR #225/#226/#228 合入 main `fdd3ec598`；G3①、G3③a、G4a、G8a
已随 PR #227 合入 main（含评审后补修 `d54498792`，合并提交 `0e572c75f`，2026-10-14 晚经用户授权）。第二波尚未开工，已在新基线上
重核并细化为 [第二批计划](2026-10-14-audit-followup-wave2.md)；下文 §5.2 的 b–d、§5.3、§6.4、§7.4、§8 的
G5–G7 以第二批计划为准。

**进度（2026-10-15 核对）：** 第二批除 G6b/G6c 待入库、G7b 未启动外均已合入 main（落点 `d2ab2dbf3`，#241）。
下一批见 [第三批计划](2026-10-15-audit-followup-wave3.md)，G6d、G7b、G8c 以它为准。

## 1. 结论

审计的判断仍成立：先把运行与验收收敛到一个可信版本，再证明长篇质量，最后按缺口定向扩展。
PR #222 已合入的 A1 修复、A3 文案与保存影响提示、A4 私有清理，以及 C2 中的 SQL 聚合、字段投影、
55 组 CSS 和三处大服务拆分，本计划不再立项。

| 波次 | 任务 | 原批次 | 规模 | 开始条件 |
| --- | --- | --- | --- | --- |
| 首批 | G1 新主干 nightly 签收 | A1 收尾 | XS | **已完成**（§3） |
| 首批 | G2 Codex/Luna 运行时收敛为单一候选 | A2 | M | **已合入 main**（PR #225/#226/#228） |
| 首批 | G3① 旧 bundle renderer 退役 | B4 | S | **已合入 main**（PR #227，`0e572c75f`） |
| 首批 | G3③a 本机文字入口缩面 + RP 连接误判修复 | B4 | S | **已合入 main**（PR #227，`0e572c75f`） |
| 首批 | G4a 服务器侧图片备份、恢复演练、保留期对齐 | B3 | M | **已合入 main**（PR #227，`0e572c75f`）；生产启用另获发布授权 |
| 首批 | G8a 改章 → 地图册来源失效登记 | C1 | M | **已合入 main**（PR #227，`0e572c75f`） |
| 第二波 | G3② window Phase2 退役 | B4 | S–M | **已合入 main**（#231） |
| 第二波 | G3③b–d 删除文字 UI、死分支与客户端 | B4 | S–M | **已合入 main**（#236、#237） |
| 第二波 | G4b 作者手动导出图片包 | B3 | M–L | **已合入 main**（#235，复核补修 #241） |
| 第二波 | G8b 改图 → 写作冲突检查结果可核对 | C1 | M | **已合入 main**（#240） |
| 第二波 | G5 日常作者闭环 | B2 | M | **已合入 main**（#233、#239、#242）；生产开启另需发布授权 |
| 第二波 | G6 评测模型合同迁移、校准与 holdout 冻结 | A2 | M | G6a 已合入（#234）；G6b/G6c 已完成待入库，G6d 见第三批 |
| 第二波 | G7 长篇质量验收 | B1 | M–L | G7a 已合入（#232）；G7b 未启动，为第三批主线；G7c 暂不做 |
| 第三波 | G8c 正典修订基线与提示 | C1 | M | 第三批（G8b 已合入） |
| 第三波 | G4c 本机自动同步 | B3 | M–L | G4b 稳定后，另立 ADR |
| 按需 | G9 多用户开放前运维就绪 | §2.13/2.16 | M | 决定开放多用户时 |

地图/正典按用户裁定优先：G8a 不依赖 G2，也不和在途 WIP 冲突，因此提前到首批。暂不排期的有：
C2 剩余的导入输入扫描优化（等 SQL/内存基线；10/14 下午改为由 G7a 用合成长篇先采）、C3（formal family、更多实验蓝图、有限协作产品化）、
RP 长期记忆评测。formal-disabled 与默认关闭的实验开关保持现状。

## 2. 基线与证据

- **主干与 CI。** 22bb49978 的 push CI 六项全部成功；手动触发的 PostgreSQL 全量 E2E 也已通过（§3）。
  在此之前最近两次定时 nightly 都在旧 974f0f508 上失败。
- **在途改动是一条继承链。** 8 个 worktree 含生产路径改动，均基于 974f0f508。按 T-20261012 记录，
  resume-checkpoints（W4）→ discovery-parallel（W5）→ batch-parallel（W6）→ discovery-window（W7）→
  eligible-window（W8）逐级继承前一版 WIP；codex-luna-runtime、codex-luna-timeouts、guimi60-bottleneck-final
  是更早的版本。按 `git status -uall` 文件名比对，W8 的 109 个改动文件覆盖其余 7 个的全部文件；内容是否
  为超集须在 G2 逐文件核对。Codex 正式适配记录为 `T-20261013-codex-luna-runtime`（本地交付，含 ADR-0033 与
  `docs/acceptance/2026-10-13-codex-luna-runtime.md`，均未提交）。
- **迁移链不冲突。** WIP 新增 `20261013_codex_text_connection → 20261013_delta_category_text`，
  down_revision 为 `20261010_evolution_source_epoch`；PR #222 没有新增 migration。
- **与 WIP 的文件重叠。** W8 与 PR #222 同时修改 `backend/modules/imports/phase2_world_extraction.py`、
  `imports/tests/test_scene_phase_refactor.py` 及 assistant、evolution、imports、story 四个 README；W8 还修改
  `backend/shared/deep_import_settings.py`。G3② 因此排在 G2 之后。G3①、G3③a、G4a、G8a 的目标文件与 W8 无重叠。
- **模型规则已进入主干（10/14 下午更正）。** 原写“只在本地提交 b22f7334e/4116b657d”；规则现已随 PR #225/#226
  进入 main，这两个本地提交已被取代，不再推送。
- **T-20261012 状态（10/14 下午更正）。** 原写“长合成两路首轮 2 条 `codex_result_unknown`（约 1.91 秒）”。G2 合入后
  该原因仍未定，只增加了未来请求的脱敏诊断；诡秘全量 paused，演化 8/63，旧 v2 快照被 v3 包装门禁拒绝续跑
  （见第二批计划 §3.8）。

## 3. G1 新主干 nightly 签收（已完成）

- 完成标准：该 SHA 的完整 nightly 全绿；失败时按“新回归 / 旧基线 / 环境”分类定向修，不放宽 reason 列表或
  调用计数来过检（审计 §3.1、§3.2 的反例要求继续有效）。
- 结果：2026-10-14 10:21 手动 dispatch run `38500624771`（headSha 22bb49978），
  `287 passed, 7 deselected in 187.99s`，结论 success。A1 在主干签收；之后的定时 nightly 只作常规监控。

## 4. G2 Codex/Luna 运行时收敛为单一候选

执行者：T-20261012 的 Codex 原线程（用户裁定，保持单一写入者）。本计划只规定目标与验收，本任务不写
那批 worktree 和该任务记录。

目标：把 W8 继承链收敛为一个基于最新 main 的分支、一个 PR，使“开发阶段业务调用走 Luna/max”在主干
可用且可审计。

前置：

1. 只读诊断长合成两路快速 unknown：核对 CLI 版本与路径、宿主路由、私有事件文件；补一条未来请求的
   脱敏、可核验错误记录（错误类别、退出码、是否收到 turn 事件），不重发旧 hash。
2. 模型规则提交（b22f7334e）随文档 PR 或 G2 PR 进入 main。

步骤：

1. 冻结 W8 现场（文件清单 + hash），逐文件比对其余 7 个 worktree：同名文件内容不同且不在 W8 祖先链上的，
   列为待裁定差异，不静默丢弃。
2. 从最新 origin/main 新建分支迁入 W8 改动；与 PR #222 重叠的文件按主干新结构手工合并（三服务拆分后的
   实际落点以主干为准）。
3. 删除只为实验存在、产品不需要的脚本与临时开关；评测专用路径保持隔离（ADR-0033 范围）。
4. 运行完整工程门禁与受影响 PG/E2E；真实 Luna 调用只做验收所需的最少探针，次数单列。

完成标准：

- owner 绑定、当前授权、请求包装版本进入 snapshot、unknown 不自动重放、超时与取消、Key/登录轮换后的
  恢复行为、跨进程/多 worker 的全账户并发上限，各有测试或探针证据；单进程并发 2 不当作部署级限制。
- 旧 local_agent 文本 snapshot 继续 fail-closed，历史回执仍可读。
- 单一 PR，含 ADR-0033、migration、权威文档与验收报告；原 8 个 worktree 在 PR 合入且原任务确认后才清理。

非目标：不在本任务完成 60 章双流程排名（属 T-20261012 / G7），不改公开或 foreign owner 的可用性。

## 5. G3 旧路径有序退役

原则：先缩面再删；每一步一个可独立 revert 的 commit；保留公开/历史兼容；同一文件被 G2 修改时等 G2 合入。

### 5.1 G3① 旧 bundle Markdown renderer（首批）

- 现状：`render_context_markdown`（`evidence/compilation/markdown_renderer.py:54`）生产零调用，只有 3 个测试文件、
  `compilation/facade.py:34-36,139-151` 包装和 `compilation/__init__.py:13,34` 导出引用。`modules/evidence/facade.py:3`
  的 `import *` 让它隐式成为跨模块公开函数；tracked 内容中无仓库外或动态调用方。所有生产路径都用
  `render_compiled_context`（:736）。
- Commit 1（缩公开面，行为不变）：删包导出与 facade 包装；测试改为直接从 `markdown_renderer` 导入。
- Commit 2（删旧半）：删 `markdown_renderer.py` 约 1–605 行的旧 renderer、`SECTION_TITLES`、`_get_section_renderer`、
  12 个 `_render_*`、`_get_budget_for_category` 及只为它们存在的 import；保留 :608–747 的活跃半。删约 20 例旧用例。
- 必须迁移：`test_context_compiler.py:850` 的隐藏真相泄漏断言改为对 `asdict(bundle)` 的 JSON 断言，语义不变；
  `:1649 test_open_narrative_obligations_marks_overdue_threads` 测的是 `_build_sections`，保留。
- 不动：`StructureContextBundle` 及其 loader/compiler、`render_compiled_context` 全部调用方、DI `CONTEXT_COMPILE`。
  `geo_locations` 等可能已死字段另批评估。
- 完成标准：对固定 IR 跑 `render_compiled_context`，删前删后输出与 hash 一致；`modules/evidence/compilation/tests`、
  `tests/unit/test_context*.py`、story 相关用例、`make lint`、`make prompt-contracts`、`make repo-gates` 通过；
  改写 `compilation/README.md:577-584`、`docs/modules/08_evidence.md:70`，顺带修
  `docs/plans/2026-10-09-guided-flow-borrowing.md:335` 的陈旧路径。

### 5.2 G3③ 本机文字链路

文字路径已经断源：`project/llm_runtime.py:208-212` 拒绝含 `local_agent` 的快照，
`local_agent/executor_service.py:69-79` 对 `_local_agent` 直接报错。剩下的是仍可被旧数据激活的入口、死分支和 UI。
ADR-0029 要求保留 `run_local_agent`；`receipts` 端点与 `LocalAgentInvocation/ToolCall` 表保留供历史读取。

- **G3③a（首批）：服务端缩面 + 修现存缺陷。**
  - `POST /companion/claim`（`local_agent/api.py:444-500`）只放行 `request_json.mode == "image"`；非图片的 pending
    invocation 置 failed 并写明原因（沿用 :486-491 写法）。已分发到作者机器的旧 companion 无法撤回，服务端缩面是
    唯一可靠防线。
  - `GET /tasks/pending`、`POST /tasks/{id}/approve` 只处理 `world_object_image_generate` 与 `map_atlas_generate`。
  - 旧文字 pending 任务的终止方式：置为失败，提示沿用现有文案“本机设备只运行图片任务；历史文字任务请使用当前
    账户模型重新发起”，历史回执照常可读。
  - `interaction/services.py:1654-1662` 的 `_story_task_meta` 不再给旧 attempt 重试打 `_local_agent` 标记，改为
    明确拒绝并提示用当前账户连接重新发起。
  - 修 `frontend-console/vue/views/interaction/InteractionView.vue:204-214`：`localExecutorAvailable` 用
    `executor.kind !== "gateway"` 判断“有文字连接”，配置了图片执行器时会误判为可用。改为只看账户文字连接。
  - 完成标准：新增旧文字 task/invocation 的 approve/claim 被拒、旧快照重试明确失败、图片全链（正常/拒绝/取消/
    重复批准/owner 隔离）的测试；`backend/tests/e2e/test_local_agent_cli.py` 首例改用图片任务类型；浏览器走查
    MapAtlas 与 WorldEntityImage 的批准流程及 RP 无文字连接时的提示。实施前在开发库只读统计受影响的旧行数。
- **G3③b–d（第二波）**：已在新基线重核。前端 UI 与后端死分支合为一个 PR（b+c），范围比原写大：
  `open_task_snapshot_client` 是协作/前瞻通用的快照打开器，需改指 Project facade；API 响应字段 `local_agent`
  一并删除；依赖棘轮按实测重算。d 在 c 后，并在 ADR-0029 追加记录。详见[第二批计划](2026-10-14-audit-followup-wave2.md)
  §3.2、§3.3。

### 5.3 G3② window Phase2（第二波）

已在 M 上重核，G2 只对该文件加 4 行并发绑定，无阻塞；行号与漏改的 README 段落已更正。详见
[第二批计划](2026-10-14-audit-followup-wave2.md) §3.1。

## 6. G4 地图册与世界对象图片的备份与恢复

### 6.1 用户裁定（2026-10-14）

1. 服务器侧备份放**同机独立目录**（不在 MinIO 卷内），B2 异地以后再接，本期不开通。
2. 用户本机备份首版做**作者手动导出图片包**；自动同步放到服务器侧稳定之后。
3. 保留期**全部对齐 30 天**：图片备份 ≤30 天，同时把数据库 restic 的保留策略修到 30 天以内，与隐私政策一致。

### 6.2 现状

- 生产 Compose 只有一个 MinIO named volume（`deploy/compose.production.yml:169-186,347-348`），两个私有 bucket
  开启 versioning，配额地图册 8GiB、世界对象 24GiB（`docker/init-minio.sh:18-22,62-63`）。
- `deploy/scripts/backup.sh` 只做 `pg_dump` 与 restic；`restore.sh`、`restore_drill.sh` 完全不涉及对象。
  `release.sh:165-169` 的备份配对与 `deployment_state.py:20-27` 的 `backup_path` 只认 `.dump`。
- ADR-0014 把“外部对象备份”列为首版未采用方案（`docs/adr/0014-…:32-33,43`），ADR-0010:43-44 把数据导出 UI
  列为非目标。G4 需要新 ADR-0034（0033 已被 G2 占用），修订这两处；用户本轮裁定即对应授权。
- 隐私政策写“整库备份另保留最多 30 天，最晚约 60 天残留”（`backend/modules/account/legal.py:45-48`），本地
  `BACKUP_RETENTION_DAYS=30` 一致，但 `backup.sh:125-130` 的 restic 是 `--keep-weekly 4 --keep-monthly 6`，最长约 6 个月。
- 作者侧没有任何图片导出；地图“下载备份”只含结构 JSON（`MapStructureEditor.vue:889-894`）。

### 6.3 G4a 服务器侧备份、恢复与保留期（首批）

1. **清单以数据库为准。** 顺序固定为“先 DB 快照 → 按该快照生成对象清单 → 复制对象”。ADR-0012 规定先上传
   再落库，所以 dump 里引用的对象在 dump 时刻一定存在；dump 之后被清理任务删掉的对象在清单里记为 missing
   并报告，不静默通过。清单每行含 novel_id、bucket、key、sha256、byte_size、类别；地图页取
   `map_atlas_pages.sha256/byte_size`，世界对象图（DB 无 hash 列）备份时流式计算。
2. **范围。** 地图册含 candidate/adopted/rejected/deprecated 全部页与 mask；世界对象图只备当前 `image_version` 的
   full 与 thumbnail（旧版本本就被异步清理）；候选与复用字节在 PG 内，随 pg_dump 走。
3. **落点。** 同机独立目录（建议 `deploy/backups/objects/`，0700/0600），每次运行产出一份清单与其 sha256，
   清单与同批 DB dump 的时间戳配对；对象按 key 增量镜像（两类 key 均不可变，目标缺 key 或 sha256 不符才复制）。
   部署文档明示：同机副本防误删和桶损坏，挡不住整盘故障，整盘故障靠作者导出的本机副本（G4b）和以后的 B2。
4. **独立脚本与 unit，不改 `backup.sh` 的 stdout 契约。** 新增 `deploy/scripts/backup_objects.sh` 与
   `ai-writing-object-backup.{service,timer}`，排在 DB 日备份（02:17）之后，共用 `production-operation.lock`；
   新增 `profiles: ["ops"]` 的一次性 compose 服务执行复制。
5. **最小权限。** `init-minio.sh` 新建只读备份用户（List/Get）；不复用 root 或应用凭据。备份产物与日志不含凭据，
   object key 不对非 owner、不经通用 API 暴露；唯一例外是 G4b 的 owner + novel_id 只读导出清单端点（no-store、
   不入日志，2026-10-14 晚用户裁定）。
6. **保留期。** 图片备份清单与镜像中不再被任何 ≤30 天内清单引用的对象，在 30 天后清除；项目永久删除或账号
   清除后，对应前缀随之老化。restic 改为 30 天以内的策略（如 `--keep-within 30d`），`validate_env.py` 对
   `BACKUP_RETENTION_DAYS` 加 ≤30 上限；隐私政策文本不变。
7. **恢复与演练。** 新增 `restore_objects.sh`：按 `init-minio.sh` 重建 versioning 与配额 → 回灌 → 对账（对象存在、
   sha256/size 一致、PNG/WebP 可解码、key 中 novel_id 与行一致）。输入可以是服务器备份目录，也可以是 G4b 导出的
   图片包（两者共用清单格式）。新增隔离无网络演练 `make test-object-restore-drill-real`，只用合成图片，记录实测
   RPO/RTO；只以 pg_restore 成功不算恢复成功。
8. **不进入 release 前置门禁**（首版），不延长发布停机窗口；release 回退时对象不删除。
9. 完成标准：演练恢复两个 bucket、元数据与权限并对账全过；人为删除对象、备份中途失败两种反例都报告“不完整”；
   保留期老化有测试；`deploy/tests/test_scripts.py` 的 unit 对应表与 `init-minio.sh` 断言、`validate_env.py`、
   `make test-deploy` 通过；ADR-0034、`deploy/README.md`、`docs/modules/12_infrastructure.md` 同步。
   生产启用另获发布授权，只经 `release.sh <40 位 SHA>`，启用后在生产做一次只读对账。

### 6.4 G4b 作者手动导出图片包（第二波）

已按 2026-10-14 晚的只读核查重写，以[第二批计划](2026-10-14-audit-followup-wave2.md) §3.4 为准。要点：现有端点拼不出
清单，需新增 owner + novel_id 只读导出清单端点；包格式沿用 G4a 已实现的 author_export；浏览器无法证明落盘，
不显示“已备份”。用户已按推荐裁定：key 仅经 owner 导出清单端点返回（§6.3 第 5 条已随之修订）；mask 导出；
部分失败重试后由作者确认生成标注缺项的包。

### 6.5 G4c 本机自动同步（第三波）

经已配对 companion 定期拉取到作者所选文件夹。需要新 ADR（修订 ADR-0029 的“仅图片生成”授权）、独立的同意语义
（不复用逐任务全主机权限确认）、设备级开关、清单与流式下载端点、设备端原子写与 sha256 校验回执；只有设备端
落盘校验后才显示“已备份到本机”。当前 companion 只验证过 Mac。

## 7. G8 地图/正典接入失效账本

### 7.1 现状

- 账本只能表达“稿件章区间 → 消费者”。`ConsumerKind`（`evolution/consumption.py:67`）只有 Story 三类；
  `SourceBinding.chapters` 要求至少一章（:156-166）；`AssetDigest` 与 `selected_assets/excluded_assets`（:200,215-236）
  是预留位，全仓无写入端。每份回执从常量 `UNSUPPORTED_CONSUMERS`（`invalidation.py:47-59`）拷入 map_atlas 与
  world_canon_revision，`receipt_public_view` 因此恒为未知范围。
- 地图来源清单已有章级 canonical `source_range`（draft_id、整稿 source_hash、offset，`map_structure_schemas.py:57-90`），
  地图读时自查 stale（`map_structure_service.source()` :274-310，前端“部分地图来源已变化”），但写作侧回执从不告知。
- 写作冲突检查读地图当前 head（`list_adopted_map_continuity_facts`），落库只存 checked/not_checked，不记 revision 或 hash。
- 正典（`WorldCanonRevision`/`WorldCanonHead`）在 world 以外零读取者；真实下游是已发布的 World Bible 页面 revision。
  M4 契约 §2（`docs/plans/2026-10-07-m4-dependency-invalidation-contract.md:42-45`）已定：正典修订不传播到 Scene
  观察，观察层记录“当时所见”。
- 依赖方向：evolution → world 已有冻结边，world 不得 import evolution；函数级跨模块 import 已达预算 524。

### 7.2 采用的决定（无新增用户裁定，均沿用既有契约）

- 正典语义按 M4 既有决定：登记基线 + 显式提示，不降级、不自动重建。若要改为“标 degraded/待重验”，须用户另行裁定
  并修订 M4 §6。
- 地图登记粒度为章级、只含 current head；不新增表、列或 outbox，采用推导式登记。
- evolution 读 world 走新增 DI 键 + 消费方 Protocol（ADR-0031 惯例，补正常态与空态 port 测试），不加函数级导入。
- 首切片只做建议性展示：不进 `recompute_options`，不改 `from_scene_index`，地图更新 run 含 LLM，不自动触发。
- world_knowledge 不在本批。

### 7.3 G8a 改章 → 地图册（首批）

- 在 `apply_source_invalidation` 同事务内，`published_changed` 时经新 world 只读 port 扫描该 novel 各节点 current head
  文档中引用被改章（draft_id + source_hash）的 `source_range` 来源，结果写入 `invalidated_consumers["map_atlas"]`
  （节点、revision、章）。working 稿变更不触发（source_range 强制 canonical）。
- 类型限定：map 判定不得置位 `chapter_registered`、不进 `affected_scenes`，保守扩大语义不变。
- 容错：条数上限与 truncated 标记；查询失败用 SAVEPOINT 降级，coverage 写明“地图册未核对”，不阻断主失效。
- unsupported 拆分而非删除：map_atlas 改为残余未覆盖项（entity/world_bible_page 来源、待审 candidate），
  `unknown_scope` 对残余继续可见；world_canon_revision 保持 unsupported 至 G8c。
- 前端：写作回执中列出受影响地图（作者语言：地图名、对应章节），提供“去地图核对”入口；后端 `CONSUMER_LABELS`、
  `RECOMPUTE_SCOPE_COVERS` 不加重算项，writing 侧镜像常量与后端对拍。
- 回执指纹会因新键变化：同步测试并保证幂等重放。
- 需同步的测试：`evolution/tests/test_invalidation.py:187-190`、`test_consumption_registry.py`（:462-480,649,677-680,1147,1318）、
  `test_p2c_revision_adoption.py:571-575`、`story/continuity/tests/test_scene_basis.py:255-261`、前端
  `tests/vue/writing/` 下 invalidationModel、InvalidationNotice、RecomputePanel 三个测试；回归
  `backend/tests/e2e/test_p2c_invalidation_recompute.py` 与 PG critical。
- 完成标准：改章后引用该章的地图节点出现在回执中，未引用的不出现；不同 novel 的地图不串；port 失败时降级可见；
  Scene 窗口与重算选项不变；`check_module_imports.py` 预算不增。文档同步 `docs/modules/15_map.md:31-33`、
  `docs/modules/22_evolution.md`、`evolution/README.md:462-476`。

### 7.4 G8b 改图 → 写作冲突检查（第二波）

已按只读核查重写，以[第二批计划](2026-10-14-audit-followup-wave2.md) §3.5 为准。要点：基线记全部载入的地图事实，
以 revision_id 为主比较（`revision_hash` 不含来源）；比较结果只在响应中计算，不入库、不进 AI 复核指纹；需要
world 批量 head 出口与 DI 键，以及 `ConflictDetailDialog` 前端改动；不新增账本入口。

### 7.5 G8c 正典修订基线（第三波）

粒度取页面 revision（revision_id + revision_digest），不取 canon head。新增 world 稳定指纹出口；在 checkpoint 预留的
`selected_assets` 记录基线；读时比对，只做提示不降级（M4 §2）。完成后 world_canon_revision 从 unsupported 中移出
相应部分。

### 7.6 必须保留的保护

owner + novel_id 双重过滤（新 port 同时过滤 node 与 revision）；未覆盖保持显式；地图与正典 revision 的 append-only
与 CAS；地图保存不回写世界正史；Evidence 对 map 目标带截止即拒绝的屏障与 ReaderRevealPolicy 读时重判；
作者确认与 manual checkpoint 只标待重验、不删历史；失效热路径中的附属动作一律可降级。

## 8. 第二波与按需任务

- **G5 日常作者闭环、G6 评测合同 Luna 校准、G7 长篇质量验收。** 已在新基线重核并拆成可独立交付的切片
  （G5a–c、G6a–c、G7a–c）。主要更正如下：G6 要迁的是独立 `CodexStructuredExecutor` 路径，Ask World 被测端早已走
  Project facade；G7 不能续跑旧 v2 run，只复用单位定义；导入扫描基线改由合成长篇先采。详见
  [第二批计划](2026-10-14-audit-followup-wave2.md) §3.6–§3.8。
- **G9 多用户开放前运维就绪（按需）。** 按真实代理拓扑收紧 `backend/Dockerfile:47` 的 `--forwarded-allow-ips *`、
  worker/account 调度容量、unknown receipt 人工处置、监控告警与排队 SLO；B2 异地备份可在此一并开通。

## 9. 写入者与并行

- 每个任务独立 worktree 与 `codex/<slug>` 分支，从最新 origin/main 建立；本计划所在分支只含计划与任务记录。
- 单一写入者：migration 与 Codex provider 归 G2；`deploy/tests/test_scripts.py`、`init-minio.sh`、`validate_env.py` 归 G4a；
  `core/service_keys.py`、`app/bootstrap.py`、ADR-0031 依赖表、`scripts/check_module_imports.py` 先由 G8a 写入，
  G3③c 在其合入后再改。
- 正式文档与 T-20261014-codebase-docs-plan（docs-refresh-luna）有交叠时，先在该任务记录中确认写入者；
  四个与 W8 重叠的 README 由 G2 先写。
- 首批中 G3① 与 G3③a 规模最小且 G3③a 修一处现存缺陷，建议先开；G4a、G8a 随后并行。
- Dependabot #224（openai 2.53 → 3.28 大版本）在 G2 合入后再评估（G2 已合入，见第二批计划 H3）。
- 第二批的写入者与冲突约定见[第二批计划](2026-10-14-audit-followup-wave2.md) §4。

## 10. 验证与交付门禁

- 每个实施任务：开工前 `make docs-check`；收尾按影响运行模块测试、`make lint`、必要的前端 Vitest 与 lint、
  `make repo-gates`、`make docs-check BASE_REF=origin/main`、`git diff --check`。涉及 PG 的任务另跑
  `make test-postgresql-critical`，涉及失效账本的加跑 `test_p2c_invalidation_recompute.py`。
- 涉及作者界面的任务（G3③a、G4b、G8a、G5）按受影响路径做浏览器验收，包括失败、离开恢复与 390px。
- 合入 main 前更新基线、完成评审并取得合并授权；生产启用（G4a）另获发布授权。

## 11. 已裁定事项与默认假设

已由用户裁定（2026-10-14）：G4 服务器侧放同机独立目录、B2 后接；本机备份先手动导出、自动同步后做；保留期全部
对齐 30 天（含修正 DB restic）；地图/正典优先（G8a 提前到首批）；G2 由 Codex 原线程收敛；首批按本计划 §1 开工
（G1 已完成，G2 交 Codex 线程；G3①、G3③a、G4a、G8a 的执行者由用户另行指派，本计划不含执行）。

本计划自行采用、实施中如证据相反再改的默认假设：G3③ 旧文字 pending 任务置失败并提示重新发起；G3② 删除未挂载
的死 probe 与 5 个设置键，不改 Prompt 字面量；G4a 不进 release 前置门禁、恢复首版只做运维级；G8 全部沿用 M4
契约与 §7.2 的决定。以下仍需用户另行决定，届时再问：改变正典语义为“降级/待重验”；开通 B2；G4c 自动同步的
授权语义；G9 是否启动。

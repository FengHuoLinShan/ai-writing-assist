---
id: T-20261015-agent-operation-surface
title: 全模块 AI 操作入口、目标运行与操作留痕设计
status: active
created: 2026-10-15T14:30:00+08:00
updated: 2026-10-15T23:31:00+08:00
---

# 全模块 AI 操作入口、目标运行与操作留痕设计

## 恢复快照

设计稿与 ADR（Proposed）已于 2026-10-15 经用户授权本地提交 `87e56f241`，未推送。之后按用户要求核对
33 条外部评审并合并 ADR：原 ADR-0038（助手地图与势力操作）、0039（操作目录与目标运行）、0040（操作留痕）
合并为新 ADR-0038 `docs/adr/0038-ai-operation-catalog-goal-runs-and-trace.md`。用户随后裁定两项默认值
（见“关键决定”），修正与裁定经用户授权在第二个本地提交中提交，未推送。
与地图增强设计（T-20261015-map-enhancement-design）同在工作树 `.worktrees/map-enhancement-plan`、分支
`codex/map-enhancement-plan`（基于 main `d2ab2dbf3`；最后核对时 origin/main 为 `00d861283`）。
2026-10-15 技术评审后按推荐修订 ADR-0038：目录项事务形态、目标运行 `goal` 模式与每项目唯一索引、
高频操作留痕合并或豁免。修订经用户授权在第三个本地提交 `20d6f1eff` 中提交，未推送。
2026-10-15 用户采纳 ADR-0038（Accepted / 未实施）；ADR-0023 补充说明与索引同步。
用户已明确三份计划全部实施，本任务执行A0–A4。primary当前4344b5f5c（生产代码b81ba6887）：A0a已审修并集成，1217相关回归通过。A0b原自有三提交f9a9d8f14/87752e8fd/203018dfd在Sol/high的map-assistant-review/codex/operation-trace-review独立审修；已复现并直接修复trace context未绑定及FastAPI included effective route未包装两个真实HTTP P1，另修任意id泄露和新route ratchet，仍未集成。Sol独占65202独立operation_trace_review_test_20261015，原测试库/评测库不变。A1/A2可用artifacts/A1-A2-HANDOFF.md恢复，待本批审修集成后继续；A3仍在范围，A4数周真实数据与前三模式不可虚构。root唯一写TASK，所有review代码问题与Git冲突由Sol直接修。

## 目标与验收

- 目标：各模块开放或增加 AI 操作入口，让 AI 能自主规划、操作，完成作者的目标；
  操作留痕，便于以后把常用操作代码化。
- 验收：设计稿和 ADR 写明与 ADR-0013、0023、0027、0029、0031、0032 的关系（修订 ADR-0023 的
  写入确认在目标运行内的适用）；`make docs-check BASE_REF=origin/main` 通过。

## 用户要求（2026-10-15）

- 开放或增加各模块的 agent/AI 操作入口，方便 AI 自主规划、操作，以完成用户目标。
- 操作留痕，方便后续版本将用户常用操作代码化实现。
- 评审核对后：可合并的 ADR 合并。

## 已核实现状（main `4efe7f21a`，评审核对时复查）

- 助手业务操作 47 个：world 18（含地图 4）、story 11、writing 9、imports 5、project 3、evidence 1；
  `suggest` 9 个，其余 `confirm`。
- 装配两条路径：story、writing、project、evidence、world 开篇插件为 `OPERATIONS_SPEC`，经
  `app/assistant_operation_registry.py` 物化；world 对象、世界书页、结果、共创、复核、地图和 imports
  仍导出 `OPERATIONS`，在 `app/bootstrap.py` 直接合并。
- 后端路由约 680 个，写路由约 430 个；evolution、interaction、collaboration、account、local_agent
  没有助手操作。`available_operations` 一次返回全部操作的完整 schema。
- 费用只记计费状态（`AIChargeState`），`AgentRunBudget` 记请求、工具、网页、token 和用量是否完整，无金额。
- 没有统一操作留痕，也没有前端埋点；`local_agent` 的产品工具中继已删除（ADR-0029）。

## 关键决定与理由

- 三份草案合并为一份：目录、分级、目标运行、留痕共享同一组字段和测试，地图与势力是第一个实例。
- 界面与 AI 共用一份操作目录；剩余 `OPERATIONS` 插件先收口到注册表，未声明写路由用棘轮清单。
- R0–R4 风险分级；目标运行的计划是数据，执行由确定性引擎推进；重新规划时服务端确定性比较授权范围，
  任何扩大都停下重新审批。
- 费用只记计费状态，预算与预览用请求次数、token 和时限，不估金额。
- 留痕挂在目录层；会话 ID 加数据库单调序号，不用链表；执行事件写在保存点中，失败只标“不完整”；
  不记录内容，自由文本只记长度和加盐 hash；明细 180 天后汇总。
- 外部 Agent（MCP）接入不在本轮范围。
- 用户裁定（2026-10-15 评审后）：目标运行允许作者按目标开启 R2 自动执行，开关默认关闭；
  本机单用户默认记录界面操作，公开账户默认关闭。
- 技术评审（2026-10-15，用户同意按推荐处理）：
  - 事务形态：助手用 `begin_nested()` + `flush()`（`assistant/operations.py:502`），请求结束统一提交
    （`core/database.py:148`）；但 `world/map_atlas_service.py`、`world/entity_fusion.py` 内部多处提交，
    ADR-0013 只覆盖长任务。所以目录项声明单事务或多阶段，多阶段按领域回执对账，结果未知时停下。
  - 目标运行存储：`assistant_runs.mode` 只有 `author`/`background`，活动唯一性按 `session_id`
    （`uq_assistant_session_active`）。新增 `goal` 模式、不绑定会话、停点用 `waiting_approval`、
    按项目的部分唯一索引。
  - 高频写入（`writing/api.py:395` autosave）按会话加时间窗合并或豁免留痕。

## 交付

- `docs/plans/2026-10-15-agent-operation-surface.md`
- `docs/adr/0038-ai-operation-catalog-goal-runs-and-trace.md`
- `docs/adr/README.md`、`docs/README.md` 索引

## 验证

- 2026-10-15（起草）：`make docs-check BASE_REF=origin/main` 通过；`git diff --cached --check` 通过。
- 2026-10-15（评审核对与合并后，未提交）：`make docs-check BASE_REF=origin/main` 通过（49 个 ADR 文件）；
  `git diff --cached --check` 通过；旧文件名残留扫描为零。

- 2026-10-15（写入两项裁定后）：`make docs-check BASE_REF=origin/main` 与 `git diff --cached --check` 通过。
- 2026-10-15（技术评审修订后，未提交）：`make docs-check BASE_REF=origin/main` 与 `git diff --cached --check` 通过。

## 风险与待决

- 无待用户裁定项。ADR-0038 已采纳；若其他分支先合入同号 ADR，顺延编号并同步引用。

## 2026-10-15T21:56:18+08:00 实施检查点

- runtime目录已实调用register_container_services核实64项唯一操作：assistant1/evidence1/evolution2/imports5/map11/project3/story11/world21/writing9。旧55项只是snapshot初次赋值，后续update不可漏算。A0独占bootstrap/main/registry/service_keys和Assistant既有核心；档案、提醒子代理仅提供新纯SPEC与接线需求。只新migration operation_trace_v2，最终Sol统一链。
- 仅本地提交与隔离验证授权；未push/PR/main合并/部署。无新的真实模型/私有评测根/真实数据库访问授权给这些实现代理。工程检查与真实作者验收分开报告。

- 2026-10-15T22:16:25+08:00：地图R3五Scene完成后结构任务严格目标解析失败，已正常停止封存，真实质量未通过；当前无live runner，新功能首批提交审查后可集成，后续评测需新pipeline身份，不复用旧实验。

## 2026-10-15T22:30:37+08:00 首批交付与独立审修

- A0a f7ba93e8bc5e428a8aef76b6d483ef4236049220已交Sol/high sol_review_operation_catalog（map-advisory-review/codex/operation-catalog-v2-review）；干净归档29定向/Ruff/docs通过。trace与写路由A0b WIP完整保留原Luna树，尚未提交/集成，下一批继续。共享装配还需接C3a/C0新SPEC，不能把A0a当全A0。
- root主树fd372d5f2仅任务记录提交，新两批尚未集成；代码问题由Sol直接修。本地开发继续，未推送或部署。

## 2026-10-15T22:44:27+08:00 审修集成与第二批交接

- 主树HEAD158cbe57b，TASK更新前干净。A0a修复：legacy forecast v3快照保留两字段；v7按实际操作兼容关闭；团队冻结不可执行项仍可describe；恢复地图编辑真实schema hash。root在dabc0b319跑Assistant/Imports/World相关扩大回归1217 passed（33.81s）。
- C3五真实来源的Sol修复含延后到期恢复、分页更多披露、处置读timeout、静态trace字段与demo只读写拒绝。R3未解析关系主题留在batch receipt，公开作者GET /api/evolution/reading的structure_review显示数量/内容/逐Scene证据，不猜实体、不关strict。root在158cbe57b跑统一通知+全Story+Evolution workflow为797 passed（21.61s）。C3新API/DI尚待组合根接线，不当产品闭环。
- 原A0b WIP与旧审查分支保留；Sol只读复制新目标分支且核哈希+17烟测，Luna继续实施。C0a23e进入Sol独立审修，C0b/C2 Luna并行，禁止共享文件双写。三migration链待统一，新C0/C3/trace尚未PG验收。
- R3封存停止，本批未重跑真实请求、未改实验DB/原始回执/种子或holdout。真实质量未通过、human_validated=false；本地工程绿色不等于作者验收。没有push/PR/main合并/部署。

- 文档门禁：158cbe57b的inventory通过（12模块/158表/61任务/16路由/49ADR）；直接BASE_REF检查列出CLAUDE.md、模块总览html/drawio、05_memory.md四个未改文件，root已逐项核对并用脚本支持的no-change-reason通过影响检查，理由为稳定导航/现有12模块61方向未变，A0/C3/R3不改Memory事件与checkpoint写入所有权。C0 typed state尚未集成，后续须重核并更新相关文档；不把此理由沿用到未来实现。

## 2026-10-15T23:04:48+08:00 C0a 审修集成与跨域回归

- 主树实现为b81ba6887（C0原13a11cff0 + Sol直接修复），另1d503209b补05_memory类型化来源边界；当前干净。Sol修复非空旧资料created_at默认失败、C3 ORM/迁移FK索引/时间/comment漂移、恢复Scene锚与停用facet、结构化legacy值、demo拒写、typed状态与有向态度、分页unknown、静态trace白名单；动态Story字段不回填World稳定层。
- Sol证据：58 unit；独立PG dossier_review_test_20261015 fresh升级、dossier_upgrade_test_20261015非空旧数据升级；1项独立session并发CAS/失败回滚/跨novel E2E通过。原map_enhancement_test仍map_node_merge未修改；C3两表metadata parity尚依赖A0b共享env/bootstrap notice_models显式导入。
- root在b81ba6887代码上扩大World+Story+Evidence+container/registry：2978 passed、1 skipped、2 deselected（67.62s），已存在Pydantic schema warning无新增失败。1d503209b docs inventory通过：12模块/159表/61任务/16前端路由/49ADR。未完成全分支最终门禁、真实质量或作者验收。
- 三层聚合Luna保存WIP633293ee2并接C3四提交后，cherry c99a702ae在dossier_service.py冲突；root暂时interrupt该子任务释放宿主并发槽，已交Sol直接解冲突，禁止root/Luna手改审修冲突。Luna恢复后继续Evidence聚合与C2。C3b新Luna/max在simulation-v3-director-impl/codex/copilot-unified-ui做真实提醒/ReadingFlow待核候选和缺失G8a/editorial薄来源；无UI假数据。A0b Luna继续trace与组合根，已要求本轮新C0写路由显式绑定op_id，不能放进历史豁免baseline。
- 世界对象统一三层读取/GenericEntityProfile映射、C2人物卡/UI、C3产品接线与界面、A0b/A1–A4、C4/C5均未标完成。R3封存原样、无新模型请求或holdout读取；没有push/PR/main合并/部署。

- 2026-10-15T23:10:03+08:00：C0b冲突已由Sol直接解决并完成cherry为4cb98784d，33目标测试与Ruff通过；原633293ee2聚合/Profile映射与c99安全修复均保留。root已followup恢复Luna，当前继续聚合，不再处于冲突停点。首commit要求独立可导入、不依赖尚未存在ServiceKey符号；角色视角不调用Evolution台账port，作者视角可显式读取，省略单列。

## 2026-10-15T23:20:08+08:00 A0b 提交与环境校验

- A0b原实现三笔自有提交 f9a9d8f14、87752e8fd、203018dfd，Luna目标树map-advisory-review/codex/map-operation-trace-impl已干净；C3/C0父提交已在主树，不能重复取。已交Sol/high sol_review_operation_catalog在map-assistant-review/codex/operation-trace-review，以dd13268fb为基线独立审修，含真实HTTP最终commit失败时序/PG事务/隐私/路由ratchet/装配/单head+parity。当前还未集成主树，不能标A0或产品接线完成。Sol独占工程PG65202新review DB，原库与C0两review库保留，禁止eval65302。
- 实证纠正验证环境：唯一正确解释器是 /Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/.venv/bin/python（3.14.8/Pydantic2.14.0/core2.50）；原repo/backend/.venv为3.14.7/2.13.5/core2.46.5，不用于最终验证。原环境Decimal schema多pattern导致194c，正确环境schema90aa；两树用正确解释器完整schema逐字段相同，golden未改。Luna A0b在正确环境重跑组合13pass与Ruff。C0b Luna承认早期定向误用原环境，已要求首commit前用正确环境重跑；root前述1217/797/2978全部使用正确worktree解释器，仍为有效证据。
- C0b冲突已解4cb98784d并恢复Luna，继续首个可独立导入的Evidence聚合/brief/API切片；C3b UI及G8a/editorial真实来源仍在实施。后续A1–A4、C2/C4/C5和外部门禁保留；无新真实模型请求、push/PR/main合并/部署。

## 2026-10-15T23:31:00+08:00 三层简报提交与真实 HTTP 追踪审修

- C0b首切片30d5b0698已独立提交，需连同前置633293ee2审查；C3/C0a父提交不重复cherry。新增Evidence三层聚合facade/API、只读Evolution provider与明确省略；角色投影不调演化台账。Luna已在唯一正确3.14.8/Pydantic2.14.0下跑45目标测试、Ruff/diff通过。未集成，也不等于C0/C2完成。
- GenericEntityProfile旧PUT仍直接写data_json/evidence_refs；旧GET/list与WorldBackground仍读旧表；类型转换snapshot/restore和generic→strong迁移仍需bridge。Luna继续C2卡片/Reaction后独立实现事务修订桥接、兼容读投影、未知字段/证据及转换恢复保真。不能把新增只读projection当新旧真相闭环。
- Sol在A0b真实PG/HTTP先失败后修复两个P1：main读取未赋值trace context；当前FastAPI include_router有效route派发绕过source APIRoute wrapper。已直接修并3项PG E2E通过，含成功/最终commit失败回滚/原文不入trace；其它审查仍在进行，未集成。另修任意result/preview id泄露、纯flush操作事务形态误报、新Vocabulary绑定与空间线索单项真实豁免。没有将新增写路由藏入旧baseline。
- C3b统一提醒前端及G8a/editorial纯来源继续实施，共享装配仍由A0/Sol单一写入。A1/A2源码、状态机和验证交接见操作任务artifacts/A1-A2-HANDOFF.md；C4/C5交接仍见对应任务artifacts。所有剩余阶段继续属于本次范围。
- R3和holdout未动；没有新增模型请求、push、PR、main合并或部署。主树本次仍只更新任务记录，不提前纳入未审代码。

- A0b新增进展：Sol在operation_trace_review_test_20261015验证fresh单head升级/ORM parity及4项真实PG E2E（成功/最终commit失败、included route、append-only与181天聚合删除）。180天归档原实现只在aggregate/export读时触发，闲置项目无法保证清理；Sol正在复用现有maintenance调度直接补齐，不引入新服务。当前仍未集成。

# C5/C0 组合与 C3/A1 实施检查点

2026-10-16T07:27:00+08:00，root 更新。本记录优先于三份 TASK 的此前批次历史，不新增授权。

primary 为 `05f51aaca7e965e3ade532467a24f84b74d18e59`（笔记在 `710dbce43107504104a3ed4840d63e249648b7d1` 之后）；产品 C4 为 `c579beb872e7f6193476ff4d0abd0d034810f95c`，Sol 净 PG 隔离 fixture 已合入。普通后端 8919、保留库 45 PG、同源前端 3182 与 lint/build/docs/repo gates 通过，日志及截图见 C4-C5-HANDOFF。当前无运行中的 root 验证进程。

用户要求三份计划全部实施，Luna/max 实施、Sol/high 独立审查并直接修复，root 负责协调/集成/验证/记录及隔离真实评测。仅本地提交；无 push/PR/main 合并/部署授权。宿主仅 root 加三个活动子槽。不重建专库，不安装/同步依赖。

## C5 Sol 固定点与 C0 顺序装配

`sol_review_world_progression` 在 `.worktrees/map-clue-review` / `codex/world-progression-review` 已形成干净固定点 `10db18e19297e6d5d139c04728763c6db1ecfef0`，含九项新操作/v14、TaskRegistry/HTTP/NOTICE/Flow/worker/DI 装配、真实阅读计数与同根 R4 恢复。前端 3187、lint/build/docs 和原 12000 token Goal PG 规划通过；全量后端和最终浏览器待回报。不能用早期定向测试代替组合验证。

root 发现原 MAX 发布章号差不符合“每读入若干章”，Sol 已撤销 Writing 发布触发，改为 Evolution live 成功且 applied 的冻结 Scene 回执、完整正文覆盖和当前 canonical draft UUID/hash/offset 投影。Story 授权记录已见逻辑章节，重读改版章不重复计数。查询仅处理未见章节，批量读 receipt/frozen payload 和候选 canonical，避免每次加载全部正文。后继 `20261016_wp_read_count` 在 `world_progression_review_test_20261016` 增量升级及 ORM parity 通过，未重写已用 DDL。

实际 PG/Worker：第一/第二个 Scene 投影为空/[1]；第 5 章只多计一章，旧来源失效不算成功。成功 receipt 与免费 coalesced outbox 同事务，回滚不留任务；重复、仅发布未读、开关关闭和撤销不产生付费推进。实际 R4 HTTP 恢复保持原 root/started_at/deadline，原角色已完成而导演 unknown 时仅重做导演，新 unknown 再停，累计 started/unknown 不清零。root 已读以下原始日志：

- `/tmp/world-progression-read-projection-20261016.log`
- `/tmp/world-progression-receipt-outbox-20261016.log`
- `/tmp/world-progression-resume-20261016.log`
- `/tmp/world-progression-resume-new-unknown-20261016.log`

模型边界为 offline LLMClient，不代表真实质量或作者验收。root 另读出合法低额度时预算预览最小值可大于最大值；Sol已直接改成完整需求估算、明确不足提醒，三种极低额度模式回归3/3通过，没有截小所需成本假装可完成。

C0 独立 Sol 干净 `008d515a07aaa13f09cb69624ee897a068b2d8df` 已在 C5 无冲突合为 `0b1ec254d`。v15 总目录含四 borrowed/manifest 与九 C5 操作，目录/路由 ratchet19项通过；<=14冻结保留，最终Goal预算/全套/browser仍待回报。World facade保留C5 `read_map_progression_state`与C0模板再出口。原C0专库 `dossier_template_interchange_review_test_20261016` 已核旧head `20261016_operation_trace_archive_days` 并增量升级至 `20261016_wp_read_count`，ORM parity及原C0两PG通过，没有CREATE；日志 `/tmp/c0-c5-transfer-upgrade-20261016.log`、`/tmp/c0-c5-transfer-pg-20261016.log`。18598/18599此前已停，合成数据保留。组合尚未交root集成。

共享顶层、keys/bootstrap、总 Story facade、Assistant 普通目录/服务、api.js/story.js、World hub、Evolution facade/store/tasks 均归该 Sol 单写。Writing api/facade/draft_service 已释放 A1；C3 只写 Evolution notice 来源。

## 两名 Luna 并行实施

`luna_copilot_alignment` 在 `.worktrees/simulation-v3-director-impl` / `codex/copilot-mechanism-alignment-impl` 从已审 c579 实施真正 forecast v2、人物弧作者计划/实际与 Evolution 阅读提醒。实际 Scene/World/Evidence → POV → TaskWorker → ForecastCandidate/feed → Writing 预览已由 SQLite 目标行为验；旧 v1 Candidate 仍可读，真实 evidence ID/逐字 quote 缺失在执行路径拒绝。人物弧/notice 仍在实施，尚未 PG/浏览器/独立 Sol 审修。Imports 默认替换门禁未满足，保留旧入口。`copilot_alignment_impl_test_20261016`、18600/18601 已分配但尚未创建/启动，等待 C5 最终线性头。

`luna_chapter_order_timeline` 在 `.worktrees/map-assistant-vocab-review` / `codex/chapter-order-timeline-impl` 从已审 02fa 实施全版本 Writing 章节重排/CAS/R3/恢复及一般 Story 事实时间线。保留 draft UUID/hash/版本；Story 绑定变更经公开 DI，不准 Writing 跨域改 ORM。不可变历史不重写；计划绑定不能笼统忽略，未知或非连续区间需准确冲突预览/重规划。重排和恢复同事务调用唯一 `STORY_INVALIDATE_WORLD_PROGRESSION_FOR_REORDER`，撤销持续授权且不重置预算/历史，不复制 ServiceKey 名称或静默省略。`chapter_order_timeline_impl_test_20261016`、18602/18603 已分配未建/启动，同样等待线性头。两个 Luna 交具体 hub exports/DI 清单给后续 Sol，不争写 api.js/总 facade。

## 下一步与真实门禁

先由C5 Sol完成最终backend/frontend/HTTP/browser/Goal预算/gates并固定干净提交；root核证预算预览修复与C0 v15组合后无冲突集成并验组合。其后安排C3/A1迁移顺序、Sol独立直接审修和集成。两个未建库仍hold，不猜父头。

C1 长篇、M5 势力路线图、RP Interaction 质量、A4 数周真实用量和真人作者验收未满足，不用合成测试规避。真实地图 R3 诊断封存，holdout 不解码/运行；本批无新真实模型请求。后续只在最终固定代码重检 pipeline/owner/范围预算，沿用“模拟作者显式指定 Scene 地点”口径，不盲续旧 51 次额度。

## 2026-10-16T07:34:15+08:00 增量恢复

primary笔记已本地提交 `3d89440d5cdb2c5f8850a1bd2fa990bbbc676624`，产品仍为已验710/C4。C5+C0组合首次完整普通后端为8944通过/14失败/2跳过/8 deselected/1既有warning（343.37s），`/tmp/world-progression-c0-c5-full-backend-20261016.log`；旧`world-progression-backend-full`曾中断，仅1667项通过，不当完整证据。Sol正直接修目录/任务/能力/HTTP登记、旧版本预期、模板预览与实际采用差异及测试隔离。依赖function_level_imports为518>517，必须消除而不能抬基线。最终组合全量尚未通过，禁止提前集成。前端组合3191/lint/build已通过；组合PG12与v15原12000预算Goal PG1通过，原始`/tmp/world-progression-c0-c5-pg-combined-20261016.log`及`/tmp/world-progression-goal-catalog-v15-pg-20261016.log`已由root读取。

root已实际看1280推进历史及390加载后历史/备注截图：`/tmp/world-progression-browser-history-visible-1280-20261016.png`、`/tmp/world-progression-browser-stale-409-390-20261016.png`。原始`/tmp/world-progression-browser-history-check-20261016.log`证明两宽度各1root/1step、键盘聚焦保存、stale409保留输入、errors=[]；页顶loading截图不当加载完成证据。带可见409及unknown恢复控件的补图尚待Sol。

Sol已确认最终schema头固定`20261016_wp_read_count`，后续C0/v15/预算修补无DDL。root因此正式释放C3的新库一次CREATE/升级；线性次序为C5 → `20261016_story_character_arc_plan`（heads+immutable revisions两表）→ A1 `20261016_chapter_order`（Writing operation+Story receipt两表）。C3先提交自有恢复checkpoint `3b494b91d`，无冲突合10db为`c8f1a5dc8d06390428e656891177f8362912cf30`，已开始迁移源码；尚未回报库创建。A1库仍hold，等C3迁移真实提交再释放。不能把C5 schema释放等同其最终工程全绿。

已知C3独立Sol待修：root读取其checkpoint发现`character_arcs/service.py:_trace`直接依赖`modules.assistant.contracts`并复制AssistantOperation物化，违反纯域装配方向；已告知Luna留给Sol直接审修、不扩大该依赖。C3及A1手工恢复都需真实restored trace并关联原`(op_id,call_id)`；当前HTTP adapter只支持prepare/execute，Goal已有自己的restored生产者。只生成新restore操作随机call_id会成为报表unmatched，不能据此声称原操作已恢复。两Luna交精确trace/DI/hub清单，后续Sol顺序处理共享装配。

root已准备仅复用脚本`/tmp/map-c5-c0-primary-reuse-pg-20261016.py`（0600），**尚未执行**；仅允许原root库C4或wp_read_count头，不含CREATE，待最终C5+C0集成后升级/parity并在原45PG基础增加C0互通和C5持久/阅读测试。后端唯一解释器仍primary/backend/.venv/bin/python，秘密env不输出。所有旧库/封存R3/holdout保留。

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

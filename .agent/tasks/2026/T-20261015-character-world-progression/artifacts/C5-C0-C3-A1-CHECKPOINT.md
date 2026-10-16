# C5/C0 组合与 C3/A1 实施检查点

2026-10-16T08:02:20+08:00，root 更新。本记录末尾最新检查点优先于三份 TASK 的此前批次历史，不新增授权。

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

已知C3独立Sol待修：root读取其checkpoint发现`character_arcs/service.py:_trace`直接依赖`modules.assistant.contracts`并复制AssistantOperation物化，违反纯域装配方向；已告知Luna留给Sol直接审修、不扩大该依赖。另`forecast/registry.py defaults('scene')`将原人物反应+转场改为仅人物反应v2，未经授权移除原转场默认能力；需Sol核实际混选/默认共存，不能以删旧能力规避v2结构输出。C3及A1手工恢复都需真实restored trace并关联原`(op_id,call_id)`；当前HTTP adapter只支持prepare/execute，Goal已有自己的restored生产者。只生成新restore操作随机call_id会成为报表unmatched，不能据此声称原操作已恢复。两Luna交精确trace/DI/hub清单，后续Sol顺序处理共享装配。

root已准备仅复用脚本`/tmp/map-c5-c0-primary-reuse-pg-20261016.py`（0600），**尚未执行**；仅允许原root库C4或wp_read_count头，不含CREATE，待最终C5+C0集成后升级/parity并在原45PG基础增加C0互通和C5持久/阅读测试。后端唯一解释器仍primary/backend/.venv/bin/python，秘密env不输出。所有旧库/封存R3/holdout保留。

随后Sol已直接修14失败的根因，失败集26/26通过，方向棘轮恢复517/517且repo gates绿。免费阅读检查任务移入可发现的_tasks模块、C5能力/active-project登记及_api边界修复；offline Worker用自有SQLite引擎避免写错全局测试manager。C0预设preview与apply统一版本计数并保留20词条限制，不更新错误预览去掩盖写入差异。最终PG组合12/12再过（2.49s），`/tmp/world-progression-c0-c5-final-pg-20261016.log`已读；第二轮完整普通后端`/tmp/world-progression-c0-c5-full-backend-final-20261016.log`仍运行。root已实际看`/tmp/world-progression-browser-unknown-resume-390-20261016.png`，原日志`/tmp/world-progression-browser-unknown-20261016.log`证明390/1280未知根恢复按钮可见、无浏览器错误；恢复确认源码显示原预算、deadline与当前未知数及可能重复计费，不静默续跑。

最新更正：上述第二轮也由Sol主动中断（3597通过/122.62s），不作完整通过。原因是真实浏览器已写章节/Scene预算preview又暴露缺模型配置500及读取StorySceneContextResponse顶层不存在scene_index；Sol正直接修成可操作409与正确上下文字段，并补真实Project/Writing canonical/Scene/World入口回归，不能仅mock Context/direct造root。源码固定后再跑一次完整门禁，无真实完成exit0不集成。root没有终止其进程或改其源码。

C3现已回报核验0600工程env后，确认不存在才一次CREATE `copilot_alignment_impl_test_20261016`，并实际upgrade至未提交的`20261016_story_character_arc_plan`；没有启停服务，专库保留。该已应用迁移冻结，后续约束修补须新增独立迁移。为防分叉，A1的库与apply继续hold到C3独立Sol确定最终DDL头后，不能只按Luna初稿parent提前apply。A1可继续SQLite/HTTP/UI及迁移源码，等待不阻止独立实现。

C3真实PG3项和范围核验SQLite2项/parity已由Luna自查通过；root又发现已应用Arc迁移仅按trigger深度放行head/revision删除，存续Project下nested/TEMP可绕过，与C5此前同类问题相同。该第三项root finding已明确交Sol以新后继迁移直接修，不能重写已用DDL或用现有3PG声称覆盖。Luna确认没有覆盖nested/TEMP。具体三项finding与后续审修边界已保存[C3尾项交接](C3-ALIGNMENT-TAIL.md)。

## 2026-10-16T08:02:20+08:00 已集成 C5/C0，下一批审修

C5 Sol最终净提交为 `339d43eded2e96ce8dda9f885bd1a52beccdcf21`，不是上文中断的全量进程。固定源码后普通后端实际exit0：8959通过/2跳过/8 deselected/1既有Pydantic warning，326.95s，RuntimeWarning转error；`/tmp/world-progression-c0-c5-full-backend-exit0-20261016.log`。同点前端254文件3191项、lint/build/docs/repo gates与517/517方向棘轮通过；前端日志 `/tmp/world-progression-c0-c5-full-frontend-final-20261016.log`。

真实入口永久PG `test_world_progression_real_entry_postgres.py` 使用实际Project、published canonical Writing、Story Scene0及World对象，实际HTTP预算200→Evidence确认→stale预算409且零root→start202→精确TaskWorker；仅模型client为离线替身，实际2调用/1持久Step。Sol修正Scene0真值判断、嵌套SceneContext字段、bare World身份/来源、root先flush避免PG复合FK以及task.meta novel_id。新增Assistant窄Scene/参与者/排除/原确认负例与同Scene正例。测试账户的临时验证连接和默认偏好按全部原列finally恢复，不解密或打印秘密。固定点12组合PG日志 `/tmp/world-progression-c0-c5-final-pg-fixed339-20261016.log` 已读。

root无冲突合339为primary `d624bde723bb8b4856ed63cc500b2b301f9b3671`，并用git diff证明backend/frontend-console/docs与审修固定点完全相同，沿用其完整同源普通后端及前端证据。root已执行预备的无CREATE脚本 `/tmp/map-c5-c0-primary-reuse-pg-20261016.py`，在原 `operation_trace_report_primary_test_20261016` 从C4增量升级至 `20261016_wp_read_count`，head/ORM parity与15文件57PG全部通过（21.03s）。日志 `/tmp/map-c5-c0-primary-{migration,head,metadata,pg}-20261016.log`；保留原数据，不重建。root已实际查看390/1280的real-preview图；对应日志证明两宽度真实HTTP preview200、1参与者、errors=[]。C5的18594/18595已停，C5/C0专库同wp_read_count头均保留。

root集成后的docs-check/repo-gates也实际exit0：`/tmp/map-c5-c0-primary-docs-20261016.log` 与 `/tmp/map-c5-c0-primary-repo-gates-20261016.log`。没有扩大依赖棘轮（61/9/0/517）；两个既有文件超3000行仅warning。此次没有新后端普通/前端源码差异，因此不重复同源全套。

C3 Luna继续人物弧/forecast v2/Evolution只读notice，已报告notice真实task失败与撤回canonical后提醒保留、cutoff/改稿fingerprint和无queue副作用的2PG及83前端定向通过；纯notice/Arc路由尚待共享hub组合。root登记的第四项为Arc pureSPEC忽略可信work/原确认范围，和前三项一起交Sol，不由Luna改root审查finding。Sol当前已在map-clue-review从d624建 `codex/copilot-alignment-review`，先只读独立审查C3 WIP，收到Luna净提交后再由root释放直接修复；不并发写原树，不提前应用DDL。

A1 Luna净领域checkpoint `003f809dd4fb8a48d3a4b7f3d591d08a77936d52` 曾因纯SPEC未装配而无法导入应用。root暂停其写入后由Sol独写该树：合339为 `4a1fc13fa`（数据库文档冲突保留两侧表），净装配 `fe5bc6247`；后继v16物化三Writing章顺序操作和一Story事实时间线，旧v15保留，唯一core `story.chapter_order`及Story continuity facade/前端storyTimeline已接。应用DI、Assistant30/route8/API14及ruff/lint/docs/module gate通过；领域尚3失败，不能当A1完成。Sol已释放写权，root正式恢复Luna领域/Git自查；专库仍HOLD到C3独立Sol最终DDL头，尚未CREATE。

A1下一Sol另需直接审修跨操作历史投影：当前 `_current_chapter_index` 按receipt逐一紧邻应用map/inverse；两个非交换重排A/B后、恢复B/A时，期间新增事件会错误按inverseA→inverseB投影。应先实际复现再按全局操作时间处理，不能重写不可变历史。该问题与scope/restored原调用关联由Sol修；现有旧页99前端通过不能替代新增modal/timeline交互。MemoryService/EventRepository复用、SceneSpan哈希与非连续区间、owner/cutoff/paging/source组合及PG并发仍需独立检查。

真实地图R3仍封存，holdout不解码，本批零新真实模型请求。C1长篇、M5势力路线图、RP协议、A4数周真实用量与作者验收仍未满足。下一步是C3净提交→Sol直接修复/安全后继DDL/真实组合→root集成，再按最终线性头放行A1 PG与独立审修。

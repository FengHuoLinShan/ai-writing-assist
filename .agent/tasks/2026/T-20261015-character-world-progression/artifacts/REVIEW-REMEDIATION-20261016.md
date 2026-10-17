# 外部 review 主会话复核与修复

- 来源：主仓库 `out/map-enhancement-review-20261016.md`，报告基线81785cd16；接管基线99bc9ce1c，工作树初始干净。
- 授权：用户于2026-10-16明确要求并行完成剩余17项，排除真实验收类；实现使用独立worktree并由主会话集成。保留五族R6及其他封存评测，未经真实质量验收不开能力门禁。无推送、合并main或部署。
- 报告作为线索，需在当前代码核实。U1–U3已被报告自身复核推翻，当前不按其原指控改代码。
- 已核实：Ruff实际为一处import排序错误；imports并发用例单跑通过，评测fixture会缓存并发2且未清理，补测试级环境/缓存清理后需组合验证。
- 当前汇总：剩余17项已实现并完成各自定向工程验证；其后复核报告提出的8项也已本地补修并通过定向验证。整套`make test-ci`中9088后端测试通过、2跳过，但总覆盖率84.37%低于85%门槛，不能宣称CI全绿。累计47项修复与L25复核结论仍按下方历史账本；真实质量/作者验收仍未完成，地图能力门禁不开放；[剩余问题交接](REVIEW-HANDOFF-20261016.md)保留原始问题与验收边界。

|报告ID|状态/验证|
|---|---|
|H1|已修：evals/tests 自动 fixture 先还原环境再清 Settings 缓存；并发用例组合及最终全量9044通过。|
|M1|已修：assistant_operation_registry import 排序；全 backend Ruff check通过。原报告退出码2/无输出不等于具体语法诊断。|
|M2|已修：精确revision跳过201批次预载；候选身份按作品批量回读并局部缓存融合链；SQL先筛选相关词条身份、保留作者后续历史，2000修订上限明确truncated/missing。SQLite范围/截断、PG两例与全World/evals通过。|
|M3|已修：role 64字符领域前置校验覆盖新增/预览/更新/恢复；API与真实PG的64成功、65拒绝及当前修订保留通过。|
|M4|已修：六类strong Profile与Dossier按冻结字段清单双向同步；Profile写、Dossier编辑/恢复与清除沿原事务语义留修订；JSON保留原型，秘密/动态字段不越界。6类型真实PG桥接用例及World单测通过。|
|M5|已修：角色读取传 visible_fields，按显式 Story/legacy/Generic 字段键及值筛选；相同文本不能证明其他字段。真实World与Evidence测试通过。|
|M6|已修：manifest v2受控携带legacy key、Generic key与原类型值，未映射值留秘密兼容区；仍支持v1导入。World单测与PG manifest interchange通过。|
|M7|已修：按receipt转换链与created_at投影当前章序，统一列表/count/max/keyset/回放/snapshot；保留原事件章号与锚点，超过500候选失败关闭。定向Story测试与章节并发PG通过。|
|M8|已修：导航卡缺少candidate_id时在IO前返回 NOTICE_NOT_ACTIONABLE/409；不再解析UUID(None)。|
|M9|已修：新增只读限长领域回执预览及带revision的applied/not_applied/still_unknown核对；服务端决定时重读原任务回执，不重放/重置/退还未知用量。Goal单测、HTTP与restore PG通过。|
|M10|已修：object_dossier/character_pattern 加入SECTION_DIMENSION_MAP；两维度预算省略不阻断的参数化测试通过。|
|M11|已修：不再清空反应组来腾容量；超限保留内存与上次备份、标备份未完成。部分多文件备份也标不完整；取消96条截断，105条决定完整恢复测试通过。|
|M12|已修：移除previewHook finally中的导演草稿重置；钩子预览成功/失败均保留手输假设与既有预算的组件测试通过。|
|M13|已修：档案展开后保持挂载，折叠不丢编辑/模板；dirty仍传离开守卫。实体切换已走query也参与的router canLeave，新增同页entity_id切换拒绝测试通过（未发现需另加确认的第二条绕过路径）。|
|M14|已修：模块文档与README同步当前v17及安全章节重排/事实时间线只读边界，历史v11/v16标为批次。|
|M15|已修：统一提醒文档同步11源；实际11源HTTP/PG组合测试通过，来源故障占位/处置/隔离仍保留。|
|M16|已修：约600行HTTP留痕适配迁入Assistant模块，app/main只安装；保留route dispatch、事务/回执与缺口标记。Assistant route、trace/report及导演HTTP PG通过。|
|M17|已修：权威Prompt清单增加story.scene_director、story.world_progression、assistant.goal.plan，写明实际入口、输出、来源/预算和候选边界。|
|M18|已修：STORY_SCENE_DIRECTOR_ENABLED默认false，配置/示例、API依赖、内部提交/续算、领域操作、worker及助手可执行目录均检查；UI关闭状态保留输入，可刷新。关闭前IO拒绝与开启工程PG通过。未开启真实评测或生产开关。|
|M19|已修：人物合并先读当前档案投影，再经legacy revision写回并更新Character；无Character目标迁移也建立兼容档案。真实SQLite读取新旧档案合并内容通过。|
|L1|已修：CreativeExperiments确认说明显示作者可读能力名，未知项回退友好文案；参数不变，前端全套通过。|
|L2|已修：隐式线索查询limit 20001，超过20000显式拒绝，不静默截断；同一校验按Scene/索引/完整binding缓存当前源、按引文缓存精确区间，仍逐条核复核哈希/端点/截止点。63定向与1975 World/evals通过。|
|L3|已修：create/create_or_merge/update/review_edit按最终状态校验validity与同项目锚点；正式关系降级须同请求显式清除区间。World定向单测通过。|
|L4|已修：scaffold刷新区分缺省与主动清除；作者secret不因未提供的scaffold值被擦除，清除仍走Dossier修订。World/Character定向单测通过。|
|L5|已修：API删除先读分支身份，再锁root→branch；PG实际争用后worker取得branch并完成，无ABBA。|
|L6|已修：advance apply重新检查active project；停用项目在parent读取前失败的负例通过。|
|L7|已修：导演提醒来源docstring同步实际登记。|
|L8|已修：SQLite跳过PG advisory lock，并覆盖保存/CAS冲突/恢复/归档/取消归档；Story单测及角色弧PG持久化通过。|
|L9|已修：地图证据错误提示统一简体。|
|L10|已修：rescan先核对run/operation/attempt/task绑定；缺失或未知状态失败关闭，不补发模型请求。Evolution定向单测通过。|
|L11|已修：map_source来源内部active-project门禁前置；拒绝时不执行正文来源读取。|
|L12|已修：Evolution成功receipt需要read-check DI；缺失时事务失败，明确no-op仅由测试DI提供。Evolution定向单测通过。|
|L13|已修：默认类型与档案类型经同一normalize_entity_type；concept/空格大小写三例通过。|
|L14|已修：迁移docstring Revises同步真实object_dossier_v2，未更改DDL或迁移链。|
|L15|已修：conftest显式钉住trace实际默认true并纠正“所有布尔默认false”的注释；新增导演false也钉住。配置守护与全量通过。|
|L16|已修：11源PG测试使用独立随机owner，绑定真实principal，只清本次project/两个随机账户；不再删除共享BOOTSTRAP账户。|
|L17|已修：用reader实际PG PID及pg_blocking_pids证明归档锁争用，释放前断言读取未完成；PG通过。|
|L18|已修：evals/tests按例隔离缓存，退出先撤销monkeypatch再cache_clear；原imports并发失败不再出现。|
|L19|已修：续算预览前确认父回合/分支仍存在；历史刷新丢失父回合时保留输入、无API调用和TypeError的组件负例通过。|
|L20|已修：档案有效期和对象身份使用真实名称/缺失说明，保留内部导航/stale；对应前端组件测试通过。|
|L21|已修：地图候选确认明细不再显示raw term/revision/Scene UUID；固定修订提交值不变，前端测试通过。|
|L22|已修：别名/对象历史有效期显示可读名称与缺失/stale文案；前端测试通过。|
|L23|已修：UnifiedNoticesPanel挂载断言stale直接显示“依据已变化”并检查定位动作；前端测试通过。|
|L24|已修：ADR索引及0025同步地图简报已接线、能力默认关闭与真实验收未通过。|
|L25|复核不成立：DirectorBudgetPreview/Start/Continue均rounds int ge=1，UI两处连续轮数，worker range(rounds_requested)逐轮持久化并共用累计预算。Literal[1]仅DirectorAdvanceRequest快捷推进一轮；旧one-click单轮限制不否定独立导演N轮入口。无需放宽快捷操作授权。|
|L26|已修（文档漂移）：现有_bridged_generic_value_visible已校验fact.field==field_key，既有错字段负例仍通过；删除计划中的过期缺口声明，并同步本批角色字段筛选。|
|L27|已修：auto_r2下R3与非allowlisted R2停在step_review且无副作用；R4仍保持不可用，Goal单测与PG通过。|
|L28|已修：仅待办限定字段和档案版本编辑继续自动恢复，均要求同事务manifest与领域CAS；其余R2仍人工，Goal单测与restore PG通过。|

## 第四批：复核报告8项补修

- 时间：2026-10-16T18:16:50+08:00；针对固定范围 `dd9946dd0..59537b4cb` 的新增复核。目标分支仍为 `codex/map-enhancement-plan`，HEAD=`59537b4cb376da20b67cd8152f4cca3ba6f286d0`；补修均为未提交本地改动。

|编号|补修与证据|
|---|---|
|1|五种生产任务适配器回执引用都带稳定 `operation_id`，覆盖写作生成/定向返修、智能去重、Story人物卡/反应预览；旧引用仅在task_id、task_type和冻结步骤指纹仍匹配时补全缺失字段。适配器测试及Goal回执测试通过。|
|2|Goal Runs面板对incomplete/unverified/stale回执保留重新读取入口，并在刷新时清空旧预览缓存；对应组件测试通过。|
|3|Scene重提取更新事件当前章节绑定时同步刷新投影基准时间，避免旧章节重排回执再次转换已重提取的chapter_index；新增重排后重提取回归通过。|
|4|Profile显式空字符串清空现在在同一Session/事务内将强档案列设为NULL并同步Dossier清除修订；HTTP/历史回归通过。|
|5|档案编辑器支持数组型 `legacy_value` 的结构化修改，保存类型化数组及对应展示文本；create/edit操作schema升至v3并同步快照。前后端回归通过。|
|6|强档案旧字段校验从ORM列读取varchar长度，预览与写入共用；128字符通过、129字符在两入口拒绝。|
|7|失败/取消任务状态本身不再被视为未应用证明；仅接受适配器明确的 `not_applied`，另对首次领取前取消且无attempt/start/result/error的任务生成明确生命周期证明。Goal负例/正例通过。|
|8|地图类型差异按项目ID与固定revision_id读取原词条名称和修订号，候选/冲突明细展示真实前后名称；同项目API与Vue回归通过。|

- 验证：受影响后端定向141 passed；保留工程PG `operation_trace_report_primary_test_20261016` 上Dossier E2E 3 passed；全后端9088 passed、2 skipped，但覆盖率84.37%低于85%门槛，`make test-ci`退出2；全前端257文件/3229 passed，ESLint、生产构建、Ruff、25个改动Python文件格式检查、`make docs-check BASE_REF=origin/main`、`make module-import-gate`、`make repo-gates`和`git diff --check`通过。Vitest日志含一次localhost:3000 ECONNREFUSED输出但无用例失败；repo-gates有Goal Runs/context compiler两条文件长度warning。
- 未验证/交付边界：未运行模型、真实稿件/作者质量或真人浏览器验收；未运行完整PG套件、通用outbox worker；未commit/push/PR/main合并/部署。覆盖率门禁是当前唯一确认未通过项，未对比基线以判断归因，不能宣称CI全绿。

## 第五批：四项P2与清单前端回环

- 时间：2026-10-16T19:01:43+08:00；用户针对最新4条P2明确要求“修复”。主会话在 `codex/map-enhancement-plan` / HEAD `59537b4cb376da20b67cd8152f4cca3ba6f286d0` 的原有WIP上独立执行，未使用子代理，未提交或执行远端操作。
- Scene：`EventRepository.replace_scene_events` 的键匹配与旧槽位匹配均在写入当前章号时刷新 `created_at`，保留事件ID/槽位。新增两例先红后绿，覆盖重排后列表、计数、时间线及Panorama回放；第四批旧测试实际只覆盖chapter替换路径，本轮已补齐Scene路径。
- Generic：manifest预览同时按目标 `legacy_field_key` 读取既有修订并纳入预览指纹。同名字段属于其他条目组时返回既有 `target_group_collision` 冲突，拒绝写入；作者显式跳过可继续。HTTP覆盖第2版、清空修订、过期预览、拒绝写入和跳过后历史不变，专用PG再次验证目标链不产生竞争分组。
- 数组：编辑时保留原元素模板，空的 `_entity_ids_json` 仍使用字符串；字符串项可移除，清空后重加不变成对象。保存数组只提交 `legacy_value`，后端沿用已有派生文本逻辑，界面继续使用可读标签。覆盖名称/说明对象数组、无名称键的resource/amount对象数组、空/非空字符串数组。
- Chromium另复现既有文件导入只接受v1，而服务端导出v2；同调用链补齐v1/v2显式允许列表，新增未知版本拒绝断言。两项浏览器测试最终通过，含390/1280宽度、v2下载导回、字符串清空重加及对象数组实际保存回读。
- 验证：定向后端105 passed；编辑器+清单组件21 passed。`make test-ci TEST_WORKERS=2` 中部署合同324 passed、依赖审计和Ruff通过，全后端9092 passed/2 skipped/11 warnings，但总覆盖率84.37%低于85%，命令退出2，未削弱阈值。随后单独完成其未执行的前端层：257文件/3234 passed；最终ESLint通过。独立原生PostgreSQL档案E2E 7 passed；Chromium 2 passed；`make docs-check BASE_REF=origin/main`、`make repo-gates`、`git diff --check`通过。repo-gates保留Goal Runs/context compiler两条原有长度提示。
- 环境与证据：沙箱内PG初始化及Chromium启动分别因共享内存/Mach端口权限失败；经自动审批后仅对本轮临时实例运行。专用PG位于 `/private/tmp/map-review-test-pg-1zzoo1hj`，数据库 `map_review_test`，已正常停止，日志/数据保留；未访问原工程库、Guimi验收库或封存评测。命令日志：`/tmp/map-review-fixes-test-ci-20261016.log`、`/tmp/map-review-fixes-frontend-full-20261016.log`、`/tmp/map-review-fixes-postgres-20261016.log`、`/tmp/map-review-fixes-browser-final-20261016.log`、`/tmp/map-review-fixes-repo-gates-20261016.log`。
- 交付边界：上述修复及文档仅本地，保留其余WIP；未运行真实模型、真实稿件或真人作者验收，未启动业务worker，未commit/push/PR/合并/部署。CI覆盖率门禁仍未通过；不把工程与合成浏览器证据当作原计划的产品质量验收。

## 第一批验证与恢复

- 最后核实：2026-10-16T14:41:14+08:00
- 全后端：9044 passed、2 skipped、8 deselected、1项既有Pydantic schema warning（316.87s）；未隐藏RuntimeWarning。随后新增两项导演入口负例，含当前人物合并/表格规划的195定向项通过。
- 全前端：257文件/3217项通过，lint/build通过。随后新增父回合缺失负例，SceneDirectorPanel全12项通过。
- 保留工程PG65202、operation_trace_report_primary_test_20261016：6文件24项通过，含新role长度/锁争用、实际11提醒源、归档读取争用。未升级/重建数据库，未访问真实评测65302。
- 全backend Ruff check、34个本批Python文件format、diff检查、docs-check BASE_REF=origin/main及repo-gates通过。全仓format探查发现160个既有非格式化文件，未批量改写；它不是本次lint成功声明的对象。仓库门禁原2项文件长度提示保留（goal3990/context3085）。
- 日志：/tmp/map-external-review-batch1-final-backend-20261016.log、final-focused、pg、final-frontend-full-tests/lint/build、director-tail、router、docs、repo-gates同前缀日期文件。
- 当前Map pipeline：e4936c97fd00e0862859ae8bd81b28e9647448741bf6eeb1d107b656317a1607。R6原a3ad、各封存根/回执、17个pending outbox及holdout原样；本批无新真实模型调用。
- 下一步先处理M2有界精确评测读取、M4强Profile收敛、M6交换，再处理M7事件重排与M9未知结果核对、M16编排归属；low逐域并入相应批次。每批验证后本地提交；无push/PR/main合并/发布/部署。

## 第二批：M2/L2 性能与有界读取

- 时间：2026-10-16T14:53:23+08:00；第一批固定点5ce9b693ade489161dcf2c51ce66abaf008ff86f，第二批仅主会话改Map源码、测试和说明。
- 精确修订读取不再扫描最新201批，图元身份先按本作品一次回读；融合目标按需读取并共享本次局部缓存。旧一般列表仍保留200批分页披露。
- 相关词条先在SQL中按evidence Scene召回身份，再保留身份完整历史；文本召回仍用精确Scene字段复核，超过2000修订的下界披露为truncated/missing/omitted>=1，不冒称完整来源。
- 隐式全范围与显式选择统一20000线索上限，超过上限要求缩范围。缓存只覆盖单次校验的相同Scene/索引/完整绑定与精确引文；不跨事务/调用，不缓存端点权限、独立复核判断或失败，不放宽来源模式/范围/哈希。
- 验证：63定向通过；全部World+evals为1975 passed、2 skipped、1 deselected、1项既有Pydantic warning（87.80s）；新增PG文件两例在保留工程库65202通过，验证JSON过滤、作者移除证据后的历史、边界截断与无领域写入。Ruff/check-format/diff、docs-check及repo-gates通过。第一批整套9044后端/3217前端+12尾例/24PG是上一固定点证据，不冒称本批全后端重跑。
- 日志：/tmp/map-external-review-batch2-focused-20261016.log、world-evals、pg、docs、repo-gates同前缀日期文件。
- 当前Map pipeline=df32dbcf8c4779cbe03b1ebbfc71b5bc7e477bed355f6a47a65030f31a4c05ea；旧R6及所有封存运行不改绑、不重放，无新模型调用。未访问评测库65302或holdout。
- 累计30项已修、L25一项复核不成立；17项继续：medium M4/M6/M7/M9/M16，low L1/L3/L4/L8/L10/L12/L20/L21/L22/L23/L27/L28。U1–U3仍是报告自身未通过的指控，不计为待修。
- 下一步：先按registry及现有迁移映射实现六类强Profile↔Dossier稳定字段双向收敛（M4），覆盖标量/JSON/秘密/显式清空与事务回滚；其后M6 manifest桥接信息保真。不得为收敛而把地点控制者/持有者等动态字段回填World稳定层。其他未完成计划/真实质量条件不变。

## 第三批：剩余17项工程修复与集成

- 时间：2026-10-16T16:40:12+08:00；按用户最新要求并行实施，8条隔离worktree从`dd9946dd0caf5d842d4421d7949e7f14a3a6b44a`分域完成，主会话审阅并按序集成。
- 目标分支`codex/map-enhancement-plan` HEAD=`59537b4cb376da20b67cd8152f4cca3ba6f286d0`。10个本地集成提交：`6d5ef698f`/`c1d4779a4` (M4/M6/L4)，`128ce321f` (L3)，`ebf654c00` (M7)，`42f0759a5` (L8)，`6620d2dc9` (L10/L12)，`390aeeb61`/`5a1a31cb8` (M9/L27/L28)，`5339b7d97` (M16)，`59537b4cb` (L1/L20–L23)。
- 工程验证：目标后端定向单测187 passed；保留PG `operation_trace_report_primary_test_20261016` 上11个E2E文件59 passed（包括六类strong Profile↔Dossier PG回归、跨项目manifest v2 JSON回环、章节重排、角色弧、Goal HTTP/restore/locking、trace/report与导演路由）；Vitest 257文件3226 passed；frontend lint/build、Ruff、`make docs-check BASE_REF=origin/main`、`make module-import-gate`、`make repo-gates`、`git diff --check`通过。没有运行真实模型、真实稿件、作者/浏览器验收或通用outbox worker。
- repo-gates保留两条文件长度warning：`goal_runs/service.py` 4502行、`evidence/compilation/services/context_compiler.py` 3085行；前端Vitest日志另有一次`localhost:3000`连接拒绝输出，但全套3226项通过。真实验收条件未满足，`human_validated=false`且能力门禁继续关闭。
- 目标worktree保留此前任务/交接WIP；根会话新增的模块说明、Memory投影说明、E2E用例及任务记录为未提交修改。无远端操作、无push/PR/main合并/部署；R3–R6、评测库65302、holdout和pending outbox均未访问或改动。
- 下一步：17项工程修复已完成；若继续原地图任务，先依[整体实施对账](FULL-SCOPE-ACCEPTANCE.md)处理未满足的真实长篇/势力前置/长期使用/作者质量验收，并遵守当时单独有效的授权和费用门禁。

## 停止检查点

- 2026-10-16T15:07:39+08:00：按用户“剩余问题写handoff”保存[交接文档](REVIEW-HANDOFF-20261016.md)，并接入三份TASK恢复快照；get_goal仍paused。写入前HEAD为dd9946dd0caf5d842d4421d7949e7f14a3a6b44a、工作树干净；仅本地文档改动，未提交业务改动或恢复运行。

- 2026-10-16T15:00:41+08:00：get_goal返回平台目标状态为paused；不是主会话调用update_goal暂停，也未标complete。核实后停止后续实现。当前工程代码固定点70e305540db5626aba92d24673f09328ae88cc8f，工作树此前干净。
- 两批累计30修复、L25一项纠正，剩余5 medium/12 low仍未完成。恢复须由用户恢复目标后先核实际Git/任务状态，再从M4稳定强Profile桥接开始；不存在已开始但未保存的M4代码。
- 本次只补持久检查点；无后续业务调用、推送、合并或部署。

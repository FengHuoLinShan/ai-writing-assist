# 外部 review 主会话复核与修复

- 来源：主仓库 `out/map-enhancement-review-20261016.md`，报告基线81785cd16；接管基线99bc9ce1c，工作树初始干净。
- 授权：剩余工作均由主会话完成，不开/恢复/消息子代理；保留五族R6及其他封存评测，未经真实质量验收不开能力门禁。无推送、合并或部署。
- 报告作为线索，需在当前代码核实。U1–U3已被报告自身复核推翻，当前不按其原指控改代码。
- 已核实：Ruff实际为一处import排序错误；imports并发用例单跑通过，评测fixture会缓存并发2且未清理，补测试级环境/缓存清理后需组合验证。
- 第一批：28项已修并验证；L25经当前实际调用链复核不成立；余6项medium、13项low继续由主会话处理。整体目标active，未冒称全部计划/质量完成。

|报告ID|状态/验证|
|---|---|
|H1|已修：evals/tests 自动 fixture 先还原环境再清 Settings 缓存；并发用例组合及最终全量9044通过。|
|M1|已修：assistant_operation_registry import 排序；全 backend Ruff check通过。原报告退出码2/无输出不等于具体语法诊断。|
|M2|已修：精确revision跳过201批次预载；候选身份按作品批量回读并局部缓存融合链；SQL先筛选相关词条身份、保留作者后续历史，2000修订上限明确truncated/missing。SQLite范围/截断、PG两例与全World/evals通过。|
|M3|已修：role 64字符领域前置校验覆盖新增/预览/更新/恢复；API与真实PG的64成功、65拒绝及当前修订保留通过。|
|M4|待修：六类强Profile与档案的双向收敛，须保持结构化JSON、秘密/动态字段和事务语义。|
|M5|已修：角色读取传 visible_fields，按显式 Story/legacy/Generic 字段键及值筛选；相同文本不能证明其他字段。真实World与Evidence测试通过。|
|M6|待修：manifest保留legacy key/必要桥接元数据与未映射字段；不能通过导入猜公开或造事实。|
|M7|待修：MemoryEvent按原章号存储，重排后所有章节重放/列表/快照需消费receipt映射；不能简单改写原事件来源。|
|M8|已修：导航卡缺少candidate_id时在IO前返回 NOTICE_NOT_ACTIONABLE/409；不再解析UUID(None)。|
|M9|待修：outcome_unknown作者核对与解除/重规划入口；不得自动重试未知结果。|
|M10|已修：object_dossier/character_pattern 加入SECTION_DIMENSION_MAP；两维度预算省略不阻断的参数化测试通过。|
|M11|已修：不再清空反应组来腾容量；超限保留内存与上次备份、标备份未完成。部分多文件备份也标不完整；取消96条截断，105条决定完整恢复测试通过。|
|M12|已修：移除previewHook finally中的导演草稿重置；钩子预览成功/失败均保留手输假设与既有预算的组件测试通过。|
|M13|已修：档案展开后保持挂载，折叠不丢编辑/模板；dirty仍传离开守卫。实体切换已走query也参与的router canLeave，新增同页entity_id切换拒绝测试通过（未发现需另加确认的第二条绕过路径）。|
|M14|已修：模块文档与README同步当前v17及安全章节重排/事实时间线只读边界，历史v11/v16标为批次。|
|M15|已修：统一提醒文档同步11源；实际11源HTTP/PG组合测试通过，来源故障占位/处置/隔离仍保留。|
|M16|待修：从app/main迁移留痕业务编排到所属模块，保留HTTP事务/回执/失败标记验证。|
|M17|已修：权威Prompt清单增加story.scene_director、story.world_progression、assistant.goal.plan，写明实际入口、输出、来源/预算和候选边界。|
|M18|已修：STORY_SCENE_DIRECTOR_ENABLED默认false，配置/示例、API依赖、内部提交/续算、领域操作、worker及助手可执行目录均检查；UI关闭状态保留输入，可刷新。关闭前IO拒绝与开启工程PG通过。未开启真实评测或生产开关。|
|M19|已修：人物合并先读当前档案投影，再经legacy revision写回并更新Character；无Character目标迁移也建立兼容档案。真实SQLite读取新旧档案合并内容通过。|
|L1|待复核/修复验证|
|L2|已修：隐式线索查询limit 20001，超过20000显式拒绝，不静默截断；同一校验按Scene/索引/完整binding缓存当前源、按引文缓存精确区间，仍逐条核复核哈希/端点/截止点。63定向与1975 World/evals通过。|
|L3|待复核/修复验证|
|L4|待复核/修复验证|
|L5|已修：API删除先读分支身份，再锁root→branch；PG实际争用后worker取得branch并完成，无ABBA。|
|L6|已修：advance apply重新检查active project；停用项目在parent读取前失败的负例通过。|
|L7|已修：导演提醒来源docstring同步实际登记。|
|L8|待复核/修复验证|
|L9|已修：地图证据错误提示统一简体。|
|L10|待复核/修复验证|
|L11|已修：map_source来源内部active-project门禁前置；拒绝时不执行正文来源读取。|
|L12|待复核/修复验证|
|L13|已修：默认类型与档案类型经同一normalize_entity_type；concept/空格大小写三例通过。|
|L14|已修：迁移docstring Revises同步真实object_dossier_v2，未更改DDL或迁移链。|
|L15|已修：conftest显式钉住trace实际默认true并纠正“所有布尔默认false”的注释；新增导演false也钉住。配置守护与全量通过。|
|L16|已修：11源PG测试使用独立随机owner，绑定真实principal，只清本次project/两个随机账户；不再删除共享BOOTSTRAP账户。|
|L17|已修：用reader实际PG PID及pg_blocking_pids证明归档锁争用，释放前断言读取未完成；PG通过。|
|L18|已修：evals/tests按例隔离缓存，退出先撤销monkeypatch再cache_clear；原imports并发失败不再出现。|
|L19|已修：续算预览前确认父回合/分支仍存在；历史刷新丢失父回合时保留输入、无API调用和TypeError的组件负例通过。|
|L20|待复核/修复验证|
|L21|待复核/修复验证|
|L22|待复核/修复验证|
|L23|待复核/修复验证|
|L24|已修：ADR索引及0025同步地图简报已接线、能力默认关闭与真实验收未通过。|
|L25|复核不成立：DirectorBudgetPreview/Start/Continue均rounds int ge=1，UI两处连续轮数，worker range(rounds_requested)逐轮持久化并共用累计预算。Literal[1]仅DirectorAdvanceRequest快捷推进一轮；旧one-click单轮限制不否定独立导演N轮入口。无需放宽快捷操作授权。|
|L26|已修（文档漂移）：现有_bridged_generic_value_visible已校验fact.field==field_key，既有错字段负例仍通过；删除计划中的过期缺口声明，并同步本批角色字段筛选。|
|L27|待复核/修复验证|
|L28|待复核/修复验证|

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

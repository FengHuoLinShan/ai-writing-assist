# C3 副驾驶机制对齐的后续缺口

2026-10-16 root 逐项对照三份计划后确认；以下仍属本次执行范围，未实施，不用 C2/C3 已通过
的部分测试代替验收。参考计划 §7.2、§9 与 ADR-0040、ADR-0041；按 Luna/max 实现、Sol/high
独立审修执行。主 TASK 的 active 状态和完整验收范围不变。

- 短期前瞻 `story.character_response.v1` 当前仍使用通用 CandidateProposal，Story forecast
  指令尚未接统一对象简报/表演卡。需核对 forecast context、Story 来源提供者、输出校验与真实
  前端动作，按对象简报提供受约束且动机不同的表演方案。不能仅更新文案或让入口跳到另一个
  新面板就称该生成链已对齐；旧 forecast 运行的冻结与历史输出保持兼容。
  当前实际清单是assistant/forecast/capabilities.json（不是capabilities.py），
  registry.py默认场景能力仍为v1，contracts.py声明Frozen forecast v1，ForecastDock.vue
  只渲染通用directions。应版本化新增输入/输出并切换新请求的真实生成与展示；不覆写旧快照，
  不把已有C2独立reaction.v2的绿色测试冒充forecast链已改造。
- “故事结构浮窗增加人物弧线：作者计划与实际对照”尚未核验交付。现有 OutlineArc 是篇章纲，
  不能直接当人物弧。先查 PlotThread 的人物关联、作者计划、已确认 Story 事件/时点来源及
  前端结构入口，复用真实可证明的数据；计划、正文发生与模型解释分别显示，无资料显示缺口，
  不把计划或候选推进写成实际发生。C5 推进路径进入滚动窗口也需在相应批次接线。
- 演化阅读状态（新章节未读、失败、待复核）统一提醒仍待加入。现有 Evolution notice_sources
  是 map_source 与来源覆盖提醒，不能替代阅读运行状态。新来源须只读已存在的领域回执，
  走 NoticeSource 登记，状态/依据指纹/缺口与跳转可核验，不能由 GET 启动/续跑/重试模型任务。
- 深度导入入口替换、场景准备替换随正式下线/默认入口依赖执行；开始前核实当前产品路径，
  不因旧 Imports facade 仍提供纯切分边界就宣称已下线，也不擅自移除仍在用的恢复入口。

上述工作可以与真正依赖长篇验收的 C1 区分：独立的读接口、提醒与界面继续实施；C1 质量门禁
仍如实保留。对象一致性及导演入口当前由 C4b 实现，避免另起一套；与 C0c 的作者有效期来源
共同注册时由 Sol 顺序组合。C4及C0c现已合primary，产品固定bd31d959d（其后root仅任务笔记），
顶层共享装配由A3 Sol独占；C5独立新文件正由另一Luna实施，不抢写其推进模块。
primary 任务记录由 root 独占，子代理只回报固定提交和证据。


## 下一实施树已准备（尚未派发）

root核实simulation-v3-director-impl旧copilot-unified-ui/a212d9faa树干净，保留旧分支后，
切到codex/copilot-mechanism-alignment-impl，起点f5c6d5cc5。该树当前无代理写入；
等并发槽位时从最新已审primary快进后派Luna/max，不能把准备当已经实施。
共享组合现由A4 Sol持有；C5独占world-progression新域、Story前端推进面板、flows.py中的
world_progression_review注册及TOML Story prefix；C0新Luna独占模板/档案互通领域。
正式开工前由root明确新增forecast/人物弧/notice范围，跨域共享接口仍顺序由Sol组合。


## 2026-10-16T06:39:58+08:00 执行检查点

root已核实准备树干净并fast-forward至942c40746（产品3caf A4），仍未派发，无活动writer。后续开工仍须核最新primary与共享文件所有权。


## 2026-10-16T06:59:09+08:00 当前执行检查点

新Luna/max luna_copilot_alignment已从干净c579正式启动，实施forecast v2、作者人物弧计划/真实事件对照、Evolution阅读notice。仅独占所属领域，C5共享顶层/story.js/Writing commit/flows/推进与C0 World hub禁止抢写。copilot_alignment_impl_test_20261016/18600/18601分配，CREATE/upgrade待C5线性固定头，非已建。

## 实施中恢复补充与独立 Sol 待修

Luna已提交恢复checkpoint `3b494b91d`，无冲突合C5 `10db18e19` 为 `c8f1a5dc8d06390428e656891177f8362912cf30`。C5最终DDL已明确固定 `20261016_wp_read_count`，root正式释放C3后继；Luna核0600工程env、确认目标不存在后一次CREATE `copilot_alignment_impl_test_20261016`，实际upgrade至 `20261016_story_character_arc_plan`（head+revision两表）。迁移已应用，即使尚未最终提交也不能重写upgrade；修补用新后继。没有服务启停，原合成数据保留。A1的 `20261016_chapter_order` 必须接C3独立Sol最终DDL头，其库尚未创建。

Luna自查真实PG3项：v1/v2、同operation幂等、stale CAS、历史恢复、软归档/恢复、无章映射未知、直接revision改写拒绝与Project删除级联；SQLite正式范围/降级证据拒绝2项、ORM parity通过。实际forecast SQLite链和旧v1回读证据此前已报；这些均不代表完整C3、真实模型或独立审查通过。API/UI/notice与共享hub装配仍需最终交接。

root已读实现和已应用迁移，四项明确交后续Sol/high直接修（Luna已确认保留，不据root finding修复）：

- `character_arcs/service.py:_trace`直接import `modules.assistant.contracts`并复制AssistantOperation物化，新增Story→Assistant依赖及棘轮风险；应以公开core DI/实际HTTP装配处理。C3/A1恢复事件还需关联原执行的`(op_id,call_id)`，不能仅给restore新随机ID制造unmatched记录。
- `forecast/registry.py defaults('scene')`从原人物反应+`story.scene_transition.v1`改成仅人物反应v2，未经授权取消了转场默认能力；须核真实v2与旧能力混选、共同输出/候选，不以删旧能力避开新格式问题。
- `20261016_story_character_arc_plan`的revision mutation/head delete trigger仅按`pg_trigger_depth()>1`放行，未验证真实`TG_TABLE_SCHEMA.projects`已删除。存续Project下任意nested trigger/父cascade可绕过不可变历史；需独立后继迁移使用C5已有的schema限定Project删除证明，并补真实PG直接/父删除/nested/TEMP绕过拒绝及真实Project删除允许。现有PG仅覆盖直接修订改写与Project级联，**没有覆盖该漏洞**。
- `character_arcs/operations.py`各prepare/apply未用context证明原work的Scene/人物/排除项/资料确认范围，仅验证作者拥有项目和模型传入的Scene/character参数。需经既有公开范围端口按可信work约束，prepare/apply都重验，不能以R3确认自动扩大原冻结范围；HTTP作者全书界面可保留。

Sol最终需顺序合已审C5+C0完整固定点，装配forecast v2/Arc pureSPEC与真实HTTP/NOTICE/前端namespace，保留旧冻结目录、map.edit hash与原12000预算。唯一解释器primary/backend/.venv、Node24，不安装/同步依赖；只用明确分配的新review库，不能借任何现存实现/primary库。root独占三份TASK与共享artifacts。

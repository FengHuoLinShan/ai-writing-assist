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

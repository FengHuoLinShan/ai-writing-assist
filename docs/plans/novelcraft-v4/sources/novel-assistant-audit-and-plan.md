# 主动创作副驾驶：代码核对与前端升级实施计划

核对日期：2026-09-21。
仓库：FengHuoLinShan/ai-writing-assist。
固定基线：main / b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201。

## 范围与证据等级

本次核对读取 GitHub 固定提交中的真实源码，包括 Assistant/Forecast 服务、上下文构造、领域事实接口、排序、前端状态控制器、写作页及全局助手。不是生产环境巡检，没有验证服务器环境变量、模型连接、实际任务调度状态，也没有运行仓库测试套件。

随附 novel-assistant-ux-prototype.html 是独立交互原型，使用完全虚构的示例正文与静态建议，不调用模型、不联网、不修改仓库。已用 Chromium 检查桌面/移动端布局，以及模式切换、暂缓与重新开启、试改预览/应用/撤销、编辑后禁用旧建议等交互。原型不代表生产功能已完成。

## 一、结论

保留现有权限、来源快照、任务预算、作者确认与领域写入机制；优先补齐上下文与推荐链路，而不是再增加一套助手。

建议一个创作副驾驶内核、一个统一右侧空间、三个展示层：文内轻提示、侧栏工作台、可选书灵入口。宠物只呈现同一份状态，不能拥有另一份权限、上下文、推荐队列或写入流程。

## 二、已实现基础

1. 旧主动检查 ProactiveCare：保存后检查、提醒处置、暂缓、重新检查与授权设置。组件直接调用 carePolicy/careNotices。
2. 新前瞻 Forecast：已保存资料、有限短期方向、精确引用、作者拒绝/普通细节/条件唤醒、来源失效、操作恢复、准备预览与单项确认。
3. Feed 与计算分离：feed 是只读；evaluate 才提交分析。默认首批 max_items=3，不是无限展示。
4. 自动前瞻队列：保存变化后 8 秒稳定窗口，同目标参考 45 秒冷却；与原主动检查共用 active slot 与日配额。不能把旧检查的 60 秒/10 分钟误当新前瞻参数。
5. 前端至少两个 ForecastDock 挂载点：WritingView 的“本章资料”上部；ProjectAssistant 的“下一步”标签页。全局助手另有“讨论、提醒、试改”；WritingView 还有 OwnerAiDrawer 和 SceneCockpit。
6. 字符定位已经包含代码点与 UTF-16 转换，不能退化为直接拿 JS 索引当后端索引。

实现不代表默认启用。运行要求 assistant_enabled、assistant_forecast_enabled；语义与自动另有各自开关，并叠加用户授权。部署情况未验证。

证据：S01—S15、S19。

## 三、优先问题与可复现验证

### P0-1 选区未进入前瞻协议

证据链：assistantContext.js 捕获 selection 文本 → useForecast.focusFrom() 重建对象时未传 selected_range → 后端 FocusRequest 支持 selected_range → context.materialize() 未收到时默认取正文末尾 12000 个字符。

后果：用户在章首、章中修订时，前瞻不一定分析当前操作的位置。

改动：
- 在 editorController/bridge 暴露光标、选区与保存基线，不从整个页面抓文本。
- 优先级：显式选区 > 光标所在段落及当前 Scene > 最近保存的变更块 > 有说明的章末回退。
- 非空 TextRange 不能直接塞入折叠光标，须先解析成合理段落窗口。
- 将 UTF-16 边界转换为 Unicode 代码点，禁止截断代理对；附 draft_id、expected_source_hash。
- dirty 编辑范围不能直接套到旧保存稿。v1 保持保存后解析；未来临时快照走独立协议。
- 模型输入与用户所见“正在参考哪一段”必须对应。

验收：章首/章中/章末、中文/emoji、折叠光标、多段选区、保存竞态、IME 输入均有测试。打开助手导致焦点离开编辑器时，不得丢失先前选区。

### P0-2 自动计算上下文与展示上下文可能不匹配

静态证据：queue.record_change() 对 writing 仅设置 draft_id 等基础字段，不补当前 Scene；WritingView 的 feed 上下文显式带 scene_id；service._valid() 要求 context_hash 完全相同；context_hash 包含 scene_id 与其相关依赖。runtime.execute() 使用原请求 focus，不进行前端场景补全。

判定：这是可由源码推导的特定条件兼容风险，需要集成测试验证，不能声称所有后台结果都不可见。

修复不得简单删除 context_hash 校验。拆分：
- authority_scope_key：账号/作品/分支/权限/可见边界/确认范围，绝不能放宽。
- evidence_snapshot_key：来源及版本依赖，变化必须失效或复核。
- task_context_key：用户当时的指令、Scene、目的等语义条件。
- presentation_focus：当前路由、光标、视口，只影响呈现相关度。

候选增加 applicability：适用章/Scene/对象、知识边界与显式条件。后台一般建议只有经过适用性和来源再验证才能进入更具体的前台焦点；确认资料范围不允许因复用而扩大。

验收：同一保存稿、有/无 Scene、同章多 Scene、切章节、改作者指令、切确认范围、切分支、作者/RP 切换。明确区分 source_stale 与 not_applicable，而不是统称资料失效。

### P0-3 多入口各自维护控制器

证据：每个 ForecastDock 创建 createForecast；组件自己的定时器每 15 秒刷新；ProjectAssistant 的 ForecastDock 由标签页挂载；ProactiveCare 主要在目标切换或显式刷新时读结果。

改动：Shell 安装账号/作品作用域的 AssistantSessionStore。感知、feed、运行与处置不依附某个可见面板。面板只维护展开状态、局部滚动和焦点。切账号销毁所有敏感状态；切作品清空/重建作用域；每个 tab/window 有独立焦点，不覆盖其他窗口。

先复用已有请求与轮询；统一一个读循环，隐藏页面降频，关闭或未授权时不计算。SSE 仅作为后续优化，不为此重建基础设施。

验收：双入口暂缓/拒绝/采用即时一致；关侧栏不丢任务回执；迟到响应不得污染新项目；列表展开阅读时缓冲新排序，不能突然跳卡。

### P0-4 task_hint 协议存在，但常用链路没有丰富它

服务端 task_hint=polish 时会排除多种推进剧情能力；前端默认 unknown，WritingView 传 page/draft/scene，没有明确任务提示。

改动：用户点击润色/续写/审稿/设计、选择某项候选、进入特定编辑工作流时，由操作意图写入 task_hint 和有效范围。低置信度推断不能覆盖明确选择。首屏最多显示“当前：润色 · 可改”，不强迫填写长提示词。

验收：润色模式不提出新剧情；上一章续写意图不能不经确认继承到新章节的设定编辑。

## 四、推荐质量改造

### 4.1 上下文不是整本资料堆叠

在现有 Evidence 与领域 facade 上增加有界 ContextAssembler：

- 焦点：保存稿中的选区/段落/Scene 及最近变更。
- 任务：明确操作、临时保留要求、作者选择的截止范围。
- 直接约束：相关对象、人物目标与已知/未知、当前 Scene 的禁止事项、仍有效的已采用规则。
- 关联背景：相同实体、因果前置、活动线索、近期作者决定；按任务选择，不整本返回。
- Coverage：搜过什么、没搜什么、哪些来源无权读、哪些已过期。

已有 Writing 领域接口提供版本差异和候选回执；Story 可提供当前 Scene 已采用剧本/人物卡。应复用这些能力，但不能把“存在某资料入口”当成“本轮已读取并验证所有相关人物知识”。

没有 Scene 的小说也应从局部正文得到条件式帮助，不能逼用户先完善所有卡片。推断对象必须保存消歧状态，不得直接写成正史。

### 4.2 上下文权限

默认仍只读已保存资料。通过项目级、可撤销的授权选择自动读取的资料类别，不要求每轮重复确认同一权限；显式确认包则维持原选择和排除，不允许自动扩展。

未保存草稿的未来支持采用 EphemeralSnapshot：只在授权下发送有限片段，短期保存，标记临时权威；不得进入 Canon、不能与已保存证据混合引用。最终写入仍需最新版本核对及作者确认。

前端只收集本应用域内必要信息；不采集键盘内容历史、不读取别的应用、不靠鼠标轨迹或停顿推断心理状态。

### 4.3 修正实际排序特征

当前 rank_key 有 window/task_help/explicit_relevance/evidence/executable/effort/narrative_lockin/repeat；但 analysis.assessments 对语义候选写死 window=2、task_help=2、evidence=1、executable=1，explicit_relevance 只是“有无指令”，effort/repeat 未在该路径提供。

改为先硬门控后排序：
1. 授权、版本、截止范围、作者明确拒绝、证据支撑不满足时不得提升曝光。
2. 使用真实任务匹配、当前对象/选区相关、可行动窗口、可验证依据、预期帮助和实际可执行状态。
3. 减去重复、成本、叙事锁定、打断与过早定论。
4. 去重后做有限多样性，最多一个主项加两个次项；不足时留白。

不直接展示未经校准的“置信度 95%”。区分资料观察、推断和创作选项。世界事实、人物相信、读者知道、作者计划必须分开。

### 4.4 每条建议自己的证据

当前语义候选 payload.evidence 填整轮 ctx.evidence。改成 claim → evidence → range/revision 的细粒度映射。展开时显示本条实际使用的片段，不用“资料很多”制造可信感。未知若会改变是否行动，必须出现在折叠卡面。

### 4.5 持久问题身份与作者反馈

当前 anchor_text 哈希进入 issue_key。修改锚文本后同一问题可能变成新身份；标题变更保护不能解决这个问题。

稳定身份采用 scope + Scene/对象/块身份 + 问题类型；文本版本单独记录。文本匹配只是候选关联线索，低把握时不自动合并不同问题。拒绝某方向不等于拒绝该场所有帮助；普通细节不应再次自动推销成伏笔；新证据触发重开时说明变化原因。

## 五、统一前端信息架构

### 5.1 唯一右侧空间

禁止在现有“本章资料 + 项目助手 + AI 工具”之外再追加第四个侧栏。由 AssistantSurfaceHost/RightWorkspaceHost 协调 right surface；资料、讨论、预览、专业工具复用该空间。

桌面建议：左导航约 200–240 px，可折叠；正文优先保障约 640–760 px 的舒适区域；副驾驶 340–420 px，可调整。容器不够宽时先折叠导航，再把助手收为轻入口；用户主动打开才覆盖，不强行并排。移动端使用手动展开的面板，并维护安全区、软键盘与返回焦点。

这组宽度是设计起点，不是已验证的仓库参数。以 1280、1440、1920 及移动端实测调整。

### 5.2 工作台三页签

- 当前：当前上下文、覆盖/版本、主建议、少量次建议、折叠持续留意。
- 讨论：承接当前事项及证据，继续复用 ProjectAssistant 的会话和批次。
- 记录：作者决定、已完成/未完成操作、过期结果和恢复入口。

“提醒”和“下一步”合并为当前任务流；“试改”由选中方向进入，不作为所有用户必须理解的顶层模块。高级设置与预算放设置页，但来源过期、费用新增、授权变化在触发动作时必须明示。

### 5.3 信息压缩契约

首层必须有：为什么现在、结论属于观察还是推测、主要行动、关键不确定性、来源版本与范围摘要。次层展开原文/替代方案/影响。第三层看运行和用量回执。

每个主卡默认一项主要操作，最多两项轻处置，其余放菜单。缺资料时给一个最小补充动作；不可用不显示成“检查通过”；保存失败独立于文学建议，不得被宠物遮住。

### 5.4 图标与宠物

书灵是可选皮肤，不改计算规则。建议尺寸 48–56 px，停靠在不挡保存/输入/地图操作的位置；不跨正文游走、不按字数或 token 奖励、不用跳动和红点催促作者。

功能状态应来自真实数据：安静、执行中、有相关项、等待确认、不可用。表情不能代替文字、无关的“情绪”不能被当成任务状态。安静并不等于系统完成全书检查。

点击显示约 320–360 px 的单卡；卡内保留关键未知和证据摘要；展开工作台后仍选中同一事项。专注/IME 输入时不自动弹出；关闭默认是本次不打扰，不等于否定内容；作者可关形象仅保留文字入口。

产品参考：Grammarly 的文内位置与浮动卡片、固定锚点和关闭控制；Intercom 的 launcher 与完整面板分离；VPet 的角色状态表达。只借鉴交互，不复制角色美术。VPet 代码与动画另有授权要求。

## 六、建议新增/调整位置

以下新增名称是拟定，不声称仓库已经存在。

```text
frontend-console/vue/
  shell/components/AssistantSurfaceHost.vue          # 新增，展示层协调
  composables/useAssistantSession.js                 # 新增，唯一作品作用域状态
  composables/useWorkContext.js                      # 新增，类型化实时焦点
  composables/useAttentionPolicy.js                  # 新增，打断/展示节流
  components/assistant/AssistantWorkbench.vue        # 新增，当前/讨论/记录
  components/assistant/SuggestionCard.vue            # 新增，统一卡片
  components/assistant/EvidenceDisclosure.vue        # 新增，本卡证据
  components/assistant/AssistantLauncher.vue         # 新增，普通图标/书灵皮肤
  components/assistant/ActionPreview.vue             # 新增或复用现有预览
  components/ForecastDock.vue                        # 渐退为兼容外壳
  components/ProjectAssistant.vue                    # 复用会话与执行，不重复状态
  components/ProactiveCare.vue                       # 接入 feed 适配器
  components/OwnerAiDrawer.vue                       # 进入唯一右侧宿主
  views/writing/WritingView.vue                      # 去重面板/注册上下文
  shared/assistantContext.js                         # 兼容旧快照捕获
  bridge/index.js                                   # 唯一 legacy 桥梁

backend/modules/assistant/forecast/
  contracts.py                                      # 版本化上下文/适用性契约
  context.py                                        # 有界局部范围与 Evidence 组装
  ranking.py                                        # 真特征与去重
  analysis.py                                       # 每项证据与可验证字段
  service.py                                        # 来源有效性与展示适用性分开
  queue.py                                          # 自动触发与上下文规范化
```

在原模块内增加小型服务即可；不需要新的推荐微服务，不默认引入多 Agent，不迁移编排框架以替代实际质量修复。

## 七、实施与验收

### 第一批：链路正确与单一入口

修选区/task_hint、建立自动/前台焦点兼容测试、统一 store、统一右侧空间、主卡与覆盖摘要。保留原 API 与协议适配，分开 feature flag，可逐项回滚。

### 第二批：上下文与质量

有界 ContextAssembler、人物/世界/线索关联召回、局部证据、真排序特征、作者决定稳定身份、曝光与无打断策略。

### 第三批：可选形象与深入工作区

在前两批通过后增加书灵皮肤；对复杂跨章修改提供“事项列表 + 证据/差异”大工作区。切换不复制状态、不创建第二套助手。

### 必测场景

1. 章首/章中选区能够改变前瞻实际材料；emoji 偏移正确。
2. IME 合成期间无提交、无跳卡、无抢焦点。
3. 自动草稿分析能在满足适用条件的关联 Scene 下正确呈现；不能靠去掉授权校验通过。
4. 不同章、Scene、项目、账号、分支、作者/RP 的迟到响应不串线。
5. 未保存/保存失败时不能采用旧预览；确认前再次核验。
6. 来源变化与“不适用于当前焦点”分别显示；未检查不等于没问题。
7. 暂缓在所有入口同步；不感兴趣的方向不因改标题或轻微改句反复出现。
8. 一个普通细节可以保持普通；没有大纲/Scene 时仍有有限帮助。
9. 润色意图不会被续写能力覆盖；低置信度意图不擅自定论。
10. 有缺失获知渠道时只说“可能”，不能判定人物知识冲突。
11. 引用可读回且严格属于本次授权；正文中的提示注入只被当数据。
12. 关闭计算授权后不再新起模型请求；展开和刷新 feed 不产生模型费用。
13. 320/390/768/1280/1440/1920 宽度、缩放、键盘导航、减弱动效均核对。
14. 点击试改只准备预览；确认按最新版本执行；部分失败有可恢复回执。

质量评估不以点击率、字数或建议数为目标。做固定小说片段与章节顺序的回放集，对照当前算法，观察主建议有用率、证据真实性、重复/打断率、违背意图率、来源失效率和整轮成本。规则违规（跨账号/越权写入/剧透边界）作为阻断项。验收阈值须在建立基线后由作者评审制定，不能用静态 mock 测试证明文学推荐已达标。

## 八、代码证据索引

全部路径属于同一固定提交，避免跨版本混用。

S01 backend/modules/assistant/README.md
S02 backend/modules/assistant/forecast/contracts.py
S03 backend/modules/assistant/forecast/context.py
S04 backend/modules/assistant/forecast/ranking.py
S05 backend/modules/assistant/forecast/analysis.py
S06 backend/modules/assistant/forecast/service.py
S07 backend/modules/assistant/forecast/runtime.py
S08 backend/modules/assistant/forecast/queue.py
S09 backend/modules/writing/forecast.py
S10 backend/modules/story/forecast.py
S11 frontend-console/vue/shared/assistantContext.js
S12 frontend-console/vue/composables/useForecast.js
S13 frontend-console/vue/components/ForecastDock.vue
S14 frontend-console/vue/components/ProactiveCare.vue
S15 frontend-console/vue/components/ProjectAssistant.vue
S16 frontend-console/vue/components/OwnerAiDrawer.vue
S17 frontend-console/vue/shell/ShellApp.vue
S18 frontend-console/vue/views/writing/WritingView.vue
S19 frontend-console/vue/bridge/index.js
S20 backend/modules/assistant/forecast/tests/test_forecasts.py

源码地址格式：
```text
https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/<上述路径>
```

产品参考原始文档：
```text
https://support.grammarly.com/hc/en-us/articles/4412816078349-Grammarly-for-Windows-and-Grammarly-for-Mac-user-guide
https://www.intercom.com/help/en/articles/2894-create-a-custom-launcher
https://www.intercom.com/help/en/articles/6612589-set-up-and-customize-the-messenger
https://github.com/LorisYounger/VPet/blob/main/README_en.md
```

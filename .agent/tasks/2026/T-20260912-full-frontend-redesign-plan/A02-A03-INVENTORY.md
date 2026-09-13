# A02/A03：主代理补充清点

2026-09-12。第二位Luna创建被宿主线程数量上限拒绝，以下只读清点由主代理完成，不能标为Luna产物。原功能均后续业务接回；本表只规定设计去向。

| 正式证据 | 新设计归属 | 对象、关键状态与返回 |
|---|---|---|
| world/WorldView.vue、library、WorldBibleTab、WorldbookImportPanel、WorldHealthPanel | 人物与世界：资料/世界书/待决定/关系/别名/图谱/资料健康 | 选中人物和来源不随页签丢失；阅读/编辑/图片异常、批量范围、导入目录和健康非审查结论 |
| outline/OutlineView.vue、OutlineArcsTab、OutlineThreadsTab、OutlineStoryTab | 故事结构：总览/篇章/剧情线/场景 | 同一篇章/剧情线，伏笔揭示、结构候选比较；场景工作台回父级 |
| scene/SceneWorkbenchView.vue:86–99、SceneScriptsPanel、SceneSimulationPanel | 故事结构下场景工作台 | 场景筛选（含状态、来源、范围、阶段、注意原因）、剧本/模拟/过期；从文稿携带当前场景返回 |
| map/MapWorkspaceView.vue、MapStructureEditor、MapRehearsalPanel | 地图：浏览/结构/审阅/排演 | 地点、来源、跨图关联、图层、图片失败、地图候选、时点；与本章地点为同一对象 |
| rag/RagSearchView.vue、RagSearchPanel、RagEvidenceDrawer | 查找：结果/来源详情/修复 | 类别与范围、选区、钉选、过期/不可用；回同一文稿位置 |
| interaction/JourneyListView、InteractionView.vue:1946–2619 | 互动故事：准备/阅读/回顾/约定/来源与进度/设置 | 当前旅程、选中分支、输入、流式超时/停止/恢复、来源升级；回到阅读位置 |
| settings/GlobalSettingsView.vue:421–560、ProjectSettingsView、SettingsShellView | 账户与偏好：账户/模型/图片/默认偏好/作品/外观 | 账户和作品范围分开；验证中/失败/未保存，禁真实密钥输入；阅读来源可返回 |
| shell/components/AccountDialog.vue、home/Auth相关入口 | 身份入口与账户面板 | 现有邮箱验证码方式、重发等待、失效和权限；不增加密码/OAuth等登录方式 |
| vue/components/ProjectAssistant、OwnerAiDrawer、ProactiveCare | 写作伙伴与工作流：意图/候选/任务/提醒 | 当前章/选区/场景，候选采用≠正式；关闭任务面板不停止任务；重开同一结果 |
| vue/shell、commands.js | 外壳文档菜单、查找、帮助、通知 | 直接普通操作仍存在；控制层键盘与返回，手机收纳而非隐藏能力 |

复用：现有ActionMenu、PreviewDialog/Notice/Icon、motion.css/js、fictional data。公共外壳保持单写；实际域拆出后才能交付子代理。验证需分别记录静态状态和连续路径；以上是清点，不是设计实现通过。

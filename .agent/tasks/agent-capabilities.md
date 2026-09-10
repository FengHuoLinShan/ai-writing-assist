# Agent 功能整合台账（作者与 RP）

执行分支 codex/agent-integration，基线 a8de5aa9e98301943e4311aa1e5a356dd1fb177e。
按用户最新指令，本轮关闭功能实现缺口；正式产品验收、人工质量评测和发布延期，不能把功能状态
解释为 P0–P5 全部验收通过。原 JSON 保留逐接口/表出处，以下按真实用户能力归并。

通用边界：每项均校验当前 account owner 与 novel_id；RP仅消费同owner绑定版本。内部读取经
Evidence，业务成果由原领域持有。确认修改保存原基线、来源、版本及事务回执；模型不能指定
owner、任意 URL 或执行表达式。文件、凭据、图片上传和危险操作留在原受控界面。

功能方式：**直接**＝助手准备具体修改并经成组确认完成；**组织**＝助手运行原任务并交回领域成果；
**受控**＝保留必需的用户选择/精细操作，精确上下文和结果入口已衔接；**兼容**＝旧入口只转接。
工程证据简称对应实际测试文件/模块，非链接本身：A=Assistant tests，W=World tests，S=Story及
outline_state tests，P=Project tests，I=Imports tests，D=Writing tests，R=Interaction tests；
FE=相应Vue/控制器测试。CUA只记已实际操作的路径；未模拟不冒充通过，正式验收统一延期。

| 用户能力 | 领域/方式与入口 | 实际来源、成果和恢复方式 | 功能证据/当前开发模拟 |
|---|---|---|---|
| 创建、选择、恢复作品 | Project／受控：目录、回收站 | 原项目身份与工作区；原回收/恢复确认 | P/FE；CUA新建、跨作品回访 |
| 模型连接与偏好 | Account/Project／受控：设置 | 当前验证连接；能力接口读原runtime配置，Key不入模型 | 账户/Project gate；缺配置有原因 |
| 续写位置与待决事项 | Project/Evidence／组织：project_overview | workspace投影；来源定位、原工作区恢复 | A/P/FE；CUA跨页回到写作 |
| 持续讨论 | Assistant／直接；共创旧入口兼容 | 同一session/message、checkpoint/成果引用；任意回合回执 | A/共创/迁移；CUA跨页面保留讨论 |
| 停止与运行恢复 | Assistant/Tasks／组织 | 原parent/child关系、lease、累计预算和版本化工具；终态清理私有历史 | A/LLM/PG并发与重启/停止；RP准备停止CUA |
| 作者待办 | Project／直接：author_tasks/add/update | 带日期待办与updated_at；确认重放不重复 | P/A批次/FE；CUA提案与确认 |
| 检索及精确原文 | Evidence／组织：search/read/inspect | SourceRange/TargetRef，hash/版本/排除/截止重验 | Evidence/A/R拒绝用例 |
| 参考资料与排除 | Evidence/Writing／受控+组织 | 原confirmation；候选重新确认产生新版，旧候选不重绑 | D/FE；CUA原补充要求保留、新v3与旧v2/v1并存 |
| 世界讨论与模板 | World/Assistant／组织+兼容 | 原意图、模板、建议；固定复核同预算 | 共创A/W/FE；旧会话迁移PG |
| 阶段成果与推进 | World／直接：save_checkpoint | 原checkpoint版本、作者决定、session推进；不直接Canon | assistant_cocreation/outcome测试 |
| 世界对象 | World／直接+受控：create/edit_entity | 原对象及修订；预览/CAS，历史操作回原对象页 | W/A/FE；既有历史恢复保留 |
| 别名与关系 | World／直接新增、受控调整 | 附着原对象、语义关系；原历史/去重裁定 | W/A成组失败与来源拒绝 |
| 世界书草稿与发布 | World／直接：create/edit/publish_page_draft | 原草稿、影响/Canon head、正式版本；restore生成工作稿 | assistant_page_tools edit/publish/restore/CAS；CUA确认草稿、编辑发布、原回执历史定位和恢复工作稿 |
| 世界候选审阅采用 | World／直接+受控：package/page_suggestion | 原采用包/候选、来源映射；原World验证，不替代裁定 | W/A/FE package/suggestion/checkpoint链 |
| 世界依赖与规则复核 | World／组织：review_assets | 原WorldValidationRun；coverage/遗漏、版本化政策和结果定位 | W/A/PG review runtime；advisory非Canon许可 |
| 总纲版本 | Story／直接保存、受控恢复 | 原head/revision；结果精确版本只读打开，原恢复确认 | S/FE；outline revision导航 |
| 剧情线与篇章 | Story／直接创建、组织P20、受控细改 | 原规划及P20采用包，基线/跨层依赖、旧范围增量通知 | S/FE P20及Thread/Arc合同 |
| Scene规划与调整 | Story／直接+组织：create/edit/P20 | 原Scene与章来源映射；原采用/恢复、准确task预览 | S/P20/FE原任务同路由刷新 |
| 人物卡与多文件剧本 | Story／直接保存、受控历史 | 原revision/adopted head；新basis v2与旧v1兼容，原成果版本只读 | S/FE Scene工作区与历史回跳 |
| 伏笔、揭示、回收 | Story／组织P20、直接edit_information_plan | 原计划内容/章节/关联线；不把计划作历史；原稿CAS | S信息依赖/信息工具/Evidence作者范围拒绝 |
| 章节工作稿 | Writing／直接new_chapter+原编辑器 | 原版本与自动保存；新章仅追加 | D/A/FE；CUA新章、手写和自动保存 |
| 生成/续写候选 | Writing／组织generate_candidate | 原生成/续写任务，冻结confirmation和base；候选原位查看 | D/A/FE；CUA真实worker+合成provider出候选 |
| 审稿及人工世界约束 | Writing/Evidence／组织review/review_world | Writing finding/实际覆盖与遗漏；人工世界约束不签知识边界 | D/A/PG；原candidate确认缺失/stale失败关闭 |
| 精确修改与定向返修 | Writing／直接revise、组织targeted_revision | 新工作稿/新candidate；精确区间、原finding与confirmation | D/A/FE；原位baseline冲突保护 |
| 采用、发布与恢复 | Writing／直接采用/restore、受控发布 | 原工作稿版本及发布回执；采用/撤销不改旧历史 | D/FE；CUA并排差异与原工作稿保留 |
| 文件导入 | Imports／受控：文件选择/进度 | ImportRecord/原正文，固定格式限制与身份；原导入回执 | I/FE；真实文件全面验收延期 |
| 整理、恢复、专项查漏 | Imports／组织：organize/resume/complete_targets | 原task/workflow、原授权与完成回执；精确任务面板含出处/撤销 | I/A/FE；同名目标具体选择后新开查漏，旧授权不变 |
| 重复资料处理 | Project/World/Story／组织+受控比较 | 原扫描、完整组预检、group_receipts；成功重放不重执行 | P/PG savepoint/FE；CUA助手扫描与原比较页空态 |
| 地图问答与定位 | World/Evidence／组织：map inspection | 原空间版本/作者资料；缺位置保持空白；有截止点改用阅读预览 | W/Evidence/A；CUA未知位置标记保存与差异 |
| 地图维护与图片 | World／直接地图操作、受控图片 | node/revision及run/page精确回跳；原采用/恢复和私有存储 | W/FE；CUA新建改名保存历史比较；缺存储提前说明 |
| 资料健康与历史维护 | Evidence/World/Story／组织+受控 | 原索引、世界健康、结构新旧影响与历史入口；不另建事实库 | A/W/S/FE原领域回执；索引等仍为确定性原任务 |
| 主动回访及 RP | Assistant/各域/Interaction／组织 | 同事务dirty、合并去重/暂缓/新额度续查、领域原文定位；RP原attempt树 | A/R/PG/FE；CUA开场、发送、准备停止、讨论恢复 |

新增公共服务已实现：私有SearXNG搜索＋公共网页回读，协议/配置指纹冻结，逐HTTP预算、来源元数据、
DNS连接固定和SSRF/注入/原作信息过滤。CUA已有真实搜索与IANA网页读取（模型回路合成）；原生搜索
旧适配继续受验证门禁，不能把配置注册视为真实通过。

工程结果以主任务最新快照为准：后端领域与LLM主回归2688通过/12跳过，Evidence/任务补充回归
652通过，最新World发布恢复定向33通过；专用PostgreSQL并发/迁移20通过；前端全套2432通过。
backend Ruff、受影响159个Python文件format、frontend lint/build、20项Prompt契约与文档门禁通过。
机器清单更新为497个API入口与114张ORM表及所有者；功能状态仅在本台账维护，机器清单不重复
维护验收勾选。上述数字不能替代真实模型效果；作者效率、RP盲评、强提醒精度、真实用户采用及发布延期。

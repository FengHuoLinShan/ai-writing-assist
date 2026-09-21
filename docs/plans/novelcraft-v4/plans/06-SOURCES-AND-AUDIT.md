# 来源、第二轮分析与交付边界

2026-09-21｜本文件区分原计划继承、本轮代码核对、设计推断、研究证据和实际交付。

## 1. 来源及信任等级

输入 A：`../sources/novel-assistant-audit-and-plan.md`。重点：L34–82 当前焦点与轮询问题；L84–128 上下文与排序；L130–160 单宿主；L198–229 回归测试。

输入 B：`../sources/PLAN-novel-world-cognition-map-v3.md`。重点：L175–224 经验视图与兼容；L232–340 W/C；L342–570 地图、媒体、失效；L724–826 工作包与实验；L828–955 验证/灰度/远期。

输入 B 明确继承旧代码基线，不等于该文档每项问题都已在当前运行系统复现。其提到的更早世界重构原稿不在本轮附件内，未把它当作已完整重读的第三份来源。完整源文件与 SHA-256 在包内 manifest 中保留。

代码基线：[ai-writing-assist / b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201](https://github.com/FengHuoLinShan/ai-writing-assist/tree/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201)。定向读取通过 GitHub 连接完成，没有完整 checkout、完整 PG 测试或线上部署检查。

## 2. 新一轮审查中的主要增量

### N01：机器 Scene 替换与人工确认之间缺少来源分区

已核对：[continuity/repositories.py L370–445](https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/backend/modules/story/continuity/repositories.py#L370-L445)。`replace_scene_events()` 按 novel/scene 取全部旧行，再按 scene_sequence 替换、删除剩余行；此函数没有限制可替换的 source family。

结合 [continuity/services.py 的人工确认追加](https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/backend/modules/story/continuity/services.py#L188-L270) 和 [imports 的空 Delta 替换入口](https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/backend/modules/imports/entity_extraction/scene_entity_persistence.py#L1020-L1125)，机器回放范围与作者权威必须分区。结论是明确的 repository 行为与跨链风险，不是宣称生产中已经发生数据丢失。整改：E00/E03 发布阻断，按 producer/epoch/input generation 替换派生事件，保留作者决定。

### N02：入口复用并不自动保证副作用一致

已读路径：Writing API 在更新/采用后请求索引；Writing assistant 操作与 Collaboration port 复用领域工作稿创建；Collaboration outbox 投递 context changed。相关代码见 [writing/api.py](https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/backend/modules/writing/api.py#L460-L650)、[writing/assistant_tools.py](https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/backend/modules/writing/assistant_tools.py#L390-L495)、[writing/creative.py](https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/backend/modules/writing/creative.py)、[collaboration/tasks.py](https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/backend/modules/collaboration/tasks.py)。

这里不把局部未见某个调用夸大为“全局一定没有索引”。本轮提出的架构整改是：建立统一领域变更回执及所有入口对照测试，不依靠每个 adapter 记住同一组后置步骤。I02/E05/U03 负责实现与验证。

### N03：复用适配器，替代所有权，而不是平行建第二引擎

[imports/orchestrator.py](https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/backend/modules/imports/orchestrator.py) 已拥有领域 run 与恢复 checkpoint，[imports/workflow.py](https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/backend/modules/imports/workflow.py) 组织各 phase runner。若新增 Evolution 后还保留它们的新请求调度权，就产生两个主游标、两套恢复和双写风险。

因此新要求必须通过项目级 owner epoch、排空/停止、历史 adapter 和旧 handler 退役落实。Shadow 只读比较允许共存，正式写入不允许双 owner。这是本轮设计推论，不是当前仓库已有 Evolution 的描述。

### N04：多 Agent 应扩现有有限协作，而非再建框架

[collaboration/recipes.py](https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/backend/modules/collaboration/recipes.py)、[merge.py](https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/backend/modules/collaboration/merge.py) 与 [bootstrap.py](https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/backend/app/bootstrap.py) 提供配方、资源 port、manifest 重验和领域采用基础。V4 扩展可靠性/创意配方及共享预算，不另建自由文本团队世界或独立采用路径。

### N05：前端新主题是设计选择，不冒充当前实现

[editorial-theme.css L1–120](https://github.com/FengHuoLinShan/ai-writing-assist/blob/b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201/frontend-console/editorial-theme.css#L1-L120) 当前定义较冷的简约底色、蓝色主操作及语义别名。本轮使用暖纸色/深墨青绿为新的创作工作区提案。应保留令牌接口与主题切换，不说“仓库目前就是这套样式”。

## 3. 原审计问题怎样使用

Delta 与状态归约断层、两个 reducer 的语义分叉、身份去重跳过观察、顺序落库非顺序认知、发布链只做索引/历史快照等，作为原审查与 B 的继承项，进入 E00 基线复现与 E01–06 方案。上一轮聊天中个别引用标记与文件名存在对照不一致风险；本交付不把那些标记当成精确定位依据，改用固定 commit 的路径和可复现契约。

整个计划中的“应当”“拟议”“建议”均是设计方向。没有执行迁移、没有更改生产代码、没有在数据库中测试新协议。新命名不是仓库现存能力的声明。

## 4. 原始研究及为何采用

### R1：架构与任务匹配

Kim 等，*Towards a Science of Scaling Agent Systems*，arXiv:2512.08296，v3，2026-04-08。

https://arxiv.org/abs/2512.08296v3

该版本报告对多种架构和任务的受控比较，并强调任务结构与协调方式匹配。用于支持有依赖任务保留顺序、团队按任务评估的设计；不是小说项目收益证明。不再混用 v1 的配置数量和 v3 结果。

### R2：自纠错需要可信反馈

Huang 等，*Large Language Models Cannot Self-Correct Reasoning Yet*，ICLR 2024，arXiv:2310.01798。

https://arxiv.org/abs/2310.01798

研究对象是在其设定下没有外部反馈的推理自修正。用于支持原文回读、代码验证与具体失败反馈；不宣称所有 2026 模型在所有任务都无法自纠错。

### R3：创意辅助与同质化

Doshi 与 Hauser，*Generative AI enhances individual creativity but reduces the collective diversity of novel content*，Science Advances，2024，DOI 10.1126/sciadv.adn5290。作者机构存档：

https://discovery.ucl.ac.uk/id/eprint/10195027/

短篇实验中的个人评价收益与故事间相似性风险支持独立发散、保留多种方向。不能直接外推为专业长篇作者的提升率；真实项目仍需人工盲评。

### R4：多 Agent 工程实践

Anthropic，*How we built our multi-agent research system*，2025-06-13。

https://www.anthropic.com/engineering/multi-agent-research-system

其独立并行研究及执行恢复经验用于借鉴输入隔离、明确成员任务、artifact 交接、成本与端态验收。内部 research 指标不移植成小说质量指标。

### R5：现有技术栈的协作能力

Pydantic 官方文档，*Multi-agent Applications*，读取日期 2026-09-21。

https://pydantic.dev/docs/ai/guides/multi-agent-applications/

用于确认 delegation、程序交接及共享 usage 的实现方向；部署要先核对仓库锁定版本，不能把在线文档的新 API 当成已安装功能。

### R6：模态交互规范

W3C WAI APG，*Dialog (Modal) Pattern*。

https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/

用于焦点进入、Tab 范围、Escape 和焦点返回设计。尚未进行真实辅助技术认证。

### R7：Figma 原生导入器

Figma Plugin Manifest 和 FrameNode 官方参考，读取日期 2026-09-21。

https://developers.figma.com/docs/plugins/manifest/
https://developers.figma.com/docs/plugins/api/FrameNode/

插件 ID 必须由 Figma 分配，不伪造。交付提供不含账号密钥的离线数据和创建代码；安装时使用 Figma 创建的本地插件 ID。

## 5. 交付与未完成的精确边界

已产出：长期总计划、独立演化/地图/多 Agent 与认知推荐/前端计划、追踪与验收矩阵、分层 SVG、PNG 审阅图、离线交互原型、Figma 重建插件代码和设计数据。

Figma MCP 的实际调用返回 Starter 额度耗尽，原生设计写入没有完成。空文件不能当成果。插件运行、字体替换与原生截图仍需在有可用编辑能力的 Figma 环境验证；不为额度问题安排付款或更改用户套餐。

已验证的离线结果和测试数量以 `../validation/DELIVERY-QA.md` 为准。那里只报告本轮实际执行的验证，不把待实施门禁写成通过。

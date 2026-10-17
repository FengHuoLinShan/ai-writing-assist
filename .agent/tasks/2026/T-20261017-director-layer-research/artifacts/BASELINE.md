# 导演分尺度研究：项目实现基线

调查时间：2026-10-17。只读调查；未运行测试、模型或数据库操作，未恢复封存评测。

实现工作树：`/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan`；分支 `codex/map-enhancement-plan`；HEAD `a479e006bc336c0009e5207f7659609ab483e901`；调查时工作树干净。以下事实属于该工作树，不代表主仓库当前主题分支或线上已提供能力。

## 结论

现有实现已经分为世界推进与场景导演，均可独立启动。但这种独立仍依赖已有项目、已有对象和实际 Scene，不等于用几句话进行无 Scene 临时探索。事件层有较多可复用零件，尚缺独立的任务边界、启动与输出契约。现有世界推进交汇到导演的桥接只传递导演侧候选假设，并非完整未来状态下钻。

## 宏观世界推进

入口在大纲页，`OutlineView.vue:98` 挂载 `WorldProgressionPanel`，只传项目、人物与对象，不要求先运行导演。支持人物和群体参与，自由/导向推进，按日、周、月、季、年或下一拍推进；运行策略有单步、多步、到目标、到预算。目标为已有篇章、剧情线或计划场景；导向模式也允许只有作者文字。

输出包含局势与滚动摘要、行动结果、状态/态度/资源/知识变化、交汇事件、目标路径、剧情钩子、所需铺垫、不自然之处和副线。这可作为沙盘模式基础，无需重新构建宏观引擎。

请求 schema 的 `scene_id` 虽可空，实际 `read_progression_source()` 会解析最新已写章节的有效 Scene；没有已写章节，或最新章节没有可用 Scene，均失败。因此当前作品起点阶段的世界沙盘不成立，也不能仅删除前端 Scene 字段就宣称支持。UI 当前先请求 `scene_id:null`，再沿预算预览返回的实际 Scene 确认资料。

证据：

- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/frontend-console/vue/views/outline/OutlineView.vue:98`：入口。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/world_progression_schemas.py:164`：输入、推进方式、预算。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/world_progression_schemas.py:407`：结果结构。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/world_progression_context.py:201`：默认截止点要求。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/world_progression_context.py:253`：实际 Scene 校验。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/frontend-console/vue/views/outline/components/WorldProgressionPanel.vue:941`：请求与确认链。

## 微观场景导演

场景模拟面板与写作驾驶舱均有直接入口，可独立选择人物、主角、导演要求、公共刺激、分歧程度与轮数。输出包含每人动作、表情、肢体、台词、潜台词、动机情绪、防御、注意与忽略对象、与上一轮差异，以及素材、角度、备选分支、候选事件、一致性和状态回放。支持继续、重掷、干预、单人物重写；保存参考副本后可供同一 Scene 的写作任务选用。

schema、API 路径、根模型、历史、参考副本与 UI 全链绑定 `scene_id`，至少一位已有角色。尚无纯临时人物/临时场地的一句话开局。每位人物表演字段较多，素材 schema 强制 2–3 个推荐角度及 2–3 个分支，简单对话探索也可能承担完整输出。

代码预算估计：导演每轮最多 `2N+2` 次请求，世界推进每步 `N+1` 次请求。这是预算公式，不是实测速度或质量结论；分层时应保留宏观少细节的成本优势。

证据：

- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/frontend-console/vue/views/scene/SceneSimulationPanel.vue:11`：场景入口。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/frontend-console/vue/views/writing/components/SceneCockpit.vue:75`：写作区入口。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/director_schemas.py:19`、`:59`、`:204`、`:285`：输入与输出要求。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/models.py:295`、`:387`：根及参考副本的非空 Scene 字段。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/director_service.py:962`：跨 Scene 参考不交给当前正文任务。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/director_budget.py:22`；`/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/world_progression_budget.py:42`：请求预算公式。

## 事件层的可复用部分与缺口

可复用世界推进的目标、行动/反制、交汇、后果、铺垫、钩子和路径，也可复用导演候选事件与分支历史。共享 `simulation_v3` 已把提出意图、有限结算、状态差量和回放分开，限定移动、资源转移、离场、信念变化等效应；未知或资源冲突可结算为 `uncertain`。这是共同结算基础，不自动证明政治、情感或文学因果正确。

缺少事件自身的边界：触发条件、参与者目标与秘密、事件起止、关键争议、允许改变的状态、固定结果与开放结果、冲突升级和退出条件，以及不依赖正式 Scene 的独立启动/历史入口。建议先以世界推进的有限事件配置实现并交付紧凑事件卡，避免复制第三套完整工作台。

证据：

- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/world_progression_schemas.py:110`、`:124`、`:147`、`:407`：事件零件。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/director_schemas.py:274`：候选事件。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/simulation_v3.py:135`、`:267`、`:299`：共同意图、结算与冲突处理。

## 现有衔接与最小工程路径

世界推进 UI 已有交汇到导演：选择交汇人物，把结果描述及目标路径放进 `intervention`，重新预算确认后启动。只有群体的交汇不能进入导演。此桥沿用原世界推进根的 `scene_id`，没有创建未来场景；`intervention` 只进入导演包，角色首轮仍收到原角色简报、原状态和公共刺激，而桥的 `public_stimulus` 为空。因此它是显式候选起点提示，并非完整的未来状态下钻。

工程建议：

1. 先让现有两种能力在统一入口和原工作位置均可直接启动；事件层先做有限配置与结果卡。
2. 跨层传递作者选定的来源回执、候选状态差量、时间锚点、角色观察/信念和保留假设，再重新预览确认。场景反向上推也建立新的沙盘分支。
3. 原分支保持不可变；下游结果不自动修改上游或正史，不把未来摘要整段塞给所有角色。
4. 无 Scene 临时探索单列能力，需要临时起点和独立知识边界；不能伪造正式 Scene，也不能只把字段改成 nullable 后沿用所有状态与 Evidence 语义。

证据：

- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/frontend-console/vue/views/outline/components/WorldProgressionPanel.vue:1512`、`:1565`：现有桥接。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/director_context.py:410`、`:425`：角色包与导演包分离。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/director_tasks.py:913`：角色真实收到的输入。

## 必须保留的安全与恢复约束

两条链均经预算预览指纹、Evidence confirmation、项目 LLM snapshot、任务根账本和独立历史；worker 再物化确认资料。导演还把每个角色简报与确认最终条目取交集，不能通过重读档案带回作者排除的资产。新层级须保留 owner/`novel_id` 隔离、秘密和未来信息隔离、候选/正史区分、幂等、未知计费停机和来源漂移重验。两个功能开关默认关闭；代码存在不代表质量已验收。

证据：

- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/director_api.py:209`、`:235`；`/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/world_progression_api.py:283`：启动链。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/director_tasks.py:196`；`/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/world_progression_tasks.py:272`：worker 确认重物化。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/director_context.py:369`：确认条目交集。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/evidence/compilation/services/confirmation_service.py:345`、`:367`、`:420`：新鲜度与指纹重验。
- `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/core/config.py:379`；`/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/modules/story/world_progression_api.py:81`：默认关闭。

文档与代码的解释边界：Story README 的“独立根启动”描述的是独立任务与预算，不表示无 Scene 运行；以实际 context/schema/ORM 链为准。本次未发现需要把其他文档描述提升为代码事实的依据。

未修改产品代码、未运行测试或模型、未访问数据库。分层后的文学质量、成本收益和作者便利性均需独立验证；不以本次静态调查替代真实验收。

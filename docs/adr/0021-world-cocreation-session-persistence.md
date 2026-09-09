# ADR-0021 — 共创会话持久化

- 状态：Accepted / Partially implemented
- 日期：2026-09-09
- 授权：用户确认“世界观能力对齐与作者工作台优化”第三期方向：项目内持久化共创会话，绑定主题/资料/世界核心，保存作者消息、完成的模型回复、作者决定、来源与成果引用，支持历史分页与跨设备继续；四动作与 checkpoint 续写沿用既有载体，不建立新事实源或自治运行时。

## 决策

World 模块新增自有数据 `world_cocreation_sessions` / `world_cocreation_messages`，保持 owner 与 `novel_id` 隔离，随项目 CASCADE 删除。会话以 `source_kind + source_id` 绑定创作对象（`project` / `world_bible_page` / `core_entity` / `world_library_topic`，读取时校验存在性），并保存工作区形状（`workflow_preset` / `target_kind` / `source_page_id`）供任意设备恢复到同一生成工作台。归档是软删除，已产生消息永不硬删。

消息只持久化终态记录：作者消息（可带四动作 `expand/connect/pressure/consolidate` 之一）、完成的模型回复、作者决定。生成类消息绑定来源 `context_confirmation_id` 与任务 `task_id`；候选类回复以 `outcome_suggestion_id` 引用既有 `creation_suggestion_queue` 成果，不复制建议内容。进行中的请求不落库：刷新后查询原 operation receipt，不自动重复提交，中断的气泡由前端标记为终态并允许显式重试。

会话绑定的生成请求仍走确定性工作流：同步会话聊天在 LLM 成功后原子追加作者消息与模型回复；异步候选任务把 `session_id` 与动作放入 task meta，worker 成功后追加成果消息。模型输入 = 近期消息（≤40 条）＋持久化作者决定（checkpoint 决定摘要）＋本次确认资料；完整历史仅可检索、可显式选入，不把“最近 40 条”当作全部创作记忆，服务端不替作者拼装隐性记忆。

checkpoint 续写沿用现有载体：会话只保存 `current_checkpoint_id` 工作区指针（checkpoint 本体仍是 suggestion 队列里的 `world_design_checkpoint.v1`）。推进指针必须携带 `expected_checkpoint_id`，与当前基线不符时返回可识别的 `pointer_drift` 409，提案保留、要求重新核对；旧 checkpoint 可读取可继续，不回写历史，不重置未修改区域，也不擅自晋升正典。会话条目状态（讨论中/待审阅/已存工作稿/已采用，另有作者否定）由消息成果引用 join 建议当前状态实时推导，不做冗余状态列。

## 影响与替代

考虑过复用 interaction 模块的 `interaction_message_nodes` 会话树：它是阅读原型的一项目一会话结构，按 `parent_node_id` 组织分支，与“一个来源对象多条会话、消息按时间分页、绑定生成 confirmation 与成果引用”的共创语义不匹配，跨模块还会引入 world→interaction 依赖。也考虑过继续用前端 localStorage v2 会话：无法跨设备、无服务端分页与检索，且 512 KiB/5 会话上限会把“完整历史”截断成最近若干条，违背第三期验收。

该决定不引入新事实源：会话消息是讨论记录，不是 Canon；候选保存与正典采用仍是两个明确动作，成果只能进入既有 pending 建议与采用流程；作者决定持久化的是“决定文本”，其权威载体仍是 checkpoint 与采用包。LLM 配置继续经 `open_project_llm_client` / secret-free snapshot seam 获取，会话不保存 provider 或 Key。

## 验证

后端 API 测试覆盖会话 CRUD 与来源校验、消息分页/检索、四动作合法性、聊天原子落库（失败不写半截回合）、任务成功后成果消息与 confirmation/task 绑定、checkpoint 指针推进与 `pointer_drift` 409（提案保留）、旧 checkpoint 只读续写、状态推导（pending/accepted+page_draft/accepted 其他/rejected/无成果）、跨项目 404 隔离与无候选自动采用。前端 Vitest 覆盖会话水合、发送回合、指针推进与四态渲染；e2e 覆盖跨设备（双页面上下文）继续、刷新不重复提交、重名资料 Wiki 引用选择与账号切换恢复。

## 当前实现范围

会话、终态消息、阶段成果指针和来源引用已持久化；指针推进使用行锁和比较后写入，本地编辑缓存按服务器会话隔离。完整消息分页/检索已有服务接口，前端尚无完整历史阅读/选择界面；同步 chat 尚无独立 operation receipt。当前阶段成果构造器仍重建 seed 状态，未实现基于父 checkpoint 的完整 world-state 增量续写；上文持续世界模型相关决策是目标契约，不能视为已完成验收。

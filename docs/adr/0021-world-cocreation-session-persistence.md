# ADR-0021 — 共创会话与持续世界模型

- 状态：Accepted
- 日期：2026-09-09；补全决策：2026-09-10
- 授权：用户确认世界观能力对齐第三期，并要求执行审查后的补全计划。

## 决策

World 自有 `world_cocreation_sessions` / `world_cocreation_messages` 保存项目内来源绑定、终态讨论和成果引用，owner 与 `novel_id` 继续隔离。主题目录只是作者组织层，不自动产生地理或事实关系。归档保留历史，旧成果在独立会话中继续。

官方聊天与世界模型推演通过 `POST /api/world/cocreation-turns/task` 使用既有任务队列。`world_cocreation_turn` 的 `mode=chat|design`、会话、当前成果、作者消息、显式选入历史、聚焦面向和原参考确认共同进入请求指纹；前端提交前保存 operation receipt，刷新/换设备查询原任务。同步聊天入口保留一个兼容版本并 deprecated，不作为官方前端的恢复路径。

worker 使用 secret-free project LLM snapshot；provider 前释放事务，写入前重验项目、来源及会话。终态作者消息、回复与可恢复结果在同一 lease-fenced commit 中保存，重入不重复追加；取消/旧 attempt 不写入。进行中的正文不作为终态消息保存，失败问题保留在本地和原任务请求内。session detail 返回最后操作的轻量引用，不能绕过任务 API 的 owner 校验。

模型输入由服务端装配：最近至多 40 条会话消息、当前成果的全部有效作者决定、本次显式选入的历史、作者聚焦的模型面向，以及同一 confirmation 允许的资料。浏览历史不会自动选入；客户端 assistant 文本不能替代服务器记录。新消息与已保存决定冲突时先核对，长期决定的修改由作者明确保存；候选生成的决定守卫同样消费这些边界。

完整世界模型沿用 suggestion 中的 `world_design_checkpoint.v1`，覆盖 19 区域。首次构造 seed；后续 `POST /api/world/design-checkpoints/revisions` 以父成果和 typed changes 合并，省略条目表示继承，废弃为显式状态，ID 和历史不因重排改变。服务端在会话锁内校验 expected pointer、保存新快照并推进指针，附带成果历史引用。旧 world_core/decision_state 摘要在新完整模型修订中清空，避免与当前世界状态冲突；旧父成果仍可读取。

受影响依赖、测试与下游状态重新待查，旧结果保留供对照。candidate/instance 依赖实际规则、生活情境与实例证据，不按聊天轮数自动升级，也不意味着 Canon 采用。模型条目可明确送入已有待审建议流程；模型快照本体不可直接采用。

容量使用既有 schema 上限、1 MiB 快照及有界上下文；聚焦面向可以缩小本轮读取，但不会静默裁掉长期决定。完整模型没有 Scene 可见性投影时失败关闭，不以普通作者模型替代人物/场景边界。资料库对象的真实 owner 由业务 `novel_id` 决定，模型内 `project.id` 保留其独立世界标识。

## 影响与替代

复用 suggestion、采用包、任务、Context 和 Vue bridge，不引入新的事实库、队列、自治 Agent 或 interaction 会话依赖。完整历史使用已有分页/检索和消息定位，聚焦、比较与编辑在当前工作区完成；后台任务引用不赋予资产写权限。

## 验证

验证覆盖完整状态保留、稳定身份、决定守卫、并发指针、来源变化、异操作指纹、任务重复执行与取消、历史定位/选择、跨设备恢复、未保存推演回看、局部编辑和窄屏。实际执行证据与尚未验证的模型质量/作者喜好分开记录；本地代码不等于发布或部署。

# Codebase 阅读与运行边界

本页帮助开发者从用户动作定位实际执行代码、确认资料和写入拥有者，再找到相应的恢复与验证说明。它解释当前代码阅读入口，不复制表/任务/路由目录，也不代表真实模型质量或生产状态已经验收。

代码基线：2026-10-14 核对，集成时重核至 `fd9e7279047ae6681893749e1d454e994dbea2b7`（Luna 运行时、审计首批与独立模型池三个合并后的 main 事实）。后续修改沿本页链接回读 owning source；若版本变动，重新核验受影响链路。

[查看流程图](runtime-boundaries.html) · [可编辑 Draw.io 图源](runtime-boundaries.drawio) · [完整模块图与图义](README.md)

## 1. 从问题选择阅读入口

| 想查的问题 | 先定位 | 再追到实际实现与文档 |
|---|---|---|
| 页面请求怎么到业务服务 | `frontend-console/vue/bridge/index.js`、对应 API namespace、`backend/app/main.py` 和模块 api | [前端文档](../modules/14_frontend.md)、[组合根 bootstrap](../../backend/app/bootstrap.py) 的 DI 注册；前端位置不是数据拥有者 |
| 身份、项目和有效模型 | `backend/core/dependencies.py`、Account middleware/context、Project facade | [Account](../../backend/modules/account/README.md)、[Project](../../backend/modules/project/README.md)、`llm_runtime.py` / `image_runtime.py`；按项目 owner 读取连接 |
| 保存、生成和采用 | Writing facade、API 与 tasks | [Writing](../../backend/modules/writing/README.md)；`services.py` 是兼容聚合，真实实现分为 draft/conflict/generation service |
| Scene 与历史状态 | `modules.story.facade` / contracts | [Story](../../backend/modules/story/README.md) 的 outline_state / continuity；Scene workbench 的 health/fusion/support 文件仍共享服务实例和锁 |
| 导入、检索和确认 | Imports orchestration 与 Evidence facade | [Imports](../../backend/modules/imports/README.md)、[Evidence indexing](../../backend/modules/evidence/indexing/README.md) / [compilation](../../backend/modules/evidence/compilation/README.md)；检索候选不替代最终回读 |
| 逐场景理解与局部复用 | Evolution API、workflow/pipeline、consumer_reuse、consumption | [Evolution](../../backend/modules/evolution/README.md) 与 [模块设计](../modules/22_evolution.md)；逐消费者证明，不只比较 Scene hash |
| 互动分支与流式恢复 | Interaction API、generation、tasks、服务职责拆分 | [Interaction](../../backend/modules/interaction/README.md)；选中路径/epoch、冻结来源和持久 buffer 与作者正文分开 |
| 任务、预算和恢复结果 | infrastructure/tasks、LLM runtime、Project snapshot | [任务契约](../../backend/infrastructure/tasks/README.md)、[LLM 基础设施](../../backend/infrastructure/llm/README.md)；恢复不等于重新付费采样 |
| 图片设备、私有存储与恢复 | World 图片/地图任务、Local Agent image runtime、部署 | [World](../../backend/modules/world/README.md)、[Local Agent](../../backend/modules/local_agent/README.md)、[部署](../../deploy/README.md)；设备目录、数据库和图片对象存储是不同边界 |

表中路径是定位线索，跨模块依赖仍经稳定 facade/contracts/已注册 DI port。所有生产组件与公开目录以现有 [机器清单](architecture-documents.toml) 为准；本页不是另一份 API 或表清单。

## 2. 对一条调用链至少读到哪里

从真实用户/API/worker 入口读参数和身份门禁，继续跟到所属领域的实际实现、读写来源、事务与失败回执。不要停在稳定再导出壳，也不要由日志中的“已完成”推断正式采用。内部 helper 的位置变化不等于公开契约变化。

### 已确认的正文候选

Writing 提交先重物化 `writing.generate` 的 Evidence confirmation，固定原请求范围与 Project secret-free snapshot；worker 准备和结束时再次核验确认、Scene/基稿/知识 guard 与实际来源指纹。外部 provider I/O 位于数据库长事务之外；可恢复候选 checkpoint 只在证明仍相符时复用。结果先落候选，作者采用再锁章节/稿件并重验上游与复核资格。

采用回包丢失时，同 `idempotency_key` 返回原采用稿件；无键/异键仍失败。此幂等语义不能写成“重复采用总是拒绝”。实际入口见 Writing generation/draft service，Scene bundle 通过 `modules.story.facade` 读取。

### 演化理解与世界采用

Evolution 固定 Scene/正文区间、前序回执与 owner epoch，形成 observation、身份解析、世界/关系候选和独立审查。`apply_frozen` 在最终来源/前序复验后，以短事务保存候选与回执/游标；World 的作者采用入口再次回读确认其当前资格。模型建议、未采用候选和 Canon 是不同状态。

真实消费者输入未变且完整请求证明一致时可以复用；不同输入仍需核验或重算。关系历史的一个合成用例断言模型调用总数为 8，限定于该特定冻结前缀的复用场景；
本轮仅核对测试源码，未运行该用例，也不证明所有改稿都没有额外调用。地图册当前已保存版本的已发布正文来源已有建议性核对（写入回执的失效提示）；地图册非正文/待审来源与正典 revision 尚不属于已登记的自动失效消费者，没有回执不能当作仍然有效。

### 绑定作品的私人互动

Interaction 保留自己的 attempt/context、selected path、selection/source epoch 与 SSE 持久缓冲路径，不机械套用作者 `writing.generate` confirmation。绑定作者作品时，来源按授权的固定 revision/截止点只读引用；生成和选择写 consumer 项目。未选分支不进入后续历史，互动正文不回写作者正史。

### 本机图片与旧任务

已登录的项目业务文本任务使用 Project 账户连接。Project 恢复拒绝旧本机文字 snapshot，直接 task_snapshot_client 同样拒绝；这些是确定的入口门禁。

本机图片经 World 提交、设备/owner/novel_id/双租约、image mode 与输出重解码，再按领域确认采用。设备工作目录不是 OS 沙箱。源码保留旧 invocation 与 companion 的文字兼容分支，但待确认/批准与设备领取入口只接受图片任务，旧文字 pending 记录在这些入口置为 failed；兼容分支只是形状，不是可领取的文字入口。

## 3. 事实应该写到哪里

- 模块职责、稳定 seam、恢复边界写已有模块 README / 设计文档；源码与 ORM/migration 判定事实，测试源码仅说明断言范围。
- 跨模块概念写 CONTEXT，整体责任写整体设计；表/路由/任务/Prompt 各自只有现有权威目录。本文链接它们，不重新枚举。
- 开发阶段 Luna/max 业务约定见 AGENTS 和开发指南。它是运行约定，不证明 B 已接入新 Codex owner/provider；旧独立真实 eval 仍暂停，接线与校准完成前保持适用业务调用停止。
- 任务/历史/在途证据保留日期、SHA 和验证身份；不将其重写为最新主干能力。当前文字、图片、试验开关与生产部署分别核验。

本页链接 [文档维护协议](documentation-maintenance.md)，不新增权限、模块、队列、数据库或发布流程。图解只呈现上述运行边界；本次开发工具子代理的分工不属于产品运行架构。

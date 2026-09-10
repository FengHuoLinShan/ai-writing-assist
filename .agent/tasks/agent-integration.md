# Agent 核心接入与全项目能力整合

## 当前范围修订（用户批准，2026-09-10）

执行“功能补全与体验修整计划”：已有服务优先复用，缺失服务在原领域补齐。联网改为自托管
SearXNG 与项目受控网页读取，用户已明确选择并要求实施；原生联网不再是关键依赖，旧任务
仍按冻结协议执行。新渠道需要显式范围说明，不能自动继承旧供应商联网授权。模型与网络预算
分别计量，恢复累计值不重置。新增共享层的风险为外部内容/SSRF、协议恢复及调用计量，必须
有地址绑定、来源/权限和兼容测试。

本轮只补功能与 Computer Use 开发体验：四条作者链、RP、变化驱动服务、领域回执与旧入口
收口。人工盲评、提醒精确率、作者效率指标、正式验收及发布延期；必要工程测试/lint/build/
docs-check保留。完成后分别记功能完成与正式验收待安排，不伪称原P0–P5全部验收通过。
继续codex/agent-integration，保留全部WIP；不自动提交/推送/合并/部署。当前docs-check通过。
本轮功能补全与 Computer Use 修整已收口。后续只在用户要求恢复正式验收或发现新功能问题时继续；不自动推送/合并/部署。原 P0–P5 总体验收保持延期。

## 目标与验收

用户已明确要求完整实施 P0–P5。作者与 RP 同步升级，不能在 SDK 或单场景接通后结束。
统一项目助手 + 专业工作台；RP 每轮全面 Agent 化；变化驱动的主动检查、站内提醒和回访
摘要；模型供应商原生联网。用户选定质量优先、自主查证、业务成果成组确认、RP 仅通用事实联网。

完成条件：全部能力台账有整合结果；作者四条任务链和 RP 全流程通过；工具协议、联网、
权限/来源、恢复、确认、主动服务、迁移和旧入口收口通过；文档和适用工程门禁完成。
作者步骤目标降低 30%；人工标注强提醒精确率至少 90%；RP 关键约定/知识/分支全部通过，
冻结盲评不低于基线。真实用户使用数据单独报告，不以模型评分冒充用户认可。

## 授权与边界

- 用户已批准新增 Assistant 业务域、PydanticAI 核心、工具协议、World 通用会话归属迁移与 ADR。
- 只允许注册的领域工具；身份由服务端绑定；沿用 owner + novel_id、Evidence、schema、
  CAS/lease、采用/回滚与 source-bound RP 唯一跨项目只读例外。
- 使用当前已验证账户连接及 Project runtime seam，不自行换模型/Key，不引入 Tavily。
- 原生搜索按供应商/模型/协议验证；DeepSeek Responses web_search；Kimi 官方工具/内置搜索。
  Kimi 启用继续受原有真实门禁约束；外部内容不得成为原作后续/角色知识或工具指令。
- RP 故事树/selected path/overview/attempt 仍归 Interaction；发送/继续/看海授权相应输出和
  既有自动摘要。长期约定、手工回顾和既有分支变更需明确决定。已显示内容不静默替换。
- 查证和临时建议无需逐步批准；业务写入成组预览确认。既有已授权导入流水线不扩大授权。
- 合并、推送、部署仍是独立授权边界；当前不自动发布或操作真实开发/生产数据。
- 用户在2026-09-10明确授权两项只读并行核对：RP全流程、能力台账与验收缺口。禁止代理写文件或真实数据。

## 当前上下文

- 工作目录：`/Users/tywww/Desktop/项目/ai-writing-assist`
- 基线：`a8de5aa9e98301943e4311aa1e5a356dd1fb177e`，远端 main 已核对。
- 分支：`codex/agent-integration`，从最新 origin/main 创建；初始无用户 WIP。
- 基线清单：8 business modules / 110 ORM tables / 40 handlers / 15 routes / 30 ADR files。
- 现有 World 第四期已经落地，不重复制造影响图/复核聚合；World 共创会话与旧结果引用要保留。
- Python 3.12 + FastAPI + PostgreSQL 队列 + Vue 3；backend uv.lock，已有 backend/.venv、frontend node_modules。

## 阶段与进度

| 阶段 | 必需交付 | 状态 |
|---|---|---|
| P0 | 能力台账、用户任务基线、供应商矩阵、ADR、迁移方案、评测集 | 进行中 |
| P1 | PydanticAI、工具协议、原生联网、预算/停止/检查点、旧 LLM 回归 | 离线核心已实现，183 项 LLM 测试通过；真实协议/持久恢复待完成 |
| P2 | Assistant 会话、World 共创迁移、作者所有领域工具、成组提案/采用 | 已实现主链与部分领域；完整覆盖/UI验收待完成 |
| P3 | RP 每轮 Agent、角色可见查证、联网隔离、全流程/质量验收 | 代码与定向回归已接入；真实盲评/全流程待完成 |
| P4 | 同事务变化标记、增量分析、去重/暂缓、提醒和回访摘要 | 各类别已接；范围和端到端收口进行中 |
| P5 | 入口/重复实现收口、完整回归、文档、交付预检 | 未开始 |

## 固定运行默认值

| 类型 | 模型请求 | 工具执行尝试 | 联网子请求 |
|---|---:|---:|---:|
| 作者 | 12 | 32 | 4 |
| RP | 8 | 24 | 2 |
| 后台 | 6 | 16 | 2 |

计入内部复核/联网子调用；恢复不重置累计值；单 run 总时限 30 分钟；现有模型输入/输出上限
继续执行。达到预算保存未完成结果，显式续查才创建新预算。不叠加 Pydantic 与旧格式修复重试。
费用未知明确显示未知。主动服务默认关闭，启用后每项目每日 12 次合并分析；普通保存稳定
60 秒，同目标 10 分钟合并；主动/发布前检查不等待；每项目后台最多一项，前台优先不抢占。

## 能力台账

| 能力域 | 既有能力/入口 | 整合方式 | 验收状态 |
|---|---|---|---|
| Account | 公开身份、加密连接、设置/验证/余额；account facade | 复用安全连接，增加 Agent 能力/用量投影 | 未验收 |
| Project | 项目/偏好/回收站、workspace summary、author tasks | 助手上下文、持续授权、提醒/回访入口 | 未验收 |
| Imports | file/deep/stages/source update/targeted completion、resume/rollback | 封装现有受控流程与范围确认 | 未验收 |
| World 资料 | Page/Draft/Entity、人物知识、关系/别名、目录/图谱、Canon/history | 查证、编辑提案、批次采用，事实所有权不变 | 未验收 |
| World 共创 | generation center、sessions/messages、checkpoint、ask world | 通用会话迁 Assistant，引用既有建议/成果 | 未验收 |
| World 复核 | validation runs/items、policy、impact、continue | 工具化复用 run/coverage/author adjudication | 未验收 |
| Story | 总纲、剧情线/篇章/Scene、卡/剧本、伏笔/揭示、continuity snapshots | 上下游查证和结构提案，adopted-only 下游 | 未验收 |
| Writing | autosave/history/publish、candidate、conflict/semantic review/targeted revision | 当前草稿范围、审查/建议、成组采用与恢复 | 未验收 |
| Evidence | indexing/search/read/inspect/trace、confirmation/snapshot、focused evidence | 统一内部证据工具，来源/知识/排除项在返回前校验 | 未验收 |
| Map/图片 | World 内统一空间版本、图片/校准/候选/历史/私有存储 | 查找定位、修改提案、原有确认；不推造地理 | 未验收 |
| Interaction | source revision/selected tree/overview/agreements/attempt/SSE/see sea | 共享核心替换每轮生成入口，保留全部领域约束 | 未验收 |
| Runtime | LLM gateway/limiter/guards、tasks/lease/coalescing/receipt | 扩展协议/执行，不新增队列或自治多 Agent | 未验收 |
| Frontend/交付 | Vue shell/islands/bridge、15 routes、恢复/窄屏、E2E/部署 | 持续助手、可操作结果、旧入口兼容后收口 | 未验收 |

## 决策与发现

- 本次用户授权取代旧的全局禁止工具选择条款，例外范围通过 ADR 固定；不全局放开数据/权限。
- 当前 LLMMessage 只有 role/content，工具 ID/参数/结果/续接必须先补齐；避免通过 raw/extra 绕过校验。
- 通用会话迁移不能双写；RP 不使用普通会话作为新正史源。
- 现有模块中若缺少 Agent 需要的稳定入口，工具置于所属领域并通过注册 DI 暴露，避免跨域导入实现。
- API key Skill 已检查：本任务显式指定 DeepSeek/Kimi，符合其“names a different provider”排除项，
  不触发 OpenAI Key 申请/阻断；不读取或修改 OpenAI 图片凭据。

## 验证

- 初始 `make docs-check`：通过。
- 主干/工作树：已 fetch，基线正确，初始干净；ready-for-agent issues 列表为空。
- 后续按影响运行 pytest/ruff/frontend tests、PostgreSQL 并发与迁移、真实 worker/browser、
  默认 DeepSeek 真实工具/联网以及固定 holdout。付费测试仅使用明确测试授权和独立数据。
- 尚未执行任何真实模型调用、迁移、用户试用或部署。

## 恢复快照

状态：主计划已获实施授权，刚创建主题分支并完成初始文档门禁，正在 P0/P1。
下一步：添加 ADR/架构例外并核实 pydantic-ai-slim 固定依赖与 Model/StreamedResponse 实际 API，
然后先实现兼容旧调用的工具协议和受限运行核心。

## 实施检查点 2026-09-10

- 依赖已固定 pydantic-ai-slim 2.42.0，backend/uv.lock 已更新；本地 venv 已同步 ci+dev。
- `infrastructure/llm/agent_runtime.py` 实际使用 PydanticAI Agent/Model/StreamedResponse，
  请求/工具/联网预算与隐藏 reasoning 续接已实现；schemas/provider 加性支持工具消息并
  拒绝 extra/extra_body 工具注入。native_search 隔离 DeepSeek Responses 和 Kimi builtin 协议。
- `pytest infrastructure/llm`：183 passed，1 deselected。真实调用尚未运行。
- World 共创 ORM 移到 assistant/session_models.py，物理表与 ID 保留；World 类型仅 re-export。
  统一 sessions.py 服务，通过 4 个 World DI ports 校验 source/checkpoint/outcome/chat。
  World 旧会话测试 6 passed；与 Agent 定向合跑 11 passed。
- 新 Assistant ORM: runs/action_batches/notices/watches；迁移 20260911_assistant_runtime 已写，
  尚未运行 PostgreSQL 迁移。元数据已在 bootstrap/conftest/alembic 注册。
- 新 /api/assistant 会话/回合/运行/停止/批次确认接口、assistant_turn handler 已注册。
  领域操作当前只有 writing.revise、project.add_task、World 对象创建/编辑/资料工作稿、
  story.edit_scene，远未覆盖完整计划。
- Assistant evidence_tools 仅走 Evidence，支持原 confirmation 重物化、排除项、当前 Scene、
  隔离联网和证据回读；还需负例/数据漂移测试、当前对象读取、完整会话查询。
- assistant_enabled / interaction_agent_enabled 默认 False（新 core.config 字段，Settings frozen）。
- 正在跑 `backend/modules/assistant/tests/test_assistant.py`；已修正根 fixture 名 async_client
  和 frozen Settings 注入（用 dataclasses.replace + service.get_settings monkeypatch）。
- 环境存在 DEEPSEEK_API_KEY（未读取/显示明文），没有 KIMI_API_KEY、E2E_DATABASE_URL。
  可做 bounded DeepSeek live；PostgreSQL 验收需独立测试库，不得迁移 backend/.env 开发库。
- 当前所有修改未提交/未推送/未部署。新 Assistant 文档已建，architecture registry、
  中央模块/数据库/Prompt/前端清单与图仍未同步，docs-check 收尾尚未通过。
- 接下来：修复并通过助手 API 测试，扩展领域工具与 UI、完成运行检查点和续查；
  再接 RP Agent 与主动服务。必须继续 P0–P5，不把当前实现视为完成。

## 检查点：作者界面与 RP 接入

- DeepSeek live gate 已实际通过（`RUN_ASSISTANT_REAL_LLM=1 ...test_agent_live.py`，1 passed）：
  工具循环、结构化结果、原生联网引用、流式输出/停止。实测发现 thinking 拒绝强制 tool_choice，
  已在 ProjectGatewayModel/隔离联网改用 auto，并保持结果/联网执行记录校验。
- 助手 API 测试 4 passed：预览/确认/重放、会话 ID 保留、跨项目拒绝、无 Key/身份注入拒绝。
- frontend 新 ProjectAssistant 面板、useProjectAssistant、API namespace、Topbar/Shell 入口；
  复用 workflowManager，novel_ 前缀备份可随账户清理，提交不确定性保存原 operation ID。
  前端定向套件 32 passed（assistant controller/context、Shell、mountIsland）。尚未浏览器视觉 QA。
- 可用操作扩展到 imports.organize、map.create_node/review_revision；完整领域覆盖仍未完成。
- Agent 私有 ModelMessages checkpoints/resume、正文基线重验、确认前来源重验已加；
  run resume 和 session latest_run 接口已加。部分失败批次 retry、决定会话记录仍待完成。
- RP 新 runtime_policy 冻结到 Project snapshot，agent 模式用独立
  interaction_agent_story_generate，所有发送/继续/看海分派与取消类型集合已改；旧快照保持 legacy。
  新 InteractionAgentRun 自主 selected-history/source/native-fact lookup + 原有流式 finalizer；
  attempt.agent_checkpoint_json 持久私有状态与预算，预算并入 usage 不重复累计。
- 旧 RP/Project runtime 定向回归 96 passed；新 RP happy path + 核心恢复/预算/隐私测试 13 passed。
  新模式仍需来源绑定、取消/长度续写、人工回顾与真实模型盲评/PG 验收。
- 新 `workflow_budget.py` 及 LLMClient.generate 可对已有确定性复核按 ContextVar 附加累计预算，
  尚未接入后台调度，正跑 client/core 测试。
- P4 仍未实施：计划复用现有领域复核任务，通过明确注入的 worker wrapper 计量/投影提醒，
  不把 Assistant 自己的 findings 变成第二个领域复核真相。
- 待核实/修正：Map create_node 返回 dict（已修）；review_preview 仅 adopt（已分支）；
  草稿/实体 AI 来源追踪需同步，报告/检查点正文长期保留需清理；批次源漂移/部分重试待补。
- 全部代码仍未提交；文档清单/中央文档/DB/Prompt/模块图尚未同步。

下一步：完成后台变更合并/授权/预算/领域复核/站内提醒；完善各域操作与 UI 后做全门禁。

## 检查点：主动服务与确认恢复（2026-09-10）

- P2/P3 已在本地接入作者助手/RP Agent，仍未完成全能力覆盖与验收；阶段表中的“未开始”是早期历史快照。
- P4 已有 assistant/proactive.py：持久授权、同事务 dirty 标记、60 秒稳定/10 分钟合并、每日额度、单项目后台所有者、已有队列前台优先、domain handler wrapper + 累计预算/授权重验、来源变更抑制、去重/已读/暂缓/忽略。
- Writing repository 所有有效正文创建/实际修改发 source.changed，重复保存同文不触发；World 复用 Evidence mark_asset_context_changed 事件。RP 路径/overview/source epoch 变化也发同事务事件。
- 新 Interaction 增量复核 handler `interaction_continuity_review`，只读近期选中节点+有效回顾+固定来源；两处原文均可回读才保留 finding，不改写故事。新 /journeys/{id}/care policy/notices 由服务端解析隐藏 novel_id。
- Frontend ProactiveCare.vue 已嵌入项目助手/RP，保存失败保留设置、晚到旧项目响应丢弃、忽略只处置提醒；源码定位需继续实机验收。前端定向 65 passed。
- 批次增加显式 retry_operation_id，保持成功组、失败依赖阻断、重放不重复写入；修正确认预检丢失 AssistantOperationContext 的问题，追加作者决定消息。
- 正文助手修订记录 assistant_revision 来源/原 context_origin/原稿基线/批准人；人工来源仍只声明 prose-only，原 AI 来源仍要求原 confirmation。World 创建标记 assistant run，采用者为确认的 owner。
- Native search：区分协议适配与实际验证，runtime 只注册已 live 通过的 DeepSeek V4 Flash；Kimi/V4 Pro 等待各自真实门禁。外部问题过滤内部 UUID/私人原文/原作检索，引用拒绝 localhost/private IP。
- 单元验证：assistant + RP 新用例 13 passed；含 native/runtime 的定向集 20 passed；World review preview→confirm→queue 实际链发现 user_note 改变指纹，已统一参数，复测通过。
- 正在运行旧 LLM+task infra+RP+Writing+World session 较大回归：exec session 81058；最近约 33% 通过仍在运行。不要重复开始同套。
- docs registry 已注册 Assistant（9 域），DB 4 表、运行默认值与 3 新任务已补；仍需中央文档、模块说明、diagram、Prompt 清单和真实迁移检查。
- 可用本地 Docker PostgreSQL：ai-novel-db，pg17/pgvector，host port 5207。尚未创建独立测试库或运行 migration；禁止迁移真实 backend/.env 数据库。

下一步：收齐后台审稿与断线/授权边界测试；继续补齐 Story/Imports 变化触发与被限制的排除范围传播、更多领域成果操作、旧共创入口收口；创建独立 PG 做迁移/并发/真实 worker/browser，再完成全部文档/工程门禁与质量评测。
待解决：后台某些失败/关闭授权 orphan 的恢复显示；已完成领域结果的通知投影重试；后台正文原 confirmation 与自定义排除范围目前明确拒绝；Story/Imports 类别尚无 submitter，不能把当前主动服务说成全域已完成。全部修改仍未提交、未推送、未部署。

## 检查点：PostgreSQL 与文档基线

- 较大旧回归：644 passed + 2 因错误 cwd 失败（不是实现错误）；在 backend cwd 定向补跑两项后 2 passed。今后全部 backend pytest 使用 cwd=backend，路径不再带 backend/。
- 当前新链路测试 13 passed，native/runtime 合集20 passed；前端助手+RP定向65 passed，定向ESLint通过。
- 已创建独立 PostgreSQL 测试库 `ai_novel_agent_e2e_20260910_1`，仅该新库执行了 Alembic head（完整链成功），没有改动真实开发库。
- `tests/e2e/test_assistant_concurrency.py` 在该库 1 passed：两连接批准重放仅一条待办、两连接 dirty 合并不丢更新、同时后台领取仅一个run。需显式 -m e2e，默认pytest排除此类。
- 构造测试数据库 URL 的安全方式：在 backend/.venv/python 中从 get_settings().database_url 用 sqlalchemy.make_url 读取，不打印；断言 host=127.0.0.1/localhost 且 port5207，再 .set(database=上名)，仅传 subprocess env E2E_DATABASE_URL / DATABASE_URL。不写含密码文件，不打印原始配置。
- `alembic check` 未通过：输出均见旧模块（Interaction source index旧名称、memory nullable、author task updated_at、story scene-script FK、world library FK/constraint/index、world validation updated_at）。需要进一步固定证据区分既有漂移与本次新增，不能声称整库schema同步通过。新助手迁移本身执行成功。
- `make docs-check` 当前通过：9 business modules /114 ORM tables /43 handlers /15 routes /31 ADR files；已补Assistant注册、中央模块导航、DB表、runtime task说明、drawio/HTML新节点。
- `make docs-check BASE_REF=origin/main` 的影响文档核对尚未收尾。图源暂未浏览器视觉验收；CONTEXT插入段附近要检查衔接。
- 当前没有运行中的测试session。未提交/推送/部署。

## 检查点：当前资料读取与编辑保护

- Assistant 新 inspect_current 工具：从当前工作位置经 Evidence 精确回读正文（每段最多8000字）、World工作稿与采用的地图空间版本。正文范围复用 Writing.build_manuscript_range_ref，包含正文/范围双hash，不手工拼不完整SourceRangeRef。
- Evidence._visible_target 增加 author-only world_bible_page_draft / world_bible_draft / map_atlas_node。World稳定facade提供工作稿/地图material；不返回私有图片URL或Prompt。读者/角色被拒绝。Map任何自定义排除范围暂明确拒绝完整地图回读，避免间接带回排除依据。
- 修复 prefixed writing_draft:<id> 排除项没匹配 SourceRangeRef 的问题；guard 现在同时匹配规范target与裸UUID。新 inspector/排除/author-only测试3passed，原novel_evidence回归25passed。
- frontend 批次确认前经 bridge SHA-256 核对当前编辑器，未保存的新输入会阻止旧正文方案提交；新增 writingFingerprint 可注入测试seam，不读取模型配置字段。
- 部分失败重试在本地备份 decisions 中保存同一 retry_operation_id；刷新/失去响应后复用原回执；服务端公开batch.selected保持原授权集合。新增2项前端测试通过，助手+Shell定向26passed。
- Assistant后端定向12passed；无活动测试进程。
- 自动生成 `.agent/tasks/agent-capability-inventory.json`（从当前API路由和ORM，标为pending_review，不伪装验收）。若数量为0需检查FastAPI新版本lazy routers展开方式后修复。该台账仍需补齐实际工具/受控界面/兼容入口映射，不能将所有HTTP包装成工具。
- 仍需补各域能力操作与主动服务闭环、严格范围传递、长期私有checkpoint过期、真正worker/browser与质量评测。原完整P0–P5目标未改变。

## 检查点：领域成果、真实 worker 与用量

- 能力原始台账已修正 FastAPI lazy router 展开，当前 487 route declarations /114 tables；`.agent/tasks/agent-capability-inventory.json` 全部仍为 pending_review，不能算能力闭环。
- 新 project_overview 经 Evidence target=project_workspace 复用 ProjectWorkspaceSummaryService（只读待办/恢复位置/待处理概览）；限定 confirmation/排除范围时拒绝扩展。新 scene_assets 经 Evidence author-only scene_story_assets 读 Scene 人物卡/剧本；不是角色知识证明。
- Story 新操作 story.save_card / story.save_script，保留版本与採用、来源/批准；移除普通edit_scene的status/scene_index/chapter_ids，防止把归档与来源迁移夹带进普通编辑。新增真实领域测试1passed。
- World 新 world.adopt_package，复用已存在采用包preview hash与World validation门禁；未单独做新wrapper验收。
- 有修改提案时，在生成结束和批准前重验所有实际读取的事实证据，不只模型自行选择引用的证据。project_workspace是瞬时事项元数据，不参与资产写入授权，各操作自己的baseline仍强制重验。
- Budget新增 pending_usage/usage_unknown：请求发出前就持久化缺失用量，worker中断/取消后不误报完整；原生多请求结果按实际requests结算。旧 unknown 预算保守恢复。26项新核心/助手/RP测试通过。
- Pydantic流式与RP流式在Task已被取消时不再尝试旧lease checkpoint；已预留请求的未知用量保留。正式RP完成会清理私有模型历史/原文副本；其他终态清理仍需核对。
- Proactive去重按正文chapter + 原文证据而非draft版本ID；当前实现已改，跨新版本的专项去重测试还需补。提醒/领域结果/Task终态改为由worker最终fenced commit一并提交，避免崩溃后留下没有完成任务回执的提醒。
- _run_guard强制watch.active_run_id归属，旧后台恢复不能绕过新后台的单项目执行所有者。
- 独立PG测试tests/e2e/test_assistant_concurrency.py追加真实TaskWorker（使用合成领域handler）首次失败→新worker实例manual resume，验证预算不重置与通知终态原子性；exec session 12165 结果需读取（下面如已完成则按最新tool结果）。
- 仍需：Story/Imports主动检查submitter、确定性结构影响与正文审查的责任/权限衔接；允许范围的精确传递；持续授权/提醒UI更多定位；私有checkpoint过期；完整领域操作覆盖；browser/390px/真实RP盲评；全量docs影响门禁。

## 最新恢复快照：2026-09-10 清晨

- PG真实worker扩展测试最终通过（1 passed,1.49s）。第一次失败其实按Writing既有auto_requeue退避1秒，并非manual_resume；新worker在退避后继续，累计requests=2且失去的用量仍unknown。纠正上条“manual resume”措辞。真正Manual Assistant回合恢复仍按原实现/单测。
- DeepSeek live gate新增实际数据库保存的Pydantic模型消息→中断→新Agent从原工具结果续接，工具不重复执行；原生联网和stream close通过。1 passed,17.55s。
- `backend/.test-artifacts/assistant-live-core.json`：gateway_model_requests3（含stream），native_web_requests1，reserved_requests5（含人为中断预留），lookup实际执行1，引用来源3，已知输入8541/输出1362，首段0.628秒，总17.183秒；流中止/中断使usage_complete=false，费用unknown。只有合成协议样本，不是RP质量验收。
- make docs-check继续通过，全部diff --check通过；BASE_REF影响门禁仍待模块文档补齐。最新代码还有若干格式需ruff最后扫，Story工具单测1passed、Assistant新范围集26passed。
- 当前没有运行中工具session；所有改动未提交。独立PG库仍在，不删除；真实开发库未改。

### 接下来要解决的实质缺口（优先）

1. P4 Story/Imports类别目前仍无submitter，schedule_due会丢弃这两类dirty。这不是完成状态。Imports应在ImportWorkflowRunService.complete同事务发事件；Story card/script保存/采用目前也未发Evidence变化事件，需补所有实际修改入口。
2. Writing manual稿现有独立审稿严格prose-only；原AI candidate必须原generation confirmation且stale fail-closed。不要为主动检查放松这一约束。可研究对manual稿使用站立授权重新物化专门的review Context，只声明已覆盖的正文/世界约束，不签署人物知识；保持原AI candidate分支不变。
3. World builtin policy.semantic_enabled默认false，当前助手world.review/proactive只复用原policy，所以没有已发布语义policy时仅规则检查。要完成主动逻辑建议，优先考虑World-owned“建议性语义复核”独立运行policy快照：仅无用户active policy时使用固定default questions，保存到现有WorldValidationRun.plan_json；不可作为Canon采用许可，用户发布policy后旧建议性run stale。不是简单改builtin/擅自启用用户World政策。需读_policy_for_run/_refresh_freshness/采用gate，更新ADR与测试再实施；此想法尚未实现。
4. Story结构变化可以先复用Story现有stale card/script/关联正文状态做确定性引用检查，再按授权把需要正文语义检查的变更交Writing；不要用生成任务假充审稿或用规则finding凑强提醒90%。
5. 作者能力仍未全覆盖：大纲/剧情线/篇章/伏笔、alias/relation、共创checkpoint、恢复/撤销/地图编辑与图片受控入口、读领域任务结果。增加实际任务需要的操作与可定位结果，不自动包装所有HTTP。原487条台账需要逐项归并并标明复用/封装/补齐/受控UI及验证。
6. 回访提醒/成组操作链须real browser/390px和P5流程测试；前端目前只做定向Vitest。提供已验证支持矩阵与冻结评测/人工盲评包，缺少真实用户数据不能编造。
7. 进一步核实alembic check旧漂移，完整迁移身份/分页关联验证，以及所有受影响模块/lint/docs/架构边界/Prompt门禁。

## 关键最新实现（恢复时以本节优先）

- World 未发布正式policy时现在用 `assistant-advisory-v1` 两条固定语义问题，保存现有 WorldValidationRun.plan_json.advisory_policy + scope_json.purpose。不会发布/修改World政策，不可作为正式采用许可；后来发布或关闭政策会使旧诊断stale。正式已发布policy（含disabled）优先。World 23项回归通过，新增测试涵盖draft Context真正入包/未改policy/采用拒绝。
- 修正World复核草稿的类型：manifest是world_bible_draft；Context通过selected_world_bible_draft_ids纳入，不能仅用world_bible_page_draft pinned refs假装覆盖。
- 外部问题/结果过滤更完整：包括结构化inspection中的私人长文本、RP实际历史/Context；结果含原作名/指令注入/缺引用不进入模型资料。新增单测通过。DeepSeek web_search_call需completed才算联网；官方参考https://api-docs.deepseek.com/api/create-response/、/guides/responses_api/（本轮重新核对）。
- Imports.complete会发同事务import_workflow事件，新增imports_completion_review只汇总原workflow覆盖/降级，不做语义审稿；Story新增story_reference_review复用采用剧本的basis/stale投影（Scene及关联Arc/thread范围最多20Scene），只做引用失效检查。
- Story card/script保存/采用/取消采用、Scene/Arc/thread Repo create/update已发事件；规范化scene/scene_story_assets→outline_scene，world_entity→core_entity，draft别名统一，避免重复目标。Imports/Story新增事件/回执测试15passed。
- 后台调度等待同项目ImportWorkflow稳定收束（含待恢复run），不抢看中途派生资料。Writer/World/RP/Imports/Story都有submitter。
- 基础设施改用通用_task_priority=background排序；worker在多槽配置保留一个前台位置（默认2槽）。新增inline_only模式只给原父助手调用，普通队列不领取。
- 只读复核不再放在确认批次：AssistantOperation.permission=suggest的world.review/writing.review由review_assets工具直接调用。用已有run_task_inline执行固定领域步骤，Parent TaskWorker.info.task_scope + workflow_budget验证，父子lease同时fence；共享同一个预算，预留1次最终回复。子流程使用父Project snapshot，固定供应商/key恢复规则。不是多Agent/第二任务平台。
- inline executor detach task progress以允许domain.expire_all；服务端停止助手先停止可信domain_reference中readonly子任务再停止父任务，避免反向锁顺序。
- 新PG tests/e2e/test_assistant_review_runtime.py已通过：实际TaskWorker→Pydantic Agent→Writing固定审稿→结果引用，2次父模型+1次子模型共3次预算，无确认批次，无正文修改。使用合成provider，非模型质量验收。
- PydanticAI output_validator已校验各操作参数与引用/依赖，修复走SDK同一retry预算；不能把suggest复核放actions。测试证明无额外应用重试。
- budget超限会给可见过程资料和未完成说明，不只留私有checkpoint；公开sources投影不返回完整inspection。orphan无task_id运行能失败/停止，避免卡住会话。
- WorkContext新增有效timezone，提交时冻结calendar_date，续查保留原日期；“明天”不因队列延迟/恢复漂移。前端捕获浏览器时区。
- 新story.save_outline（版本化、确认后当前总纲）、story.create_scenes（追加最多20个场景，project锁+基线，不改现有正文）；新增空项目起步测试2passed。

### 最近门禁

- 大范围backend回归：1738 passed /12 skipped /5 deselected，2失败是旧测试替身Thread/Arc缺novel_id；已补齐实际契约，正定向补跑exec session11778（读取结果）。
- frontend助手/RP/Shell：17files184tests passed，定向ESLint通过。
- earlier worker/assistant suites129passed；新SDK/domain校验5passed；PG并发/恢复与父子复核各1passed。
- make docs-check刚通过：9业务域114表45任务15路由31ADR。BASE_REF影响门禁仍未收尾。
- ruff仍需最后全扫（新增代码/长行/import整理），未跑完整frontend build和真实browser。

### 不要忘记的未完成工作

- 完整能力台账仍为487项pending_review；需补主要作者能力（剧情线/篇章/伏笔/别名/关系/共创候选/checkpoint、地图编辑图片受控入口、撤销/恢复等），不把所有HTTP包装成工具。
- Writing manual稿仍prose-only；需要研究在持续授权下专门物化review Context以核对世界约束，同时不放松原AI candidate原generation confirmation与人物知识边界。不能声称已全覆盖。
- review_assets当前对失败/旧running子任务仅返回已有部分回执，不自动重放。父停止后若子finalize被父lease拒绝，子可能需stale收敛；需明确清理/恢复测试与追踪，不能放开inline_only让普通worker丢预算执行。
- 需要当前运行事件恢复API、结果/来源UI定位、更多作者全链与RP取消/断流/看海真实浏览器/390px验证。
- P0冻结代表任务、支持矩阵、盲评/强提醒人工标注评测包未齐；不能拿规则提醒或自动评分凑90%，不能把现有绿色单测说成真实用户认可。
- 新迁移在独立PG库成功；alembic check有旧模块漂移（详上节），需固定证据核实。真实开发库未改。
- 模块/中央/Prompt文档和BASE_REF gates未收尾，未提交、未推送、未部署；合并/推送/部署仍保留授权边界。主计划未完成，继续实施。

## 当前交付边界更新（2026-09-10 08:40）

- 新增运行事件游标API `/runs/{id}/events`（只读恢复、安全事件，不暴露私有模型消息），有游标去重测试。
- 新增world.add_alias/add_relation（关系要求明确relation_kind）以及writing.new_chapter；别名/关系/新章领域测试3passed，确认与原World门禁保留。
- 新增World/Story/Writer操作的可读字段标签和来源/成果回跳。作者助手把讨论与提醒分为两个视图，避免390px展开设置时挤压正文。
- `tests/support/assistant_browser_app.py` 是严格guard的专用agent_e2e本地库测试app：真实API/worker，只有LLM IO合成；绝不能用于真实环境。
- `playwright.assistant.config.js` + e2e/assistant.spec.js 已通过真实API/worker的提交→确认→待办落库、跨页/刷新保留输入、390px键盘退出/恢复、提醒设置；第一次失败是合成provider误用notes而不是note，第二次是DOM精确文本包含子按钮的测试定位，修正后两轮通过。最新一轮1passed/12.4s，截图在frontend-console/test-results/assistant-项目助手确认、跨页恢复与390px键盘路径/。讨论/提醒分视图也已验证。
- 独立测试库遗留的全局图片清理job因该harness没有S3 bucket配置而重试，未接触真实存储；不要把这次浏览器通过说成图片存储验收。
- 已使用ui-ux-pro-max技能（首次说明已发），重点焦点可见、窄屏和原有Vue视觉。桌面/390px截图已看过；仍需进一步深色/失败/大型内容/RP全流程视觉验收。
- Backend大回归1738通过后的2项旧替身缺novel_id已修复，定向2passed；累计约1740个既有用例。此后新增事件与工具等另有定向28passed/20passed等，未把数字相加冒充全量覆盖。
- frontend相关17文件184tests passed；新增助手定向12passed；完整frontend lint及build通过。backend完整ruff与20个Prompt契约通过。BASE_REF文档影响门禁通过（9域114表45handler15routes31ADR）。最后新alias测试import顺序已auto-fix，正在最终检查。
- 当前异步问题：已向用户询问“人工盲评由本人还是已有评审人/标注集”，暂无回答；这是P5产品评测信息，不是实现/推送许可。

主计划仍未完成：能力台账尚未逐项关闭；advanced Story/World/地图/恢复入口与作者四条链要完整验收；人工prose跨世界约束检查、inline子任务停止/失联收敛、RP真实质量盲评/Source/看海完整浏览器链、独立迁移身份关联/旧schema漂移、发布门禁仍有剩余。全部本地改动在codex/agent-integration，未提交/推送/合并/部署；真实开发数据库和.env未改。

## 收尾计划已授权：2026-09-10

用户明确要求实施剩余缺口计划；继续当前主题分支/WIP，不提交/推送/合并/部署。人工评审由用户本人完成：20组RP盲评，每段200–300字，每批最多5组，前情≤120字；强提醒使用短卡片。人工评分尚未获得，产品质量门禁不能标成通过。

已重新核对HEAD/origin/main=a8de5aa9…，开工docs-check通过（9域114表45handler15routes）。优先修复共享任务取消/失联收敛与协议兼容：从创建meta读取父子关系，新运行保存逐工具签名，旧v1目录冻结，新增工具不扩张旧运行。正在完成代码和测试，尚无阶段完成声明。

后续：父子恢复/协议 → 作者与主动服务闭环 → RP完整链 → 独立迁移和全门禁 → 短文本人工评测 → 旧入口清理与台账关闭。实质剩余仍以用户最新完整收尾计划为准。

## 收尾实施检查点：2026-09-10 12时

本轮已继续实现（仍未提交/推送/合并/部署，真实开发库和.env未修改）：

- TaskLifecycle.cancel_exact按创建meta中的父子关系取消，公共task取消入口改经同一根实现并保持子→父锁序；不再依赖Assistant checkpoint里较晚出现的evidence refs。失联扫描收束终态父任务的孤儿inline子任务，保留可恢复父任务；禁止从通用retry单独重试inline子任务。inline心跳和取消清理绑定调用者DB，避免误用默认库；独立清理只写Task元数据。
- Assistant协议v2保存逐操作schema hash/revision及读取工具签名，v1快照保存在runtime_v1.json（19个原操作、7个读取工具）。新增工具不会扩张旧运行。批准前重验操作签名；完成回执重放不写。终态私有model_history清理，既有worker维护入口批量清理30分钟前的终态模型历史。
- 人工正文新增writing.review_world / review_world_constraints，通过Evidence现有Compiler选择，再逐个inspect精确回读，最多8份/16000字符，不传Compiler混合摘要、不读邻章或未授权Scene合同。排除项先筛、目标与来源指纹重验、世界引用必须可回读；人物知识依旧不签署。后台manual稿自动使用该模式；AI candidate仍绑定原confirmation，不能用新范围替代。Writing读取回执和Assistant回访会识别世界来源变化。
- 新project.update_task复用AuthorTaskService版本CAS，支持更新/完成待办，新增字段或当前改变都会重验，不改作品事实。
- World共创chat旧API在功能开启时返回Assistant RunResponse；原session/message身份保留，operation_id重放只排一个Agent回合。开启后不走第二套legacy聊天。附带讨论作为作者输入，不作为证据；World持有模板/方向/World Core约束解析。quality_mode=pro保留固定复核步骤，无工具、共用预算，已准备的答复缓存避免恢复重跑主循环；原工作台模板、补充材料均传递。
- Frontend新增受控bridge打开同一助手会话；World共创移走重复聊天输入/记录，原输入保留为专业建议补充说明。共享会话完成后通知World刷新记录（带session/project晚到检查）。切换会话保留原草稿。
- 浏览器截图揭示旧OwnerAiDrawer遮挡桌面Assistant，已增加handoff回调：保存本页后收起旧抽屉；E2E现在必须确认抽屉隐藏并实际点击助手输入框，不能只查visible。最新改动后的浏览器复跑正在exec session 见工具状态，勿把之前13.3秒通过当成该遮挡修复已验收。

已验证证据：任务/助手/审稿定向153 passed（之后又有上述共创更改）；新manual-world两项真实领域测试通过，含排除、邻章隔离、AI拒绝、来源变化。独立PG的tests/e2e/test_assistant_review_runtime.py现在3 passed/1.56s：正常review、provider在途停止、manual世界约束实际worker链（provider IO合成），共享预算保留unknown pending usage。新增共创fast/pro与恢复身份后，World会话+Assistant合集27 passed。Frontend助手/Generate定向106 passed；旧版本读写UI兼容119 passed（早期范围）。当前OwnerAiDrawer专项与build、修复遮挡后的browser复跑尚待取回。docs-check BASE_REF最近通过，但需更新新公共契约的语义说明；完整最终门禁还没完成。

剩余：能力台账仍未关闭；Story剧情线/篇章/伏笔揭示、World checkpoint/建议采用、写作candidate/返修采用与恢复、地图维护/导入维护具体组织仍需补齐；current-scope助手跨回合讨论的安全连续性仍需完善（目前非project/带confirmation时主要不注入旧服务器讨论，legacy适配明确携带用户已提交讨论）。协议已变实现必须保留旧版本，不能只因新增工具阻止旧运行。需补pro复核中断恢复专测、来源失效/伪造世界引用通知专测、元数据清理专测；新API返回Union的兼容说明待正式文档。

RP全流程Agent-mode/PG/browser仍未完成；真实DeepSeek门禁须末次复验；20组短文本盲评和强提醒标注包尚未产出，用户选择本人评审，每段200–300字、每批≤5组、前情≤120字。独立数据库旧schema→head会话身份/关联/分页/恢复与基线schema漂移对照仍未执行（初次head迁移成功的证据不能代替这项）。作者4链各3任务的30%步骤对照未冻结。后续优先完成接口语义与四链实际成果，同时安排RP和迁移验收；不可宣称主计划完成。


## 最新恢复快照：2026-09-10 下午（继续实施，主计划未完成）

本节优先于上方旧状态。所有改动仍在 codex/agent-integration，未提交/推送/合并/部署；保留全部WIP。

已补：父子任务关系取消与inline orphan收敛（绑定db的heartbeat/cleanup）；v1目录冻结/v2逐项manifest；manual世界约束审稿与原AI confirmation严格分流；project.update_task；World legacy聊天启用后单写Assistant，同session/message身份、原模板/Context/pro固定复核，重复operation原请求hash恢复；current-scope旧讨论过滤与服务端恢复范围/联网偏好；安全受控目的地和当前checkpoint只读工具；story.create_thread/create_arc（仅新建规划，尚不代表完整结构闭环）。

确定验证：PG实际worker父子review三场景3 passed（provider IO合成）；隔离scratchDB从world_review_phase4旧schema/43条消息升级head，身份/关联/分页/跨项目保持，1 passed7.53s。使用与alembic同一比较规则（抽出infrastructure/schema_comparison.py），新Assistant schema漂移0，其他既有漂移前后完全相同，证据backend/.test-artifacts/assistant-migration.json。整库alembic check仍非绿色，不删除约束。浏览器旧共创drawer遮挡已修，真实API/worker＋合成provider的Playwright1passed13.6s，包括桌面实际点击、390px、刷新、旧输入/同会话恢复；截图已目视检查。Frontend相关115passed与build通过（后续修改后需适用复验）。

两项只读审计完成，确认需要修复：授权收窄后旧dirty、World.location字符串schema、部分批次自写导致stale、旧run回执丢UI、确认消息缺原scope、导入/World review/map/Story回跳、World提醒依赖stale、RP准备丢system资料/目录label&aliases隐私/工具私文外发/短失败残段/RP约定和资料无法合法引用。它们是实际缺陷，不能当仅验收缺口。

当前已实现并正在补测的修复：
- proactive在save/claim/execute重验当前类别与excluded根；Story拒绝排除根。
- World把实际finding字符串位置投影为manifest target+review/finding身份；提醒列表经World原get刷新stale。
- RP只替换第一条故事执行指令，保留约定/回顾/来源；搜索保护作品title、label、aliases和所有工具回读私文；普通失败原attempt事务保留短尾段，epoch/lease保持严格。
- Assistant历史message返回assistant_run_id，UI打开原run并本地保存查看位置；确认decision携带task/originalconfirmation；不放宽history_visible。
- 批次只为已完成操作真实返回目标保存授权后置检查（不改原引用，不更新无关来源/原confirmation或review guard）。writing.revise回执含replaces_draft_id/source_hash。需覆盖自写＋独立失败重试和外部改动拒绝，不能静默更新整份旧Context。
- RP proactive追加本次物化的overview section/source packet引用，与原message引用兼容；仅精确成对引文保留，正在实现/测试。

最近测试：新授权/RP等23passed，Assistant+RP+World会话48passed；frontend助手14passed+eslint。当前测试进程78342（后置状态+RP14项左右）需取结果。两项审计代理只有RP刚收到只读复核前四项修复的followup，能力代理已结束。

下一步：收齐这些修复测试，修来源/成果route真正消费身份；继续四条作者任务链（World阶段成果/候选采用、Story P20规划/伏笔揭示、Writing candidate/定向返修采用恢复、Imports恢复/查漏/回滚、Map定位维护）。能力审计建议按32项用户能力归并487路由/114表（目前台账仍pending），不能链接等于闭环。需要补story.create_thread/create_arc实际测试；P20 _apply_scenes max(index) or -1可能把0视为无值，读调用链后复核。

仍未完成：12个作者基线任务与30%实测；RP真实Agent/PG/browser全流程；最新DeepSeek真实门禁；20组200–300字盲评（每批≤5，前情≤120，用户本人评分）与强提醒短卡>=90%人工精度（无评分不能通过）；全能力/旧入口/文档收口、最终lint/test/build/prompt/PG/docs-check BASE_REF和差异门禁。本轮make docs-check已再次通过9域114表45tasks15routes31ADR。不要再次从零实现已完成链，也不要提前标P0–P5完成。


## 暂停恢复点：2026-09-10 15时（原生联网真实门禁连续3次失败）

仓库AGENTS.md规定外部依赖连续3次不可用/同项验证反复失败需停止并报告，因此本轮停止新增开发。
当前分支/WIP全部保留，未提交、推送、合并、部署。主计划未完成，不得将其标为完成。

最新变化：权限修复扩展至领域operation预览（operation_scope.py经稳定facade），World对象/别名/
关系、Story关联篇章/Scene/card/script、Writing精确修订等在读取前重验排除、原confirmation及
当前章节/Scene；复杂整体预览不能证明范围则明确拒绝。AI正文精确修订也复用原freeze_draft
重验原generation confirmation。author_tasks现经Evidence专门只读seam查询Project原日期/状态/
分页投影，不把TargetRef.target_path当查询表达式。用户任务能力表已写agent-capabilities.md，32项
都保留实际边界与缺项；机器487项JSON仍未逐项验收关闭。

历史消息assistant_run_id与一次/每run恢复按钮含失败/取消；viewedRuns保存旧回执查看位置。
部分批次后置状态只更新已成功目标，不删除原review guard；新增POST batches/{id}/recheck显式
重新查证剩余项，沿用原范围/排除，不重做成功项，新提案仍须确认。该API幂等/范围单测通过。
公开sources保留domain_reference与完整受控review_result；AssistantReviewResult.vue显示实际
语义覆盖/世界约束边界/遗漏与原文，世界复核保留run回跳。issue类型必须绑定领域finding_id。
Map节点、Imports原task（可无本地指针恢复）、World validation_run_id、Story thread/arc精确
读取及原编辑窗口已接通；还未浏览器实机复验这些新增路由。P20首个Scene index=0后追加重复
index的根因已修，现有P20规划用例覆盖空库/已有0。RP失败/停止/worker失联清理私有Agent历史，
保留用量与必要引用；awaiting_continue继续保留可用执行状态。

验证：一轮后端1110 passed/12 skipped/5 deselected（48.16s）；前端200 passed及生产构建通过；
其后RP终态私有历史清理定向82 passed；隔离PG父子review/停止/预算/并发4 passed（2.64s）；
make docs-check BASE_REF=origin/main通过9域114表45task15route31ADR。后续联网关闭保护的
backend定向测试和frontend测试/build还在运行，收尾需取工具结果。不要把早期大回归当作覆盖
所有之后改动。未做新的真人质量评测/完整浏览器/发布验收。

真实DeepSeek联网：本轮3次完整门禁均停于native_search，pytest耗时17.21/4.33/4.50秒。
工具循环和DB历史恢复均在此前通过，但本次未抵达stream_close阶段。最后诊断明确
response_completed=true、search_events=0、source_count=0；不能把模型回答当联网事实。
官方Responses文档说明支持指定web_search，已试隔离non-thinking+强制web_search，仍无事件。
代码保留严格completed搜索事件校验（没有放宽为消息或虚构引用），记录失败费用/用量；
未返回usage时现在为None/未知，不填零。RP/作者工具将不可验证联网回执转为明确遗漏。
已撤下verified_native_search全部运行时注册，capabilities给出失败原因，前端禁用联网并保留
用户原偏好。协议适配仍仅供显式真实门禁调用。恢复注册时需同时更新API能力投影/文档，不能
只修改静态helper。真实报告backend/.test-artifacts/assistant-live-core.json为最新失败，旧通过
报告备份assistant-live-core.last-passed.json；更详细失败为assistant-live-failures.jsonl（只含安全
元数据，不含Key/供应商正文）。最早一次失败由pytest输出/本记录留证，没有同格式jsonl。

下一步（用户恢复任务后）：先检查当前连接/DeepSeek Responses实际工具协议为何未执行搜索，
使用安全事件结构诊断并重过真实门禁，再恢复注册；禁止重复盲跑或静默换供应商。可随后继续
作者四链剩余开发：优先复用Story P20已存在prepare/outline_generate/apply_structure_preview
与information_movements（p20_service.py），避免另建一套规划/历史；World checkpoint与候选、
Writing generation/targeted-revision/adoption、Imports继续/回滚、Map图元/图片等尚未齐。
RP全流程Agent-mode真实worker/browser，12个作者效率冻结任务，20组200–300字盲评与强提醒
人工精度>=90%仍未完成。用户亲评，每批最多5组；没有样例评分前不能通过质量门禁。

最终保护验证已收齐：后端联网/Assistant/RP定向49 passed（1.95s），前端助手22 passed，
生产build再次通过；相关Ruff/ESLint与git diff --check通过，make docs-check BASE_REF=origin/main
再次通过。没有活动测试或子代理。暂停状态不变，全部154个修改/新增路径保留在当前分支。
下次从此恢复点继续，不重复将前面未完成项当成已验收。


## 恢复：用户修复配置与Flash联网注册后继续（2026-09-10）
用户已明确恢复本任务。已核对当前codex/agent-integration，大量既有WIP与新增.zcode保留。
原暂停快照中的联网“全部撤下”已过时：native_search现注册deepseek-flash及旧v4-flash别名，
API按当前有效账户模型投影能力；只取正式message annotations，仍拒绝无事件/无引用结果。
用户另外调整了profiles/capabilities/连接默认值和测试，不能回退这些改动。初始docs-check通过。
正在重跑真实门禁，随后优先接Story P20与作者已有生成/采用链，不新增第二套领域成果/历史。
本轮仍服务作者画像A的减少切页与重复选材，RP画像B保留直接故事体验。风险集中在跨域工具
请求/回执、原confirmation、父子任务预算与采用基线；沿用ADR-0023，无额外架构批准请求。
验证包含作用域拒绝、原采用包幂等、旧运行恢复与新工具目录兼容、真实worker/browser及人工评测。


## 持续实施检查点：恢复后的结构/写作接入（2026-09-10）

用户另明确授权发现问题时修改配置。两项既有只读代理已完成后续核对，未写代码；结果已消费。
已保留用户新增配置、README/CONTEXT和.zcode改动。真实开发DB只做了local owner配置只读查询，
使用SET TRANSACTION READ ONLY；没有写真实数据或.env，没有暴露/落盘Key。

联网仍未通过：最初环境Key与真实local owner已验证Key不同；实际账户model=deepseek-v4-flash，
base_url与官方模板一致。分别测试环境连接、required工具选择、直连（临时去LLM_PROXY_URL）、
当前账户Key和当前model，均无web_search_call和正式引用。GET /models成功返回deepseek-flash/
v4-pro；一次无私人数据的原始响应诊断发现仅reasoning+普通message，正文写“我将搜索”和JSON，
没有真实搜索。因此不是可接受的联网证据。停止重复付费重试；已再次撤下Flash运行时注册并更新
动态capabilities原因，保留用户新增model别名/配置与严格正式annotations解析。Native适配的
追加明确搜索指令保留，tool_choice已恢复用户原auto。真实门禁新增ASSISTANT_REAL_LLM_MODEL
可固定被验连接的model，且opt-in测试直接调已绑定Project客户端的provider适配，避免“未注册
无法执行注册前验收”的循环；生产LLMClient.research仍要求已验证注册。没有静默换供应商。
此联网缺口单独保留未通过，当前继续不依赖它的作者实现；不能说P1/主计划已完成。

新增并已跑定向检查：
- Story原API的P20提交编排下沉OutlineAIWorkflowService.submit_layer_generation；HTTP委托，
  支持服务端冻结snapshot/parent meta/稳定operation payload。新增assistant_structure_workflow.py
  的story.plan_structure（suggest）和story.adopt_structure（confirm）；复用原P20上下文、
  outline_generate、原采用包及信息推进投影。受限/排除范围无法证明完整层预览时明确拒绝。
  SQLite真实领域用例已证明原task复用/parent关系/未采用前无PlotThread，采用生成PlotThread+
  ForeshadowingPlan，保留adopted_from_preview_task_id，并同事务标记待检。P20 adopt所有result_refs
  经Story.proactive.changed发事件。暂无真实完整Agent→P20→批准PG/browser验收。
- Assistant.execute_suggestion复用原review_assets执行器，新工具generate_structure/gen_candidate/
  revise_candidate按冻结operation清单有条件注册。permission必须suggest，不能把confirm操作
  经工具直接执行。非review结果用domain_result（不是review_result），公开保留候选/结构提案。
- workflow_budget.budgeted_tool覆盖Assistant读工具与suggest准备期、RP lookup_source，所有资料
  准备中隐式LLM计入原预算。保留工具参数签名；嵌套scope只计一次，恢复外层context，单测通过。
  原v1工具哈希兼容与Assistant定向集44passed（其后还加了Writer候选链）。
- Candidate当前稿入口：Assistant guard允许选定candidate按ID/hash阅读，但不放宽working latest；
  Evidence新增writing_candidate作者限定、按content[offset]最多8000字读取，不扩展working/canonical
  SourceRangeRef。reader/角色、跨截止/不匹配Scene、已采用/撤回拒绝；读取不是原资料审查。
  候选读取/原AI缺confirmation拒审/变化失效用例通过（修过两处fixture错误后14项合集通过）。
- WritingGenerationService.submit_generation从原API下沉，保留原confirmation、stale_script明确
  决定和入队/索引副作用；WritingSemanticWorkflowService新增submit_targeted_revision，并抽出
  prepare_targeted_revision供预览和原worker共用，保留原review/finding/context/bundle严格门禁。
  原generation API27passed；Writing/Assistant合集63passed；独立semantic原16passed。
- 新writing.generate_candidate（suggest），无排除时按当前章/Scene/截止物化原始生成confirmation，
  已有confirmation保持原ID/action/目标章；有未明确可物化的排除范围时要求原受控确认入口。
  固定parent/snapshot/operation，不确认已变stale script，不覆盖working；submission专项测试
  正在session78536（取结果）。generation/continue完整真实模型/worker链仍待验收。
- 新writing.targeted_revision（suggest）、adopt_candidate/restore_version（confirm），文件
  assistant_candidate_tools.py。返修复用原问题与confirmation，返回新candidate后仍须再审；采用/
  恢复双重检查working head和hash、保留原版本、请求working索引。restore只从draft/published
  已采用版本创建新工作稿，不滥用publish接口；保持AI origin和清除旧审稿资格。前端采用/恢复
  也检查当前编辑器未保存输入。领域测试2passed（含后来改稿拒绝/新工作稿恢复/缺原确认拒采用）。
- AssistantValue增加P20作者词汇，隐藏内部refs和model confidence，结构提案与候选通过sources
  展示。尚缺P20原专业审阅页的task_id恢复深链（当前只能在助手看/采用，结果导航待补）。
- 旧evals RP fixture把test-provider改为匹配DeepSeek，保持生产未知模型短上下文限制；先前3失败
  已定向修复，后补blocker fixture同步后2passed。不是新20组Agent盲评。

当前活动测试：78536生成提交用例、79542frontend lint/assistant（若已输出按最新工具结果更新）。
其他完成测试无须重跑同样集合，除非又修改对应逻辑。新共同service/metadata契约文档尚待同步；
尚未做此批改动最终Ruff/全受影响测试/PG/browser/docs-check BASE_REF。所有改动未提交。

立即下一步：取回活动测试结果；检查新增生成scope/parent幂等和公共API错误形状，补共同budgeted
读工具实际worker回归；继续World保存checkpoint→推进当前会话（需从run绑定session，模型不能
指定session/manifest授权）、准备采用包/整页建议应用；再接Imports恢复/rollback/查漏和地图维护。
两条完整产品路径、主动强提醒分类及>=90%人工精度、12作者效率任务、20组短文盲评、RP真实PG/
浏览器全场景、全能力台账和迁移/P5收口都未完成。不要把新增SDK或几个工具测试当主计划完成。


## 最新恢复快照：作者能力增量与验证收口（2026-09-10 晚）

在用户“继续”和“授权修改配置”后已继续完成下列本地增量，并保留所有既有WIP、.zcode及用户
配置改动；未提交、推送、合并、部署。不要把只读审计或单项测试当成P0–P5闭环。

新增World链：assistant_cocreation_tools.py保存当前run绑定会话的Core/Design checkpoint并推进
原指针，继承上一轮决定/WorldState；源manifest、parent、round、session均服务端派生。Assistant
session.advance_checkpoint加行锁和populate_existing防并发丢指针。record_generation_outcome
增加checkpoint类型且保留旧默认；新增helper discussion_scope/run_discussion_scope供World。
注意scope哈希只用原author_message及evidence，不能用将要生成的run.result_json，否则预览自我
失效（已修并加测试）。World checkpoint测试证明保存/继承/迟到拒绝/成果消息关系，1passed。

新增World结果：assistant_outcome_tools.py准备独立采用包（服务器描述conversation来源，
generated_bridge，不准模型指定授权/来源hash）与原整页建议应用工作稿。用原World包/基线/采用
门禁，不把checkpoint直接采用。package保存测试已并入checkpoint用例；整页建议尚需独立实际
验收。当前package接口偏新增设计，不替代原focused补全或promotion的细粒度授权。

新增Imports：organization_status只读最近十次/指定run的范围与安全进度摘要，经Evidence→Imports
投影；imports.resume基于原task生命周期恢复同ID/范围/快照（定向测试1passed，已修旧fixture缺
novel_id和meta.recovery_required，没放宽生产门禁）。imports.complete_targets复用原专项查漏，
先冻结正文来源和目标；该新工具仍缺独立执行验收。放弃/回滚/文件操作保留原受控入口，尚需完整
回跳和流程验收，不能说Imports全闭环。

新增Map：add_known_location只把canonical地点放入当前空间版本，points为空；edit_feature_label
只改名称/备注，不接受几何/校准/来源伪造。原save/review版本门禁保留；inspector增加最近50个
版本元数据以支持选择恢复。领域测试1passed：旧锁定坐标保持，未知新地点无坐标，迟到修改拒绝。
首次测试误假定create_node无初始revision，已按真实返回基线修正fixture。图片/地图完整浏览器
与存储流程仍未验收。

Writing新服务/工具状态：submit_generation/submit_targeted_revision从旧API下沉；原语义预检
prepare_targeted_revision被助手与worker复用。generate_candidate/revise_candidate新工具有条件
按冻结目录注册；候选显式作者读取、原确认独立审稿/返修/采用、最新工作稿冲突与新版本恢复
已接入。生成子任务绑定/幂等/原confirmation及不改working测试1passed；candidate readonly和
缺原确认拒审、写入后失效测试通过；采用/恢复领域测试2passed；完整“Agent生成→审稿→返修→
再审→采用”的真实worker/browser仍未走完，必须保留这个缺口。

预算：新增budgeted_tool覆盖读工具/建议准备（含可能的内部检索LLM），原工具JSON schema
保持；嵌套计量只记一次并恢复上下文，1passed。RP lookup_source也使用该边界。原长记忆eval
fixture provider与真实capability不匹配导致3项旧失败，已修测试替身为deepseek并定向通过，
不代表新20组Agent盲评。

本轮较大后端集1509passed/12skipped/1deselected、1旧fixture失败；失败是story_asset_freshness
仍patch api.py已下沉函数，已改为稳定facade注入，定向3passed。未把数字相加冒充一次全绿。
最后PG真实worker/父子/预算/停止4passed（3.21s）；前端受影响200passed+生产build通过；
Ruff/ESLint受影响检查与docs-check BASE_REF=origin/main及diff --check通过。浏览器现有assistant
spec复跑session36689需取结果（仅合成provider，不能当完整新工具或RP验收）。

当前联网阻塞有新证据：先读配置/模型注册，再检查实际模型列表、代理、环境Key与current local
account Key差异。真实开发库仅SET TRANSACTION READ ONLY，没写Key/.env。current账户model
是deepseek-v4-flash，base与模板一致；用实际已验证账户Key+model复制到隔离测试也失败。
一次仅含IANA公共问题的原始响应显示reasoning+普通message，正文写“我将搜索”和JSON示例，
没有web_search_call和annotations引用。已停止该付费路径重试，撤下运行时Flash网络注册并
保留可读原因，没有换供应商/抓网页替代/将普通文本当搜索。门禁现在可通过已绑定Project client
直接测试provider适配，避免注册前验收循环；生产client仍要求注册。最新报告已写
backend/.test-artifacts/assistant-live-core.json（失败），完整安全元数据见assistant-live-failures.jsonl。

下一步：先读取浏览器结果并必要修复；不要重复付费盲跑Native。继续完整作者/RP验收与剩余
能力台账，特别是P20专业结果页task_id深链、World整页与资料编辑/发布回执、Imports撤销/歧义/
去重维护的真实受控交接、地图完整流程、所有来源变更入口（总纲头变化等仍须逐一核对）、新
操作的partial批次/跨owner拒绝、旧入口删除证据。RP真实Agent全流程PG/browser与20组短文盲评、
强提醒>=90%人工精度、12个作者效率任务仍未完成，样本未生成/用户未评分，不得关闭主计划。

浏览器复跑已取回：现有assistant.spec.js成功（真实API/worker＋合成provider），日志
backend/.test-artifacts/assistant-browser-latest.log。该用例仅覆盖统一助手基础确认、共创转接、
跨页/刷新/390px，不证明新增P20、Writer整链、Map全部操作或RP真实Agent验收。当前没有后台
测试会话需要继续等待。所有改动留在codex/agent-integration，未提交/推送/部署。

最终状态：本轮完成一批作者能力增量及验证，但主计划未完成。Native实际账户连接仍不返回
搜索执行/引用，按仓库重复失败规则停止该依赖的继续尝试；当前变更保留为待评审WIP。
现有浏览器基础路径1passed/14.3s，仍非四条作者链或RP全流程的全验收。恢复任务应优先完成
独立的完整任务链验收和剩余维护能力，不重复现有成功的单项工具测试，也不盲目重跑付费联网。

## 恢复快照：自建联网、领域补全与 Computer Use（2026-09-10，实施进行中）

用户已批准新补全计划：正式验收/盲评/效率指标延期；按功能、入口、体验模拟分开记录，不能
因延期就宣布P0–P5验收完成。继续本分支所有WIP，无提交/推送/部署。两个原已授权只读子代理
本轮已完成最新审计，无写入；反馈的作者/主动服务实际缺口已作为下文后续工作依据。

新增infrastructure/llm/web_search.py：私有SearXNG单引擎搜索（Bing→失败后DuckDuckGo），
每次最多5结果；read_public_page只读本轮搜索引用，2MiB/12000字/20秒/3重定向。httpcore
PublicNetworkBackend解析后连接数值公网IP，TLS保留原hostname，防SSRF/DNS重绑定；网页去
script/nav等后保存标题、URL、时间、原字节hash、摘录hash和覆盖，摘要不能作为查证引用。
复用已安装httpcore/dnspython（现列直接依赖，uv.lock已offline更新）。本机DNS返回198.18
代理占位地址，未放宽公网检查；增加可选WEB_DNS_SERVERS，1.1.1.1实测解析/读取成功。
WEB_SEARCH_URL只有管理员环境设置；新协议searxng-v1冻结endpoint_hash，不读取模型Key。

Compose新增search profile私有SearXNG，官方镜像索引digest
sha256:50978048218cfa6f31cd833a1c828cfb94e908be65842aac09ef1d5644f7b002，版本2026.9.10-ba055b3e0。
本机Docker daemon直接pull停滞，但经已有显式代理读取官方registry正常；校验arm64 manifest
和每个blob SHA后导入本地tag searxng/searxng:novelcraft-5097804，config image ID
sha256:e703aabed8eecd3bf42be0385c696bd237085e09f289c515acf49c0f4da4a1a7。
本地compose用SEARXNG_IMAGE覆盖为此tag，SEARXNG_SECRET仅临时进程生成；没改.env/真实凭据。
容器ai-writing-assist-searxng-1运行127.0.0.1:8888，local DNS显式1.1.1.1。
原始blob/解压层/导入archive在backend/.test-artifacts/searxng-image，均本轮生成，可后续清理
这些明确产物，不能清整个.test-artifacts。生产compose仍默认完整digest，未部署。

Assistant新run runtime_version=3，read_tools用search_general_fact/read_web_source；v1/v2原
目录保留。TurnCreate新增web_backend=searxng-v1显式授权，旧allow_web不会自动继承。
工具只扣web_requests；不伪造模型usage。已读取网页在原evidence_refs中复用，恢复不重读。
capabilities新增web_search、model状态/原因；search_availability会访问私有/healthz。旧native
仍保留不可用状态。display_sources新增web_source元数据。前端新渠道默认未勾选，解释仅发
通用问题；旧localStorage/server历史web选择没有backend标记时不继承。

RP新增journey.web_search_enabled，migration20260912_web_search_consent（已在独立DB升级），
新Project快照agent_runtime v2冻结web_search；旧v1严格保持原生工具语义。开关经原mode更新
接口/owner/epoch保存；initial/create/send/see-sea新快照按旅程显式选择，新工具同样有原作/
私文保护、预算、scope复验，搜索摘要不能入生成资料。新增真实页面独立开关，下一轮生效。

世界书新增assistant_page_tools：编辑标题/正文/sections（保留引用校验），发布，历史恢复。
prepare不落稿，编辑/恢复加页面锁后重验，发布沿用Canon head/impact/正式validation与
确定性decision ID；恢复拒覆盖已有稿。新定向测试通过编辑→发布→编辑→原discard→恢复，
当前正式版保留。注意后续仍要补世界历史的Evidence读取与精确历史导航。

P20导航支持outline_generate原task_id＋target_kind，专业页按同项目任务加载，不依赖本地
workflow缓存；已采用显示result_refs，禁止再次采用。P20 applied_result加类型化result_refs。
新增恢复函数restoreLinkedOutlineTask、linkedTaskReceipt界面及错误重读，避免展示虚假的空
结构列表。已通过相关导航/工作流测试；还需实际Computer Use走新增P20页面与待完成状态。

主动服务：StoryOutlineRepository.set_current_revision统一三种总纲head写入通知；伏笔/揭示
共享StructurePlanRepository增加通知，_DOMAINS/_snapshot接新类型。总纲检查已有采用剧本；
信息计划暂按明确章节发“需要对照”提醒，不宣称语义冲突。**仍缺：旧/新关联范围移动覆盖、
related_thread_ids映射、信息计划进入新剧本依据的版本兼容；World CharacterRepository更新
触发也待补。** 两个旧计划repository fixture补novel_id，未放宽生产隔离。

提醒新增作者/RP notice/{id}/recheck：重新校验当前授权、原run owner与来源，复用待检标记，
明确新一轮额度且旧run预算保持，活动lease不重跑，保留操作ID列表避免旧批准重放。
_notice更新保留这些重查回执。新测试8passed（含RP现有+重查），下一轮修改后需适用检查。
RP read_continuity_review使用领域结果新source_state（leaf/epoch/overview/source revision
fingerprint），只查版本和来源可用性，不从CompletedTaskPayloadContract读取不存在的meta，
不在提醒GET重编译Context/发模型请求。旧无source_state结果标未知需重查。这个最新读取路径
仍需专门正/负测试；之前source_state mock fixture已补相关字段。

Computer Use已实际创建独立项目c7e3c6df-5a4f-4115-9c81-181d0f35f702（雾港记事）及
6b1e81d0-c7b0-46cb-851d-2515368165bd（公开资料）。发现首次自动建session丢失web开关与
context，已修useProjectAssistant.send保留完整首条composition，专项前端测试12passed。
另跨项目新会话误留messageTotal导致空态“查看更多”已清零。修复后从前端完成真实SearXNG
搜索＋IANA原文读取，界面显示实际来源、模型3次/联网2次（模型IO为合成，实际网络非合成）。
390px布局、Escape关闭及焦点返回入口已通过Computer Use观察；viewport已reset。

RP模拟旅程0bee6bb5-d03a-48e7-9b47-a566967d342a，独立隐藏项目
4fb58c50-5906-4b09-a1ea-b215d0890af1。已从原入口创建/生成/继续，开启旅程web开关；新一轮
在准备阶段停止后保留先前两段故事和用户输入，显示重新生成入口。最初失败来自模拟器
OpenAIProvider.generate_stream应await返回iterator而不是直接async-generator，已修harness；
不是生产Agent实现错误。**当前UX发现：用户主动停止仍显示泛化“这次生成未完成”，可改为明确
已停止文案；还未做RP分支/看海/刷新全部开发模拟。**

当前运行：backend exec session11051（127.0.0.1:8028）、frontend session48314（127.0.0.1:8098），
server用真实API/worker＋合成模型IO；独立DB ai_novel_agent_e2e_20260910_1、localhost:5207。
启动脚本backend/.test-artifacts/run_cua_backend.py，命令backend cwd PYTHONPATH=. .venv/bin/python
.test-artifacts/run_cua_backend.py；输出日志assistant-cua-backend.log。脚本无Key/DSN明文。
后端无--reload，改后端需停这个已知uvicorn再启动（先确认无活动用户生成）。前端Vite热更新。
模拟浏览器Chrome1 tab670126693，CUA绑定simulationTab、simulationBrowser、simulationViewport。
当前停在上述RP旅程，最后一次attempt已用户停止；不要动原localhost:8080真实作品tab。
本例存储未配置，系统图片cleanup有失败日志，因此**不代表地图/图片存储可用**，后续须给明确
能力原因或配置专用模拟存储，不要用真实bucket做清理。

验证：本轮docs-check/BASE_REF检查通过（9modules114tables45handlers31ADR）；非最终全门禁。
新network+旧native+Assistant首轮26passed；RP/Project97passed；Assistant/RP较大集后来59passed；
world新链+计划旧集30passed7skipped；前端相关115passed，首次发送专项12passed。
最后需同步权威文档、lint/build/受影响PG检查；不能用这些单项数字冒充一次全绿或正式验收。

下一步：继续Computer Use已发现的问题及未模拟链，补World历史读取/导航、维护去重衔接、
结构历史、Writing原confirmation重新确认回跳、剩余主动触发与信息计划依据兼容、能力台账。
本轮尚未完成整个补全计划，不得结束为“已全部完成”。


## 恢复快照：2026-09-10 22时，继续补功能（正式验收延期）

保留所有 WIP，仍在 codex/agent-integration，未提交/推送/合并/部署。两项已授权只读审计已结束。
本节优先于此前恢复快照。新版方案是自托管 SearXNG + 受控网页回读；原生模型搜索不再作为功能补全依赖。

新增：World 工作稿编辑/发布/历史恢复与 Evidence 作者历史读取；Story 信息计划编辑、旧脚本basis版本兼容、结构变化到旧/新Scene增量通知；总纲/人物卡/剧本/P20成果精确回跳；主动检查失败用新额度重查（无child的准备失败也可重查）、RP source_state freshness；SmartDedup扫描建议工具、原比较界面精确task打开和持久化group_receipts幂等；详细调用链见代码与新测试。

本次最新增量：Writing GET draft/regeneration-context + 候选页“重新确认资料并生成新版”，原confirmation排除/范围保留，旧candidate不重绑，缺记录明确让作者为本章重新选材。生成确认期间跨项目/章节/Scene晚到响应不提交。20后端+36前端定向检查通过。
Imports targeted_completion 回执已被Writing受控恢复识别；原面板保留continue/出处/待审包/rollback；专项同名歧义新增具体candidate_ids与章节范围，面板读取所选同名对象后明确授权新查漏，不改旧任务冻结targets。此新增尚需专项前端/worker测试。
Map 新增精确revision/run/page导航；历史地图以只读比较打开。World map_capabilities +地图/Assistant接口仅投影配置可用性，不透露存储Key；结构不依赖S3，缺存储则阻止图片入队/上传，外部画面说明继续可用。inspect_map_node带最近20张图片的安全状态/成果引用。新Web错误引用改ModelRetry，避免一次错误ID终止整个RP/作者循环。

验证：较大后端2683 passed/12 skipped/2 failed，两个失败是新约定对应旧fixture（Web ValueError=>ModelRetry和map fixture缺storage）；已修并在后续48个通过的集合内验证。新增信息计划测试发现DTO时间戳在SQLite刷新后时区表示不同导致错误CAS，已标准化UTC；第二次测试推进到reader缺cutoff的fixture，已补cutoff，活动pytest session68611需取回。backend Ruff全仓通过（之后有少量新测试/修复，需最终再查）；frontend lint通过、build通过；map/nav前端110passed。docs-check BASE_REF=origin/main通过9域114表45任务15前端routes31ADR，语义文档还需同步最新增量。

Computer Use：原模拟tab670126693仍在Map，对应新map node f6f8badf-6a6a-49e0-bb05-b7318f365384、项目6b1e81d0-c7b0-46cb-851d-2515368165bd。实际完成新建空间图、未知位置标记“模拟钟楼”、保存、改名“模拟钟楼 · 修订”、历史比较。点击恢复触发native confirm，CUA getJsDialog发生focus超时；之后CDP Page.handleJavaScriptDialog回复No dialog，恢复结果尚未核实。不要把点击当完成。
Chrome CUA部分Input.dispatchMouseEvent会超时但实际动作已完成，应先getAXState查看，不重复点击。新tab670126699（continuedSimulation）接续Writing，实际新建章节、41字合成正文“钟楼来信”、自动保存、参考资料确认并提交普通生成。模型输出为harness固定ok，此路径只模拟运行/版本，非模型质量；当前待取回生成结果并检查新reconfirmation UI。
真实用户tab localhost8080未改。CUA nativeApp只为诊断读取了原窗口，随后切回模拟标签。所有新增数据只在ai_novel_agent_e2e_20260910_1。

活动服务：uvicorn8028无reload，runner session91380，前端8098 session48314，SearXNG8888 ai-writing-assist-searxng-1。后端在地图capability增加后重启，此后Imports新歧义/Writing文案/Story时间标准化尚未重启。启动helper backend/.test-artifacts/run_cua_backend.py只迁移专用模拟DB。不要碰localhost8080真实库/.env。旧backend session11051已停止。
下一步：先取回68611；补新歧义/地图capability导航/信息计划等最小真实行为测试，继续CUA核实Writing候选/恢复、World及RP；用另一专用PG跑并发兼容（不得和模拟worker共库）；更新32项能力台账为功能闭环/受控衔接/正式验收延期，不可把原P0-P5标已全面验收。


## 本轮功能补全收口：2026-09-10 22:45

用户修订范围已执行：自托管 SearXNG +受控网页回读、领域工具/成果/恢复、主动服务边界和
Computer Use体验修整。32项用户能力均记录为直接/组织/受控/兼容及实际成果恢复；机器清单
重新从实际嵌套FastAPI路由与ORM生成，497个API入口/114表并附所有者，OpenAPI路径覆盖核对。
不再在机器清单重复维护pending验收状态，功能状态以agent-capabilities.md为唯一台账。
原P0–P5总体验收未关闭：人工RP/提醒精度、效率、真实用户质量、完整正式模型/发布验收均按用户要求延期。

最后Computer Use发现并已修的实质问题：
- 新一轮写作生成的进度卡残留旧成果按钮，开始时清空旧result；共用busy按钮避免误称正在审查。
- 世界提案出现page_type等字段名，现展示作者标签，模板/引用载体元数据不进入修改正文。
- 世界工作稿发布会被原生命周期消费，旧draft链接原先仅落在资料库；新增World同项目不可变
  Canon发布回执查询 drafts/{id}/publication，验证封存来源后准确打开对应页面历史，丢失/放弃明确失败。
  恢复工作稿后更新URL与创作继续指针，去掉旧history参数。已在真实专用PG/browser走通。
- 世界历史原因、发布说明与写作对话框的技术文案已收敛；Assistant未定义的主题变量改为既有token。

CUA实走：作者新建作品/跨项目、首轮真实SearXNG/IANA网页来源；新章节/41字模拟正文保存、
合成provider候选v2→原选材重确认→v3，v1工作稿及v2均保留，并排差异已看；助手成组确认世界
草稿→专业页修改保存→影响预览→发布v1→原草稿链接定位v1历史→恢复工作稿；助手相似资料
扫描→原去重比较页无重复空态；390px深色助手无横向溢出，Escape回到助手入口，最后已恢复
跟随系统与正常viewport；RP开场/发送/停止/重生/看海/离页后返回。模型均为合成IO，不代表质量。
RP日志核对离页时序：22:38:51 leave后仅已发出的回合于22:38:54结束；22:41:08 leave后仅当前回合
于22:41:11结束，没有后续claim。多出段落均在浏览器工具调用间隔、仍在页面时生成；不要误改领域
“完成已发回合但停止后续”的既有规则。重新进入看海开关为关闭。

工程结果：后端领域+LLM2688passed/12skipped；Evidence+任务+novel配置静态边界652passed；
最后WorldAuthority/发布恢复33passed。专用 ai_novel_agent_gate_e2e_a1599d8439 的真实PG并发/
迁移20passed（最新schema、World旧会话identity/pagination、组回放/savepoint、RP并发/任务coalescing）。
frontend全套176files/2432passed；backend Ruff通过，159个受影响Python文件format通过；
frontend lint/build与生产产物验证通过；Prompt20契约通过；docs-check BASE_REF=origin/main与
git diff --check通过。全仓format曾发现133个既有未格式化文件，仅修本次受影响3个，不进行无关格式重排。

本地状态：HEAD与origin/main仍为a8de5aa9...；246个WIP状态项保留，未提交/推送/合并/部署。
未改.env、真实开发数据库或真实用户作品。专用浏览器tab670126693/670126699已关闭；专用
uvicorn8028(旧PID75428)与Vite8098(旧PID20098)已停止；session57266/48314均已返回SIGTERM结束。
SearXNG8888及已校验固定image保留，供本地接入；prod只有Compose/配置文档，未发布。
模拟DB ai_novel_agent_e2e_20260910_1与独立gate DB、忽略产物都保留。用
backend/.test-artifacts/run_cua_backend.py可重启合成IO专用演示；勿误当真实模型。

下一个可执行步骤：用户要求正式验收时，先复核现实Git/配置，从本记录和能力台账冻结待验样例；
不自动开启人工评测、真实付费模型或发布。若用户只要求Review，审查当前全部WIP而不重复实现本轮已闭环功能。


## 合入前只读审查：2026-09-10

结论：当前不可直接合入 main；本次只审查，未修代码、未合并或推送。
实时核实 origin/main=a8de5aa9e，本地 main=6eec78cca（另有9个提交），主题分支仍指向
origin/main，功能全部为WIP。用独立临时index包含当前tracked修改与未跟踪交付文件
（排除.zcode）建立无分支快照，merge-tree预演本地main得到39个冲突文件；真实index/
工作树/分支均未参与合并。冲突包含tasks、Evidence、World复核、共创、去重及前端入口。

新增已复现问题：
- AssistantService.resume(renew_budget=True)只复制allow_web，遗漏web_backend；原v3
  searxng-v1运行续查后TurnCreate.web_backend=None，submit不再冻结web_search，联网失效。
  recheck_batch构造TurnCreate有同样遗漏，应一起检查，不能给旧渠道自动授权新渠道。
- execute历史查询task_id != 当前task会过滤NULL；旧World chat和手工决定原本无task_id，
  即使history_visible允许也进不了模型上下文。应显式保留NULL，再走既有范围过滤。

本次实跑：后端Assistant/Agent/Web/预算/RP定向72passed，前端8files/81passed，后端
Ruff通过，docs-check BASE_REF=origin/main与git diff --check通过。复现脚本位于忽略目录
backend/.test-artifacts/review_agent_merge_repro.py；backend cwd用PYTHONPATH=. uv run python
运行，不访问真实数据库或模型。未重跑全库、PG并发、真实浏览器或模型，不宣称整合结果通过。
下一步：获修复任务后修上述两处并增加回归，再在隔离整合工作树处理本地main冲突，验证
实际整合结果；不把本记录当作修复/合并授权。


## 审查缺陷修复完成：2026-09-10

用户已批准实施两处修复，明确不处理main冲突、不提交/合并/推送/部署。本节取代前一节
“两个代码问题待修”的状态；正式验收及main整合状态不变。

AssistantService的新额度resume和partial batch recheck现同时传递原allow_web/web_backend；
原请求没有backend时仍为None。历史SQL现保留NULL task_id，后续history_visible保持不变。
模块README同步说明。未新增API、迁移、依赖或抽象，原WIP保留。

回归采用现有SQLite/API及合成provider：两条续查入口分别覆盖明确SearXNG、关闭联网、
旧请求无渠道，核对搜索快照、操作ID重放只产生一个新run、原预算不变。历史测试通过真实
查询并捕获模型输入，覆盖全项目、章节限制、排除范围、真实confirmation（匹配与不匹配）、
跨项目过滤与当前任务不重复注入。修复前6failed/4passed，修复后10passed。

Assistant全模块及Agent/Web/native-search/workflow-budget相关套件75passed；全后端Ruff、
两份受影响Python格式检查、实现前docs-check、收尾docs-check BASE_REF=origin/main及
 git diff --check通过。未重跑PG并发、真实联网/模型或浏览器；本次修复不改变这些底层协议。
审查时忽略目录的旧复现脚本保留作历史证据，其断言描述的是修复前错误状态，当前验收以
modules/assistant/tests/test_assistant.py为准。

下一步：用户授权整合时，在隔离工作树解决本地main的冲突，并验证实际整合结果；
当前仅两个代码缺陷修复完成，不能直接据此宣布可合并。


## 修复后合并复审：2026-09-10

重新读取修复差异，未发现本次两处修复引入的新问题；相关75项测试和docs-check
BASE_REF=origin/main、git diff --check再次通过。实时远端main仍a8de5aa9e，本地main仍
6eec78cca，分支全部功能仍为未提交WIP。独立index快照的merge-tree再次确认：本地main
39个冲突文件；origin/main无文本冲突（它仍是本分支基线），后者不代表保留本地main的
9个独有提交或整合验收。未操作真实分支合并及暂存区。
结论：本次两处修复复审通过，当前仍不能直接合入本地main。下一步仍为用户授权后隔离
解决冲突并验证实际整合结果。本次没有重审全库或重跑正式产品验收。


## 隔离整合完成

本工作树已将Agent快照与本地main整合，39处文件冲突解决且完整工程回归通过。
唯一交付记录：[隔离整合任务](2026/T-20260910-agent-main-integration/TASK.md)。
本节仅对codex/agent-main-integration工作树有效；原Agent工作树不变。
合并结果已暂存，未创建merge提交或移动main；下一步需用户授权提交/合入。


## 本地 main 已交付

用户明确授权合并后，整合提交a6c9ecf8a已fast-forward进入本地main；业务tree与完整回归
验证结果一致。详见[隔离整合任务](2026/T-20260910-agent-main-integration/TASK.md)末节。
未推送/部署，原Agent工作树WIP与整合工作树保留；正式模型/人工验收仍按原范围延期。

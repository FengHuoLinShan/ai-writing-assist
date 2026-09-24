# NovelCraft V4 长期计划实施

- id: T-20260921-novelcraft-v4-implementation
- title: NovelCraft V4 演化式小说整体引擎长期计划实施
- status: active
- created: 2026-09-21T00:00:00+08:00
- updated: 2026-09-22T19:25:00+08:00

## 最新恢复快照（2026-09-22 19:25，真实模型验收进行中）

- 保持原目标：附件 V4 计划 review + 做完；工程完成与模型/作者质量分开。分支仍 `codex/v4-audit-fixpack-1`，没有提交/推送/合并/部署。现有大量 WIP 全部保留。
- 用户已授权默认已验证连接、总费用不超过 USD 5（含重试）；后又明确要求默认模型对齐最新 V4.1 Flash。已通过账户 SettingsService 激活正式 `deepseek-flash`（旧值 `deepseek-v4-flash`），恢复原 timeout/max_tokens/temperature/top_p/extra/creative_mode，再读 runtime profile 确認。代码默认原本就是新名。**此项按新明确授权修改了真实库账户默认设置；没有修改 Guimi 小说内容、项目、凭据或重启/迁移保护库。** 零额外请求，回执 `artifacts/paid-20260922/default-model-alignment.json`。
- G2/R06 新增：Evolution 完整前缀只读投影（当前 live 成功回执、完整递归原文根、同 Scene 重算/来源变化重验、模态与原引用保留）；InputManifest 带 typed refs；Cognition 保存 evolution_refs，新 migration `20260922_cognition_evolution`。第一独立 case 真读 Evo，第二 case 真读 C，Forecast 真读作者回顾 C，World map/Story panorama/Evidence loader 同源回读，真实 Writing 改稿使旧消费者失效。可执行场景在 `backend/evals/v4_vertical_slice.py`，固定 provider 的生产 handler 全链测试在 `test_g2_consumers.py`。
- R06 安全：全章来源完整读；旧稿排除扩为整章排除；同章与后章 C 不自动进入写作焦点；Scene 焦点和显式历史 cutoff 不使用 case 派生 C（作者 goal/constraints 没有 Scene 时点证明），人物/读者同样关闭。作者回顾理解明确非首次阅读证据，C commit 额外保留真实 author instructions/work inputs。新旧 forecast 消费协议用显式 understanding_enabled 冻结，旧任务恢复/卡片重验不偷偷补 C；知识审查收到与生成器相同的 C refs/source_map。
- schema 修复：LLM 只提供 subject_surface，宿主只在实际引用的已解析 mentions 中消歧；全部引用必须匹配主体/模态，混合传闻不能升级 full。Story 提供机器状态 payload 校验（保留合法局部 update/delete），无可物化 payload 进 pending；knowledge 主体/稳定记录 ID 由宿主填，关系端点/实体身份重验；未解析地点 DTO 允许 location_id=None，保留 text_state。不声称结构门证明了语义蕴含。
- 真实验收专库 `ai_novel_agent_e2e_v4_live_20260922` 从空库迁移 head，完整 native synthetic preflight 通过。`evals/v4_live.py` 只读源库当前默认账户连接，进程内复制密文到专用 owner，业务仍经 Project facade；结束删除测试凭据，保留项目/证据。每次 transport 前持久化峰价预留；同 ledger 累计全部 run，未知用量封锁，进程锁防重复消费。`test_v4_paid_cap.py` 并发预留/中断/未知用量检查通过。
- 官方已核对 `https://api-docs.deepseek.com/quick_start/pricing/`：Flash 谷价 input miss $0.15/M、hit $0.003/M、output $0.60/M，峰价两倍；旧 alias 同价。当前谷价。共享费用回执 `artifacts/paid-20260922/paid-calls.json`，绝不能为重跑另建 ledger 重置 $5 上限。
- 真实 live-01：2 requests，约 $0.004686。第二场景模型给唯一逐字引文错误 end_offset，严格 compile 拒绝；保留失败/冻结，不原地重采样。修复仅 ProjectLLMSampler 适配层：唯一 Scene 逐字引文由宿主对齐，第二次 find 检查重叠重复，原 offsets + 对齐 + method exact-unique-scene/v1 留付费回执；重复/缺失引文原严格规则不变。已有 sampled 失败不自动修写。
- 真实 live-02：两 Scene 成功；知识过度推断已 pending。后续查证一个 WorkOutput 用尽 12000 输出预算而空；另两项通过后 planner 输出 recipe 不允许 test，host 正确拒绝。累计 11 requests，谷价估算 $0.038141832，峰价上界 $0.0771492。所有原文响应已保留。
- 修复 live-02 根因：runtime WorkOutput 不再把 world_stress 指令发给普通 deep_review；GraphDelta schema 依据 recipe 缩小 capability 枚举，只有 revise 配方才收到试改/试验指令。29 个 collaboration+G2 回归通过。live-03 正在运行（外部 session 53468，日志 `/tmp/v4-paid-live-03.log`）；如进程已结束读输出文件 `live-03.json` 与共同 ledger，不盲重启。
- 验证：全后端冻结环境 flags（ASSISTANT/RERANKER/RAG_QUERY_PLANNER=false，make test ARGS）：**6202 passed / 15 skipped / 7 deselected**，仅基线 pytest mark warning，`/tmp/v4-backend-full-frozen.log`。全前端 **202 files / 2574 passed** `/tmp/v4-frontend-full.log`。后续 scope/provenance/prompt 小变更的定向套件正在 `/tmp/v4-consumer-scopes-final.log`（session 98429）。Evolution/Forecast/Cognition+paidcap 197 passed；追加 reading 同场景重算/append/shadow/映射变更测试 1 passed。
- 下一步：检查 live-03 实际成功请求/输出与 map/feed 修改前非空→修改后空，修真实根因、不伪造通过；补 scope 边界/混合知识/配方 schema 断言，跑相关回归、Ruff、native PG、frontend lint/build、docs-check BASE_REF=origin/main、diff-check。全面更新权威文档及 IMPLEMENTATION-AUDIT（后者仍严重过时）；继续 E07 入口适配等剩余离线包。完整 G0–G8/长期试用未完成，不能改总任务 complete。

## 当前恢复快照（2026-09-22，附件计划 review + 续做）

- 用户要求：附件计划已部分执行，review 并完成。先要求离线工程，2026-09-22 18:17 改为允许付费，明确「默认的，费用不超过5美元」，并提醒当前谷价。可使用默认已验证连接，总费用（含重试）<= USD 5；不得把工程绿色冒充质量/作者验收。
- 工作区：原仓库 `codex/v4-audit-fixpack-1`，HEAD `0efb1359d70af3bec92ad47d0493238d62bc7861`；保留最初来源完整性修复等未提交 WIP。没有提交、推送、合并、部署；保护 Guimi 库未使用/重建。
- 附件 plans 与仓库副本逐文件相同。长期 G0–G8 尚未完整完成，审计文件是此前快照，收尾必须重写当前结论，不能照旧数字宣称完成。
- 已完成 E05/I02：所有 working/published 保存、发布回退、删除、Scene 变更/融合/撤销/重排集中索引及来源失效；旧 run epoch 封锁，事件软失效，作者历史保留。精确来源/引用、竞争身份、冻结 parent/CAS、run 模式与来源范围均已返修。
- 已完成 C01/C02 工程：Collaboration 独立 head/commit/record，CAS/幂等/no_change/追加历史；用户显式授权保留，Evidence 精确根来源/继承引用/负面查询重验，新独立 case 实际 Prompt 使用合法理解。作者修正/撤回、历史、草稿切换保护及数据库不可变 trigger 已接线。两轴复审问题已修。
- 已完成地图最小生产消费：World owner API 通过 Story facade 查询 Scene 截止点在场；匹配以 location_id 为先，同名不串对象；退役 Scene 历史不投影；未知路线不伪造距离/时间。面板打开时 revision 变化重载，保留来源回读与窄屏。
- 验证：Cognition 28 项；地图/认知前端 127 项；API+worker+合成 provider 浏览器认知/试改 2 项；地图实际 API 浏览器 1 项；两者手机截图已检查；前端 production build 通过。均零真实模型。
- 后端初次全量 6112 passed/45 failed 已在 HEAD detached worktree 复现，原证据 JSON 保留。续做全量 6140 passed/50 failed，其中 6 个新增失败为索引集中化后的旧测试假设；实际索引与 API 不重复投递断言已修，定向 82 passed。其余基线失败仍待处理/界定，不可声称全量绿。
- 当前 E07 开发：Project 增加 engine/epoch/schema floor，Evolution switch 在项目独占锁下排空/停止 imports 和 live run、保留预算与历史、撤队列 lease；两端提交检查项目世代。PG trigger 保护旧 SQL，不允许降 schema；新任务使用 evolution_scene_step_v2，全部旧 v1（含 shadow）不能继续写，防基线旧 worker mode 复用漏洞。
- E07 已修只读复审发现：trigger child→project 死锁改 NOWAIT；旧 checkpoint 精确保留 token 键是否存在；旧 cancelled→done 不再豁免；新 v2 任务防旧二进制识别；迁移取消旧 v1 和暂停项目旧队列，防全局最早 pending 卡住队列。
- 最近回归：Evolution+imports owner 173 passed；imports 全模块+Project+任务+地图初跑 1022 passed/8 failed（8 项均测试夹具悬空 project，已补真实项目）；针对修复后的 209 passed/1 deselected。
- 专用 PG `ai_novel_agent_e2e_v4_resume_20260922` 已迁移到 understanding_owner。原 C/E05/单写者 6 项通过；新 owner 首跑测试仅旧 SQL fixture 列名/novel_id meta 不完整导致失败，已修。新加真实旧 schema→head 独立临时数据库迁移测试；正在重跑 native T35/T36、旧任务 checkpoint、心跳锁序与迁移不堵队列。未提交 migration 的函数变更须仅在专用 PG 用 CREATE OR REPLACE 刷新，不能碰保护库。
- 两个只读 code-review 子代理：v4_spec_review 已关闭 Map 三项并提供 E07 接线建议；v4_standards_review 正在复核 E07，其已报问题已修。主代理单写入。
- 下一步：跑完 PG 与 E07 复审、修剩余真实缺陷，更新权威文档/审计与离线验收矩阵；随后继续 E07 入口适配/余下离线包。E08 删除、默认主链切换须满足计划门禁，不能拿 fixture 代替真实质量证明。


## 续做检查点（2026-09-22 18:06，R00–R05 进行中）

- E07 新旧 owner/旧 SQL/心跳锁序/缺 token checkpoint/历史 schema 迁移共 11 个原生 PG 检查已分别通过；Imports/Project/task/Map/Evolution 回归 1191 passed。两轴只读复审 E07 无新增阻断。
- 权威 Project/Imports/Evolution/数据库/tasks 文档与整体设计、HTML/drawio 的旧 E01 无运行时说明已同步。`/tmp/v4-docs-latest.log` docs-check 通过。审计文件尚未重写，不能引用旧完成结论。
- 最新后端全量 6147 passed / 43 failed：1 个本轮 fixture 覆盖根 test_project_id，已改为显式 evolution_project_id；其余大部分基线失败由本机 ASSISTANT_ENABLED/RERANKER_ENABLED/RAG_QUERY_PLANNER_ENABLED 开关污染。三项设 false 后相关 588 passed，另 TESTS 环境传入 Make 自检有一项假失败，后续用 ARGS 传路径。4 个旧 Story 单元 fake session 缺新增来源捕获，已在真实 helper 边界打桩且补 capture 调用断言。未改生产门禁/真实配置。
- R 真实缺口已据 reviewer 反例修：主 Writing 选区与光标段落、意图；4 keys 与适用性；一个 account/project feed store/轮询；同 focus 读取序号；授权变化清旧卡；分页不同 scope 不追加；不确定提交不能以新范围静默重试旧范围；修改/润色交接现有 Assistant 精确修订预览，保留 WorkContext 与草稿范围，不强转 continue。
- 复审发现并已改但仍在验：新默认字段兼容序列化、旧冻结 scope 精确比较；旧无 direction_id 预览遇拒绝失败关闭；shared host 交互取得焦点；异步修订冻结 token/project/focus；notice 锁后重验 candidate 与评估指纹；重复领域 issue 同根；方向拒绝按 condition/proposal 保留，不随标题/ID 改名或 read/snooze 丢失。
- 当前新增 `forecastStore.js`、`forecast/tests/test_context_boundaries.py`。前端 forecast/ProjectAssistant/WritingView 85 passed（稍后安全改动仍需重跑）。后端定向 71 passed/7 skipped/1 failed（新测试在同一 run 重复 ordinal，已改第二个真实 run，待复跑）。最近日志 `/tmp/v4-forecast-backend2.log`、`/tmp/v4-forecast-ui3.log`。
- Reviewer v4_standards_review 已交 8 项，需修后复审；v4_spec_review 还指出 R06 未读 Cognition、当前历史 cutoff 不支持。不要把 R 全包关闭。当前主代理单写入，没有付费模型、commit/push/merge/deploy，也未碰 Guimi。
- 下一步：完成 R 安全回归（旧 queued/resume/prepare 幂等、双宿主意图、分页、旧提交、异步草稿切换、逐方向拒绝和 notice 并发）；同步文档并跑定向 lint/UI。随后继续 R06 安全 Cognition 消费与 G2 同一事实全链离线验证、E07 入口/余下离线包。E08 删除仍受真实质量与观察期门禁阻断。

## 续做检查点（2026-09-22 18:23，R 收尾与 G2 真链路）

- R 前次复审 8 项及后续 3 项已补：异步 activate 返回配置/宿主身份凭据；旧 pending 新增空默认字段规范化比较但重试原 payload；空拒绝记录不占 explicit_decisions 的 limit。后端 forecast 全 21 passed，前端 Forecast/ProjectAssistant/WritingView 91 passed，日志 `/tmp/v4-forecast-boundaries2.log`、`/tmp/v4-forecast-ui6.log`。
- 真实支付授权更新如上。仅只读查当前配置数据库的账户默认连接元数据：默认数据库是受保护 Guimi，账户默认 deepseek 已验证。**没有修改其项目/数据/配置或迁移/重启**。后续密钥仅进程内复制到专用 live 测试库账户，退出删除测试凭据，业务调用仍经 Project facade。实际 model 模板 deepseek-flash。
- 官方计价 `https://api-docs.deepseek.com/quick_start/pricing/` 已核对：谷价输入未命中 $0.15/M、命中 $0.003/M、输出 $0.60/M；峰价两倍。UTC 10:21 已谷价。每调用先按峰价与输入字节/输出上限原子预留，未知用量封锁后续；回执单列谷价估算和峰价上界，总预算 $5（尚未调用任何真实模型）。
- G2 审查发现：Story creative resource 只提供可编辑 Scene 规划，没有 Evolution 已提交理解。原 test_g2_vertical_slice 的 case 仍是 replay_state；C→新 case 已通，但与 Evolution 链断。下一步在 Evolution 增只读、完整根来源约束的观察回执投影，Evidence 按实际选材/排除/截止装入 InputManifest；不得把模态和原文引用抹平成事实。需要全读集/继承依赖重验、历史与 shadow 隔离，随后真实独立 case 与 World 地图纵切验证。
- 主代理单写入。v4_spec_review 正只读核对上述最小 seam 与反例；v4_standards_review 已报告 R 后续 3 项（已修待复核）。没有提交/推送/部署。审计仍需整体重写。

## 意图与授权

用户指令（2026-09-21）：「实现此长期计划」，附件为 NovelCraft-V4-Long-Range-Plan-and-HiFi.zip。
按 AGENTS.md 自主决策条款视为执行授权；但该计划是 G0–G8 多里程碑长程计划，
单次会话不可能完成全部，按计划自带的关键依赖链推进：
`G0 → E01/E02/E03 → E04 → G2 → E07/E08 → G3`（地图壳/前端统一宿主可并行）。
每个里程碑独立分支提交；G0 为首个发布阻断修复包。

## 权威输入

- 计划包已复制到 `docs/plans/novelcraft-v4/`（来源 zip 在 ~/Downloads，勿再依赖）。
- 入口：`plans/00-MASTER-v4.md`；演化：`plans/01-EVOLUTION.md`；
  追踪与验收矩阵（T01–T36）：`plans/05-TRACEABILITY-ACCEPTANCE.md`；
  证据与代码核对（N01–N05）：`plans/06-SOURCES-AND-AUDIT.md`。
- 代码基线：`b5a3ef2e6`（计划即按此 commit 静态审查编写，与当前 main 一致）。

## 关键决定

1. **G0 = E00/E07.a**：人工事件保护 + 两视图归约契约测试 + 重复实现清单 + 入口副作用矩阵。
   这是计划 §7 表格与 01-EVOLUTION §7.2 明确的"新模块开发前先修旧链保护"。
2. **保护策略**：`replace_scene_events()` 内做权限分区（protected = author authority），
   机器行按"跳过保护槽位的顺序分配"落位，不引入序号带迁移（避免既有数据迁移），
   不改 `append_confirmed_scene_event` 语义。producer/generation 细分留给 E03。
3. **两套 reducer 分叉**（章节视图 `services._apply_event_to_replay_state` vs
   Scene 视图 `scene_projection._apply_event`）G0 只钉住共同路径契约并记录缺口，
   统一语义内核属 E03，不在 G0 顺手改。
4. 计划文档放 `docs/plans/`（历史/长程计划区，不进 architecture-documents.toml 注册表）。

## 进展

- [x] 2026-09-21 会话 1：调查确认 N01 风险在当前代码成立（replace_scene_events 无来源分区；
      空 Delta 重跑经 imports `_record_deltas` → facade `replace_scene_memory_events(events=[])`
      会删除 author_confirmation 事件）；两 reducer 分叉点确认。
- [x] 2026-09-21 会话 1：计划包入 `docs/plans/novelcraft-v4/`；分支 `codex/novelcraft-v4-g0-baseline`。
- [x] 2026-09-21 会话 1：G0 全部完成——人工事件保护修复（repositories.py 作者权威分区 +
      跳过保护槽位的机器行分配）、契约测试 5 例（T04/T05 + 两个缺口钉住）、
      G0 基线文档（重复实现清单、入口副作用矩阵、语义缺口）。
      入口副作用矩阵发现：助手应用/创意采用/协作采用/导入四类入口缺
      `request_chapter_index`（上下文失效已由仓储层 `_changed/_created` 收敛），
      留 I02 统一领域变更回执时修。
- [x] 2026-09-21 会话 1：E01 契约层完成——`backend/modules/evolution/`（contracts.py +
      observations.py + 23 测试）。SourceRevisionRef（range_hash 确定性推导）、
      ObservationEnvelope（modality 七态、MentionRef 禁伪造 UUID）、IdentityResolution
      （reuse 须候选证据、ambiguous 须 ≥2 候选）、TypedStateOperation（observe/move 分离、
      knowledge 须主体、documentary_assertion 不改状态）、EvolutionReceipt
      （failed/blocked/unknown_billing 游标必须等于前值且禁止倒退）。
      稳定观察 ID = sha256(来源范围+观察语义+契约版本)，无输出位置/run id（T06）。
      已注册 architecture-documents.toml / 00_整体设计 / CONTEXT / docs README /
      架构图 drawio+HTML（docs-check 带 no-change-reason 通过）。
- [x] 2026-09-21 会话 2：E02 完成——`evolution/identity.py` 确定性解析内核：
      仅精确名/别名证据自动 reuse（阈值永不自动合并）；同名多候选保持竞争
      （ambiguous，绑定冲突时把绑定对象补进候选集满足 ≥2 契约）；无精确 →
      new_candidate 记录模糊候选；观察者自带 UUID 绑定必须重验否则 unrelated。
      观察积累分离：解析不改 observation_id 不吞观察。world 候选经
      `facade.find_similar_entities` 结构适配（`candidates_from_world_results`）。
- [x] 2026-09-21 会话 2：E03a 完成——`continuity/reducer.py::StoryStateReducer`
      单一语义内核，章节重放与 Scene 投影委托；统一语义：manual_correction 与
      未知实体 entity_updated 一律入 changes（不造幻影不丢信息）、knowledge 同 id
      后写覆盖；章节重放状态/快照续算携带 changes。G0 两个缺口钉住测试转为
      一致性断言；T04 强化（knowledge 替换 + changes 相等）。
- [x] 2026-09-21 会话 2：T13 第一段对齐——助手新章/改写应用保存后显式
      `request_chapter_index`（与 API/candidate 工具同一调用），
      `test_assistant_side_effects.py` 断言。协作/导入两处仍缺，留 I02。
- [x] 2026-09-21 会话 2：E03b 完成——`replace_scene_events` 家族分区 +
      稳定 `meta.event_key`：作者确认与其他 producer 家族永不参与本调用替换；
      按键匹配的行原地更新（行 ID/槽位不变，T06 重排不重建）；未匹配行
      Core 立即删除 + expunge 防幽灵行；服务层统一注入 event_key
      （content_hash 语义指纹，不含输出位置）；`ingest_delta_events` 按
      (scene, source) 分组传 family；imports 空 Delta 重跑限定
      `producer_family="deep_import"`；facade `replace_scene_memory_events`
      加性可选参数。测试：`test_producer_replacement.py` 4 例（重排稳定/
      家族隔离/内容换键重建/legacy 全派生面）。
- [x] 2026-09-21 会话 3：E03c 完成——`evolution/commit.py` 窄提交协议：
      freeze_attempt 先持久化冻结负载（T10 恢复基础）；apply_frozen 短事务内
      重验 owner epoch（T12 前置，StaleOwnerError）→ 来源 manifest
      （CommitConflictError source_changed）→ 父回执身份与前缀
      （parent_advanced/parent_missing），再执行注入 applier 并保存回执——
      游标只在回执持久化后推进；同 attempt 重入直接重放原回执（T11，不重复
      领域写入）；recover_attempt 复用冻结负载、全程不接触 provider。
      存储经 AttemptStore port 注入（InMemoryAttemptStore 供测试；生产 PG
      实现随 E04/E07 接线）。T10/T11/来源漂移/父推进/失败无回执/旧 owner
      拒绝共 6 例故障注入测试。测试坑：rollback 会过期 ORM 属性（固化
      scene_id 字符串）并把未 commit 的场景行卷走（先 db.commit() 封存）。
- [x] 2026-09-21 会话 4：E04 完成——三表 + 迁移 + 编排内核：
      `evolution_models`（evolution_runs：owner epoch/已提交前缀游标/根预算；
      evolution_frozen_attempts；evolution_receipts）+ Alembic
      `20260921_evolution_tables`（本地真 PG ai_novel_acceptance_guimi 验证
      到 head、三表建成；注意 alembic.ini 写的 ai_novel_engine 是旧库，
      实际走 settings 的 guimi 库）。`store.PostgresAttemptStore` 绑定
      (db, novel_id) 实现 AttemptStore：回执落库同事务推进游标+head、
      回执不可改写、reserve_budget 条件 UPDATE 原子预留（T21）。
      `orchestrator.py`：prepare_scene_input 前序屏障（T07：Scene N+1 输入
      实际包含 Scene N 已提交回执，前序未提交显式 blocked 不带假结论）；
      plan_parallel_batches 确定性准入（同 Scene 依赖键不相交并行、
      键冲突/叙事顺序分批）。10 例新测试（含并发预留恰好耗尽预算）。
      本机坑：出现 `* 2.py` 陈旧副本文件破坏 lint（第三次遇到，删除即可）。
- [x] 2026-09-21 会话 5：E05 完成——`evolution/invalidation.py`：
      compute_source_change 物理差异（同字数替换给出非空窗口，T08 的
      4000 字后场景有专测）；apply_source_invalidation 传播正文变更
      （evidence request_chapter_index 换源重建 + Scene 投影软 supersede，
      保守扩大自锚定受影响章的最早 Scene，回执记 coverage）；
      apply_scene_reorder_invalidation（align_scene_indices + 从最早移动
      Scene 起失效，T09）。失效不删历史（作者确认保留有专测）。未接缝
      消费者 world_knowledge/map_atlas/assistant_suggestions 显式
      unsupported（待 G2/V/R 接线）。新增 story facade 薄缝
      supersede_scene_projections_from（story/facade __all__ 已登记）。
      测试坑：全角句号与逗号同为一字符（长度变更用例别拿它造长度差）；
      stage0 快照 scene_index 为 None 断言要排除。
- [x] 2026-09-21 会话 6：G2 纵切完成——pipeline.run_scene_step 组合器
      （屏障→预算预留→采样→观察→身份解析→冻结→窄提交，sampler 注入）；
      consumers.check_suggestion_validity（T17：索引指纹分叉即失效，含
      "已请求未重建"态；失效回执接线 assistant_suggestion_validity）；
      story/continuity/presence.py 在场投影（T03：仅自带 moved_from 证据
      才 traveled，否则 unknown 不造路程）。端到端切片
      test_g2_vertical_slice.py（林舟/青竹/白石城/铜钥匙）：Scene0 重逢
      （身份 reuse×2）→ Scene1（输入含 Scene0 回执，T07）→ 新 case 重放
      读到 custody 知识 → Scene2 渡口（presence 两节点+unknown 段）→
      修订 Scene0 → 失效传播 → 旧建议 verdict=stale；全新 run 的 Scene1
      未提交前 BarrierBlocked。**边界**：worker/async_tasks 挂接有意不做
      （E07 前接 handler = 第二编排 owner，违反 N03）；world 知识与地图册
      资产仍 unsupported（V/MI 接线）。
- [x] 2026-09-21 会话 7：E06 完成——recovery.py：replay_committed_prefix
      键集分页有界重放（链缺口 ChainGapError fail-closed、checkpoint 信任锚
      跳过早期页、max_pages 拒绝无界扫描）；verify_run_checkpoint（游标与
      head 漂移 CheckpointDriftError + 恢复期 owner fence）。
      T12 完整：store.save_receipt 游标推进以 epoch 匹配为条件——中途切换
      的旧 worker 回执在持久化边界被拒（专测：applier 内推进 epoch →
      StaleOwnerError，游标不动，新代际可提交）。测量：
      tools/evolution_checkpoint_bench.py 在本地真 PG 专用库跑 1k/5k/10k
      档位——全量回放线性（5/25/50 页），增量回放三档均 1 页/100 行
      <10ms，检查点校验 <10ms；报告在
      docs/plans/novelcraft-v4/e06/E06-恢复与性能测量.md（本机档位非承诺）。
      bench 坑：create_all 前须 _register_orm_models()（FK 依赖）且库要先
      建 pgvector 扩展；种数据先插 Account 再 Project（owner FK）。
- [ ] E07 迁移切换（影子运行/canary/在途兼容/入口重定向）（未开始）
- [ ] E07 迁移切换（影子运行/canary/在途兼容/入口重定向）（未开始）
- [ ] E08 deep_import 退役（未开始）

## 验证

- 2026-09-21 会话 2（E03b 后终态）：`continuity` 109 passed；`evolution`
  33 passed；`imports` 717 passed（含更新后的空重跑签名断言）；`writing`
  仅 1 例既有基线失败；lint 与 docs-check 通过（05_memory.md 已同步替换
  接口语义）。
- 2026-09-21 会话 2（中段记录）：`continuity` 105 passed；`evolution` 33 passed；`writing`
  仅 1 例既有基线失败；`imports` 全通过；world 35 例失败为基线既有
  （未改动基线复现归属，本地环境问题）。lint 与 docs-check（带
  no-change-reason）通过。已回退 ruff format 对范围外文件的无关重排。
- 2026-09-21 会话 1：`modules/story/continuity + modules/imports` 815 passed；
  `modules/evolution + continuity` 121 passed；`make lint` 通过；
  `python3 scripts/check_architecture_docs.py --base-ref origin/main --no-change-reason "..."`
  通过（Makefile 的 docs-check 目标不透传 NO_CHANGE_REASON，须直接调脚本，
  理由见当日命令记录：E01 无 make 目标/文档流程/测试分级变化）。
- 本机既有基线失败（与本改动无关，基线 commit 复现）：outline_state
  test_repositories 2 例、test_foreshadowing_reveal 2 例、writing
  test_create_many_reads_versions_once_and_flushes_once 1 例。

## 恢复快照（2026-09-21 会话 9，历史参考；最新状态见下方会话 10）

分支 `codex/novelcraft-v4-g0-baseline`，累计 26 个提交：G0×2、E01–E07、
G2、E09 第一步 + 真实模型验收（0cee8a3c5）。**用户已授权推送并建 PR；
分支已推送，PR #158 已建（未自动合并，等 CI 与评审）。**
E09 真实模型验收已通过（用户授权，DeepSeek 实调：schema 化观察 + 计量
回执，`modules/evolution/tests/test_real_llm_sampler.py`，Makefile
BACKEND_REAL_LLM_TESTS 已登记；密钥从 ~/.zshrc 种入账户连接，不经环境
直连）。
E03b 与计划 §2.2 的差异（有意收窄）：以 `meta.event_key` JSON 键替代新列
（避免生产迁移，语义等价——身份=语义指纹而非输出位置）；producer_family
暂用 source 字符串（deep_import/ai_extraction），generation/input_revision
登记在 delta meta，完整 `replace_derived_scene_events(...)` 签名留给 E03c
随 evolution/commit 落地。
下一步：E09（真实模型采样器接线 + 真实质量验收——需要账户连接与
用户授权跑真实 LLM，超出纯代码范围）；或按计划并行推进 G3+（项目级
切换落地/前端统一宿主 U 系列/地图 V 系列/R 系列推荐）。E08 实际删码
被 E09+canary 阻断（登记表已列）。world 知识/地图册资产留 V/MI。
合并 main 需用户授权；建议合并前跑 PostgreSQL e2e 专用库（配方在 memory）。

## 评审返修（2026-09-21 会话 10，PR #158 Request changes → 全项修复）

**PR #159（独立前端修复）已全绿合入 main（610d3872a）**：main 上
"Frontend functional browser" 必需检查红的根因是 65df0c789（前瞻/创作
试验，直推未走 PR 门禁）——creative-forecast.spec.js 留在 functional 套件
（无 ASSISTANT_ENABLED/合成 provider，等「项目助手」按钮超时）+ RP 页
forecasts/capabilities 未 mock 打真实后端 403 噪声。修复：接线
playwright.creative.config.js（script+CI 步骤+functional testIgnore）、
mockRpApis 补 capabilities mock、useForecast.refresh() dirty/saving 期间
跳过（保存落库竞态必然 SOURCE_STALE 409，建议入口此间本就禁用）、spec
补资源勾选。本地专用库全绿（interaction 16/writing 28/agent-teams 1/
assistant 1/creative 1/vitest 2536/eslint）。

**PR #158 评审（用户提供的 Request changes 报告）R1–R6+P2×3 逐项核实
（全部属实）并返修**：

- R1：SceneSampler 协议改 async；提及身份宿主派生
  （observations.derive_mention_id，观察身份+表面名+序位）；采样器工厂改
  async context manager（客户端 __aexit__ 成对）；handler 集成测试经过
  registry async sampler→world facade 精确名召回→一致性门→领域 applier→
  数据库回执（test_e07_switching + test_review_remediation）。
- R2：SceneSourceBinding 锚定真实 Writing 草稿（指纹来自 DB；scene_text
  须与草稿逐字一致，sha256 同 writing.source_hashing）；提交时
  _source_verifier 重查当前草稿（非自比较）；一致性门——scene_events
  引用未解析实体的提议 gated 进 pending_decisions；编译后观察（含提及
  身份与解析结论）持久化进冻结负载；G2 夹具引文改逐字子串。
- R3：屏障顺序检查（head.through_scene_index 必须恰为 N-1；scene 0 有
  head 即拒；跳场/倒序显式 blocked）；plan_parallel_batches 每 Scene 取
  最大批次（后放小批不回写）；前序输入带 previous_observations（链头
  冻结负载观察谓词有界摘要），build_scene_messages 注入真实前序理解。
- R4：事务边界重排——预算预留先 commit 持久化；provider 调用在提交点
  之间；冻结单独 commit；apply 为最后一笔短事务。域失败回滚不抹预算与
  冻结（test_review_remediation 故障注入：budget 只扣 1、frozen 仍在、
  recover_scene_step 免采样重放、sampler.calls==1）。handler 恢复优先：
  已提交→原回执幂等重放（load_scene_receipt）；已冻结→recover_scene_step；
  才走新采样（test_task_handler_recovery_replays_frozen_without_resample）。
- R5：单写者改数据库不变量——部分唯一索引
  uq_evolution_run_single_live_writer（novel_id WHERE live+active，
  migration 20260921_evolution_single_writer）；register_run 捕
  IntegrityError→single_writer_violation；排空/停止 run 重复注册拒绝
  （run_not_active）；reserve_budget 仅 active。真实 PG 双会话竞态 e2e
  （tests/e2e/test_evolution_single_writer_concurrency.py，专用库
  ai_novel_agent_e2e_evolution 全迁移含新 head 验证）恰好一个 owner。
- R6：legacy_adapter 预算严格沿用 requested_budget（不再 max 抬额）；
  paid_call_receipts 类型放宽 dict[str,Any]，sampler 回执带 provider/
  model/usage，applier 并入 ApplierResult→EvolutionReceipt。
- P2×3：save_receipt 显式生成 record.id（head_attempt_id 指针非空断言）；
  consumers 有效性收窄（indexed None 或 claimed None→unknown，不宣称
  一致）；_shadow_applier 按本步真实位置推进影子游标。

**G2 声明收窄（按评审）**：test_g2_vertical_slice 定位为「确定性夹具下的
存储/投影集成切片」（模块 README 已改）；完整 G2（持续认知闭环、真实模型
质量、独立 case 经 Evidence 消费、地图消费合法状态）留后续里程碑。
评审门槛第 6 条（独立 case 经 Evidence 消费+地图消费）未在本轮实施——
consumers seam 已收紧，Evidence 入模消费链待 E09+。

验证：modules/evolution 78 passed + 1 real-llm deselected；evidence fusion
contract 通过；ruff 全绿；docs-check 通过（01_数据库设计 §3.11 已登记新
索引）；真实 PG 迁移至新 head + 双会话并发 e2e 通过。全量后端单测运行中。

## 会话 10 收尾（2026-09-21）

- PR #158 CI 11/11 全绿（PostgreSQL critical 一次红为 artifact 上传 403
  基础设施抖动，测试本身 37 通过，rerun 即绿），已合入 main（41b2377d0）。
- main 现状：41b2377d0（V4 主链 + 评审返修 + 前端 CI 修复）。
- 下一里程碑（用户指令二选一）：E09 长书规模验证（真实作品多 Scene 影子
  运行对比）；或 G3+/U 系列前端统一宿主（R00 选区传递、U01 单右侧宿主）。
- 遗留（登记未做）：复审门槛第 6 条（独立 case 经 Evidence 入模消费 +
  地图消费合法状态）；E08 实际删码（待 canary+E09）；真实作者试用。

## E09 长书规模验证（2026-09-22 会话 11，分支 codex/evo-e09-scale-validation）

新增 `backend/tools/evolution_scale_harness.py`：专用空库上把
synthetic_ten_chapters（真实叙事，回归人物林舟/柳青/星盘/钥匙/顾遥）按章
建真实 Scene+Writing 草稿，shadow run 走真实 handler（evolution_scene_step）
逐 Scene 推进，按计划 §9 退出标准断言并出报告（stdout MD + --json-path）。

**deterministic 档**（10 Scene 0.26s；--repeat 5 → 50 Scene 1.12s，专用库
ai_novel_agent_e2e_evoscale）：链完整、前序状态注入 Scene 1..N-1、预算
恰尽且幂等重跑零扣减、影子零 MemoryEvent、跳场拒、重跑同回执、改原文后
旧文本推进被 source_changed 拒、引用逐字、提及有据——全部通过。

**real 档**（十幕，DeepSeek 经账户连接，用户已授权真实模型验证；~10 次
调用/轮）：43→41 条 schema 化观察、逐字引用、提及有据（模型实际跟踪了
顾遥/观星会/篡改星盘记忆等剧情线）、completion_tokens ~1.0-1.2k/幕进
回执；退出标准全过（耗时 ~52-89s/十幕）。

顺手修两处真实链路缺陷：①ProjectLLMSampler 经 generate_structured 的
diagnostics 通道捕获 structured_usage 计量（原 usage 恒 None）；②
_shadow_applier 现在把 provider 计量带入回执——影子运行消耗真实额度，
费用必须可审计（此前影子回执 paid_call_receipts 恒空）。

遗留：真实档观察里混有「本章标题为…」类平凡观察（质量噪音，非阻塞）；
身份全为 new_candidate（专用库无 World 实体，诚实待作者裁定）；跨模块
消费链（Evidence 入模+地图）仍属复审门槛第 6 条，未在本轮。

- PR #160 CI 11/11 全绿，已合入 main（2f3e6e9dd）。E09 里程碑完成。
- 下一候选：G3+/U 系列前端统一宿主（R00 选区传递、U01 单右侧宿主）；
  或复审门槛第 6 条（独立 case 经 Evidence 入模消费 + 地图消费）。

## U00+R00（2026-09-22 会话 12，分支 codex/u00-r00-entry-selection）

**U00**：`docs/plans/novelcraft-v4/u00/U00-入口与状态清单.md` 建立——15 路由
→岛→视图全清单、6 个命令模式命令、顶栏入口、公开演示白名单、状态面
必测清单、R00 断点事实底账与归宿决定记录（04-FRONTEND-HIFI §10 要求）。

**R00 三断点修复**（选区/intent 数据链一致传递）：
1. 选区 SourceRange：`captureWorkContext` 在写作页干净编辑器上捕获码点
   偏移（`Array.from` 计数，emoji 不漂移；dirty/saving 只留文本不带偏移）；
   `WorkContext` 新增 `selection_start/end`（成对+须绑定草稿+长度=码点数）；
   `AssistantService.submit` 载草稿后 `verify_selection_range` 逐字复核——
   漂移即 `assistant_selection_stale` 409 失败关闭。
2. task_hint/intent：`WorkContext.task_hint`（schemas.TASK_HINTS 封闭集，
   forecast 契约同源）；助手面板新增「这次要求」选择器（不限/续写/只润色/
   修改/设定设计/查证/检查/整理），经 withIntent 并入 turn 与前瞻上下文；
   `work_directive` 把意图行为边界渲染进最终 user 消息（如 polish="不得
   扩大情节、新增设定或改动事实"）——forecast 侧既有 polish 能力收窄
   （runtime 剔除扩情节项）自此可被触发。
3. forecast selected_range：`useForecast.focusFrom` 在干净写作页带
   draft+hash 时发送 `{start,end}`（契约本就要求并消费），前瞻实际分析
   选中段落。

验证：后端 assistant 89（77+12 新增）通过、ruff；前端 vitest 2538
（含 4 条 assistantContext 新用例：码点偏移/emoji/dirty 门控/项目隔离）、
eslint；assistant e2e 与 creative-forecast e2e（专用库）通过；docs-check
带理由通过。全量后端单测（无 .env）后台复核中。

- PR #161 CI 11/11 全绿（Architecture docs 首跑因 module-contract 规则要求
  评审清单文档，真实更新 assistant README + 20_assistant.md 并走第三项
  理由行后通过），已合入 main（561bcc133）。U00+R00 工作包完成。
- U 系列下一步候选：U01 AppShell/overlay/返回栈（以 U00 清单为底账）、
  U02 选区/intent/单 feed store；R01 scope/snapshot/task/focus 分离。

## U01 AppShell/overlay/返回栈（2026-09-22 会话 13，分支 codex/u01-appshell-overlay-backstack）

以 U00 清单为底账正式化 overlay 层（04-FRONTEND-HIFI §4「只有一个 overlay
root」），保持功能等价与公开演示路由白名单可达：

- 新增 `frontend-console/vue/shell/overlayStack.js`：模块级 LIFO overlay
  注册表（registerOverlay/unregister、topOverlay/isTopOverlay、
  closeTopOverlay）。`installOverlayEscapeRouter()` 在 AppShell 安装一次，
  **冒泡阶段** document keydown 兜底路由：未被元素级处理消费的 Escape 才
  关闭最上层 overlay；`#modal-overlay` 遗留全局模态可见时让位（先走旧链）。
  早期 capture 实现会在嵌套浮层（版本历史「更多操作」popover）首按时抢关
  底层对话框——回退为 bubble 兜底后语义正确。
- `useModalDialog` 开启时自动登记（requestClose 复用 canClose 守卫）；自身
  Escape 处理改为「非栈顶则放行冒泡给路由」，17 个既有模态零改动纳入。
- shell 三浮层显式登记：AccountDialog（shell:account）、ShortcutHelp
  （shell:help）、CommandPalette（shell:command-palette，Esc→close 且还原
  触发控件焦点=§4 返回触发控件）。
- 新增 `tests/vue/shell/overlayStack.test.js` 6 用例（最上层才关/逐层退/
  空栈不拦截/遗留模态让位/序关系/closeTopOverlay 返回值）。

验证：vitest 全量 2544 通过；eslint 清洁；e2e 回归 writing 28 + interaction
16 + assistant 1 + creative-forecast 1 全绿（功能等价）；docs-check 带理由
通过；U00 清单归宿决定记录已补 U01 行。

- PR #162（head c0b378d4d）CI 11/11 全绿，2026-09-22 合入 main（merge
  cb97d3f79）。
- U 系列下一步候选：U02 选区/intent/单 feed store；R01 scope/snapshot/
  task/focus 分离。

## V4 审查修复包 2（2026-09-22 会话 16，分支 codex/v4-audit-fixpack-1 续）

用户指令「继续修复」，按审查报告第七节顺序实施修复包 2（A02/A04/A08，
顺带 A09）：

- **A02（P1）Scene 来源区间**：`SceneSourceBinding` 增码点区间
  （start/end offset，缺省整章；end=None 落定稿尾；range_hash 可选自洽
  校验）；`load_current_source` 重验整稿版本+权威区间切片——服务端按
  草稿取出精确片段与 scene_text 逐字比对（非自比较），同章多 Scene 各自
  推进；观察 SourceRevisionRef 偏移映射回草稿绝对空间（分段变化不复用
  旧观察身份）；handler 请求带 start/end_offset 并经 outline_state 校验
  scene_id↔章号权威映射。**已登记缺口：跨章 Scene 多区间绑定契约未做**
  （审查回归清单中的跨章项仅部分覆盖，README 已注明）。审查反例修正趣闻：
  首段同长度替换后，后段逐字未变、重绑新稿仍可推进——被拒的是旧绑定。
- **A04（P1）结构化前序认知**：`store.load_prior_observations` 覆盖最近
  `PRIOR_OBSERVATION_WINDOW=3` 个已提交 Scene 的结构化观察（modality/
  主体表面名/观察身份/来源 Scene），SceneInputManifest.previous_observations
  改 list[dict] + `previous_observations_coverage`（scenes_included/
  total_committed_scenes/omitted_observations，未注入≠不存在）；
  build_scene_messages 按 modality 分级渲染（"[belief] 谓词（主体：…；来自
  Scene N）"，标题不再宣称"已确认的观察"，截断条数披露）。传闻在下一
  Scene 输入保持传闻有专测。完整历史认知/持久知识查询仍属验收包 3。
- **A08（P2）任意已提交 Scene 幂等回放**：`load_committed_scene_receipt`
  按 scene_index + 稳定请求身份（新 `compute_scene_manifest_hash`：
  run/scene/正文/整稿版本/区间，raw binding 口径）查任意已提交回执；
  handler 重放判定用它——同请求重试拿原回执不重采样不扣费，修订请求
  指纹不同不套用旧回执（走屏障拒绝）。旧 `load_scene_receipt`（仅链尾）
  已删。0→1→2 后重复 0/1/2 + 修订不套用有专测。
- **A09（P2）harness 精确 code**：stale-source 分支断言 `exc.code ==
  "source_changed"`，报告新字段 stale_source_rejected_code，退出门禁校验
  code 一致性（parent_advanced 混过判失败）；门禁测试加两条负向变异。

验证：modules/evolution 130 通过（+9 fixpack2 +2 gates 变异）；
story/writing 仅 5 例本机既有基线失败；venv ruff（0.16.7，**注意 anaconda
0.16.2 格式化有版本差，须用 .venv/bin/python -m ruff**）全绿；docs-check
带理由通过；deterministic harness 专用库重建 20 Scene 全绿（报告显示
code='source_changed'）。harness venv 直跑需 PYTHONPATH=.（.venv 无项目
安装）。

审查遗留（未做）：A02 跨章多区间绑定；A04 完整历史认知/合法 cognition
refs 消费（验收包 3）；验收包 3 不作弊 G2 重做、迁移包 4 canary/旧 owner
退役、前端包 U02+；harness real 档复跑需授权。

## V4 审查修复包 1（2026-09-22 会话 15，分支 codex/v4-audit-fixpack-1）

用户提交 NovelCraft-V4-PR-Goal-Audit-2026-09-22（A01–A09）。按报告建议顺序
实施**修复包 1**（A01/A03/A05/A06/A07），五项均在当前 main（#164 已合并）
核实成立后修复：

- **A01（P1）影子恢复隔离**：执行模式进入冻结/提交协议——run_scene_step
  把 execution_mode 盖章进冻结负载；`_resolve_step_applier` 统一写入策略
  解析（run 登记模式或负载盖章任一 shadow 即换隔离 applier），首次与
  恢复同规则，不信任调用方；`apply_frozen` 提交边界拒绝影子负载经未标记
  `shadow_isolated` 的 applier（CommitConflictError shadow_write_rejected）；
  未盖章 legacy 负载按 run 登记兜底。回归：影子冻结后回执持久化前故障 →
  恢复正式写入器零调用、Story 零写入；边界直接拒；legacy 兜底。
- **A03（P1）语义证据门**：新 `state_gate.py::gate_scene_events`——证据
  绑定（scene_events 必须引用同批观察 `source_observation_indices`，伪造/
  越界/缺引用一律拦）、modality 分级（客观维度只认 event_observed；
  statement/belief/hypothesis 只撑 knowledge 且须 `knowledge_subject`；
  author_plan/figurative/unclear 不撑任何状态操作）、主体须在被引用证据
  中解析。通过事件带 `source_observation_ids`+`authority_basis` 证据链；
  被拦提议带 `_gate_reasons` 进 gated/pending_decisions 待作者裁定。
  SamplerSceneEvent schema 增两可选字段，SYSTEM_PROMPT 同步约束。
- **A06（P2）计量未知口径**：`_build_receipt` 任一尝试某字段未知 → 该
  字段总量 None；`usage_complete`（全部尝试报齐三字段）+ `unknown_attempts`
  （缺失任一字段的尝试数）显式留痕。混合未知（100+未知≠100）有专测。
- **A07（P1）阶段化持久化+失败回执**：冻结负载按 `sampling → sampled →
  compiled` 阶段推进（attempt 身份+预算关系请求前落库；provider 结果任何
  领域推导前落库；编译为纯确定性推导）。sampler 最终抛错也固化
  failed_final 回执（含已发生请求真实用量）再重抛；`recover_scene_step`
  按阶段恢复：compiled→重验重提交，sampled→确定性重编译（需
  identity_candidates，handler 已补传）后提交，sampling/failed→
  `SamplePendingReconciliationError` 待核对（费用可能已发生，不自动
  重采样）。store 增 `replace_frozen_payload`（阶段充实，manifest 不变）。
  预算单位在 README 声明：Scene 步为准入控制单位，计费以回执为准。
- **A05（P1）前端选区绑原稿**：`useForecast.focusFrom` 记录选区捕获时
  origin draft_id，`result.draft_id !== origin` 一律不带 selected_range——
  不同稿同位置同文字（审查反例，文本重验会通过）也失效；新测试补齐
  （既有「切稿失效」用例换了文字，证明不了草稿身份检测）。

夹具更新：test_review_remediation/_e07_switching/_g2_vertical_slice 的
scene_events 补 `source_observation_indices`（g2 knowledge 事件补
knowledge_subject）。新测试：test_state_gate.py（9 例审查反例清单）、
test_audit_fixpack.py（6 例 A01/A07 管线级故障注入）、test_llm_sampler
+4 例（混合未知/字段级/失败回执）、Forecast +1 例（跨稿同文本）。

验证：modules/evolution 121 通过；modules/story 仅 4 例本机既有基线失败
（outline_state×2+foreshadowing_reveal×2，与改动无关）；ruff check+format
清洁；vitest 全量 2557 通过；eslint 清洁；docs-check 带理由通过
（22_evolution.md 已同步影子边界/语义门/计量口径）。deterministic
harness（专用库 ai_novel_agent_e2e_evoscale 重建 + --repeat 2，20 Scene）
全绿：链完整/前序注入 1..19/预算恰尽且幂等重跑零扣减/影子隔离 0 正式
写入/跳场拒/同回执/过期来源拒/引用逐字/提及有据。坑：harness 命令里
dropdb/createdb 必须带 PGPASSWORD=novel_dev_pass，否则后台卡密码提示。

审查遗留（未在本包）：A02 Scene 来源范围绑定、A04 前序认知结构化输入、
A08 任意已提交 Scene 幂等回放（属修复包 2）；A09 harness 精确 code 断言
（P2，后续顺手）；G2 重做/迁移包/前端包按报告第七节顺序。

## PR160–162 审查补修（2026-09-22 会话 14，分支 codex/v4-pr160-162-review-fix）

用户提交 PR160-162-review.md（8 项：F1/F2 两个 P1 + F3–F8 六个 P2），按报告
建议顺序全部补修：

- F1（P1）useProjectAssistant.send：新操作上下文以入参为唯一权威并冻结
  （含 task_hint），未传才沿用 state.context；blueprint 指纹刷进冻结副本而非
  面板态；未确认 pending 仍原样重试。两条依赖旧「入参被忽略」契约的既有用例
  按组件契约（withIntent(state.context)）迁移断言。
- F2（P1）useForecast.focusFrom：选区文本/偏移与 draft_id+指纹做原子重验——
  携带 selected_range 前先在当前已存正文原偏移处切片比对原选区文本，验不上
  即失效（不带范围），不允许新 hash 配旧 offsets。
- F6 overlayStack：注册身份改栈管理器唯一 token（两个 modal:2 不再认错栈顶）。
- F7 useModalDialog：非栈顶 Escape 在 stopPropagation 之前放行（原来入口先
  stop，document 栈路由永远收不到，底层按键两层全不关）。
- F8 Escape 单次消费：栈路由终结消费处加 stopImmediatePropagation（先于旧
  useShellShortcuts 注册），旧处理器的关面板/返回父视图分支尊重
  defaultPrevented（纵深防御）。
- F3 llm_sampler：回执计入结构化修复全部已发生请求（failed 也计费）——
  usage 跨尝试累计（100+120+80→300）、attempts=全部次数、新增
  succeeded_attempts 与 attempts_detail；未知用量保持 None 不当零。
- F4 harness 退出判定：real 模式 usage_recorded 非 True 判失败；前序注入改
  精确覆盖集断言（除链头外每 Scene，单 Scene 语料期望空集）。
- F5 harness 验证源统一：跳场请求 scene_id/正文/章节号同章（--limit 裁剪
  曾第六章正文配第十章号，触发 source 拒绝而非屏障拒绝）；过期测试修订与
  请求同指链尾第 budget_total 章、scene_index 取下一 Scene 防幂等短路。

回归：新增 F1（意图冻结/pending 原负载）、F2（携带/插字失效/切稿失效，dock
级含 crypto 真实异步需 real timers 的 settle）、F6/F8（overlayStack 同 id 身
份 + 终结消费阻断）、F7（双模态内部派发：非栈顶放行/退栈后关底层/嵌套
popover 先消费/canClose 拒绝不外漏）、F8（useShellShortcuts 尊重已消费）、
F3（三次尝试 300 tokens/未知 None）、F4/F5（新 test_scale_harness_gates.py：
13 项变异全拒 + 单 Scene 不适用 + --limit 2/5/9/10 请求字段同章不变量）。

验证：vitest 全量 2556 通过（+12）；eslint 清洁；后端 evolution 模块 103 通过
+ ruff 清洁；e2e writing 28 + interaction 16 全绿（Escape 行为变更回归）；
docs-check 带理由通过。


## 本轮审查与续做收尾（2026-09-22）

用户本轮授权范围是审查并继续实现，未要求发布。当前分支仍为
`codex/v4-audit-fixpack-1`，HEAD 仍是 `0efb1359d`；本轮所有修改均未提交。
逐包结论与优先级：[实施审查](../../../../docs/plans/novelcraft-v4/IMPLEMENTATION-AUDIT-20260922.md)。

- 已补：跨章最多 16 段来源及逐段版本校验；精确 Unicode 引用与歧义拒绝；跨章
  EvidenceQuote 与稳定身份；跨章原子事件在末章生效；恢复核对原请求与 Scene；
  run live/shadow 模式不因重试变化；Story 实际负载保存证据 ID/认知主体；
  handler 走 Story facade，shadow 同样校验场景序号；harness 使用真实探针 Scene。
- 新增 `test_source_integrity.py` 14 个行为用例。最终 Evolution 144 passed、
  1 real-LLM deselected；Ruff check/format、docs-check BASE_REF=origin/main 和
  diff-check 通过。文档门禁首次要求复核 tasks 文档，已补真实恢复/合并契约后通过。
- 全量后端一次：6112 passed / 45 failed / 15 skipped。起点 detached checkout 的
  相同 venv/.env 上复跑失败所属 11 文件：553 passed / 45 failed / 7 skipped，
  失败 node ID 集合完全相同。未删除断言或修改这些范围外基线测试；合并门禁仍不绿。
- 前端审查复验 5 文件 56 passed；没有本轮前端代码改动，没有重跑完整浏览器。
- 专用新库 `ai_novel_agent_e2e_v4_resume_20260922` 从空库迁移到当前 head；确定性
  20 Scene 影子链 1.02 秒通过、正式 MemoryEvent 0、重放零重复预算、source_changed
  精确拒绝。真实 PG 两会话单写者回归 1 passed。新库保留供续做，非保护库；没有
  操作 ai_novel_acceptance_guimi，也没有跑付费模型。
- [机器证据摘要](artifacts/v4-audit-verification.json) 记录失败集合及影子结果；
  工程验证 `quality_claim_allowed=false`。本轮 baseline 临时 worktree 为自建验证副本，
  验证后移除；原有 detached worktree/WIP 未处理。
- 长期任务保持 active：E05/I02 尚无真实生产接线，C 持久域/独立 case 经 Evidence
  入模、World 地图消费、新旧 owner 项目级迁移和 E08 核销仍未完成。下一步见恢复快照。

# 发现账本（全代码库优化审查）

更新：2026-09-11 19:4x +08:00（W2a 合并）。本文件是发现总索引与去重视图；每条发现的
完整字段（§7 全 12 项）以 `units/<槽位>.md` 对应小节为准，此处不重复维护。
发现 ID 保持槽位前缀；跨槽重复用 `dup-of`/`cross-ref` 标注，不重编号。

2026-09-11 独立复核补充：本文件目前不是 241 条发现的完整逐 ID 清单，且未保存全部去重映射；
`241（P0=0/P1=4/P2=58/P3=179）` 是原审查汇总值，不应被描述成可由本索引机械复算。
具体实施只采用在目标 HEAD 上重新核实的 ID。冻结覆盖账本对应 `main@e7d0b8d5b`；当前前端
分支的新增文件与 19 个已变更 blob 不在该覆盖结论内。

## 累计汇总（W1+W2+W3 全部完成）

- 覆盖：**2453/2453 路径全部已审**（F 1033 + W2a 252 + W2b 261 + W2c 334 + W2d 573）；P2 端到端 9 条链全部走读完成。
- 发现 241 条：P0=0，P1=4，P2=58，P3=179。历史候选复核累计约 120 项次（含 Wave0 十条命令逐条）。
- P1 四条：F4-1（测试扫 venv）、D5a-1、D5b-1（显式恢复的窄进程死亡窗口可保留 failed 态）、E1-1（52 个账户/偏好测试不在任何自动门禁）。
- 动态性能基准全线受阻（performance_probe 本机必败 + 需隔离环境/专用 PG），已按 §5/§7 如实记录"收益待测"，未虚构 p95/p99。

## W3 新增（X1–X4，12 条：P2=2、P3=10）

- **X1-1（P2）** assistant resume 缝隙：`AgentBudgetError`/裸 ValueError（lifecycle.py:151/157）未映射 DomainError，而前端对 failed run 无条件显示"恢复本次查证"（ProjectAssistant.vue:26，已抽查实锤）——超时窗口后点击必 500，同函数另一分支是干净 409；与 D1-4/D5b-2 同族。
- **X2-2（P2，功能性）** deep_import 恢复无来源漂移门禁：high_quality 下 Phase 1c 融合非确定性使 provenance key 幂等失效，可产生重复重叠 draft Scene；普通导入恢复则重付 Phase 1a/1b LLM 费用。与 D5b-1 叠加使恢复契约成为导入链最薄弱段。
- P3：X1-2（snapshot 双查 get_project_context）、X1-3（并发同 operation_id 幂等退化 500）、X2-1（ImportWorkflowRunService.fail 生产零调用）、X2-3（取消后部分产物无清理入口）、X2-4（review 组指纹漂移后 resume 零进度循环+提示失实）、X3-1（跨服务私有访问）、X3-2（S3 补偿窄失败窗口无孤儿对账）、X3-3（world 长预算任务无用户取消入口，产品裁定）、X4-1（contract_hash vs bundle_hash 键不对称，当前行为闭合）、X4-2（stale 内部英文文案透传作者）。

### 链路走读总结论（P2 出口）

- 链 1/7（账户→LLM→worker；助手）、链 3/5（世界采用/失效；地图 CAS）、链 4/6/8（正文候选/指纹；RP 反证；编辑器三层保存）全部闭环：五重 fail-closed、租约/幂等 fence、confirmation 七门禁重验、CAS 冲突用户可见保留、RP 无作者资产写回反证均实证成立。
- 唯一系统性薄弱段：导入链恢复语义（D5b-1 + X2-2 + X2-3 + X2-4 叠加）。
- 错误语义映射不一致是跨模块共性缝隙（D1-4、D5b-2、X1-1、X4-2 同族）。
- 单模块简化最需保护的契约：llm_runtime snapshot 双轨存储、decide_batch 逐操作 savepoint、Canon Admit 唯一 seam、confirmation 指纹不透明传递、autosave 发送前同步 flush。
- 链 9：F5 发布契约事实全部核验自洽，无新发现。

## W2d 新增（E1/E2/E3，31 条：P1=1、P2=9、P3=21）

- **E1-1（P1）** `backend/tests/account_project_preferences/` 52 个测试（含 owner 隔离、偏好/连接合同）不进任何自动门禁——`41412c2ec` 收窄 testpaths 时掉出 fast 层；testing-guide.md:43-44 声称的覆盖面实际从不执行。修复=testpaths 加一行。
- **E1-2（P2）** backend/evals/tests 124 个确定性测试无自动门禁；`make eval-fast` 裸 pytest 绕过锁定运行器（与 F5-9 同型）。
- **E1-3（P2，并入 F4-1）** 修复落点精化：`test_identity.py:26` 改用现成 `tests.support.inventory.production_python_files()`（跳过 .venv，语义正合）。
- **E1-4（P2）** `/api/story` 路由组 9+ 端点 HTTP 层零测试。
- **E2-1（P2）** api-contract.test.js 的 productionJsFiles 守卫完全缺 `vue/`（176 个真实生产视图），且 views/ 迁移会让 readdirSync 直接崩 4 用例——X1-9 同步义务具体化。
- **E2-2（P2）** shared/workspaceRail.js 整模块（65 行+44 行测试）仅测试消费；**E2-9（P2）** world review 两套同名导出+两套互不相交测试（D8b-1 互证），并警示 `markEntityReviewed` 经 SFC 模板 `@click` 生产可达，删除须逐符号三查。
- **E3-1（P2）** `make generate-e2e` 缺必需 env，加载即抛错（必败死入口）；**E3-2（P2）** 53MB tracked 二进制夹具可运行时生成替代；**E3-3（P2）** 定宽 sleep 型 flaky 残留 4 处。

P3 共 21 条见各槽位报告（含 E1-9 e2e 样本为《诡秘之主》原文节选入库的法务提示、E2-5 `expect(true).toBe(true)` 假覆盖、E3-8 95 张 darwin-only 视觉基线等）。

重要澄清与修正：历史"evals 与 Makefile eval-* 为 CI 活跃调用"修正为仅 `eval-ask-world` 单目标 CI 活跃；mock autospec 合规由 AST 守卫机器强制、零违规（历史担忧不成立）；D4-1/D3b-1 的失实断言载体精确定位在 `test_conflict_checks_real_llm.py:209/211/329`（make test-real-llm），前端 real-LLM spec 无此问题，前端仅 ConflictDetailDialog.vue:124 死展示映射残留；E2 口径差（183 vs 186 文件）已在报告中标注。

## W2c 新增（D6a/D6b/D8a/D8b/D8c，46 条：P2=11、P3=35）

P2 亮点：
- **D8c-1** styles.css 三对成批逐字重复约 780 行纯冗余（两次"UI 一致性"提交重复粘贴引入，已定位到行级并给出逐对保留/删除方案）。
- **D8c-3** settings 死组件簇 LlmFormFields.vue 210 行 + llmForm.js 175 行 + 2 测试文件，全库唯一引用是其自身测试（已抽查实锤）。
- **D6a-2** `index_state.summary()/freshness()` 全量 ORM 加载后 Python 计数，挂在 `GET /chunks` 每次列表请求（收益待测）。
- **D6a-1** `query_expansion._expand_query_with_project_terms` 与 QueryExpander.expand 33 行逐字重复且生产零调用（测试 monkeypatch 的死符号=no-op patch）。
- **D6b-1** import_activation 死方法簇+恒空 `world_entries` 契约字段；**D6b-2** legacy bundle Markdown 渲染器生产零调用约 600 行。
- **D6b-4** world scope 搜索 N+1 + `list_for_source_chapter` 全量加载 Python 过滤（收益待测）。
- **D8a-1** 六个 localStorage 草稿键前缀未登记账号清理清单，用户草稿跨账号残留。
- **D8b-1** world review 操作死代码簇 ~280 行（仅各自单测消费），且存在两份同名已漂移实现、测试保障为假（已抽查实锤）。

其余 P2：D6a-3 / D6b-8（evidence 两级 facade 缺 `__all__`，A7-4/X1-3 形态更新为"新增"）；D6b-9（legacy GET 死路由+守卫测试，A7-1 缩小定案）。P3 共 35 条见各槽位报告（含 D6b-5 planner 搬家关键词语料特判需产品裁定、D8c-2 死选择器族、D8a-4 三页 900 行同构骨架等）。

移交与增量：F3-1 的 activationPreview 死链定案（前端死契约+死包装可删；POST `/activation-preview` 有真实消费者 useWorldBible.js:1731 不得误删）；F1-3 census 再增（D6b compilation 内 9 处 sha256-json 指纹，含两个持久化比对面禁止输出漂移）；D8a-6 列出三处手写 manager 与工厂的能力差距（含必须保留的语义）；D8b-2 raw status 枚举暴露给作者（产品裁定项）。

## W1/W2 生产与基础设施 P1（3 条；E1-1 见 W2d）

| ID | 一句话 | 位置 | 状态 |
|---|---|---|---|
| F4-1 | `test_identity` 用 `rglob("*.py")` 从 backend 根 AST 遍历，把 `backend/.venv`（约 1.4 万文件）全部解析——基线"失败"实为 fast 层超时判负；排除 venv 后断言通过，单独跑需 27 分钟 | `backend/infrastructure/tasks/test_identity.py:26`（BACKEND_ROOT.rglob） | 已由独立复跑证实（1 passed in 1623.90s）；修复=测试内加 venv 排除，归 F2/E1 文件，实施批次处理 |
| D5a-1 | 生产 prompt 硬编码《诡秘之主》实体名清单与内部评测名"Codex5.3"注入小样本 sweep（8–12 Scene 且初抽 <29 实体可达）；bulk_entity_memory_context 另有 1–7 章题材特判——第三方内容注入任意用户的抽取请求，属已有功能错误 | `backend/modules/imports/entity_extraction/scene_entity_bulk.py:416-423`（已独立实锤）；关联 `scene_fusion.py:33-40` 死 reducer 内同类内容 | 按 §2 单列功能性修复任务；持久化证据门禁兜底了大部分落库风险 |
| D5b-1 | `phase="failed"` 与 `recovery_required=true` 同时保留的窄进程死亡窗口中，显式 resume 重新入队后 `_progress_from_task` 不重置（仅 targeted_completion 特例），`workflow.run_step` 再抛「无法处理当前进度状态： failed」。普通优雅失败是 dismiss-only，并非全部可 resume；现有测试未覆盖该窄窗口的 fail→resume→重跑 | `backend/modules/imports/orchestrator.py:1368-1396`；精确触发面见 `units/X2.md` | 按 §2 单列功能性修复任务；只在显式恢复意图下归一状态并补窄窗口回归测试 |

## P2（29 条，索引）

### W1 原有 22 条

- **F1-1** shared/enums.py 17 枚举中 14 个生产零引用（约 300 行+自测试；EventType 与 continuity 本地枚举同名异义已排除）。
- **F1-2** shared/utils.parse_llm_json/is_valid_uuid 死代码；活跃解析器在 infrastructure/llm/client.py（cross-ref F2）。
- **F1-3** stable_hash 13 份收敛（修正历史 A5-10 的"16 份"），含 3 个语义变体，须指纹字节兼容；权威位置待 P3 裁定。
- **F2-1** 任务 API 37 项手工黑名单可由注册面推导；响应差异须按功能变更立项（修正 A1-1"端点恒 403"的旧判断）。
- **F2-3** 六处私有 snapshot LLM 客户端 CM 收敛 ~110 行（=A5-2/A2-4 链，调用方在领域槽位，cross-ref D3a/D4 等）。
- **F2-4** commit→in_transaction→expire_all 十处样板收敛（=A1-7）。
- **F2-5** TaskStatus 枚举收敛，94 处裸字符串（=X1-6 机制侧；领域侧待 W2）。
- **F2-6** test_identity 扫描 venv 的机制描述（dup-of F4-1，不单独立项）。
- **F3-1** 11 个已定义未接线契约（7 个 cocreation 会话/消息/推进 + 3 个 map atlas + context.activationPreview 死包装）；在用的 cocreationChat/enqueueCocreationTurn 已切契约不受影响；后端 activation-preview 死路由 cross-ref D6 待查。
- **F3-4** SmartDedup DOM 桥接 split-brain 机制侧（=A8-3；领域本体归 D8，列 Phase 5 架构候选）。
- **F4-2** prune_rendered_context 全量 ORM 加载 vs 同文件 set-based delete 双模式。
- **F4-3** UUID 列类型 4 种声明收敛。
- **F4-4** world_library 5 表 ORM/migration FK 声明漂移。
- **F4-5** A3-1 机制侧仍成立（StructurePlanRepository 已有 2 子类，PlotThread/OutlineArc 未继承）。
- **F4-6** A3-5 仍成立且规模扩大：手写 novel_id 列约 64 处/13 文件（历史估计 24 处）。
- **F5-1** `backend/backend/.test-logs` 11 个 tracked 测试日志经 git-archive 构建上下文进入全部生产镜像 ~74KB（cross-ref F6-3 同对象）。
- **F5-6** CI 缺 Playwright chromium 与生产镜像层缓存，每次全量下载/构建。
- **F6-1** `scripts/dev_migrate_worldbuilding_v1.py` 已损坏（导入 6 个已不存在的旧模块 models，运行即 ModuleNotFoundError），仍被 development-guide.md:51 指引。
- **F6-2** `backend/.coverage 2/3` 带空格名二进制副本误入库（`*.coverage` ignore 规则匹配不到）。
- **F6-3** `backend/backend/` 11 个嵌套 cwd 错误产物为唯一副本，删除前需与验收证据留档裁定（cross-ref F5-1）。
- **F6-4** 工具历史目录 57 个运行时/历史工件被跟踪（含 pid 锁），与 docs/README.md"运行时产物非项目文档"声明矛盾。
- **F6-6** deepseek probe 本地 config.local.json "真实 key 需轮换"警示维持开放（内容未读取）。

### W2a 新增 6 条

- **D1-4** legacy `smart-dedup/apply`（suggestions 路径）`confirmed=false` 裸 ValueError→500，与 apply_groups（400）/scan（409）错误语义不一致；功能性修复单列。
- **D2a-1** `world_background.py` CharacterKnowledge 查询 limit 前无 ORDER BY、relation 平局未消序——超限时背景包组成不稳定，影响 context 激活输入确定性。
- **D2b-1** boto3 S3 client 无缓存，5 个生产实例化点（`map_atlas_service.py:80` 等），图片批量读取放大；收益待测。
- **D5a-2** `scene_fusion.py` 约 1000 行旧 Phase 1b reducer 生产零调用（仅测试引用），内嵌 78 行《诡秘之主》情节锚点（删除时一并清除 D5a-1 关联内容）。
- **D5a-3** `phase2_world_extraction.py` 的 window 级路径生产零调用（约 1250 行，`existing_checkpoints` 形参接受即丢弃）。
- **D7-1** interaction services.py/generation.py 概要入队 helper 逐字重复 + ~15 处跨类私有互访（两文件实为一个工作流拆两个类；A5-7 领域侧）。
- 增量标注：**F1-3** stable_hash census 13→17（D7 在 interaction/assistant 新增 4 处变体，并入同批）。

### W2b 新增 8 条 P2（含 1 条跨槽 dup）

- **D3a-1** A5-1 仍成立且扩大：story/api.py 两 enqueue 逐字重复，outline_state/api.py 另有 3 处同型入队流。
- **D3a-2** F2-3/F2-4 调用方配对：story 侧 snapshot CM 4 处（含 scene_fusion_draft 次序变体）、checkpoint 三步 4 处（2 处未入 F2-4 清单）；`_require_llm_execution_snapshot` 实存 2 份（历史称 4 份，部分已解决）。
- **D3b-1** `get_continuity_evidence_for_writing` + MemoryContinuityEvidenceContract 生产零调用（已独立实锤：仅 writing/README.md:283 宣称+测试消费），且 real-LLM 测试断言生产无法产出的 `continuity_location_mismatch`——死 seam+文档失实+失实测试，裁定"补实现（功能 backlog）或删 seam（优化批）"。**D4-1 为同一事实的 writing 侧视角（dup-of D3b-1）**，其增量：验收必然失败于规则层。
- **D3b-2** 生产唯一 memory 事件写入路径全落 `manual_correction` 场景，章级重放无该分支——`MemorySnapshot.full_state` 与 `ChapterPanorama` 在当前流水线下恒为空壳；双投影不对称属 Context 输入语义，领域裁定后单列。
- **D4-2** writing 内 3 份逐字同构 JSON 稳定指纹 + 2 份相同 compiled-context 序列化器，~90 行收敛须指纹字节兼容（并入 F1-3 批）。
- **D4-3** `/semantic-reviews` API 仍内联 snapshot+enqueue 编排，应委托已存在的 `submit_review`（=A5-8 残留单点）。
- **D5b-2** `/review-resolutions/{id}/rollback` 与 `/decisions` 对"整理记录不存在"抛裸 ValueError→500，同文件同类条件是 404/409，违反 README 统一口径。
- 增量标注：**F1-3** census 继续扩大——D2c +2（=19）、D3a story 面 8 同语义+4 异构、D3b +1（`scene_projection._hash`）、D4 +2；最终数目 P3 阶段统一裁定，收敛须逐份指纹字节兼容。

## P3（37 条，索引）

F1-4 shared/constants 死常量+双源漂移；F1-5 shared/types.py 整文件死；F1-6 core/dependencies 死导出+session 重复；F1-7 container register_factory/override 零生产引用；F1-8 run_worker 内嵌 interaction_ 领域分支。
F2：OutputGuard 死修复层与死字段；retryable/from_project_settings 零生产调用；enqueuer reuse_active 第二查询死代码；llm_runtime 双入口尾部重复（A2-4 缩小版）；快照构建重复项目查询；llm README 目录漂移；publish 双重试循环（A1-6）。
F3-2 超时双权威源+timeoutKind 死字段；F3-3 today/generate 死路由注册（模块导出被复用只删注册）；F3-5 state.mode 只写不读；F3-6 wechatStartUrl slice 耦合；F3-7 pollTaskProgress 无退避上限；F3-8 healthCheck 绕读不绕写污染 LRU；F3-9 _lastApiError 单槽竞态；F3-10 nc-theme* 清理不对称（待产品确认）。
F4：frozen 快照护栏记录；alembic.ini 开发凭据；0710 注释失实；scene_spans 重复索引；reconciliation 冗余索引；downgrade 幂等约定；squash DROP EXTENSION。
F5-2 wheel 元数据含 evals+测试；F5-3 EMBEDDING_IMAGE digest 不一致（需网络取证）；F5-4 pgvector 同 tag 异 digest（需网络取证）；F5-5 dev compose postgres 浮动 tag；F5-7 uvicorn forwarded-allow-ips *；F5-8 nginx location 头继承中断；F5-9 Makefile eval 目标绕过锁定运行器。
F6-5 docs 索引缺口；F6-7 deep_import 验收脚本 import 生产私有适配器且无测试；F6-8 backend/.test-logs 240 文件 27MB 政策张力；F6-9 个人 skill 说明占据 docs/。

## 历史候选复核结论（W1 范围，42 项次）

- **仍成立**：A1-2/A2-1（合并）、A1-5（定位修正：imports 4 handler 测试专用 else 分支）、A1-6、A1-7、A2-4（缩小）、A5-2、X1-6 机制侧、A3-1、A3-5（规模 24→64 处）、A8-3、A8-4 部分（死契约 12→11，timeout 数值分歧已消失）、A7-1 前端侧（缩小到 activationPreview 单点）、A2-7+A9-5 部分（镜像面已解决、wheel 元数据仍在）、`backend/backend/.test-logs`（加重，见 F5-1）、deepseek key 轮换。
- **已解决**：X1-7 机制侧（全局 handler 唯一存在 main.py:559）、A8-6 大部分（vanilla 渲染器已删，剩余 ~20 行建议不再立项）、迁移压缩（20260703 已 squash 过一次）、根 `.test-logs`、镜像携带 test 文件（.dockerignore 已解决）。
- **误报/不成立**：A1-3 机制侧、A1-4（制度性 seam）、`deep_import_phase01_real_llm_check.py`"零引用删除"（实为 deep import 真实验收工具链，产出 tracked 验收产物）、`tools/deepseek_scene_probe` 删除（DECISIONS 是 production Phase0/1a 依据）、`frontend-console/docs`"未跟踪"（现已跟踪且被索引）、A1-1"端点恒 403"（是被测扩展机制）。
- **功能变更/重新定性**：X1-8（flag 是运行时 session 标记非部署开关，生产恒走 domain 分支）。
- **待查**：A1-8（历史明细缺失）、A3-6/A9-12 squash（生产 revision 证据在服务器 DB；`migration_compatibility.py:288-300` 已有 fail-closed 门禁；按 §6 不默认 squash）。

## 跨槽合并与待办移交

- F2-6 dup-of F4-1（单条 P1）。
- F5-1 与 F6-3 同对象双面（镜像污染 vs git 卫生），实施时合并为一批。
- F1-3 stable_hash 权威位置待 F2/D 组认领后 P3 裁定。
- F3-1 的后端 activation-preview 死路由移交 D6a/D6b 核实。
- F2-3/F2-4/F2-5 的调用方侧证据由 W2 领域槽位补充。
- A1-8 待查需原始 A1 底稿（已不存在则按现状重新取证关闭）。

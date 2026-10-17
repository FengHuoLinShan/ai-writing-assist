# map-enhancement 分支评审汇总报告

- **评审对象**:实现工作树 WT(`.worktrees/map-enhancement-plan`)HEAD `81785cd16d1310f747e7790832567a593d6a9952`,diff 范围 `origin/main`(00d861283)...81785cd16,即分支 codex/map-enhancement-plan(764 文件、+16.6 万行);工作树另有 **4 项未提交**。
- **评审组成**:4 份计划逐里程碑只读对账 + 18 个分片审查(发现均经复核)+ 脚本统一执行的 7 项门禁。
- **报告日期**:2026-10-16。本报告仅汇总呈现本次评审输入的结果,汇总过程未新增验证、未运行任何测试/构建;unconfirmed 发现保持 unconfirmed 标注。

## 1. 总体结论

**实现状态**:四份计划的工程实现主体已完成,与计划及 ADR-0035~0041 契约总体一致。计划一(地图系统增强)M0–M4 全部 implemented、M5(势力)按计划正确 deferred;计划二(对象档案/场景导演/写作副驾驶)C0、C2–C5 与关键裁定均 implemented,C1 如实 missing、代码无假装;计划三(C0 映射)15 项中 12 implemented、1 partial(22 个 current_* 文件实查 12 个)、C1 deferred、文档自曝两处缺口已在代码修复(仅文档陈述过时);计划四(Agent 操作面)A0–A4 全部 implemented(A4 真实使用数据未完成属既定边界,报告侧如实标注、未以合成样本冒充)。安全面:各分片与计划对账均报告**未发现 novel_id 隔离、owner 校验、LLM 私建客户端或动态内容注入违规**(横切分片"安全与 novel_id 隔离零命中")。

**当前问题**:HEAD 81785cd16 上 **ruff 与后端全量测试两项门禁失败**(后者 1 例失败:`modules/imports/tests/test_scene_phase_refactor.py::test_codex_enrichment_admits_before_work_starts_and_keeps_every_scene`,`assert 2 == 8`)。共 51 条复核后保留的发现:1 high(门禁)、22 medium(19 verified + 3 unconfirmed 且复核均未通过)、28 low(全部 verified)。verified medium 中包含:数据正确性缺陷(Character.role varchar(64) 溢出、六种 strong profile 双写不收敛、人物合并被旧档案值遮蔽、章节重排 MemoryEvent 章节锚不一致)、作者草稿静默丢失(前端 3 处)、契约违背(Evidence SECTION_DIMENSION_MAP 缺两维度、manifest 丢 legacy 元数据、导演总开关缺失、组合根内嵌约 600 行业务逻辑)等。

**合并判断**:实现完成度与诚实度足以**进入合并讨论**,但当前 HEAD **不满足合并门禁、不能合并**。合并前必须先修:① ruff 门禁失败;② 后端全量测试失败(上述 1 例);并强烈建议同批处理 verified medium 中数据正确性 / 作者数据不丢失 / 契约违背项(见第 6 节 P1)。

### 分片审查覆盖一览(18 个分片)

| 分片 | 文件 / 新增行 | 小结要点 | 已复核发现 |
|---|---|---|---|
| 横切契约与安全 | —(全 diff)| 七条红线(LLM 客户端、novel_id/owner 隔离、前端转义、Mock/patch、eval/Key、跨模块直引、异常吞噬)逐一检索;LLM 客户端/隔离/Mock/eval/直引通过,安全与 novel_id 隔离零命中;25 个新迁移构成自 20261014_model_scope_budget 起的单一头线性链 | 2(其中 1 条后经复核推翻)|
| 世界·地图与词表 | 43 / +16115 | API 均经 require_active_project(_exclusive)、查询带 novel_id,测试覆盖跨项目隔离;空间线索采用前强制原文重验证(G8a/G8b);写路径 NOWAIT+savepoint+FOR UPDATE+CAS | 2 |
| 世界·对象档案 | 11 / +6546(全新增)| 修订链(部分唯一 active 索引、409 CAS)、模板版本化、Generic 桥接、manifest 并发与幂等总体扎实;测试断言真实但跑在 SQLite 上不暴露 varchar 溢出 | 4 |
| 世界·实体与服务 | 76 / +13522 | 跨模块仅经 contracts/facade/DI port;统一 entity-first 锁序、CAS 指纹、NOWAIT 55P03→409;迁移链无新分叉 | 2 |
| Story·导演与推进 | 40 / +16369 | 跨模块边界/校验/预算/幂等/恢复实现完整;两条 LLM 任务链仅经 project facade 快照通道 | 3 |
| Story·连贯性与弧线 | 59 / +11234 | 409 CAS/幂等键/advisory lock/迁移与 ORM 一致;测试含 PG e2e 并发串行化用例 | 2 |
| 助手·提醒与地图工具 | 29 / +5741 | 聚合只经 DI 登记表、每来源独立 session 带超时降级;POV 秘密/作者未来计划不进角色上下文有专门测试 | 2 |
| 助手·操作目录 | 36 / +13097 | 隐私最小化(参数仅形状/长度/分桶/项目盐 HMAC)、goal 侧 advisory-lock+行锁+savepoint+80% 预算停点自洽 | 2(其中 1 条后经复核推翻)|
| Evidence·参考维度 | 46 / +7468 | 能力开关默认空集、DI 只读 port、confirmation stale fail-closed 与测试吻合 | 1 |
| Evolution·空间发现 | 41 / +8633 | quota 版本化、主理解保留额、行锁+owner_epoch fencing、续读冻结均有实现且断言真实 | 3 |
| 写作与其他后端 | 70 / +8669 | collaboration/interaction/project/writing 隔离闭环、幂等重放贯穿;迁移与 ORM 新表核对一致 | 1 |
| 迁移与基建 | 39 / +3715 | 25 迁移单链至 20261016_chapter_order、downgrade 齐全、30 张新表与 ORM 一致;信封 V3/V4 能力白名单失败关闭 | 2 |
| 后端 e2e 测试 | 34 / +10575 | 隔离矩阵/真实 PG 锁/CAS/秘密不进 trace 断言真实;无 skip/xfail、无断言删除,仅 2 处 patch 均带 autospec | 2 |
| 后端单测与评测 | 33 / +17614 | 原文/gold/prompt 强制存放仓库外私有目录、scope 门禁 fail-closed、无硬编码密钥 | 1 |
| 前端·写作与场景 | 21 / +4031 | 无 v-html、409 冲突/预览-确认指纹/幂等键/未保存保护/窄屏均有实现 | 3 |
| 前端·世界与组件 | 57 / +8128 | 危险写操作 preview/confirm+指纹、409 与 epoch 竞态防护完整;读者视图不泄漏私有空间名 | 4 |
| 前端测试 | 52 / +5630 | 三大新行为断言完整真实;16 个含删除行的文件逐一核对、删除均有更强替代,无空转快照 | 1 |
| 文档与任务记录 | 77 / +8959 | ADR-0035~0041 登记、路由前缀、新表名、commit 引用核对一致 | 5 |

## 2. 门禁结果表

| 门禁 | 结果 | 详情 |
|---|---|---|
| ruff | ❌ 失败 | 退出码 2(无输出)|
| eslint | ✅ 通过 | 通过 |
| docs-check | ✅ 通过 | 通过 |
| repo-gates | ✅ 通过 | 通过 |
| 后端全量测试 | ❌ 失败 | 退出码 2:1 failed(`modules/imports/tests/test_scene_phase_refactor.py::test_codex_enrichment_admits_before_work_starts_and_keeps_every_scene`),9025 passed,2 skipped |
| 前端测试 | ✅ 通过 | 3212 通过 |
| 前端构建 | ✅ 通过 | 通过 |

分支状态:HEAD `81785cd16d1310f747e7790832567a593d6a9952`,未提交项 4。

## 3. 计划逐里程碑对账

### 3.1 docs/plans/2026-10-15-map-system-enhancement.md(地图系统增强,ADR-0035/0036/0037 + ADR-0038 §10)

小结:M0–M4 与计划及 ADR 契约逐条吻合,关键裁定均有代码证据;M5 势力正确 deferred;novel_id 隔离抽查(词表/线索/自动草图的 API 与服务查询)均按 novel_id 过滤并经 require_active_project,未发现越权。小结中提及的 1 条 ADR-0037 §2 契约偏离(consumer_action)经复核被推翻,最终保持 unconfirmed(见 4.4 U3)。本计划对账按指令只读,未运行测试/构建;另核实 simulation_v3(story/simulation.py:114)属同分支 ADR-0041 范围,非本计划里程碑,未纳入对账。

| 里程碑 | 状态 | 证据(要点)|
|---|---|---|
| M0 空间模型 v2+项目词表+Evidence 参考维度基础 | implemented | 约束白名单 map_structure_geometry.py:149-183 + 回归测试 test_map_geometry_hash_v1.py:58,78,85;v2 模型 map_structure_schemas.py:343(schema_version)、:345/:348(spaces/journeys)、:77-82/:231-240/:270-301(type_ref 成对固定 revision)、:111(生效区间稳定锚点)、:436-441(跨空间行程)、:476-488(level_type_ref);模态复用 shared/observation.py:5-13(7 值);词表 project_vocabulary_models.py:29-34/:41、presets.py:29-160(五题材)、assistant_vocabulary_tools.py:534-570;参考维度 policies.py:122、scope.py:398-410/:463-535/:558-563/:595-618(advisory_omitted 单独记录、scope_complete 不受影响、require_scope_complete 只查必查维度)|
| M1 演化统一可选阅读步骤与空间发现/独立复核/线索候选 | implemented | optional_steps.py:13-51(details+spatial 纯数据 SPEC);workflow.py:58(discover_spatial 默认 False)、:83-89(关闭时快照字节形状不变)、:191-192/:382(设置不符显式报错);optional_scene.py:1-60(主回执先行、shadow 隔离、可恢复);spatial.py:873-881(密度预检)、:180-193(方法指纹)、:204(抽取/独立复核两套提示);线索四态 map_spatial_clue_models.py:29-34、clue_service.py:740/:1190/:1238、涌现类型 :1098-1142(需 ≥2 个 Scene 证据+复核 passed);test_optional_steps.py:31-70/:289 |
| M2 增量草图/分片/托盘/候选绑定降级/审核界面与助手操作 | implemented | map_atlas_models.py:322(superseded)/:336(唯一约束);auto_draft_service.py:841-849(增量基础=待审候选)、:1476-1505、:1750-1772、:889-903(五种整片重做触发)、:86-92(层级来源四级优先级与 ADR-0036 §7 逐字一致)、:439-483/:486-497、:653-970(分片+托盘)、:2462、:1103-1126/:1140-1146/:1241-1248(融合跟随+降级文字标签)、:1936(每分片独立 task_id);workflow.py:1044-1075(批次末合并、build_key 幂等);map_candidate_locations.py:19;前端 Map*Panel 四个;assistant_map_tools.py:1182-1250(11 项操作,批量≤20 :92/:234/:1003);map_source_consumption.py:168-226(G8a);spatial_rescan.py;guided_flow/map_cold_start.py |
| M3–M4 World 空间简报/Evidence loader 与能力默认关闭/确定性提醒与修复预览/五题材评测骨架 | implemented | config.py:372-378(MAP_SPATIAL_ENABLED_CAPABILITIES 默认空);map_spatial_loader.py:26-90(经 DI 只读)、context_compiler.py:241-249;map_spatial_brief_service.py(3000 字/20 节点 brief_schemas.py:31/:44、check_knowledge_visibility :414-436);G8b confirmation_service.py:70-130(只省略不阻断)、snapshot_service.py:252-280;确定性提醒 map_spatial_advisory_service.py:153-186/:824/:569-608/:848;修复预览/静默 assistant/map_spatial_advisories.py:57-234;只读问答 evidence_tools.py:949/:1056-1084/:1096-1117/:1208-1212;assistant.turn 开关 service.py:647-652;forecast.py:43/:154/:355-368;评测骨架 evals/map_spatial.py:27-36/:185-199/:282/:401-407(诚实 not_run/human_validated=false);ADR 状态行与 FULL-SCOPE-ACCEPTANCE.md:12-14 如实标注 |
| M5 势力(应 deferred,代码不得假装提供领地图层) | deferred | grep backend/modules/world/map_*.py 无 territory/faction 引用(仅词表 kind 字面量,ADR-0035 §6 允许);profiles.py diff 为空、旧字段原样保留未读取;forecast.py:166 明示"当前没有势力边界资料,因此不判断接壤冲突机会" |

### 3.2 docs/plans/2026-10-15-world-object-dossier-and-scene-director.md(对象档案/场景导演/写作副驾驶,ADR-0039/0040/0041)

小结:C0、C2–C5 与计划及 ADR 契约总体一致且证据扎实;C1 如实未启动、代码无假装;深度导入入口按计划明示保留未替换。发现 2 处 ADR 偏离:①场景导演缺 ADR-0040 承诺的默认关闭总开关(M18);②"连续推进 N 轮"未实现且未声明延后(L25)。未发现 novel_id 隔离或安全违规。

| 里程碑 | 状态 | 证据(要点)|
|---|---|---|
| C0 档案分层/开放面向/统一接口/旧接口写回 | implemented | models/dossier.py:26-160(core/project、六类 source、可见性、状态、锚点);dossier_service.py:1946-2030(同值不改 :1971-1972、异值收拢+superseded :1982-1983+2009-2030)、:126-139(LEGACY_CHARACTER_FACINGS);character_service.py:240-258(409 编辑基线+model_fields_set);统一读取 object_dossier_brief.py:1-22(三个只读 DI 键);validity_policy.py + object_dossier_settings.py:34(allow_story_override 默认 False);三个迁移;前端 WorldObjectDossierEditor.vue |
| C1 演化对象档案发现/台账扩类/采用到档案/人物时间线 | missing | optional_steps.py:24-49 仍只有 details/spatial;grep 喜好表现/能力展现/价值取向/关系态度及"采用到档案"在 evolution、world 零命中;continuity/fact_timeline.py 为章节事实只读投影、非人物时间线;声明与代码一致,无假装实现 |
| C2 对象简报/参考维度/人物卡v2/反应v2/能力开关 | implemented | object_dossier_brief.py(993 行)+object_dossier_loader.py;policies.py:100-102(三维且省略走 advisory_omitted,scope.py:463/:563);story/schemas.py:127-163(人物卡 v2,v1 可读)/:625-666(反应 v2,2-4 performances+动机去重);config.py:379-391(默认空元组);capabilities.json 注册 character_response.v2 default_enabled=false |
| C3 七类统一提醒/只读结构缺项/短期双前瞻v2/人物弧版本化计划 | implemented | notice_source_registry.py:50-67(纯数据规格);notices_api.py(require_active_project+Scene 归属);migration 20261015_notice_dispositions + notice_service.py(CAS/row_version/mute);story/notice_sources.py(结构缺项后端化)+sceneAlerts.js 整文件删除(249 行全删);forecast/character_response.py:109-315;character_arcs/schemas.py:20-96(版本化);reading_notice_sources.py(553 行);深度导入按钮保留(WritingView.vue:101,计划§7.2)|
| C4 simulation_v3 统一/有限结算/表演卡素材角度/历史树/RP 迁移边界 | implemented | simulation_v3.py:13-60(typed 引用禁自由文本);state_trial.py:322-329;旧协议停止新建 api.py:511-514 与 rehearsals.py:98-101(409);Interaction 保留 observation_v2 为迁移期唯一新建入口(simulation.py:100-170,与 ADR-0040 §3 一致);director_schemas.py:204-321(表演卡/素材/角度)、:64(发散度默认 balanced);director_service.py:465-520(30 天恢复、仅作者删除);service.py:1161-1203(参考剧本不进 story 依据);director_candidate_transfer.py:142(转 World 候选不自动建对象);cliche_phrases 反同质化 director_tasks.py:422/1110/1506;director_reference 默认关闭 |
| C5 离场候选推演/阅读计数/同根恢复/Scene0 入口 Worker | implemented | world_progression_engine.py:10-60(确定性交汇检测,typed ID);schemas.py:169-200(mode/step_length/run_policy);WorldProgressionPanel.vue:34/:867(参与者默认 12 前端默认、可增减,schema min_length=1);world_progression_budget.py:84/:150(80% 停、只记计费状态不估金额);migration 20261016_wp_read_count;world_progression_api.py:504-593(同根恢复+未知计费显式确认)、:81-87(总开关默认关)、:737-767(历史仅作者删除);evolution/store.py:535-538(同事务 outbox)→ bootstrap.py:405-416 → world_progression_continuous_tasks.py:13-22 |
| 关键裁定对账(参与者12/单轮/历史保留/发散度/聚合归属/旧协议下线/倾向开关/省略不阻断/作者有效期默认优先) | implemented | WorldProgressionPanel.vue:867/:34;api.py:520-522(单轮);director_service.py:465-520 与 world_progression_api.py:737-767(软删+30 天、无自动清理);director_schemas.py:64;notice_source_registry.py 组合根物化 + check_module_imports.py:102(assistant 冻结出边不变);api.py:511-514 + simulation.py:166(RP 保留 observation_v2 待评测门禁);policies.py:175 + config.py 开关默认关;scope.py:163-164/:463/:563(省略不阻断);ADR-0031 依赖表已补 evidence↔evolution(docs/adr/0031:58)|

### 3.3 docs/plans/2026-10-15-world-object-dossier-c0-mapping.md(C0 映射,ADR-0039)

小结:计划主体落地且与代码高度一致;C2 消费端表七行"当前接入与边界"逐行与代码相符(含 assistant.turn"不能算已消费"的诚实边界);数据库唯一索引保证条目组单当前修订;ADR-0031 依赖表已补登记。计划文档自曝的两处缺口在代码中均已修复(时点证明已绑定 fact.field==generic_profile_field_key;config.py 已有开关字段及 env 解析),故不记 plan-gap,但文档两处陈述过时,记 docs/low(L26)。发现 1 个 medium 行为缺陷:人物合并不同步 dossier(见 4.2 M19)。

| 里程碑 | 状态 | 证据(要点)|
|---|---|---|
| Character 旧字段映射表(修订不重复/null 清除/expected_updated_at 409/聚合排序/desire_fear 双键) | implemented | dossier_service.py:126-138(11 项与计划表逐一相符)、:1971(同值不建修订)、:1984-2008(null 清除 status=cleared)、:1982-1983/:2010-2030(superseded+新修订)、dossier_repository.py:188-195(五键稳定排序)、:2071-2073(只聚合显式 legacy_field_key)、:2032-2052(behavior_rules 按项合并)、:130-131(desire/fear 双旧键共享面向)、character_service.py:270(model_fields_set)|
| expected_updated_at 行锁与 409(缺失/过期) | implemented | api/characters.py:76-83(require_edit_baseline);character_service.py:242-255(get_for_update 行锁+assert_edit_baseline);common.py:121-141(缺失/过期均 409)|
| Generic data_json 桥接(模板 key/facing 唯一才映射、legacy_unmapped、CAS 可选、exclude_unset) | implemented | dossier_service.py:1247-1284(len(matches)!=1 不映射)、:232(legacy_unmapped)、:1370-1376(未知值 secret);profile_service.py:311-320 与 dossier_service.py:1298-1305(CAS 可选)、upsert_profile:76(恒行锁);:1306-1309/:1339-1342(null 清除);profile_service.py:359-361(GET 只读投影);object_dossier_brief.py:499-541(时点证明门槛仅 legacy_import)|
| C2 消费端表:object-dossier-brief HTTP+Assistant 双入口(R0 只读/free/无 apply) | implemented | compilation/api.py:168-193(require_active_project);assistant_dossier_tools.py:97-125(R0/fee_category=free/read_only/无 apply);operation_api.py:283-297 |
| C2 消费端表:story.character_card.generate(卡片 v2、独立默认关闭参考开关) | implemented | object_dossier_loader.py:20;story/generation.py:313-317(只返回 interpretations、只可用输入 ID);loader :33-37/:124-127(默认空集关闭)|
| C2 消费端表:story.reaction.generate(reaction v2、2–4 表演卡、仅预览) | implemented | loader:21;generation.py:364-429(:390 每人物 2-4 performances、:421-428 范围校验);tasks.py:734(schema_version=story.reaction.v2);_govern_preview 无写入 |
| C2 消费端表:story.script.generate 能力映射与确认用途解析 | implemented | loader:24→story.script;confirmation_service.py:916-927(用途服务端解析、不匹配 400);contracts.py:131(consumer_action 仅内部参数);schemas.py:447(留痕响应非确认字段)|
| C2 消费端表:world.ask 对象档案+空间参考按开关加载 | implemented | loader:24 与 map_spatial_loader.py:18(均登记 world.ask);loader :117-127(默认空集关闭)|
| C2 消费端表:assistant.turn 仅识别未消费的边界 | implemented | loader:25(识别);grep consumer_action 于 assistant/service.py 零命中;operation_api.py:283-297 仅工具直调、非 context compile 消费;与计划"目前不能算已消费"一致 |
| C2 消费端表:writing.* 与 story.one_click.simulate 既有映射保留 | implemented | loader:16-19/:23(保留既有映射);simulation.py:114-120(protocol=simulation_v3);grep simulation_v2 于 modules/story 无残留 |
| 22 个 current_* 文件处置抽查(实查 12 个) | partial | 抽查 12 个与处置相符:context_compiler.py:52-57/:250-259(标注"非本场时点真源")、p20_context.py:650-651、repositories.py:2317-2331/:2351-2353、entity_revision_service.py:333/scene_projection.py:1052/entity_fusion.py:391/rp_long_memory.py:571(同名局部变量非消费者)、entity_baselines.py:43-44、contracts.py:338-340、planning.py:337-344、前端 useStorySceneWorkspace.js:444-446、WorldEntityDetail.vue:56-57。例外:dedup_service.py 处置声明"经 Character 档案写回"未实现(转入发现 M19);其余 10 个未抽查 |
| 文档自曝缺口 1:字段级时点证明未绑定 fact.field 与 Generic 字段 key | implemented(代码已修复;文档陈述过时,记 docs/low L26) | object_dossier_brief.py:82(`fact.get("field") == field_key`,:511-519 取自 source_metadata.generic_profile_field_key);git diff 确认为分支新增;计划文档 :29 仍称"尚未绑定" |
| 文档自曝缺口 2:core.config 缺 OBJECT_DOSSIER/CHARACTER_PATTERN 能力开关设置 | implemented(代码已修复;文档陈述过时,记 docs/low L26) | config.py:379-389(两个 tuple 字段+逗号分隔 env 解析,默认空);loader:35-36 实际消费;git diff 确认分支新增;计划文档 :44 仍称"本批没有修改配置层" |
| ADR-0039 关键契约:能力开关默认关闭、参考维度省略单独披露、依赖表登记 | implemented | loader:33-37(默认空集);object_dossier_brief.py:428-458/:496-549(omissions 逐条累计、继续不阻断);docs/adr/0031:56-58(三个只读 DI 键登记)、bootstrap.py:529-535、service_keys.py:92-101;models/dossier.py:109-116(部分唯一索引 uq_world_dossier_active_group)、:65-93(novel_id 进全部唯一键与 FK)|
| C1 Evolution 档案发现延后(不得假装实现) | deferred | grep dossier_discovery/对象档案发现/object_dossier_discovery 于 modules/evolution 零命中;与计划 :90"只能经 World 候选/修订预览入口写入"及执行记录"C1 还未启动整批"一致 |

### 3.4 docs/plans/2026-10-15-agent-operation-surface.md(AI 操作目录/目标运行/操作留痕,ADR-0038)

小结:A0–A4 与计划及 ADR-0038 契约一致、五个里程碑均 implemented;A4 的数周真实使用数据与真实 Top3 代码化未完成属任务声明的既定边界,报告侧以 not_measurable/partial 覆盖状态如实标注、未以合成样本冒充。四项关键契约点单独核对符合:参考维度省略单独记录不阻断、草图增量优先(assistant_map_tools.py:663 只审 status==candidate)、能力开关默认关闭(config.py:368-383)、simulation_v3 统一(RP 侧保留 rehearsal_v1/observation_v2 待独立评测)。安全面抽查(owner 过滤、demo 拒绝、留痕脱敏、novel_id 隔离)未发现越权或跨项目泄漏。两条 low 发现(L27、L28)。

| 里程碑 | 状态 | 证据(要点)|
|---|---|---|
| A0 纯SPEC目录/路由关联/真实HTTP留痕/隐私与保留期 | implemented | registry(app/assistant_operation_registry.py):102-137(缺 v2 字段失败关闭)、:318-357(R0-R4/费用/事务/留痕校验);HTTP 留痕 adapter app/main.py:884-1414(生命周期事件/保存点/incomplete 响应头);棘轮 test_assistant_operation_route_ratchet.py:187-219(446 条豁免只减不增);隐私 operation_trace_service.py:123-160(形状/长度/盐 HMAC/分桶)、保留期 :520-521(180 天)+归档接入 schedule_due;开关 :533-543(本地默认开/公开默认关);find/describe operations.py:279-362(目录 hash 不匹配即隐藏)|
| A1 第一波89项目录与主要领域入口/章节重排/事实时间线 | implemented | 目录共 142 项(A1 波次 15 项→v8=89→经 C0/C2/C4/C5 增至 142,每版有 v8~v17 冻结隔离测试);operation_api.py:56-83(require_active_project+schema 校验+expected_preview_hash 防 TOCTOU);chapter_order_operations.py:135-167(writing.chapter.reorder R3+restore)→ writing/facade.py:75-117、writing/api.py:145-218;continuity/operations.py:38-69(story.fact_timeline.read R0)+独立 HTTP 测试 |
| A2 目标DAG/范围冻结/分级确认/同根计量/恢复与漂移 | implemented | migration 20261016_assistant_goal_runs.py(mode=goal+部分唯一索引);planning.py:18/:96-127/:76-93(MAX_PLAN_STEPS=30、拓扑无环、禁 $eval/$each)、:213-279(compare_scope 确定性判定扩大)、:338-341(uuid5);service.py:2619-2633(_step_is_manual:R4/R3 恒停,R2 仅 auto_r2+白名单+恢复支持)、:1166-1195(80% 停点+unknown_charge)、:3270-3314(指纹漂移 fail-closed)、:2684-2960(多阶段按领域回执对账)、:3926-3990(逐项 CAS 恢复);GoalWorkflowCounter :127-203(同根计量);config.py:293-294(默认 False+项目 allowlist);service.py:293-305(owner 匹配+demo 拒绝)|
| A3 作者操作/摘要worker/Collab原子 | implemented | interaction/author_operations.py 6 项(summary.refresh 声明 R4/possible_model_charge/单独确认 :810-830);collaboration/assistant_tools.py 6 项(atomic_adopt 经 author_operations_api.py:258-301 绑定 op_id);合计 12 项=test:519-533;真实摘要 worker interaction/tasks.py:30-54 + author_operations.py:355-620;author_api.py:41(独占);旅程操作 author/consumer 双项目校验 :93-135(ADR-0018 边界)|
| A4 统计报表/边界序列/前向真实测量 | implemented | operation_trace_report.py:412-470(归档+实时合并、GET 只读)、:158-220(跨日恢复边界、uncertain 不重复计数)、:324-405(not_measurable/partial/measurable、不填 0、不把 executed 当作者接受);assistant/api.py:100-173(owner-only 聚合/导出,demo 拒绝);migration 20261016_operation_trace_reports.py;e2e test_operation_trace_report_postgres.py 多场景;数周真实数据/真实 Top3 代码化未完成属既定边界,未以合成样本冒充 |

## 4. 发现清单(按 severity 分组)

统计:共 51 条 —— high 1(verified)/ medium 22(19 verified + 3 unconfirmed)/ low 28(全 verified)。verified 共 48 条;verified 各条的复核结论均为"复核成立/独立复现",门禁两条为退出码判定(无需复核)。

### 4.1 high(1 条,verified)

| # | 位置 | 类别/分片 | 问题 | 证据 | 状态 |
|---|---|---|---|---|---|
| H1 | (门禁)后端全量测试 | test / gates | 门禁在当前 HEAD 失败(退出码 2) | FAILED `modules/imports/tests/test_scene_phase_refactor.py::test_codex_enrichment_admits_before_work_starts_and_keeps_every_scene`:`assert peak == 8` → `assert 2 == 8`;汇总 `1 failed, 9025 passed, 2 skipped, 2 warnings in 110.73s`;`make: *** [test] Error 1` | verified(退出码判定,无需复核) |

### 4.2 medium — verified(19 条)

| # | 位置 | 类别/分片 | 问题 | 证据(要点) | 状态 |
|---|---|---|---|---|---|
| M1 | (门禁) ruff | test / gates | 门禁 ruff 在当前 HEAD 失败 | 退出码 2(无输出) | verified |
| M2 | backend/modules/world/map_evaluation_read_service.py:161-177 | quality / world-map | 评测读取一次性无界拉取项目全部词条的全部修订(无 limit、evidence 场景过滤未下推 SQL),并对每个批次引用逐个调用内部会加载 200 个批次并逐图元解析实体的列表函数,长项目下显著变慢甚至超时 | :161-177 join 查询仅按 novel_id、:178-185 Python 端过滤;:118-120 逐 batch ref 调 list_map_auto_drafts(limit=1);map_auto_draft_service.py:2088-2098 每次拉 201 个批次、:2148-2150 逐条 _project_candidate_entities(:1132-1154 逐 feature 经 _resolve_merged_entity 逐条查询) | verified |
| M3 | backend/modules/world/dossier_service.py:2105 | bug / world-dossier | 编辑 legacy_field_key="role" 的档案条目时,dossier 侧 content 允许 20000 字符并直接回写 String(64) 的 Character.role 列,超 64 字符将在 PostgreSQL 触发 varchar 溢出使保存失败,无前置校验 | models/character.py:56-59(String(64));schemas/characters.py:118(max_length=64)vs schemas/dossier.py:74(20000);:2088+:2105 update_entry/restore_entry 路径 setattr 回写;_validate_legacy_field(:484-498)与 _updated_values(:1675-1712)均无长度校验;conftest.py:100 SQLite 不强制 varchar 长度故现有测试不暴露 | verified |
| M4 | backend/modules/world/dossier_service.py:2078 | bug / world-dossier | species/faction/location/rule/item/secret 六种内置类型的旧 profile 表经 migration 物化为 active 档案条目后,dossier 编辑的 _sync_legacy_storage 只回写 Character 与 CoreEntity 字段,旧 profile API 的 _upsert_strong 只桥接 generic 类型,同一字段在新档案读取接口与旧 profile 接口各持不收敛的当前值 | :2078-2122 仅两个分支;migration 20261015_object_dossier_v2.py:310-352/:385 写入表前缀形式 legacy_field_key('species_profiles.origin_summary' 等)不命中;profile_service.py:72-74 对 PROFILE_REGISTRY 走 _upsert_strong 只写旧表且为活跃读路径;character 侧有双向桥接而六种类型两方向均无 | verified |
| M5 | backend/modules/world/dossier_service.py:728 | plan-gap / world-dossier | C0 文档自曝的字段级时点证明缺口仍在:visible_contents 过滤只按 content 字符串全局匹配,未把 Story fact 的 field 与档案条目的 facing/legacy_field_key/Generic 字段 key 绑定,内容相同的其他字段条目会被一并放行进入角色视角简报 | :728-730 `entries=[row for row in entries if row.content in allowed]`(全 read() 内无 facing/legacy key 参与该过滤);object_dossier_brief.py:406-416 构造 visible_contents 只收集 fact["value"] 字符串;计划文档 :29 原文;两文件均为本分支新增 | verified |
| M6 | backend/modules/world/schemas/dossier_manifest.py:38 | contract / world-dossier | 档案清单(manifest)交换格式不携带 legacy_field_key 与条目 metadata:导出时 generic 桥接行的 generic_profile_field_key 元数据丢失、legacy_unmapped 行被 read() 移出 entries 后整体不导出,跨项目导入后旧 Character 字段投影与 Generic data_json 兼容读取拿不到迁移数据 | :38-69(extra=forbid,无相应字段);dossier_interchange.py:267-286(export 不带 metadata)/:705-724(apply 仅 dossier_manifest_import);dossier_service.py:721-727(移出 entries)、:916-925/:1017-1026(投影只读本地 data_json/extra_json) | verified |
| M7 | backend/modules/story/continuity/services.py:997 | bug / story-continuity | 章节重排 apply 只把快照/checkpoint 置 stale,不重映射也不失效 MemoryEvent.chapter_index;get_panorama/_apply_events_in_range/list_events 按存储的旧章节号区间重放、无 receipt 换算,重排后到手动 rebuild 前按新章节号查询会混入旧编号≤N 的事件、漏掉旧编号>N 但新编号≤N 的事件,capture_snapshot 会把混合结果固化为 current 快照 | chapter_order.py:1176-1194(仅置 stale,事件仅作统计/指纹从不写入);services.py:991-1012/:1244-1258/:1094-1125 直接按存储 chapter_index 查询;对照 fact_timeline.py:350-374 显式换算;writing/draft_service.py:1645-1655 confirm 后无事件重建 | verified |
| M8 | backend/modules/assistant/forecast_notice_source.py:152 | bug / assistant-notices | decide_forecast_notice 对本源自生成的 more 卡(无 disposition_ref.candidate_id)执行 UUID(str(None)) 抛未捕获 ValueError,处置接口返回 500 而非 409/422;GET 拿卡后 POST /dispositions 即可复现 | :110 more 卡无 disposition_ref(正常卡 :96-100 有);notice_service.py:270-282(空 reference 使预检通过)、:291-294(无 try/except);复核实测 python3 抛 "badly formed hexadecimal UUID string",经 notices_api.py:63-65 直通全局 handler 返回 500;三文件均为本分支新增 | verified |
| M9 | backend/modules/assistant/goal_runs/service.py:3522 | plan-gap / assistant-operations | 多阶段步骤进入 outcome_unknown 后目标运行没有任何作者核对/解除动作,唯一出路是取消整个目标;uq_assistant_goal_run_active 部分唯一索引覆盖 waiting_approval,取消前同项目无法新建目标;计划 §6 要求"停下请示作者…在已授权范围和预算内重新规划",停下已实现、请示后的作者决定入口缺失 | _record_step_failure :2638-2655(调用点 2748/2809/2845/2860/2908/2945);replan :3522-3526(另 :2254/:2271)、advance :3429-3433、resume :3565-3569(仅 paused/budget_80)全部阻断;api.py 全部路由与前端 api/assistant.js:77-89 无核对动作;models.py:82-88 唯一索引 | verified |
| M10 | backend/modules/evidence/compilation/knowledge/scope.py:45 | contract / evidence | 知识治理 v2 的 advisory(参考维度)契约对 object_dossier/character_pattern 失效:两维度未登记进 SECTION_DIMENSION_MAP,预算逐出条目反查维度为空进 omitted_unknown_keys → 并入 blocking 写入 receipt.omitted 并使 scope_complete=False(可阻断生成),违反 compilation README 明文承诺"参考维度省略单列 advisory_omitted,不进入 omitted,不影响 scope_complete 或 require_scope_complete" | :45-47 仅新增 map_spatial/director_reference;policies.py:175 声明 _OBJECT_REFERENCE_ADVISORY 并写入 writing.generate 等能力;复核以内存构造运行 build_scope_receipt 复现(两维度逐出→blocking→scope_complete=False/require 抛 KnowledgeContractError;map_spatial 对照通过);test_scope.py:133-233 advisory 用例仅覆盖 map_spatial | verified |
| M11 | frontend-console/vue/views/scene/sceneRuntimeSession.js:129 | bug / fe-writing | v2 reaction 序列化字段大幅扩张(实测顶层 7 个+selectedPerformance 内 8 个 slice(0,12000) 字段)且条数上限 24→96,256KB 草稿预算更易超限;超限时 serializedDraftWithinLimit 直接以 reactions:[] 降级写盘且 persistSceneRuntimeDraft 仍置 backupComplete=true,刷新后全部 reaction 及保留/拒绝决定静默丢失、界面仍显示已备份 | :128-129(上限 96);:146-172(v2 分支,分支新增);:192-202(超限整组清空);:266-269(降级写盘仍置 true);readStoredDraft :82(硬编码 true);基线 git show origin/main 同文件为 24 条且无 v2 大字段 | verified |
| M12 | frontend-console/vue/views/outline/components/WorldProgressionPanel.vue:1415 | bug / fe-world | previewHook 的 finally 中被错误嵌入一整段场景导演草稿(directorDraft)重置代码,任何"钩子预览"完成都会静默清空作者已打开的场景导演草稿(含手输起点假设文本与已生成的预算预览),与该草稿是否属于当前钩子无关 | :1412-1425(7-8 行 directorDraft 重置换与上下文脱节);directorDraft 唯一填充点 openDirectorDraft :1528-1533;模板 :385 v-if="directorDraft.key" 渲染整节(:391 maxlength=3000 textarea、:398-401 预算预览);文件全为新增行 | verified |
| M13 | frontend-console/vue/views/world/library/WorldEntityDetail.vue:324 | bug / fe-world | 对象档案 details 折叠或切换实体时经 v-if 直接卸载 WorldObjectDossierEditor,编辑中的档案条目/模板草稿(上限 20000 字)无确认、无本地持久化即被静默丢弃;dirty 信号只接到路由离开守卫 | :324-329(@toggle 直写 worldDossierOpen)、:235-236(切实体 watch 直接置 false、无 getConfirm);Editor :639 onBeforeUnmount 仅 emit("dirty", false)、草稿全为组件内存态(grep 无 localStorage);dirty 仅经 WorldBibleTab.vue:901-904 setExternalLeaveGuard 接路由守卫,不拦 details 折叠 | verified |
| M14 | docs/modules/20_assistant.md:124 | docs / docs-task | 权威模块文档称章节重排与一般事实时间线"尚无安全领域写入服务,不属于本首批闭环",但同分支操作注册表已物化 writing.chapter.reorder(R3、prepare/apply 真实领域写入)与 story.fact_timeline.read 并进入留痕装配;同文件 :108 仍称"新作者运行冻结为 v11",与 assistant/README.md:128 的 v16 及任务记录 v17 矛盾 | registry :375/:399;chapter_order_operations.py:134-166(经 modules.writing.facade preview/confirm 真实写入)+migration 20261016_chapter_order_timeline.py;FULL-SCOPE-ACCEPTANCE.md A1 行声明完成;grep 全文无更正段落 | verified |
| M15 | docs/modules/20_assistant.md:22 | docs / docs-task | 统一提醒 provider 清单与代码矛盾:文档仅列 5 个 registry providers 并称编辑员意见、地图空间/对象一致性/世界推进等"仍需后续接入",组合根实际登记 11 个来源 | notice_source_registry.py:50-61 登记 11 个(assistant.editorial:13、world.object_validity:26、story.world_progression:42、story.scene_director:14、world.map_source:16、evolution.reading:21 等);bootstrap.py:252/:525 装配;notice_service.py:36-39 消费 | verified |
| M16 | backend/app/main.py:884 | contract / docs-task | 组合根 app/main.py 内嵌约 600 行操作留痕业务编排(撤销回执的 SQL 匹配与事件写入、终态事件策略、call_id 指纹派生、响应头标记、幂等重放判定),违反仓库"组合根禁业务判断/app.main 仅限路由注册"的明文规则 | :884-1417(record_reversal :913-1009 含 select+LIKE 匹配与 restored 事件写入、uuid5 call_id :1124-1129、终态判定 :1169-1262、响应头 :1306-1313;:207 与 :1417 双重安装);diff 新增 608 行而 origin/main 无 operation_trace 引用;development-guide.md:331 与 AGENTS.md 原文 | verified |
| M17 | docs/prompts/Prompt体系设计.md:767 | docs / docs-task | 权威 Prompt 清单未收录本分支三个新生产 LLM 调用能力 story.scene_director、story.world_progression、assistant.goal.plan(本分支仅补 evolution details/spatial 四行) | capability_bindings.py:112-113/:184 登记;director_tasks.py:878/:1615、world_progression_tasks.py:12-23、goal_runs/service.py:1271-1349 均含 LLMCallRequest+open_project_snapshot_llm_client 真实调用;899 行文档 grep 三关键词及表演卡/参考剧本零匹配;documentation-maintenance.md:88 与 architecture-documents.toml:44 同步要求 | verified |
| M18 | backend/app/main.py:784 | plan-gap / 对账·档案与导演 | ADR-0040"后果"节承诺的导演总开关 STORY_SCENE_DIRECTOR_ENABLED(默认关闭、经评测后开启)不存在,导演 API 无条件挂载且操作目录注册为可执行,与同分支其他新能力均有默认关闭门禁的做法不一致 | grep backend/ 该变量零命中(仅任务类型常量 STORY_SCENE_DIRECTOR_TASK);main.py:820 无条件 include_router(784 为 import 行);director_api.py(992 行)与 director_operations.py:416+ 无任何 enabled/503 门禁;对照 world_progression_api.py:81-87 读 STORY_WORLD_PROGRESSION_ENABLED 默认 false 并 503 | verified |
| M19 | backend/modules/world/services/core/dedup_service.py:754 | bug / 对账·C0映射 | 人物合并只经 CharacterRepository.update 写旧列、未同步 dossier 档案条目,而人物读取(GET/list/context)被 dossier active 条目覆盖,合并后的字段值在作者读取视角被合并前的旧档案值遮蔽,与计划处置"保留旧字段合并并经 Character 档案写回"不符 | :712-795 仅 CharacterRepository.update(repositories.py:2304,无 dossier 逻辑)且全文 grep dossier 零命中;读取路径 character_service.py:126/:228/:298-304/:370-397 均被 legacy_character_values(dossier_service.py:2054,仅取 active)覆盖;仅 CharacterService.update(:264-274)调 sync_character_legacy_field,合并入口 entity_facade.py:398-406 不经过 | verified |

### 4.3 medium — unconfirmed(3 条,复核均未通过)

以下 3 条为分片/对账提出的原始发现,输入中的复核结论均为"复核未通过"(核心指控被推翻)。按规则保持 **unconfirmed** 标注;原始指控与推翻理由一并列出,是否仍需关注由仓库主人裁定。

| # | 位置 | 类别/分片 | 原始问题 | 复核结论(未通过的理由) | 状态 |
|---|---|---|---|---|---|
| U1 | backend/modules/assistant/operations.py:1026 | bug / 横切契约与安全 | 批量确认写路径中宽泛 except Exception 把非 DomainError 意外故障降级为"资料或操作条件已变化"用户消息、不记录原始异常、循环继续处理,掩盖真实故障 | 复核未通过::1026-1052 中非 multi_stage 路径在 _record_batch_event 后于 :1052 裸 raise 重抛原始异常(不产生该用户消息、循环不继续;multi_stage 时 :1043 break),与 DomainError 分支并不相同,核心指控被该 raise 直接推翻 | unconfirmed |
| U2 | backend/modules/assistant/operations.py:1011 | bug / assistant-operations | 批次确认的 apply 失败路径把同一终态留痕事件(同 call_id、同 event_type)重复写两行,使所有者聚合报表失败/结果未知事件数翻倍 | 复核未通过:apply 调用被 :970 db.begin_nested() 业务 savepoint 包住,traced_apply 异常路径写入的终态行随 ROLLBACK TO SAVEPOINT 一并回滚(经项目 venv+内存 aiosqlite 等效结构实验证实),失败路径最终只落一行终态事件,不存在双写翻倍 | unconfirmed |
| U3 | backend/modules/writing/conflict_ai.py:322 | contract / 对账·地图增强 | 冲突检查 AI 审查重物化上下文时未传 consumer_action=writing.conflict_check.ai_review,空间简报实际跟随原生成的 writing.generate 开关,ADR-0037 §2 声明的该能力独立开关在此链路不可达 | 复核未通过:未传 consumer_action 属实,但后果推断错误——require_confirmation(confirmation_service.py:290-291)严格校验确认 action 必须是 writing.conflict_check.ai_review(不可能复用 writing.generate 的确认),该确认创建时 consumer_action=action(:187)经 :676 持久化,重物化后 loader 回退 options.consumer_action 拿到的正是 writing.conflict_check.ai_review,_ACTION_CAPABILITIES 映射可达(test_map_spatial_loader.py:193-237 已参数化覆盖);semantic_review 传 consumer_action 是因其复用 writing.generate 的确认,场景不同 | unconfirmed |

### 4.4 low(28 条,全部 verified)

| # | 位置 | 类别/分片 | 问题(要点) | 证据(要点) | 状态 |
|---|---|---|---|---|---|
| L1 | frontend-console/vue/components/CreativeExperiments.vue:43 | quality / 横切 | 作者确认文案直接展示内部能力标识 task_root_capability_id,违反"不暴露 raw ID"边界 | grep 全 vue 目录仅此一处;后端值为内部 slug "collaboration.run";本分支新增行 | verified |
| L2 | backend/modules/world/map_auto_draft_service.py:180-195 | quality / world-map | clue_ids 缺省时按 run_id+截止 Scene 全量选取空间线索且无行数上限(显式路径限 20_000),每条线索逐条 Scene span 与原文重验证,成本无界 | :181-195 无 limit;schemas :36 max_length=20_000;_validated_clue_inputs(:271-343)逐行重验证(内含逐 range read_manuscript_range 原文重读) | verified |
| L3 | backend/modules/world/services/core/entity_relation_service.py:1349 | bug / world-core | create/create_or_merge 强制"待复核关系不能声明作者有效期"(status 须 canonical),update/review_edit 只校验 Scene 锚点不校验 status,待复核关系可经 PUT 绕过该不变量 | :360-364/:411-414 有校验 vs :1349-1350/:1438-1439 无;repositories.py:1822-1838 仅 validity 在 fields_set 时改写,单传 status='candidate' 可保留有效期 | verified |
| L4 | backend/modules/world/repositories.py:2317 | quality / world-core | CharacterRepository.update 语义从"仅非 None 才写入"改为"显式提交即写入(可置空)",依赖调用方控制 model_fields_set,误传 None 清空字段的风险面扩大;现有调用方逐一检查暂无行为回归(唯一差异为 ensure_for_core_entity 在 auto_materialized=True 分支的 secret 清空) | diff 原文(model_fields_set+clearable_fields、aliases/behavior_rules/meta 显式置空);调用方逐一复核(character_service.py:349-360、dedup_service.py:757+common.py:73-83、author_migration.py:1203 等) | verified |
| L5 | backend/modules/story/director_api.py:785-786 | bug / story-director | 作者删除导演分支接口加锁顺序先 branch 后 root,与 worker handle_scene_director 的 root→branch 相反,同一聚合 AB-BA 死锁窗口,并发时一方事务被中止(请求 500 或任务失败) | director_tasks.py:165-166(root→branch);其余路径(:834-847、:342)均 root 在前;lock=True 即 with_for_update;两文件均本分支新增 | verified |
| L6 | backend/modules/story/director_operations.py:240-246 | quality / story-director | _apply_advance 未像 _apply_start(:115)/_apply_continue(:200) 在 apply 内复核 require_active_project,依赖"先 prepare 后 apply"框架约定;当前不可达越权,属防御深度缺口 | operation_api.py:67/:71/:74 与 operations.py:918-928 均先 prepare;continue_director_root 写入前也补跑校验 | verified |
| L7 | backend/modules/story/director_notice_sources.py:1-6 | docs / story-director | 模块 docstring 称应用注册表尚未接入该提醒来源、集成留待 C4b 交接,与组合根已导入并注册矛盾 | notice_source_registry.py:16 已导入 NOTICE_SOURCE_SPEC、:55 已列入 _specs | verified |
| L8 | backend/modules/story/character_arcs/service.py:157 | test / story-continuity | save/restore/archive/unarchive 依赖的 _lock_character_plan 直接执行 pg_advisory_xact_lock 原生 SQL 无 postgresql 方言守卫,标准 SQLite 单测无法覆盖该写路径,现有覆盖仅在 PG e2e | :155-160 无方言判断;对照 chapter_order.py:242-244 与 continuity/repositories.py:125-126 守卫惯例;conftest.py:100 sqlite 内存库;写路径仅 tests/e2e/test_character_arc_plan_persistence.py 覆盖 | verified |
| L9 | backend/modules/assistant/evidence_tools.py:223 | quality / assistant-notices | 用户可见错误消息使用繁体"確認後地圖參考已變化,請重新讀取後再引用",与同文件相邻分支及全库简体文案不一致 | :223 繁体 vs :244 相邻同码分支简体;全 backend 繁体特征文案仅此一处;两条均为新增 | verified |
| L10 | backend/modules/evolution/spatial_rescan.py:593-599 | bug / evolution | task 处理器在 try 块外用无默认值 next() 取补扫登记,run 缺失或 spatial_rescans 无该 operation 时以 AttributeError/StopIteration 裸崩,且发生在 _status("running") 与异常处理块之前,无法进入 needs_reconciliation 分支 | :593 load_run 无 None 检查、:594-598 next() 无 default,均在 :599/_status 与 :600 try 之前(except 在 :624-636);同文件 resume/start 同类查找均带 default | verified |
| L11 | backend/modules/evolution/notice_sources.py:193-270 | security / evolution | list_map_source_notices 函数体内未做项目 owner 校验,与同注册表 reading_notice_sources(函数内 require_active_project)约定不一致,仅依赖外层 API/处置入口先行校验,新增直接调用方时有绕过纵深防御的缝;函数内查询均带 novel_id 过滤 | :193-270 无校验;对照 reading_notice_sources.py:450-454;现有生产调用仅经 notices_api.py:53 等先行校验 | verified |
| L12 | backend/modules/evolution/store.py:537-542 | quality / evolution | 回执同事务 outbox 的 DI 缺失被 except KeyError: pass 静默吞掉,生产组合漏注册该 key 时 world progression 读核对将无痕迹永不入队,与模块 fail-closed 自声明不一致 | :537-542(注释"Isolated Evolution unit tests…");对照 spatial.py:809-819 同类缺失显式记录缺口;bootstrap.py:413-417 已注册故当前生产正常 | verified |
| L13 | backend/modules/imports/spreadsheet_migration/planning.py:360-370 | quality / other-backend | 无行内类型列时 entity_type 直接取 default_entity_type(未归一化),而档案列一致性检查用 dossier_profile_type.strip().lower() 比较,两个作者自由输入字段仅大小写/空白不同即误报 migration_dossier_profile_type_mismatch 拒绝迁移(直接调 API 可复现;官方前端会预归一化) | :354-366;schemas 两字段无一致性校验且全链路原样透传;复现 default='Concept'/dossier='concept' 即抛错 | verified |
| L14 | backend/alembic/versions/20261015_operation_trace_v2.py:4 | docs / schema-infra | docstring "Revises: 20261015_map_node_merge" 与实际 down_revision="20261015_object_dossier_v2" 不一致,误导迁移链人工排查(alembic 以代码为准不受影响) | 文件 :4 vs :15;脚本解析全部 124 个迁移确认单链(map_node_merge→notice_dispositions→object_dossier_v2→operation_trace_v2)、唯一 head、无缺失引用 | verified |
| L15 | backend/conftest.py:24 | test / schema-infra | 新增布尔开关 ASSISTANT_OPERATION_TRACE_ENABLED(代码默认 true)未按 conftest 自身"新增布尔开关须同步此处"规则钉住,与"布尔开关一律按 false 运行"策略相悖;本机 .env 设 false 时守护用例会条件性失败(当前机器 .env 无该键,属条件性失败路径) | config.py:307-308(default True,分支新增);conftest.py:22 注释与 23-53 清单无该键;test_config.py:107-114 判定逻辑 | verified |
| L16 | backend/tests/e2e/test_unified_notices_composition_postgres.py:246 | test / be-tests-e2e | 测试自建 BOOTSTRAP 账号后于 finally 硬删,Account 删除经 owner_id 外键 ondelete=CASCADE 级联删除库中所有属主项目;当前 make test-e2e 串行不触发,按仓库惯例追加 -n 并行跑 e2e 时存在跨测试级联删数据竞态 | :50-54/:246-250;models.py:40-47 与迁移确认 CASCADE;Makefile test-e2e 无 -n 但 ARGS 可透传(发现称 test 目标带 -n 实为 test-fast-coverage);其余 9+ e2e 文件共享同一账号;未实际并行复现(只读约定) | verified |
| L17 | backend/tests/e2e/test_operation_trace_report_postgres.py:394 | test / be-tests-e2e | 归档与读并发场景用固定 asyncio.sleep(0.1) 代替事件同步,慢环境下读可能未真正与持锁归档事务重叠,"读不阻塞、不双计数"的并发验证意图覆盖不充分(断言本身不假) | :392-394(lock_taken.wait 后 create_task+固定 sleep);:400-401 断言计数;无事件或断言保证读查询在 allow_commit.set() 前发起 | verified |
| L18 | backend/evals/tests/test_map_spatial_guard.py:63-90 | test / be-tests-unit | binding_fixture 以 monkeypatch.setenv(ASSISTANT_ENABLED=true、LLM_MODEL_LIMITS_JSON)+get_settings.cache_clear() 修改进程级配置且无 teardown 清缓存,同进程后续依赖 get_settings() 的测试可能读到污染值(ASSISTANT_ENABLED=true、被改写模型并发限额) | :63-67;map_spatial.py:638 经 get_settings 读配置且 core/config.py:654 为 @lru_cache;conftest 无统一清理;13 处调用方无出口清理;对照 test_map_spatial_control.py:358/:372 双 clear 模式;origin/main 无此用法 | verified |
| L19 | frontend-console/vue/views/scene/SceneDirectorPanel.vue:737 | bug / fe-writing | previewContinue 在 parentRoundId 对应回合不存在(草稿从 sessionStorage 恢复后历史加载失败或回合已删除)时 branch 为 undefined → branch.root_id 抛 TypeError,catch 把英文异常消息当错误提示展示 | :729-737;canPreviewContinuation(:395-397)只校验非空;restoreDraft(:432-449)从 sessionStorage 恢复 parentRoundId;context 切换 watch 先恢复草稿再异步加载 history,触发路径可达 | verified |
| L20 | frontend-console/vue/views/writing/components/ObjectDossierPanel.vue:510 | quality / fe-writing | 对象名称缺失时以 UUID 前 8 位作用户标识("对象 ab12cd34"/"Scene ab12cd34"),与其他面板不暴露内部 ID 的展示约定不一致 | :510 shortId;:45/:83 名称缺失时渲染;:520-521 validityLabel 无条件输出;对照同 diff 新增 OutlineFloat.test.js 有 not.toContain(id) 断言 | verified |
| L21 | frontend-console/vue/views/map/mapStructureEditor.js:35 | quality / fe-world | 地图候选采用前必读的变更明细把"固定项目类型"显示为"词条 <term_id> · 修订 <revision_id>"、"生效范围"显示为"场景 <scene_id>"(均为完整裸 UUID),违反"不暴露 raw ID"约定 | :35-36 拼接 type_ref/type_revision_id/effective.start.id(后端为 UUID,无截断);:94/:97/:106/:109/:112 推入 fields;MapStructureEditor.vue:60 MapChangeReview 渲染 | verified |
| L22 | frontend-console/vue/views/world/components/WorldAliasesTab.vue:227 | quality / fe-world | 别名总表"作者有效期"列对所有设有效期别名显示"场景/章节 <截断UUID>",不做名称解析;同模式也在 WorldEntityRevisionHistory 的 aliasValidityLabel | :227-235;WorldEntityRevisionHistory.vue:259-267;两文件均无场景/章节列表解析(对照 WorldObjectDossierEditor.vue:627 先解析名称的先例) | verified |
| L23 | frontend-console/tests/vue/writing/UnifiedNoticesPanel.test.js:33 | test / fe-tests | 旧 sceneAlerts.test.js 的 stale 检测断言迁移不完整:UnifiedNoticesPanel.vue:314-316 的 item.stale → "依据已变化"渲染分支在全部分片测试中无直接断言 | 首例显式 stale:false 只断言另一分支;其余用例默认 stale:true 但未断言该文本;grep 仅 TeamProgress/TodayView(其他组件)断言该文本;被删 sceneAlerts.test.js 第 4 条用例原有该断言 | verified |
| L24 | docs/adr/README.md:54 | docs / docs-task | ADR-0037 索引行仍称"地图简报与能力接线未实施",与同分支 ADR 正文状态、模块文档及代码矛盾;ADR-0025:81 残留同一过期表述 | ADR-0037 正文"M3 工程切片已实现";docs/modules/08_evidence.md:575(已接入七/八项能力、默认关闭);map_spatial_loader.py:7/:71 实际消费 WORLD_READ_MAP_SPATIAL_BRIEF(bootstrap 已注册) | verified |
| L25 | backend/modules/story/api.py:520 | plan-gap / 对账·档案与导演 | ADR-0040 §2 承诺的"连续推进 N 轮"模式未实现且未在任何计划/任务记录中声明延后:入口固定单轮,rehearsal_rounds≠1 一律 409 | api.py:521-525 与 rehearsals.py:100-101(409"当前一次只提交一回合");director_schemas.py:133 rounds: Literal[1] 锁死单轮、全后端无 N 轮入口;ADR-0040 §2(第 70 行)明确承诺;C4-C5-HANDOFF.md:41 仍列为规格、FULL-SCOPE-ACCEPTANCE.md 未标未完成 | verified |
| L26 | docs/plans/2026-10-15-world-object-dossier-c0-mapping.md:29 | docs / 对账·C0映射 | 计划文档两处自曝缺口陈述与当前代码不符:文档称"尚未把 fact 的 field 与 Generic 字段 key 绑定""core.config 尚无这两个 tuple 设置字段……本批没有修改配置层",两处在 HEAD 81785cd16 均已实现,现状映射文档未更新 | object_dossier_brief.py:82(field 绑定已实现,:511-519);core/config.py:379-392(两 tuple 字段+env 解析已实现);git diff 确认均为分支新增 | verified |
| L27 | backend/modules/assistant/tests/test_goal_runs.py:247 | test / 对账·操作面 | 计划§9验收条目"越权测试:R3/R4 在任何配置下都不能自动执行"缺直接测试断言:goal 全部测试无 auto_r2=True 下 R3/R4(或白名单外 R2)步骤仍停审批的用例;_step_is_manual 无测试锁定 | grep 全 backend 仅 :247 一处 auto_r2=True(helper);全部 goal 测试(含 3 个 e2e 与 contracts)无相应断言;service.py:2619-2635(R4/R3 无条件 return True);细微偏差:手动步骤实际停在 phase=step_review+stop_code=step_approval | verified |
| L28 | backend/modules/assistant/goal_runs/service.py:120-123 | plan-gap / 对账·操作面 | 目标运行的 R2 自动执行只对 R2_RESTORE_OPERATIONS 白名单内 2 项操作(world.dossier.entry.edit、project.update_task)生效,开启 auto_r2 后其余 R2 操作仍逐步停确认;ADR-0038 §6 表述为开启后 R2 即可连续自动执行(保守方向收窄,与 ADR"自动执行的 R2 须可一键恢复"要求自洽) | :2629-2634(需同时满足 auto_r2+operation_id∈白名单);:116-119 注释明说有意收窄(每项须有具体领域恢复操作和 CAS 基线) | verified |

## 5. 未覆盖与风险

- **PostgreSQL critical 层未跑**:本机 PG 正在运行 R6 真实评测,为避免干扰本次未执行 PG critical 层测试。风险放大:多项发现仅在 PG 显现——M3(Character.role varchar(64) 溢出)现有 SQLite 测试不暴露;L8(character_arcs 写路径)仅 PG e2e 覆盖。
- **Playwright e2e 未跑**:需起服务,本次未执行。
- **真实模型评测与作者验收未完成,R6 评测进行中**:五题材评测骨架诚实保持 not_run/human_validated=false(backend/evals/map_spatial.py:185-199/:282/:401-407);ADR-0035/0036 状态行与 FULL-SCOPE-ACCEPTANCE.md:12-14 均如实标注;A4 的数周真实使用数据与真实 Top3 代码化未完成属任务声明既定边界。
- **性能未测**:全分支未做性能测试;且存在无界查询/成本类发现(M2 评测读取无界+逐图元解析、L2 线索全量逐条原文重验证)。
- **对账与分片审查均为只读**:按任务规定测试/构建/门禁由脚本统一执行,分片与计划小结中的测试质量评价均为读码结论、未复跑;门禁结果为脚本输出,非本汇总复跑。
- **计划声称的 390/1280 页面验证数字未核**:后端 e2e 分片声明不属其职责,未核也未冒充。
- **工作树尚有 4 项未提交**:评审结论锚定 HEAD 81785cd16 与工作树文件,输入未说明这 4 项的内容。

## 6. 建议后续动作(按优先级)

**P0(合并硬阻断,必须先做)**
1. 修复 ruff 门禁失败(退出码 2、无输出,需本地复跑定位具体违规)。
2. 修复后端全量测试失败:`modules/imports/tests/test_scene_phase_refactor.py::test_codex_enrichment_admits_before_work_starts_and_keeps_every_scene`(`assert 2 == 8`),并区分该失败为本分支新增还是基线问题。
3. 处理工作树 4 项未提交,明确去留。

**P1(建议合并前:数据正确性 / 作者数据不丢失 / 契约阻断)**
- M3:role 档案条目回写前按 String(64) 加长度校验(PG 上会溢出报错)。
- M4:六种 strong profile 类型补双向桥接或显式收敛策略,消除双写源不收敛。
- M19:人物合并同步 dossier 档案条目(或调整读取覆盖逻辑),消除合并值被旧档案遮蔽。
- M7:章节重排后重映射/失效 MemoryEvent 章节锚,阻止混合结果固化为 current 快照。
- M11 / M12 / M13:三处前端作者草稿静默丢失(v2 reactions 降级清空仍标已备份;钩子预览清空导演草稿;档案编辑器卸载丢草稿)。
- M8:forecast more 卡处置 500(补 candidate_id 缺失分支的领域错误)。
- M10:SECTION_DIMENSION_MAP 补 object_dossier/character_pattern,或按实现修订 README 契约与测试。
- M6:manifest 交换携带 legacy_field_key 与桥接元数据。
- M2:评测读取加上限/过滤下推,消除无界查询。

**P2(契约与文档一致性,合并前或紧跟合并)**
- M18:补 ADR-0040 承诺的 STORY_SCENE_DIRECTOR_ENABLED 默认关闭总开关,或修订 ADR-0040"后果"节。
- M16:将 app/main.py 约 600 行操作留痕业务编排迁出组合根。
- M9:为 goal outcome_unknown 增加作者核对/解除入口(与计划"停下请示作者"闭环)。
- L25:"连续推进 N 轮"实现或声明延后,并同步 ADR-0040/任务记录。
- 文档同步:M14、M15、M17、L24、L26(模块文档两处矛盾、Prompt 清单漏登三个能力、ADR 索引过期、C0 映射文档过时)。

**P3(low 清单其余项)**
- 测试与断言补齐:L16(并行 e2e 账号级联删)、L17(事件同步)、L18(get_settings 缓存清理)、L23(stale 标签断言)、L27(R3/R4 越权断言)、L8(方言守卫)、L15(conftest 钉住布尔开关)。
- 展示与文案:L1、L20、L21、L22(raw ID/UUID 暴露)、L9(繁体文案)。
- 后端小修:L3(status 校验不对称)、L5(锁序反转)、L6(apply 内复核)、L10(next() 崩溃路径)、L11(函数内 owner 校验)、L12(DI 静默跳过)、L13(类型归一化)、L14(迁移 docstring)、L2(线索全量上限)、L7(过期 docstring)、L4(update 语义变化文档化)。

**P4(验证补齐,待条件允许)**
- 待 R6 完成后执行 PostgreSQL critical 层测试(重点回归 varchar 溢出、advisory lock、并发与锁序类路径)。
- 起服务执行 Playwright e2e。
- 性能测试(优先覆盖 M2/L2 无界查询路径)。
- 推进真实模型评测与作者验收(五题材评测、A4 数周真实使用数据)。

---

*本报告为评审汇总:全部事实与结论来自本次评审输入(4 份计划对账、18 个分片审查、51 条含复核结论的发现、7 项门禁结果);汇总过程只读,未运行测试、未写其他文件。3 条 unconfirmed 发现(U1–U3)的复核结论均为"复核未通过",已按原样标注。*

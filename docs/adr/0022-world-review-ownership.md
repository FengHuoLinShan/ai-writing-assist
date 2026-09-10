# ADR-0022 — 复核所有权

- 状态：Accepted / Implemented
- 日期：2026-09-09
- 授权：用户确认“世界观能力对齐与作者工作台优化”第四期方向：改动规则后能看到确定受影响的资料和待查漏范围，完成复核后保留可追溯记录；复核聚合归 World，Story/Writing 经稳定接口提供来源并维护本域状态。

## 决策

世界变更的**复核聚合与回执归 World 模块**：`world_validation_runs` 继续作为唯一校验回执载体，第四期在其上扩展冻结影响清单（`impact_json`，创建时枚举跨模块可证明依赖）、分批计划与覆盖进度（`plan_json` + packet 账本推导）、逐项复核记录（新表 `world_validation_review_items`，绑定 run 的 manifest/target 哈希）与失效原因（`stale_reason`）。复核记录只能由作者显式写入处置（已修正 / 已知悉 / 稍后再定），普通异步任务的“完成”不替代领域校验或作者裁定：`require_gate` 在存在未处置的作者裁定项或未签收警告时保持阻断（`review_pending` / `warnings_not_accepted`）。

**Evidence 只提供只读证据**：影响预演与语义查漏消费 confirmation 的 selected 资料语义不变；复核过程不把任何跨模块来源写回 Evidence，也不扩大生成上下文——依赖图的传递遍历只用于列示影响。

**Story / Writing / 地图经稳定只读接口提供来源**：本 ADR 仅新增真实缺失的窄读取接口（故事线按实体反查 `list_plot_threads_referencing_entities`，正文术语扫描沿用 `scan_manuscript_terms`，地图节点沿用 `map_atlas_nodes.location_entity_id` 同模块关联）。影响预演只读枚举，输出各域条目（标题、来源版本或 hash、路径/距离）并显式列示**未覆盖范围**（Scene 仅到章节粒度、代词与改写无法字面匹配、证据分片实体标注未纳入等）；`complete=false` 时禁止把清单表述为全量。各域状态由本域维护：修复建议以“打开来源/去所属模块处理”呈现，检查过程不自动改写正文或正式设定。

**定向语义查漏复用 validation run**：新 scope 目标 `semantic_gap`（根对象 + 声明依赖一跳：`requires`/`derives`），冻结清单即查漏范围，目标内容再变化由既有 target-hash 失效链路强制重新待复核；不做独立查漏任务类型，不用 Top-K 检索冒充全库覆盖。

**完整检查分批续接沿用同一 run 行**：`POST /validation-runs/{id}/continue` 只允许失败或预算中断的 run 重入队；已持久化的 packet 输入哈希被跳过，预算按剩余未检查分片计算，覆盖账本持续展示已检查 / 遗漏 / 失败，不重开新回执、不重置已完成分片。

**引用语义分级落在既有 `TargetRef.relation`**（`informs`/`requires`/`derives`/`conflicts` = 参考/依赖/派生/冲突）：前端引用编辑补齐分级选择，知识图谱区分“资料关联”与“已声明依赖”，后端校验与依赖哈希不变。

**政策编辑复用版本化验证政策**：政策仍是 rule 页 `page_meta_json.validation_policy`，编辑界面产出该页工作稿并走既有发布门禁（rule 页强制 full 校验）；政策变化改变 `policy_hash`，使旧回执失效（`stale_reason=policy`），需重新校验与复核。

## 影响与替代

考虑过为复核记录建独立聚合表（脱离 run）：无法继承 target-hash 失效链路，且“目标再变化后重新待复核”要另建比对逻辑，等于复制 run 的冻结机制。考虑过写时主动失效（改动即推送标记旧 run）：惰性 `_refresh_freshness` 已在每次读取与门禁前强制重算，主动推送只省一次重算却引入写路径耦合；保留惰性失效，仅补充 `stale_reason` 让前端能区分“政策变化 / 内容变化 / 依赖变化 / 目标变化”。

考虑过新建“影响分析”跨模块服务：会诱导 Story/Writing 反向依赖 World 的目标语义。最终由 World 持有枚举逻辑、经 facade 拉取只读来源，未覆盖范围显式声明，避免把“列示影响”膨胀为“跨模块写协调”。

## 验证

后端测试覆盖：复核记录绑定与 unknown/stale 拒绝、author-required 门禁在处置前后 `review_pending` 变化、continue 的续接与运行中冲突、semantic_gap 冻结范围与目标漂移失效、影响预演各域来源与跨项目隔离、findings 分页筛选、政策草稿端点与旧回执 `stale_reason=policy`、冲突队列分页。前端 Vitest 覆盖政策编辑器、引用分级选择、图谱依赖区分、健康面板筛选/分页/逐项处置；e2e 覆盖“找到资料 → 安全修改 → 继续创设 → 采用成果 → 完成复核”的完整作者流程。

## 2026-09-10：跨域来源与实际语义范围

影响来源扩展为 Story 故事线/篇章纲/Scene/当前总纲、正文精确选段和地图当前空间版本。Story 经 `list_world_dependencies` / `read_world_dependency`，Writing 经 manifest/range facade，地图由 World 自有版本服务提供。来源 hash 与范围 hash 包括版本与依赖集合；新增关联、正文改版或地图换版使旧回执过期。来源打开时重验，返回清单保留位置；声明关联与字面提及分开显示。

`semantic_gap` 可显式选择 `review_domains` 和 0/1 层范围。真正进入模型的是原 confirmation 编译后保留的 items，不把原始全文重新塞回被裁剪/排除的确认。World 受审采用包是领域执行资料，其外部引用仍受原确认约束。Focused Evidence 用于冻结范围和只读回读，回执不复制正文、不增加写权限；检索覆盖不宣称穷尽。

run 的 manifest 保存实际语义资料、确认指纹、范围指纹、聚焦回执和遗漏。开始、续接、完成、读取与门禁重验；失败或预算中断只复用同一输入分片。旧未保存实际语义范围的回执须重建，不能继续沿用旧全文语义结果。硬错误始终阻断，待定仍未完成，旧签收不跨来源版本复用。

Evidence 的 Story/map 规划资料只向无 Scene 截止的作者读取开放，reader/character 或带截止上下文不走这条无投影路径。pinned prose 严格截取回读结果的 highlight 区间。地图语义范围覆盖保存的空间声明及其依据，不包括图像视觉几何识别。

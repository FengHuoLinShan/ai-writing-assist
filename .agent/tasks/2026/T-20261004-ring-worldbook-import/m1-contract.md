# M1 来源契约 —— 理法之环 Wiki 导入与增量维护

状态：草案 r7，五轮评审/审查意见已逐条冻结（M1 交付物；r5 随实现落盘，r6 为收尾评审遗留 low 整改，r7 为双轴代码评审整改与合并前审查整改，同日两轮）。
修订记录：r2 按 2026-10-04 独立评审意见修订——修正基线 wikilink 事实错误；补冻 files[].path/rel_path 唯一性/source_path/baseline 口径/接续补写副作用五项；声明跨 suggestion 并发缺口及 M3 方案。r3 复核轮：七条意见引用的全部代码行在 HEAD 逐一核实属实；据此修正 r2 四类引用误差——① `require_active_project` 共享锁 docstring 实在 `project/services.py:663`（FOR SHARE 语义见 `project/repositories.py:46-50`），原写 :657-658；② `_lock_page_universe`（`world_bible_lifecycle_service.py:934-942`）是项目级 `pg_advisory_xact_lock` 而非「page 行锁」，第 0/6/7.6 节表述已改；③ rel_path 唯一性冲突状态码：业务规则拒绝走 `ValidationError`→HTTP 400（`core/errors.py:38-41`、`backend/app/main.py:560-584`），422 仅适用 manifest 解析路径（`api.py:488-490`），第 2/7.5 节与冻结表已改；④ 校验引擎/服务消费行号精化（engine 取值 :408-417、判定 :418-420，`_scan_wikilinks` :183，service aliases :1746、source_path :1749-1751）。r4 按 2026-10-04 第二轮独立复核修订四项——⑤ 接续 legacy 的匹配基准统一：对 legacy `source_path` 应用同一剥根规则得等效 rel_path 再逐条比对（原口径直接比 source_path 恒不等、接续空转），新增 7.7 失败用例；⑥ 并发方案 a 升级为 a+b 混合（也须先取 dataset advisory lock 再锁内重放 `_analyze`，包内 rel_path 唯一性无法防并发重复建稿），表达式唯一索引列为 migration 触发条件 c；⑦ 冻结「含未解析引用的导入页发布 gate=block 属预期」，M4 验收覆盖 + 文案披露，豁免须新契约修订；⑧ 7.6 落点改判：SQLite 模块测试层单连接不可真并发，M1 仅落顺序 409 对照，真并发入 M3 PostgreSQL e2e。r5 按 2026-10-04 第三轮独立评审修订三项——⑨ 冻结 M1/M3 后端实现新增的 `dataset_intent`（manifest/payload/preview 响应三态 `Literal["continue","new","adopt_legacy"]`）与 `payload.legacy_bindings`：new 撞已有 dataset_key 拒绝（ValidationError→400）、adopt_legacy 按 legacy `source_path` 剥根等效 rel_path 唯一匹配并预览展示待绑定映射（第 2 条已补记，第 8 节冻结表已补行）；⑩ 冻结 dataset 写路径携带旧 `source_path`：接续绑定/来源更新/恢复重写整份 meta 时必须携带既有页最初原始提交路径，legacy（v1）路径不变（第 8 节表已补）；⑪ 声明 `dataset_intent` 不单列入 preview_hash 输入集的理由：其行为结果（target/current_hash 变化）经 items 间接纳入，intent 值固化于 stored payload 供重放（第 5 条已补记），指纹输入集合其余不变、不升 schema 版本。r6 按 2026-10-05 收尾评审遗留四条 low 整改——⑫ 第 6 条冻结锁键实格式：`worldbook_import:{novel_id}:{dataset_key or ''}`（`worldbook_import_service.py:1099-1116` `_lock_import`，`pg_advisory_xact_lock(hashtextextended(:key,0))`），含 novel_id 与 publish 链 `world_bible_pages:{novel_id}` 键模式对齐；实现定案为导入链不取 universe 键，两键空间独立、无交叉加锁顺序要求（第 6 条已改）；⑬ 第 8 节补 `source_format` 枚举消费方同步行、第 4 条补 `allow_local_refs` 接线注记（lifecycle `create_draft`/`update_draft` :636/:1526 已有参数，导入物化写路径必须传 True）；⑭ 第 0 节补三处既有消费点（suggestion 列表摘要与 `_validated_payload_json`、engine `title_matches_source_stem`）；⑮ 遗留「三态选择字段未入冻结表」经复核已被 r5 覆盖（`dataset_intent` 第 2 条补记 + 第 8 节三行，间接入指纹见第 5 条），无需再改。r7 按 2026-10-05 双轴代码评审（standards/spec 两子代理）整改七项——⑯ 第 4 条物化边界补 ③：四态候选按 identity 去重时，已发布页身份与 dataset 成员/工作稿对齐（`draft.page_id` 反查同 source_key，含 draft 遮蔽 page 行的形态），batch/工作稿命中升级为已发布页候选：目标为已发布页（含该页同时在本批的重导场景）一律写真实 TargetRef id，不回落 `local:`（第 4 条已补）；⑰ 第 2 条 adopt_legacy 补写口径精化：apply 仅对工作稿（draft）目标补写 dataset 字段；已发布 page 目标本轮不改写其 meta（补写须走发布链显式确认路径，后续单独实现），预览经 `legacy_bindings[].target_kind="page"` 如实标注并在前端披露，堵住「预览展示映射、apply 不生效」的空转缺口（第 2 条与第 8 节已改）；⑱ 第 4 条明细定案：逐条引用明细 `link_details`（raw/target/alias/anchor/origin/state/resolved_path/resolved_title）随 payload 持久化以支撑恢复预览冻结语义，不入指纹（先例同 `legacy_bindings`），每页 200 条截断；未决事项「明细进 payload 还是仅预览响应」就此关闭（第 4/5/8 节已改）；⑲ 第 8 节补 `payload.source_paths` 行（兑现 §2「source_path 携带旧值」的既有实现补记）、`link_details` 行、`legacy_bindings[].target_kind` 行；⑳ `new` 撞名拒绝带机器码 `worldbook_dataset_exists`（`ValidationError(code=…)`），前端按响应体 `error` 字段匹配作者文案、不依赖报错措辞；㉑ 前端本地圈定（`worldbookImportScope.js`）词法/归一化口径与后端对齐：双链词法同 `_WIKILINK_RE`（不含换行）、related 纯名称不拆 `#`、related 双链解析 alias、标题键不去 `.md` 后缀、路径键去 `.md`、声明标题注册后顶替 stem 条目（服务端每页单有效标题），并引入双端共享测试向量（前端 vitest 与 `test_worldbook_import_links.py` 消费同一 `frontend-console/tests/vue/world/bible/fixtures/worldbook-link-vectors.json`）作漂移防护；已知残差：JS 无 `str.casefold`（ß 类折叠）、未读页声明标题未注册前以 stem 占位、本地 YAML 仅覆盖受限子集，四态计数以服务端预览为准。㉒ 冻结 `local:` 待发布引用的编辑与发布语义（第 4 条物化边界 ⑤）：公共草稿 `create/update` 路径传 `allow_local_refs=True`（编辑器整份回传 refs 不再 422）；发布链经 `_materialize_local_page_refs` 物化目标已发布的引用（预览与 SEAL 同口径，凭预览 `impact_scope_hash` 发布不得误报冲突；SEAL 在校验与口径比对通过后才把物化值写回工作稿），目标仍未发布的保持 `local:` 随页落地、不阻断发布（Wiki 互链阻断即死锁），发布影响新增 `pending_page_reference` omission（`WorldBibleImpactOmission` reason 枚举扩展 + 回执/前端文案同步），语义缺口清单与生成中心资产目录跳过 `local:` 引用；㉓ `_ensure_declared_categories` 的 create_category 包 `begin_nested()` savepoint，`IntegrityError`（同项目跨数据集并发 apply 建同一分类撞 `uq_world_bible_category_key`）重查后按「已存在」继续、查无则升 ValidationError，不再冒 500（导入锁按 dataset_key 划分，覆盖不了跨数据集同分类并发）；㉔ apply 循环 `item.action in {"update","preserve"}` 修正为 `== "update"`（preserve 已整体 continue，原 preserve 臂不可达）；㉕ 方向取舍：审查给出的方向 B（导入只保留已发布页真实引用）与第 4 条冻结的 `local:` 物化冲突、需重开契约并丢弃已实现四态/披露链路，不采纳。
核查基线：r2–r5 行号对照 `96dc807283b876b3dbeabac72e675b828f8f7a87` 前后实现期工作树核实；r6 全部引用对照 HEAD `287f9e43d4f8a0f5225e8680f54c8fa58ac67ee8` 复核；工作树含其他任务的 writing WIP，本契约不涉及；r7 引用对照 r7 整改轮工作树核实（本轮改动文件以当轮 diff 为准），其他行号沿用 r6 基线，落地后行号以代码为准。主计划：同目录 `TASK.md`（决策 1–6、里程碑 M1–M3）。本契约冻结所有影响预览的字段，M2/M3 实现不得偏离。

## 0. 现状事实基线（核查结论，实现的事实来源）

以下均为本轮实际读取的代码事实，后续条目引用不再重复证明：

- 入口与鉴权：三个端点 `POST /api/world/bible/imports/preview`、`GET /api/world/bible/imports/{suggestion_id}`、`POST /api/world/bible/imports/{suggestion_id}/apply`（`backend/modules/world/api.py:1702-1746`），均经 `ActiveNovelIdQuery` → `_require_active_novel_id` → `require_active_project`（`api.py:394-402`）完成项目与 owner 门禁。preview 请求体上限 64 MiB（`api.py:476-491`），经 `WorldbookImportManifest` 校验。
- 格式识别：`WorldbookImportService._detect_format`（`worldbook_import_service.py:568-583`）只看提交路径集合——含 `/.obsidian/` 判 obsidian；含 `/.wiki/raw/`、`/.wiki/wiki/` 或文件名 `_sidebar.md`/`home.md` 判 llmwiki；否则 generic。`_page_type`（`:585-610`）在 generic 下一律 `source_material`，仅 obsidian/llmwiki 正文 `.md` 采纳受限 frontmatter page_type。
- Manifest/Payload schema：`WorldbookImportManifest` 只有 `schema_version`（Literal `world_worldbook_import.v1`）与 `files`，`extra="forbid"`（`backend/modules/world/schemas.py:2935-2939`）；`WorldbookImportPayload` 有 `source_format: Literal["obsidian","llmwiki","generic"]`、`manifest_hash`、`preview_hash`、`files`、`items`、`ignored_paths`（`schemas.py:2964-2987`）。
- 页级身份：`source_key = sha256(f"{source_format}\0{file.path}")`（`worldbook_import_service.py:485`）；`file.path` 来自前端 `file.webkitRelativePath || file.name`（`WorldbookImportPanel.vue:112`），即**含所选根目录名**。
- 既有来源索引：`_existing_sources`（`worldbook_import_service.py:419-451`）按 `novel_id` 全量扫描 `world_bible_page_drafts` 与 `world_bible_pages`，取 `page_meta_json.worldbook_import.source_key` 建映射，无 dataset 概念。
- 三方比较：`_analyze`（`:344-379`）对本次出现的 source_key：来源 hash 未变 → `preserve`；站内可编辑内容 hash 等于 `baseline_content_hash` → `update`；否则 `conflict`。可编辑 hash `_editable_content_hash` 只含 title/page_type/free_text/sections/linked_asset_refs/template 字段，**不含 page_meta_json**（`:612-645`）；而导入写入的 `baseline_content_hash` 以 `sections_json=[]`、`linked_asset_refs_json=[]` 的空口径计算（`_source_meta`，`:651-658`）——两个口径对 refs 的取值不一致，是第 4 条 baseline 冻结决定的直接依据。
- missing 判定：existing 中不在本次 `seen_keys` 的一律 `missing`（`:380-399`）；apply 时写 `source_missing=True` + `missing_manifest_hash`（`:142-185`），恢复时仅清标记、不覆盖内容（`:190-217`）。
- 预览指纹：`manifest_hash = sha256([{path, source_hash}…])`（`:335-340`）；`preview_hash = sha256({manifest_hash, source_format, items 全量 dump})`（`:401-407`）。apply 重放 `_analyze` 后双重比对，任一不符抛 `ConflictError`（`:127-133`）。恢复预览 `get_preview` 直接反序列化 `suggestion.payload_json` 返回，不重算（`:96-108`）。
- 并发 CAS：`SuggestionQueueService._claim_pending` 用 `UPDATE … WHERE status='pending'` 原子置 `processing`，rowcount≠1 时抛 `SuggestionAlreadyProcessedError`（`suggestion_queue_service.py:1249-1270`）；apply 先双 hash 校验再 claim（`worldbook_import_service.py:117-137`）。**已知缺口**：CAS 只防同一 suggestion 重复 apply；两个不同 suggestion 并发 apply 均可各自 claim 成功，`update_draft` 默认无行锁、无基线校验（`world_bible_lifecycle_service.py:543-557`，`require_edit_baseline=False`），`require_active_project` 持的是共享项目行锁（docstring「Hold a **shared** project row lock」，`project/services.py:663`；`get_active_for_share` 以 FOR SHARE 加锁，`project/repositories.py:46-50`），不构成互斥——跨 suggestion 并发 apply 的缺口在第 6 条冻结 M3 方案。
- 冲突队列：`replace_worldbook_import_conflicts` 把同 source_key 的旧 pending `worldbook_import_conflict` 置 stale，再按 item 建新项，`target` 携带 source_key/source_path/target_id/suggestion_id（`conflict_queue_service.py:24-79`）。
- 工作稿写入的上下文失效链：`update_draft` 在 flush 后调用 `_mark_draft_context_changed`（`world_bible_lifecycle_service.py:588-593`）→ Evidence facade `mark_asset_context_changed`（`evidence/compilation/facade.py:1136-1153`，docstring「Invalidate confirmations that explicitly selected this working draft」，`world_bible_lifecycle_service.py:1807-1823`）→ 分发 `source.changed` observer（`facade.py:1154-1166`）。即**任何**经 `update_draft` 的 meta 写入（含现行 missing 标记写入/恢复 `:155-163`、`:207-215`）都会使显式选中该工作稿的 confirmation 失效，是第 2 条接续补写决定的直接依据。
- 世界校验引擎已有 wikilink 扫描与导入元数据消费：`world_validation_engine.py:22` 定义 `_WIKILINK_RE`，`:183` 起 `_scan_wikilinks` 分别扫描正文（`:549`）与 frontmatter JSON（`:559`），按 manifest 的 `link_lookup`/`anchor_lookup` 解析报 findings；`:408-420` 用 `page_meta_json.worldbook_import.source_path` 做 policy `schema.source_prefixes` 前缀校验（取值 `:408-417`、判定 `:418-420`）；`world_validation_service.py:1739-1751` 的 `_lookup_manifest_item` 消费 `worldbook_import.frontmatter.aliases`（`:1746`）与 `source_path`（`:1749-1751`）构建校验清单。是第 3、4 条冻结决定的直接依据。
- 导入 payload 的其余既有消费点（r6 补记，v2 兼容读取已覆盖）：① suggestion 列表对 `worldbook_import` 目标的 payload 摘要（`suggestion_queue_service.py:319-320`，`WorldbookImportPayload.model_validate` 直读 `payload_json`）——v1/v2 双 Literal 兼容读取覆盖；② `_validated_payload_json` 对 payload 的重校验（`suggestion_queue_service.py:1108` 起，同一 Payload 模型）——同上覆盖；③ 校验引擎 `title_matches_source_stem` policy 用 `source_path` 的 POSIX stem 比对标题（`world_validation_engine.py:432-434`）——「source_path 保留原始提交路径不变」冻结覆盖。
- `source_format` 枚举的 Literal 消费方（r6 补记）：Manifest `schemas.py:2957`（含 `auto`）、Payload `:3015` 与 PreviewResponse `:3061`（均无 `auto`）；suggestion 列表摘要与 `_validated_payload_json` 经同一 Payload 模型消费，枚举扩展随模型自动兼容，无独立硬编码枚举。
- 存储载体：`CreationSuggestion.payload_json/result_ref_json` 为 JSON 列（`models/worldbuilding.py:564-578`）；`WorldBiblePageDraft.page_meta_json`（`:259-289`）与 `WorldBiblePage.page_meta_json`（`:121-143`）均为 JSON 列。
- 引用契约：`_validate_asset_refs`（`world_bible_lifecycle_service.py:1664-1735`）要求 type+id、relation ∈ {requires, informs, derives, conflicts}、每页 ≤100、目标必须是本项目 canonical/confirmed 的 CoreEntity/EntityRelation/WorldBiblePage；`target_hash` 声明值必须等于 TargetRef 指纹（`:1693-1698`）；`allow_local_refs=True` 时 `local:` 前缀跳过存在性校验（`:1703-1704`），现唯一调用方为采用包（`adoption_package_service.py:1305`），其 `local:` → 真实 id 的物化先例在 `adoption_package_service.py:1160-1170`。
- Wiki 引用解析：**导入服务本身**无任何 `[[…]]` 或 frontmatter `related` 解析，frontmatter 整体存入 `source_meta.frontmatter`（`worldbook_import_service.py:670`）；但世界校验引擎已有独立的 wikilink 扫描与 `aliases`/`source_path` 消费（见上一条），M2 的引用解析与它是并存的两套机制，关系在第 4 条冻结。
- 前端：面板限 2000 文件/单文件 2 MiB/总量 25 MiB（`WorldbookImportPanel.vue:96-99`），预览→应用传 `preview_hash`（`:135`），`onMounted`/`suggestionId` 变化时经 `getWorldbookImport` 恢复预览（`:150-165`）。
- 既有测试：`backend/modules/world/tests/test_worldbook_import.py`（三方更新/冲突、policy 页保持工作稿、unsafe path 拒绝、missing 标记与恢复、原子回滚等 8 个用例）。

---

## 1. 格式识别：受 schema 限定的显式格式，保留 auto 默认

**结论**：manifest 新增显式 `source_format` 字段，取值 `Literal["auto","obsidian","llmwiki","wiki_markdown","generic"]`，默认 `"auto"`；`"auto"` 走现有 `_detect_format` 路径检测，显式值直接生效并在 payload 固化。不通过伪造 `.obsidian` 等配置文件解决识别。

**理由与证据**：仅选择概念子目录时，浏览器提交的相对路径不含上层 `.obsidian`/`.wiki`，`_detect_format` 必然落 generic，Markdown 全部降为 `source_material`（基线第 2 条；TASK.md 决策 1）。格式选择权应交给作者，且必须受 schema 限定而非自由字符串。在本次资料上，`concepts/真名回响/` 页面是 Obsidian wiki 正文（带 frontmatter），显式 `obsidian` 可恢复 page_type 归类与 `activation_eligible` 语义（`:669`）。

**取值补充**：`wiki_markdown` 为新增受支持格式，语义 = 「Obsidian 正文子集：无 vault 控制目录标记，但 `.md` 按 obsidian 规则解析 frontmatter/page_type」；raw/非 `.md` 行为与 obsidian 一致。是否并入 M2 由实现成本决定，schema 先保留该枚举位。

**影响字段（冻结）**：
- `WorldbookImportManifest`（v2）新增 `source_format: Literal[...] = "auto"`；`extra="forbid"` 不变。
- `WorldbookImportPayload.source_format` 语义变为「auto 解析后的最终格式」，枚举仍为 `{obsidian, llmwiki, wiki_markdown, generic}`；`auto` 不出现在 payload（预览响应同理）。
- apply 重放沿用 `:333` 的固化机制（payload 的 source_format 优先，不再检测），显式选择在预览→应用之间冻结。

**兼容**：v1 请求（无该字段）= `auto`，行为与现状逐字节一致。控制文件过滤 `_is_control_path`（`:559-566`）不变，格式选择不豁免任何控制文件。

---

## 2. 资料集身份：作者声明的 dataset_name 派生 dataset_key；页级 key 改挂资料集内相对路径

**结论**：
- 新增资料集身份 `dataset_key = sha256(f"worldbook.dataset.v1\0{normalized_dataset_name}")`，`normalized_dataset_name` 为作者在面板显式输入/确认的资料集名（NFC、casefold、去首尾空白、限长 1–80）。**不使用本机绝对路径、不使用所选根目录名**。
- 页级身份改为 `source_key = sha256(f"{dataset_key}\0{rel_path}")`。**rel_path 剥离规则（冻结）**：提交 path 含 ≥2 段时，首段视为所选根目录名，`rel_path = 去掉首段后的 POSIX 相对路径`；path 仅 1 段（单文件选择、无 `webkitRelativePath`，前端 fallback `file.name`，`WorldbookImportPanel.vue:112`）时整段即 rel_path，不视为有根名。两种形态混入同一包且剥后撞名时，由下述 rel_path 唯一性校验拒绝。根目录改名 → rel_path 不变 → 页级身份不变；不产生重复。
- **rel_path 唯一性（冻结）**：同一提交包内，全部文件的 rel_path 经 NFC + casefold 归一化后必须唯一，冲突即拒绝——抛 `ValidationError`，经 DomainError 处理器映射 HTTP 400（与现行 duplicate path 拒绝同型：`core/errors.py:38-41`、`backend/app/main.py:560-584`；422 仅适用 manifest 解析路径 `api.py:488-490`；preview 与 apply 重放都执行）。这是对现状防线的必要收紧：现状唯一性只对原始提交 path 去重（`worldbook_import_service.py:306-311`），API 直调可提交不同首段（根名）的混合包，剥根后 rel_path 相同 → 同 source_key 两个 item → `mapped_files` 按 key 覆盖（`:138`）且循环对两个 item 各 create 一次 → 重复建稿。
- 旧来源兼容：无 dataset 字段的请求沿用现行算法（`sha256(source_format\0path)`，基线不变）。站内已有 legacy 条目（meta 无 `dataset_key`）**不默默绑定、不批量改写**：仅当作者显式选择「接续旧来源」且新包 rel_path 与 legacy 条目的**等效 rel_path 逐条相等**时，apply 才为匹配条目补写 `dataset_key`（一次性、经预览确认、逐条可核对；对已发布 page 的补写走发布链的显式确认路径——r7 精化：本轮 apply 不改写已发布 page 的 meta，预览经 `legacy_bindings[].target_kind="page"` 如实标注并由前端披露「本轮不改写已发布页归属」，见修订 ⑰）。**等效 rel_path（冻结，r4）**：对 legacy `source_path` 应用与新包相同的剥根规则（≥2 段去首段、单段整段，NFC+casefold 归一化后比较）——legacy `source_path` 是含根名的原始提交路径（`worldbook_import_service.py:662`），直接与新包已剥根的 rel_path 比较恒不等，根改名重导（7.3 场景，接续的核心动机）下显式接续将永远匹配失败、功能空转；接续预览必须向作者展示「legacy 路径 → 新包 rel_path」待绑定映射，逐条可核对、可取消。作者也可选「重建新集」，legacy 条目保持原样、不参与新集任何判定。

**理由与证据**：现行 `source_key` 混入格式与含根名的完整路径（`:485`），根改名即换身份（TASK.md 决策 2；失败场景 C）。`_existing_sources` 全扫建索引（`:419-451`）说明成员资格天然以 `page_meta_json` 为真相，dataset_key 冗余进每页 meta 即可，无需独立身份表。补写 meta 不会误触三方比较：`_editable_content_hash` 不含 `page_meta_json`（`:612-622`）。「同名冲突」：同项目内两个不同 dataset_name 规范化后同名即同一资料集（key 相同，合理）；sha256 碰撞可忽略。

**影响字段（冻结）**：
- manifest（v2）新增 `dataset_name: str | None`（1–80 字符）；`dataset_key` 由服务端派生，**不接收客户端值**。
- manifest（v2）/payload（v2）新增 `dataset_intent: Literal["continue","new","adopt_legacy"] = "continue"`（r5）：作者的新建/继续/接续显式选择，`new`/`adopt_legacy` 必须携带 `dataset_name`（manifest 校验拒绝，422 解析口径）；intent 值固化进 stored payload，apply 重放从 payload 恢复、不在重放间漂移。`continue` 为 v1 兼容默认，行为与本节其余描述一致。
- `new`（冻结）：派生 key 在本项目已存在（任一既有条目 meta `dataset_key` 相等）→ preview 即拒绝（`ValidationError`→HTTP 400），提示继续维护或换名；preview 与 apply 重放均执行（重放经 `_analyze` 复验）。
- `adopt_legacy`（冻结）：对项目内 legacy 条目（meta 有 `source_key` 无 `dataset_key`）的 `source_path` 应用同一剥根规则（≥2 段去首段、单段整段）+ NFC + casefold 得等效 rel_path，与新包 rel_path 唯一匹配；同一等效 rel_path 命中多个 legacy 条目时不绑定（同名不猜身份）；匹配条目走既有四态判定（preserve/update/conflict），preserve 与 update 在 apply 时对**工作稿（draft）目标**一次性补写 `dataset_key/dataset_name/rel_path/commit_mode/dataset_root_name`（走 `update_draft`/更新路径，接受 confirmation 失效副作用，预览文案须披露）；目标为已发布 page 时不补写（r7 精化，见修订 ⑰）；conflict 不写、绑定延后至作者处置。未匹配的包内成员照常 create，不触碰其他 legacy 条目、不产生 missing。
- payload（v2）新增 `legacy_bindings: list[{source_key, legacy_source_path, rel_path}]`（≤2000，r5）：接续预览展示的「legacy 路径 → 新包 rel_path」待绑定映射（仅匹配项，逐条可核对、可取消）；仅展示与恢复预览用，不单独入 hash——判定要素由 items（target/current_hash）间接纳入。
- payload（v2）新增 `dataset_name`、`dataset_key`（64 hex）；`payload.files[].path` 与 `item.path` **统一为 rel_path**（展示与身份与 manifest_hash 同基准）；原始含根名路径只存 `dataset_root_name`（dataset 级诊断字段）与每页 `source_path`（见第 8 节，语义保留原始路径）。apply 重放直接以 `stored.files` 的 rel_path 重算（`:121-126`、`:335-340`），**不得二次剥根名**，否则与 stored 的 rel_path 基准 hash 恒不等、所有 v2 预览 apply 恒 409。
- `page_meta_json.worldbook_import` 新增：`dataset_key`、`dataset_name`、`rel_path`、`commit_mode`、`dataset_root_name`（仅诊断）；**`source_path` 保留原始提交路径（含根名）不变**——校验引擎 `schema.source_prefixes` 前缀校验（`world_validation_engine.py:408-420`）与校验清单构建（`world_validation_service.py:1749-1751`）消费该字段，不得改存 rel_path。dataset 写路径（接续绑定/来源更新/缺失恢复）重写整份 meta 时**必须携带既有页最初的 `source_path`**（r5 冻结）；legacy（v1）写路径保持现状，不做携带。
- 「新资料集」选择（即 `dataset_intent="new"`）若派生 key 在本项目已存在 → 拒绝（`ValidationError`→HTTP 400，同唯一性冲突口径），提示改用「继续维护」或换名。
- **接续补写副作用（冻结决定）**：显式接续为 legacy 条目补写 `dataset_key` 走 `update_draft`，接受其既有副作用——触发 `_mark_draft_context_changed` → Evidence `mark_asset_context_changed` → `source.changed` observer（`world_bible_lifecycle_service.py:589-593`、`:1807-1823`；`evidence/compilation/facade.py:1136-1166`），显式选中该工作稿的 confirmation 失效。这与现行 missing 标记写入/恢复路径（`:155-163`、`:207-215`）行为一致，不新增跨模块窄 seam；预览确认文案必须向作者披露「接续会使已选中这些工作稿的作者 AI 上下文确认失效，可重新物化」。不做静默绕过（直写模型会绕过既有不变量）。

**兼容**：v1 payload/条目不携带 dataset 字段；`source_key` 在 schema 中仍为 64 hex，校验无需变化。

---

## 3. missing 判定范围：两种提交语义 + 资料集隔离

**结论**：新增 `commit_mode: Literal["full_snapshot","append"]`（默认 `full_snapshot`）。
- `full_snapshot`：本次文件集合 = 该资料集完整快照。missing 判定输入从「项目全部带 source_key 条目」（`:380-399` 现状）**收窄为「`dataset_key` 等于本次 dataset_key 的既有条目」**；本次未出现的成员标 `missing`，apply 行为不变（标记不删除，恢复只清标记，`:142-217`）。
- `append`：局部追加/选择性页面，**不产生 missing**；本次出现的条目照常四态（create/update/preserve/conflict），未出现的成员一律不触碰、不标记。
- 跨资料集隔离：不同 dataset_key 的成员互不进入对方判定，互不产生缺失标记（失败场景 B）。
- legacy 条目（无 `dataset_key`）不属于任何资料集，不参与 missing 判定，除非经第 2 条的显式接续绑定。
- 旧契约保持：v1 请求（无 dataset/commit_mode）继续按项目级判定，行为与现状一致。

**理由与证据**：TASK.md 决策 3 指认 `_existing_sources` 按项目取来源导致跨集误报（失败场景 B）；`missing` 的写标记/恢复逻辑已经满足「不删除资产、保留历史」（`:142-217`），只需收窄判定输入，不必改动 apply 分支。M3 的「完整快照缺失项保留历史」直接复用该分支。

**影响字段（冻结）**：payload 与每页 meta 各新增 `commit_mode`；item.reason 文案随 commit_mode 区分（append 下无 missing 文案）。

---

## 4. Wiki 引用：解析规则、歧义不猜身份、站内物化沿 TargetRef、不产生 EntityRelation

**结论**（M2 预览层扫描，M3 物化）：
- 解析范围：正文 `[[名称]]`、`[[名称|显示文本]]`、`[[路径#段落]]`；frontmatter `related`（字符串或列表，值可含 `[[…]]` 或纯名称，逐项拆分）。原始文件与正文**不改写**；解析结果只进预览的每页引用清单，四态：`resolved`（唯一命中）、`ambiguous`（同名多候选）、`unresolved`（无命中）、`unselected`（命中本次未纳入的页面）。
- 匹配优先级：显式 `路径`（含 `a/b.md` 或 `a/b`）优先命中资料集内 rel_path（忽略 `#anchor` 与 `.md` 后缀差异）；其次唯一标题命中（站内已采用页标题或本批内标题）；同名多候选一律 `ambiguous`，**不按名称猜测身份**（TASK.md 完成条件第 3 条）。`related` 与双链只是「提示性引用」，不进入 `requires/derives/conflicts` 有向依赖，不参与既有依赖无环校验（TASK.md 决策 4）。
- `alias`（`|显示文本`）与 `#段落` 原样保留在预览清单中，供导航与恢复；不参与身份匹配。
- 站内物化（M3，沿既有契约）：`resolved` 且目标为已发布页（`WorldBiblePage` canonical/confirmed）→ 按 TargetRef 写入 `linked_asset_refs_json`，relation 固定 `informs`，`target_hash` 按现有指纹规则（`world_bible_lifecycle_service.py:1693-1698`）；目标为本批工作稿或未发布 → 用 `local:` 约定指向 `{dataset_key}:{rel_path}`（复用 `allow_local_refs` seam，`:1703-1704`；物化先例 `adoption_package_service.py:1160-1170`：发布/物化时将 `local:` 替换为真实 id），**不得伪造正式页 id**；`unresolved/unselected/ambiguous` → 保留链接原文并提示，不建 ref。每页 ref ≤100（`:1672-1673`），超限在预览明示。**接线注记（r6，随整改轮落地修订）**：lifecycle `create_draft`/`update_draft` 的 `allow_local_refs` 关键字参数由本轮整改补齐（`world_bible_lifecycle_service.py:462`/`:524`、`:556`/`:581`，默认 False、既有调用方零变化；`:642`/`:678`、`:1532`/`:1538` 为既有 preview/validation 路径参数）——导入物化写路径必须显式传 `allow_local_refs=True`，否则 `local:` ref 会被存在性校验拒绝；采用包（`adoption_package_service.py:1305`）是先例；r7 起公共 `create/update` API 路径同样传 True（见物化边界 ⑤）。**物化边界（实现确立，冻结）**：① legacy（v1，无 dataset 身份）提交中 resolved→本批/draft 工作稿的引用**不物化**（`local:{dataset_key}:{rel_path}` 无 dataset_key 可拼、不伪造 id），仅计 resolved；resolved→已发布页照常物化真实 ref。② `local:` 目标超出 TargetRef `target_id` 255 字符上限（rel_path 过长）时该条不物化（TargetRef 契约零改动），计数不受影响。③（r7）候选身份对齐与已发布页优先：已发布页与同 dataset 成员/工作稿共享 identity（`draft.page_id` 反查同 `source_key`，含 draft 遮蔽 page 行的形态），batch/工作稿命中在判定后升级为已发布页候选——目标为已发布页时**一律**写真实 TargetRef id，包括该页同时在本批的重导场景，不回落 `local:`。④（r7）每条引用出现明细随 payload 返回 `link_details`（`raw/target/alias/anchor/origin/state` + resolved/unselected 附 `resolved_path/resolved_title`），alias 与 `#段落` 原样保留；明细**不入指纹**（先例同 `legacy_bindings`），随 payload 持久化以支撑恢复预览冻结语义，每页 200 条截断并标记。⑤ **发布链语义（r7 合并前审查整改冻结）**：`local:` 待发布引用是工作稿的合法持久态——公共草稿 `create/update` API 路径传 `allow_local_refs=True`（编辑器整份回传 refs 不再 422，与导入物化写路径、采用包先例同 seam）；发布链（`preview_publish_impact` 与 `_seal_draft_for_admission`）先经 `_materialize_local_page_refs` 把目标已发布（canonical/confirmed 且 meta `dataset_key`+`rel_path` 命中）的 `local:` 引用物化为真实 id 并重算 `target_hash` 与分区 `linked_asset_ref_hashes`（照采用包 `_page_draft_data` 先例），预览与 SEAL **必须同口径物化**（`impact_scope_hash` 含 refs 全量，单侧物化即失配误报冲突），SEAL 在校验与口径比对通过后才把物化值写回工作稿（提前写回会经 autoflush 抬升 `updated_at` 再次破坏口径）；目标仍未发布的引用保持 `local:` 随页落地、**不阻断发布**（Wiki 互链普遍，按修订 ⑦ 的阻断语义外推会死锁），发布影响新增 `pending_page_reference` omission（`WorldBibleImpactOmission` reason 枚举扩展，回执文案「有引用目标尚未发布」，前端 `worldBiblePublishing.js` 同步），语义缺口清单（`world_validation_service` 语义任务展开）与生成中心资产目录（`_asset_catalog`）跳过 `local:` 引用；目标发布后，已落地页的待发布引用经重导入（resolved→已发布页物化）或作者手动编辑生效，不做发布时的跨页反向改写（改写已采用页需走修订链，超出本轮）。
- `alias`（`|显示文本`）与 `#段落` 原样保留在预览清单中，供导航与恢复；不参与身份匹配。
- **不产生 EntityRelation**；不凭同名融合既有页面（TASK.md 非目标）。
- **与既有校验引擎的关系（冻结）**：导入预览的四态解析与世界校验引擎的 `_scan_wikilinks` findings（`world_validation_engine.py:22`、`:183`、`:549`、`:559`）是**两套独立机制**：预览四态只服务导入范围决策与 ref 物化，不写 findings、不阻断导入；引擎 findings 服务发布校验门禁，发布时以引擎结论为准。两套身份口径不同（预览用 rel_path/标题；引擎用 manifest `link_lookup`/`identity_key`），不混用、不宣称互为等价。frontmatter `aliases` **不参与**预览「唯一标题命中」：歧义判定只看 title 与 rel_path——aliases 是作者声明的额外名称，纳入会扩大自动绑定面，违反「同名不猜身份」；引擎侧 aliases 消费（`world_validation_service.py:1745-1748`）保持现状不变。
- **未解析引用与发布门禁（冻结，r4）**：引擎的 wikilink-dangling（`:207-217`，severity=error）与 wikilink-anchor-dangling（`:224-235`，severity=error）进入 `overall_result` 后任一 error 即 `("fail","block")`（`world_validation_engine.py:1281-1282`）——导入按契约保留 `[[…]]` 原文，凡含 unresolved/ambiguous/unselected 目标的页面，发布校验 run 会整体判 block。**冻结决定：这是预期行为，本轮不为 worldbook_import 页降级引擎语义**；M4 验收必须覆盖「含未解析引用的导入页发布 → gate=block」，预览与发布文案必须向作者披露「未选择/未解析的引用目标会阻断发布校验，可补全资料集范围或清理链接后重导」。若 M5 作者验收证明该门禁阻断正常流，豁免口径（如对 worldbook_import 页 dangling 降级 warn）属引擎语义变化，须以新的契约修订提出并带引擎回归测试，不在 M4 临时决定。
- **baseline 口径（冻结决定，评审意见 1 三选一之 a）**：M3 物化 refs 的页面，`baseline_content_hash` 在**同一 apply 事务内按「物化后含 refs」的字段组写入**（即创建/更新该页时以最终 title/page_type/free_text/sections/refs/template 组合计算 baseline），声明这是导入流程授权的基线口径，仅导入写入路径使用，不含作者手动编辑。不这样做的后果：baseline 以 `refs=[]` 空口径计算（`worldbook_import_service.py:651-658`）而 `_editable_content_hash` 含真实 refs（`:612-622`），物化后任何来源变化都会从 `update` 误判为 `conflict`，违反 TASK.md「仅来源变化更新工作稿」。存量处理：v1 导入页未物化 refs（refs=[]），其既有 baseline 口径天然一致，无需迁移；M3 首次物化即切换口径，物化后的作者后续编辑使 current ≠ baseline，仍正确走 conflict。禁止在物化之外的任何路径改写 baseline。

**理由与证据**：当前代码无任何 `[[…]]` 解析（基线第 12 条），frontmatter 整体保留（`:670`）意味着 `related` 数据已在 `source_meta.frontmatter` 中，M2 只需读取不需要新存储。`allow_local_refs` + `local:` 物化是采用包已验证的同构先例，符合「未发布目标不得生成假正式页 ID」（TASK.md M3）。

**影响字段（冻结）**：item 新增 `link_summary`（`{resolved, ambiguous, unresolved, unselected}` 计数，计数纳入 preview_hash）；payload/预览响应新增 `link_details` 逐条明细（r7 定案：随 payload 持久化、不入指纹，未决事项就此关闭）；`linked_asset_refs_json` 契约零改动（含 relation 枚举、上限、指纹）；`baseline_content_hash` 按上文口径决定随物化写入（字段本身不新增）。

---

## 5. 预览指纹：format、资料集、提交模式、目标基线全部纳入；恢复预览保持冻结语义

**结论**：契约升级 `world_worldbook_import.v2`（Payload 兼容读取 v1）。v2 的指纹输入为：

- `manifest_hash = sha256({schema_version, dataset_key, [{rel_path, source_hash}…]，按 path 排序})`——**用 rel_path 取代含根名的提交 path**，使根改名后同内容包的 manifest_hash 稳定（第 2 条目标在指纹层的对应物）；payload.files[].path 与 item.path 同为 rel_path（第 2 条冻结），apply 重放不二次剥根。
- `preview_hash = sha256({manifest_hash, source_format, dataset_key, dataset_name, commit_mode, items 全量 dump, ignored_paths})`——在现有三项（`:401-407`）基础上加入 dataset 与 commit_mode。目标基线仍通过 items 间接纳入（action/target_id/current_content_hash/reason 变化即 hash 变化），无需单独基线 hash。`dataset_intent`（r5）不单列入输入集：其行为差异必然改变 items（adopt 命中把条目从 create 变为 preserve/update 并携带 target；new 撞名在产出 payload 前即拒绝），经 items 间接纳入指纹；intent 值固化于 stored payload 供重放，同一 hash 不存在跨 intent 复用的安全缺口。

**恢复预览冻结语义**：`get_preview` 保持「原样反序列化 payload，不重算」（`:96-108`）——返回的 items/counts/引用清单（含 `link_details` 明细与 `legacy_bindings`）永远是预览当时的快照；apply 时才重放 `_analyze` 并按 v2 输入重算双 hash，任一不符 409（`:127-133` 机制不变）。前端「刷新后恢复预览」展示的即是冻结值。

**理由与证据**：`expected_preview_hash` 是应用前唯一防串台凭证（`schemas.py:3000-3008`），若 dataset_key/commit_mode 不入 hash，同一 hash 可在不同提交语义间复用，属安全缺口；manifest_hash 用 rel_path 是「根改名不换身份」的必要条件（否则 `:127` 的 manifest 比对会拒绝改名后重选的包）。v1→v2 兼容：`extra="forbid"` 且 `get_preview` 会反序列化存量 pending payload，v2 模型必须对 v1 payload 可校验——v2 全部新字段带默认值（dataset_key 可空 = legacy），schema_version 接受 `v1`/`v2` 双 Literal 并在读取时归一化。存量 v1 pending 预览的 apply 行为：重放会按 v1 归一化路径（旧 manifest_hash/preview_hash 算法、项目级 missing）计算，保证已存 hash 仍可匹配；仅在归一化无法成立时 409 要求重新预览，绝不静默改用 v2 算法比对 v1 hash。

**影响字段（冻结）**：`schema_version: Literal["world_worldbook_import.v1","world_worldbook_import.v2"]`（写入恒为 v2）；上述 hash 输入集合即冻结的指纹契约，任何后续字段变更必须再次升版本。

---

## 6. 跨请求状态：现有 suggestion + 页面 metadata 足够，不提 ORM/migration

**结论**：M1/M2/M3 全部跨请求状态沿用现有 JSON 承载，**本轮不提出任何新表或 migration**：
- 资料集成员资格与状态 → 每页 `page_meta_json.worldbook_import.dataset_key/rel_path/commit_mode`（页级即真相；资料集清单与成员聚合读取时按 dataset_key 分组构建，复用 `_existing_sources` 全扫模式 `:419-451`，项目内 bible 页数量级下可接受）。
- 预览与恢复 → `CreationSuggestion.payload_json`（现有，含 files 全量重放所需）。
- 并发/幂等 → `_claim_pending` 的原子 UPDATE CAS（`suggestion_queue_service.py:1249-1270`）+ apply 双 hash 重验 + 冲突队列 stale 替换（`conflict_queue_service.py:48-51`）。**CAS 覆盖范围声明（冻结）**：它只保证同一 suggestion 的重复 apply 产生一次结果（`SuggestionAlreadyProcessedError`）；**跨 suggestion 并发 apply 不在其覆盖内**——两个不同 suggestion（同 dataset、页面重叠）并发 apply 时都能通过各自双 hash 重验并 claim 成功，`update_draft` 默认无行锁无基线校验（`world_bible_lifecycle_service.py:543-557`），`require_active_project` 的共享项目锁不互斥（`project/services.py:663`），可交错写同一工作稿或对新建页重复建稿。TASK.md M3 的「并发重复 apply 只产生一次结果」不能靠现有机制达成，**M3 实现时必须补互斥**，方向二选一并在实现前定案：a) apply 事务内对本批 item 命中的既有 target 行（draft/page）逐个 `SELECT … FOR UPDATE`；b) 按 `dataset_key` 取项目级 advisory lock 后复验基线再写入。**共同前提（冻结，r4）：无论 a/b，都必须先按 `dataset_key` 取 advisory lock、在锁内重放 `_analyze` 复验后再写入——方案 a 原文「新建页按 dataset 内 rel_path 唯一性兜底」不可实现**：rel_path 唯一性只是 preview/apply 对提交包的应用层校验（与 `:306-311` 同型、包内比对），数据库无 (novel_id, dataset_key, rel_path) 唯一约束，两个并发 apply 各含同一新 rel_path 时双方 `_analyze` 都在对方提交前执行、都判 create、各自建稿，兜底无从发生。a 与 b 的差异仅在是否再对既有 target 行取逐页行锁（a 更强，可与 publish 链页级写入对齐）。无论选哪个，都必须核对与 publish 链锁的加锁顺序——正式页写入/发布链经 `_lock_page_universe`（`world_bible_lifecycle_service.py:934-942`，调用点 `:171/:216/:641/:769`）取项目级 `pg_advisory_xact_lock`（key `world_bible_pages:{novel_id}`），是 advisory 事务锁而非行锁。**锁键格式（冻结，r6）**：dataset advisory lock 键含 novel_id，实现定案为 `worldbook_import:{novel_id}:{dataset_key or ''}`（`worldbook_import_service.py:1099-1116` `_lock_import`，`pg_advisory_xact_lock(hashtextextended(:key, 0))`），与 publish 链键模式对齐且键空间不同；**导入链不取 universe 键**，两条锁链各自只有一把锁、无交叉加锁顺序要求（M3 实现已按此落地）。非 PostgreSQL 方言 `_lock_import` 为无操作（模块测试层不感知）。「跨 suggestion 并发 apply」列入第 7.6 节可测定义与 M3 验证矩阵。

**触发最小 migration 的条件（写明才提出）**：仅当出现 a) 需要按 dataset_key 的高效索引查询（资料集清单成为高频路径或单项目成员达数千页）；b) 需要 dataset 级跨页原子事务（成员集合同写同回滚）；c)（r4）需要数据库级防重复建稿硬约束——对 `page_meta_json` 的 (novel_id, dataset_key, rel_path) 建表达式唯一索引（同步数据库文档）。届时方案也只是对 `page_meta_json` 的 dataset_key 建表达式索引/生成列（同步数据库文档），不是新表。当前证据（payload items 上限 4000、单项目 bible 页数百级、全扫已在生产路径运行；并发互斥已由第 6 条 advisory lock + 锁内复验承担）不满足触发条件。

**理由与证据**：TASK.md 决策 6 要求优先 JSON 承载；补写 meta 不破坏三方比较（`_editable_content_hash` 不含 meta，`:612-622`），页级 meta 作成员真相与 `_existing_sources` 现机制同构。PostgreSQL JSON 列无索引是这个方案的唯一代价，当前查询模式（按 novel 全扫后内存过滤）不受影响。

---

## 7. 失败场景的可测行为定义（M1 用合成 Wiki 复现）

均用合成资料 + 可丢弃库（沿用 `test_worldbook_import.py` 的 service 直调风格），不触碰本机真实 Wiki。每个场景先在当前 HEAD 复现现状行为（作为回归对照），再按契约断言目标行为。

### 7.1 子目录误识别

- 构造：合成包仅含 `wiki/concepts/真名回响/理法之环.md` 等正文（无 `.obsidian`/`.wiki` 目录、无 `_sidebar.md`），正文 `.md` 带受限 frontmatter `page_type: concept`。
- 操作 A（现状对照）：`source_format` 不传 → 断言 `source_format=="generic"`、全部 item `page_type=="source_material"`（`:583`、`:598-599`）。
- 操作 B（契约行为）：manifest 显式 `source_format="obsidian"` → 断言 `source_format=="obsidian"`、非 raw `.md` 的 item `page_type=="concept"`、`activation_eligible` 按声明类型计算；apply 后 payload 中 source_format 固化不变。
- 失败判据：B 下仍出 generic/source_material，或 auto 与显式在 apply 重放时漂移。

### 7.2 跨资料集误报缺失

- 构造：资料集 A（`dataset_name="理法之环"`，2 页）先 preview+apply；资料集 B（`dataset_name="星锻环"`，2 页，独立 rel_path）以 `full_snapshot` 提交 preview。
- 现状对照（同 algorithm 不带 dataset）：断言 B 的 `counts["missing"]==2`（A 的条目被误报）。
- 契约行为：断言 B 的 `counts["missing"]==0`、B 条目全 `create`；apply 后 A 的每页 `page_meta_json.worldbook_import` 无任何改写（无 `source_missing`）。
- 失败判据：B 预览出现 A 的 source_key，或 apply 触碰 A 的 meta。

### 7.3 根名变化重复

- 构造：同内容包分别以根目录 `理法之环/…` 与 `ring/…` 提交（rel_path 相同、同一 `dataset_name`）。
- 现状对照：断言第二次全 `create` 且旧条目 `missing`（source_key 含根名，`:485`）。
- 契约行为：第二次 preview 断言 `counts=={"preserve":2,…, "missing":0, "create":0}`、`manifest_hash` 与首次一致（rel_path 基准）、`dataset_key` 一致；apply 后工作稿总数不变、无重复标题工作稿。
- 失败判据：出现任何 create/missing，或双 hash 与首次不同。

### 7.4 双边编辑冲突

- 构造：资料集 A 导入后，经 lifecycle 修改其中一页工作稿 `free_text`（偏离 `baseline_content_hash`）；随后修改同名来源文件内容重导。
- 现状对照：`test_worldbook_import_three_way_update_and_conflict`（`test_worldbook_import.py:44-124`）已覆盖。
- 契约行为：`full_snapshot` 与 `append` 下断言一致——该页 action=`conflict`、其余页正常；apply 后冲突队列新项 `severity=="high"`、`resolution_json.author_action=="needs_decision"`、target.source_key 为新页级 key、工作稿内容未被覆盖；再次以同包 apply 时旧 pending 冲突置 `stale`、只留一条。
- 失败判据：conflict 页被静默更新，或同 key 冲突重复堆积。

### 7.5 混合根名包撞 rel_path（评审意见 4）

- 构造：同一包内提交 `ring/concepts/理法之环.md` 与 `vault/concepts/理法之环.md`（不同根名首段，剥后 rel_path 相同），同一 `dataset_name`。
- 现状对照：不带 dataset 提交（旧算法）不撞 key（source_key 含完整 path），可各自 create——说明现状防线不含此形态。
- 契约行为：preview 以 `ValidationError` 拒绝（HTTP 400，rel_path 归一化冲突），**不产生任何工作稿**；apply 重放同包同样拒绝。
- 失败判据：preview 通过，或 apply 产生 2 个相同 rel_path/标题的工作稿。

### 7.6 跨 suggestion 并发 apply（评审意见 5、r4-4；真并发属 M3，M1 仅落顺序对照）

- **落点约束（冻结，r4）**：`backend/modules/world/tests/` 所用 `db_session` 建立在 SQLite StaticPool 单连接上、每测试一个外层事务（`backend/conftest.py:117-125`、`:145-166`），「两个事务/连接上并发 apply」在该层物理不可行；`_lock_page_universe` 在非 PostgreSQL 方言直接 return（`world_bible_lifecycle_service.py:936-938`）。**真并发断言只能在 PostgreSQL e2e 层实现**：`backend/tests/e2e/conftest.py:123` 的 engine 为 `pool_size=1, max_overflow=0`，用例须自建第二个 engine/连接并以事件编排交错两方——与 TASK.md「不以 SQLite 替代并发证据」对齐，列入 M3 验证矩阵。
- M1 现状对照（落 world 模块测试层）：顺序 apply 同一 dataset、页面重叠的两个 suggestion——第一个正常 accepted；第二个因来源/目标已变化、重放 `preview_hash` 不符被 409（`worldbook_import_service.py:127-133`）。**该用例证明的是双 hash 防串台，不证明 CAS 的并发覆盖范围**，不得据此宣称「现状已防住并发」。
- 真并发对照（M3 实现+验证）：两个独立连接同时 apply——两者均通过 `_claim_pending`（不同 suggestion 各自 claim 成功）与各自双 hash 重验后交错写同一工作稿，证明现有 CAS 不足（`suggestion_queue_service.py:1249-1270`；`project/services.py:663` 共享锁）；按第 6 条 M3 方案（dataset advisory lock + 锁内重放复验，a 另加既有 target 行锁）实现后断言：一先一后串行生效或后者 409，每个页面只保留一个确定性结果，无交错半写、无重复建稿；与 publish 链锁（项目级 `pg_advisory_xact_lock`，`world_bible_lifecycle_service.py:934-942`）并发时无死锁。
- 失败判据：同页内容交错（后半覆盖前半的非预期字段）、重复建稿或死锁；以顺序 409 用例替代真并发断言。

### 7.7 根改名后显式接续 legacy 来源（r4-1）

- 构造：先以 v1 旧算法（无 dataset 字段）导入 `理法之环/concepts/真名回响/理法之环.md` 等 2 页（legacy `source_path` 含根名，`worldbook_import_service.py:662`）；再显式声明同一 `dataset_name` 并选「接续旧来源」，根目录改名 `ring/…` 重导同内容包（新包 rel_path 为 `concepts/真名回响/…`，剥首段）。
- 现状对照：无接续语义时，同内容按旧算法生成新 source_key → 全 `create` 且旧条目 `missing`（根改名即重复建稿，7.3 的 v1 形态）。
- 契约行为：接续预览按「legacy `source_path` 剥首段 → 等效 rel_path」匹配成功，向作者展示待绑定映射（legacy 路径 → 新包 rel_path）；apply 后匹配条目补写 `dataset_key/rel_path/dataset_name/commit_mode` 等新字段、**不新建工作稿**（工作稿总数不变、无重复标题），三方比较按 preserve/update/conflict 正常判定；单段 legacy `source_path`（历史单文件提交、无根名）按剥根规则整段参与比较。
- 失败判据：匹配失败导致全 create+missing；补写后出现重复工作稿；预览展示的映射与 apply 实际绑定不一致。

---

## 8. 冻结字段总表（M2/M3 不得偏离）

| 载体 | 字段 | 冻结语义 |
|---|---|---|
| Manifest v2 | `schema_version` | Literal，写入恒 `world_worldbook_import.v2` |
| Manifest v2 | `source_format` | `auto` 默认；`obsidian/llmwiki/wiki_markdown/generic` 显式生效 |
| 兼容 | `source_format` 枚举消费方（r6） | 枚举扩展（如 `wiki_markdown`）须同步全部 Literal 消费方：Manifest（`schemas.py:2957`，含 auto）、Payload（`:3015`）、PreviewResponse（`:3061`，均无 auto）；suggestion 列表摘要与 `_validated_payload_json`（`suggestion_queue_service.py:319-320`、`:1108`）经同一 Payload 模型消费、随模型自动兼容，无独立硬编码枚举 |
| Manifest v2 | `dataset_name` | 作者声明名，服务端派生 `dataset_key`，不收客户端 key |
| Manifest v2 | `commit_mode` | `full_snapshot`（默认）/`append`，决定 missing 判定 |
| Manifest v2 | `dataset_intent` | `continue`（默认，v1 兼容）/`new`（撞已有 dataset_key 拒绝 400）/`adopt_legacy`（等效 rel_path 接续绑定）；`new`/`adopt_legacy` 必须携带 `dataset_name` |
| Payload v2 | `dataset_intent` | 与 manifest 同值固化；apply 重放从 payload 恢复；`dataset_key` 为空时必须为 `continue` |
| Payload v2 | `manifest_hash` | `sha256(schema_version + dataset_key + [{rel_path, source_hash}])`，根名不敏感 |
| Payload v2 | `preview_hash` | `{manifest_hash, source_format, dataset_key, dataset_name, commit_mode, items, ignored_paths}` |
| Payload v2 | 新增 | `dataset_key/dataset_name/commit_mode`（v1 归一化为 legacy 默认值） |
| Payload v2 | `legacy_bindings` | 接续待绑定映射 `[{source_key, legacy_source_path, rel_path, target_kind}]`（≤2000；r7 补 `target_kind: draft/page`，page 目标本轮不补写、预览如实标注）；仅展示与恢复预览，判定要素经 items 纳入 preview_hash |
| Payload v2 | `source_paths` | （r7 补记既有实现）rel_path → 原始提交路径映射（≤2000）：兑现第 2 条「source_path 携带旧值」，apply 重放按原语义回写 `page_meta.worldbook_import.source_path`；不参与任何指纹 |
| Payload v2 | `link_details` | （r7）逐条引用明细快照，按 `source_key` 分组：`raw/target/alias/anchor/origin/state` + resolved/unselected 附 `resolved_path/resolved_title`；随 payload 持久化支撑恢复预览、**不入指纹**；每页 200 条截断并标记 `truncated` |
| Preview 响应 | `dataset_intent`/`legacy_bindings`/`link_details` | 与 payload 同值回显（r7 补 `link_details`，并澄清 `dataset_intent` 无条件同值回显——payload 校验已保证 dataset_key 为空时恒为 `continue`）；恢复预览保持冻结语义（不重算） |
| Payload v2 | `files[].path` | 与 item.path 统一为 rel_path；apply 重放不二次剥根 |
| 剥离规则 | rel_path | path ≥2 段去首段，单段整段即 rel_path；包内 NFC+casefold 唯一，冲突拒绝（ValidationError→HTTP 400；preview 与 apply 重放均执行） |
| Item | `path` | rel_path（资料集内 POSIX 相对路径） |
| Item | `source_key` | `sha256(dataset_key\0rel_path)`（v1 路径保持旧算法） |
| Item | `link_summary` | 四态引用计数，纳入 preview_hash |
| page_meta | `worldbook_import` | 新增 `dataset_key/dataset_name/rel_path/commit_mode/dataset_root_name`；`source_missing` 写清/恢复语义不变 |
| page_meta | `worldbook_import.source_path` | 保留原始提交路径（含根名）不变；校验引擎 source_prefixes/清单消费（engine:408-420、service:1749-1751）不受影响；rel_path 只存新字段 |
| refs | `linked_asset_refs_json` | TargetRef 契约零改动；双链只写 `informs`；目标为已发布页一律写真实 id（含本批重导场景，r7③）；未发布目标用 `local:{dataset_key}:{rel_path}` |
| refs | `baseline_content_hash` | 物化 refs 的事务内按含 refs 字段组写入（导入流程授权口径）；其余路径禁止改写 baseline |
| 接续补写 | meta 补 dataset_key | 走 update_draft，接受 confirmation 失效 + 预览文案披露；不开 meta-only 窄 seam |
| 兼容 | v1 请求/payload | 行为与现状逐字节一致（auto 格式、项目级 missing、旧 source_key 算法） |

## 9. M1 完成判据与未决事项

- 本契约可审查即 M1 文档部分完成；七个失败场景（7.1–7.7）的用例落在 `backend/modules/world/tests/test_worldbook_import.py`（或同目录新文件），M1 收尾时在当前 HEAD 先断言现状对照行为；7.6 的真并发对照与互斥实现属 M3（PostgreSQL e2e，自建第二连接），M1 只落顺序 409 现状对照用例。
- M2 验收新增：已配置 `source_prefixes` 的 policy 页重导后校验结果不变（`source_path` 保留原始路径的直接回归）。
- M2 前端（r5）：导入面板须承载 `dataset_intent` 三态（新资料集/继续维护/接续旧来源）并展示 `legacy_bindings` 待绑定映射与接续补写的 confirmation 失效披露文案；`new` 撞名 400 的错误文案须提示继续维护或换名。
- M4 验收新增（r4）：含未解析/未选择引用的导入页发布 → 校验 `overall_result=("fail","block")`（`world_validation_engine.py:1281-1282`）属预期行为；预览与发布文案向作者披露「未选择/未解析引用会阻断发布校验」；引擎豁免（worldbook_import 页 dangling 降级 warn）不在本轮，须新契约修订并带引擎回归测试。
- M3 实现前定：第 6 条跨 suggestion 并发方案 a/b 二选一（含与 publish 链锁顺序核对）。**决定性差异点（r4）**：dataset 级 advisory lock + 锁内重放 `_analyze` 复验是 a/b 共同必选项，单靠 a 的行锁或包内 rel_path 唯一性都无法防「双方各含同一新 rel_path」的重复建稿；a/b 差异仅在是否再对既有 target 行取 FOR UPDATE 行锁。
- 未决（不阻塞契约）：`wiki_markdown` 是否首版实现；「接续旧来源」对已发布 page 的 meta 补写具体走发布链哪条路径与确认 UI（r7 精化：本轮 apply 不改写已发布 page meta，预览经 `legacy_bindings[].target_kind="page"` 如实标注，补写留待后续单独实现）；meta-only 窄路径作为可选优化，仅在作者验收反馈 confirmation 失效过频时再提，需同步 Evidence 侧语义。（r7 已关闭：「link_summary 明细进 payload 还是仅预览响应」定为随 payload 持久化、不入指纹。）
- 边界重申：`source canonical` 不自动发布、导入元数据不自行升级权限（TASK.md 决策 5）；本契约不改变白名单、大小限制、路径规范化、owner/novel_id 门禁与事务边界。

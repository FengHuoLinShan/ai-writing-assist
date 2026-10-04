# M1 来源契约 —— 理法之环 Wiki 导入与增量维护

状态：草案 r2，待审查（M1 交付物）。
修订记录：r2 按 2026-10-04 独立评审意见修订——修正基线 wikilink 事实错误；补冻 files[].path/rel_path 唯一性/source_path/baseline 口径/接续补写副作用五项；声明跨 suggestion 并发缺口及 M3 方向。
核查基线：HEAD `229491796b9b05fb753c02b8aa2168cbb11c04e4`（与 TASK.md 恢复快照一致）；工作树含其他任务的 writing WIP，本契约不涉及。
主计划：同目录 `TASK.md`（决策 1–6、里程碑 M1–M3）。本契约冻结所有影响预览的字段，M2/M3 实现不得偏离。

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
- 并发 CAS：`SuggestionQueueService._claim_pending` 用 `UPDATE … WHERE status='pending'` 原子置 `processing`，rowcount≠1 时抛 `SuggestionAlreadyProcessedError`（`suggestion_queue_service.py:1249-1270`）；apply 先双 hash 校验再 claim（`worldbook_import_service.py:117-137`）。**已知缺口**：CAS 只防同一 suggestion 重复 apply；两个不同 suggestion 并发 apply 均可各自 claim 成功，`update_draft` 默认无行锁、无基线校验（`world_bible_lifecycle_service.py:543-557`，`require_edit_baseline=False`），`require_active_project` 持的是共享项目行锁（docstring「Hold a **shared** project row lock」，`project/services.py:657-658`），不构成互斥——跨 suggestion 并发 apply 的缺口在第 6 条冻结 M3 方案。
- 冲突队列：`replace_worldbook_import_conflicts` 把同 source_key 的旧 pending `worldbook_import_conflict` 置 stale，再按 item 建新项，`target` 携带 source_key/source_path/target_id/suggestion_id（`conflict_queue_service.py:24-79`）。
- 工作稿写入的上下文失效链：`update_draft` 在 flush 后调用 `_mark_draft_context_changed`（`world_bible_lifecycle_service.py:588-593`）→ Evidence facade `mark_asset_context_changed`（`evidence/compilation/facade.py:1136-1156`，docstring「Invalidate confirmations that explicitly selected this working draft」，`world_bible_lifecycle_service.py:1807-1819`）→ 分发 `source.changed` observer（`facade.py:1157-1166`）。即**任何**经 `update_draft` 的 meta 写入（含现行 missing 标记写入/恢复 `:155-163`、`:207-215`）都会使显式选中该工作稿的 confirmation 失效，是第 2 条接续补写决定的直接依据。
- 世界校验引擎已有 wikilink 扫描与导入元数据消费：`world_validation_engine.py:22` 定义 `_WIKILINK_RE`，`:184` 起 `_scan_wikilinks` 分别扫描正文（`:549`）与 frontmatter JSON（`:559`），按 manifest 的 `link_lookup`/`anchor_lookup` 解析报 findings；`:409-417` 用 `page_meta_json.worldbook_import.source_path` 做 policy `schema.source_prefixes` 前缀校验；`world_validation_service.py:1742-1760` 的 `_lookup_manifest_item` 消费 `worldbook_import.frontmatter.aliases` 与 `source_path` 构建校验清单。是第 3、4 条冻结决定的直接依据。
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
- **rel_path 唯一性（冻结）**：同一提交包内，全部文件的 rel_path 经 NFC + casefold 归一化后必须唯一，冲突返回 422（preview 与 apply 重放都执行）。这是对现状防线的必要收紧：现状唯一性只对原始提交 path 去重（`worldbook_import_service.py:306-311`），API 直调可提交不同首段（根名）的混合包，剥根后 rel_path 相同 → 同 source_key 两个 item → `mapped_files` 按 key 覆盖（`:138`）且循环对两个 item 各 create 一次 → 重复建稿。
- 旧来源兼容：无 dataset 字段的请求沿用现行算法（`sha256(source_format\0path)`，基线不变）。站内已有 legacy 条目（meta 无 `dataset_key`）**不默默绑定、不批量改写**：仅当作者显式选择「接续旧来源」且新包 rel_path 与 legacy `source_path` 逐条相等时，apply 才为匹配条目补写 `dataset_key`（一次性、经预览确认、逐条可核对；对已发布 page 的补写走 M3 的显式确认路径）；作者也可选「重建新集」，legacy 条目保持原样、不参与新集任何判定。

**理由与证据**：现行 `source_key` 混入格式与含根名的完整路径（`:485`），根改名即换身份（TASK.md 决策 2；失败场景 C）。`_existing_sources` 全扫建索引（`:419-451`）说明成员资格天然以 `page_meta_json` 为真相，dataset_key 冗余进每页 meta 即可，无需独立身份表。补写 meta 不会误触三方比较：`_editable_content_hash` 不含 `page_meta_json`（`:612-622`）。「同名冲突」：同项目内两个不同 dataset_name 规范化后同名即同一资料集（key 相同，合理）；sha256 碰撞可忽略。

**影响字段（冻结）**：
- manifest（v2）新增 `dataset_name: str | None`（1–80 字符）；`dataset_key` 由服务端派生，**不接收客户端值**。
- payload（v2）新增 `dataset_name`、`dataset_key`（64 hex）；`payload.files[].path` 与 `item.path` **统一为 rel_path**（展示与身份与 manifest_hash 同基准）；原始含根名路径只存 `dataset_root_name`（dataset 级诊断字段）与每页 `source_path`（见第 8 节，语义保留原始路径）。apply 重放直接以 `stored.files` 的 rel_path 重算（`:121-126`、`:335-340`），**不得二次剥根名**，否则与 stored 的 rel_path 基准 hash 恒不等、所有 v2 预览 apply 恒 409。
- `page_meta_json.worldbook_import` 新增：`dataset_key`、`dataset_name`、`rel_path`、`commit_mode`、`dataset_root_name`（仅诊断）；**`source_path` 保留原始提交路径（含根名）不变**——校验引擎 `schema.source_prefixes` 前缀校验（`world_validation_engine.py:409-417`）与校验清单构建（`world_validation_service.py:1750-1752`）消费该字段，不得改存 rel_path。
- 「新资料集」选择时若派生 key 在本项目已存在 → 422，提示改用「继续维护」或换名。
- **接续补写副作用（冻结决定）**：显式接续为 legacy 条目补写 `dataset_key` 走 `update_draft`，接受其既有副作用——触发 `_mark_draft_context_changed` → Evidence `mark_asset_context_changed` → `source.changed` observer（`world_bible_lifecycle_service.py:588-593`、`:1807-1819`；`evidence/compilation/facade.py:1136-1166`），显式选中该工作稿的 confirmation 失效。这与现行 missing 标记写入/恢复路径（`:155-163`、`:207-215`）行为一致，不新增跨模块窄 seam；预览确认文案必须向作者披露「接续会使已选中这些工作稿的作者 AI 上下文确认失效，可重新物化」。不做静默绕过（直写模型会绕过既有不变量）。

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
- 站内物化（M3，沿既有契约）：`resolved` 且目标为已发布页（`WorldBiblePage` canonical/confirmed）→ 按 TargetRef 写入 `linked_asset_refs_json`，relation 固定 `informs`，`target_hash` 按现有指纹规则（`world_bible_lifecycle_service.py:1693-1698`）；目标为本批工作稿或未发布 → 用 `local:` 约定指向 `{dataset_key}:{rel_path}`（复用 `allow_local_refs` seam，`:1703-1704`；物化先例 `adoption_package_service.py:1160-1170`：发布/物化时将 `local:` 替换为真实 id），**不得伪造正式页 id**；`unresolved/unselected/ambiguous` → 保留链接原文并提示，不建 ref。每页 ref ≤100（`:1672-1673`），超限在预览明示。
- `alias`（`|显示文本`）与 `#段落` 原样保留在预览清单中，供导航与恢复；不参与身份匹配。
- **不产生 EntityRelation**；不凭同名融合既有页面（TASK.md 非目标）。
- **与既有校验引擎的关系（冻结）**：导入预览的四态解析与世界校验引擎的 `_scan_wikilinks` findings（`world_validation_engine.py:22`、`:184`、`:549`、`:559`）是**两套独立机制**：预览四态只服务导入范围决策与 ref 物化，不写 findings、不阻断导入；引擎 findings 服务发布校验门禁，发布时以引擎结论为准。两套身份口径不同（预览用 rel_path/标题；引擎用 manifest `link_lookup`/`identity_key`），不混用、不宣称互为等价。frontmatter `aliases` **不参与**预览「唯一标题命中」：歧义判定只看 title 与 rel_path——aliases 是作者声明的额外名称，纳入会扩大自动绑定面，违反「同名不猜身份」；引擎侧 aliases 消费（`world_validation_service.py:1742-1755`）保持现状不变。
- **baseline 口径（冻结决定，评审意见 1 三选一之 a）**：M3 物化 refs 的页面，`baseline_content_hash` 在**同一 apply 事务内按「物化后含 refs」的字段组写入**（即创建/更新该页时以最终 title/page_type/free_text/sections/refs/template 组合计算 baseline），声明这是导入流程授权的基线口径，仅导入写入路径使用，不含作者手动编辑。不这样做的后果：baseline 以 `refs=[]` 空口径计算（`worldbook_import_service.py:651-658`）而 `_editable_content_hash` 含真实 refs（`:612-622`），物化后任何来源变化都会从 `update` 误判为 `conflict`，违反 TASK.md「仅来源变化更新工作稿」。存量处理：v1 导入页未物化 refs（refs=[]），其既有 baseline 口径天然一致，无需迁移；M3 首次物化即切换口径，物化后的作者后续编辑使 current ≠ baseline，仍正确走 conflict。禁止在物化之外的任何路径改写 baseline。

**理由与证据**：当前代码无任何 `[[…]]` 解析（基线第 12 条），frontmatter 整体保留（`:670`）意味着 `related` 数据已在 `source_meta.frontmatter` 中，M2 只需读取不需要新存储。`allow_local_refs` + `local:` 物化是采用包已验证的同构先例，符合「未发布目标不得生成假正式页 ID」（TASK.md M3）。

**影响字段（冻结）**：item 新增 `link_summary`（`{resolved, ambiguous, unresolved, unselected}` 计数，明细进预览响应或按需展开，计数纳入 preview_hash）；`linked_asset_refs_json` 契约零改动（含 relation 枚举、上限、指纹）；`baseline_content_hash` 按上文口径决定随物化写入（字段本身不新增）。

---

## 5. 预览指纹：format、资料集、提交模式、目标基线全部纳入；恢复预览保持冻结语义

**结论**：契约升级 `world_worldbook_import.v2`（Payload 兼容读取 v1）。v2 的指纹输入为：

- `manifest_hash = sha256({schema_version, dataset_key, [{rel_path, source_hash}…]，按 path 排序})`——**用 rel_path 取代含根名的提交 path**，使根改名后同内容包的 manifest_hash 稳定（第 2 条目标在指纹层的对应物）；payload.files[].path 与 item.path 同为 rel_path（第 2 条冻结），apply 重放不二次剥根。
- `preview_hash = sha256({manifest_hash, source_format, dataset_key, dataset_name, commit_mode, items 全量 dump, ignored_paths})`——在现有三项（`:401-407`）基础上加入 dataset 与 commit_mode。目标基线仍通过 items 间接纳入（action/target_id/current_content_hash/reason 变化即 hash 变化），无需单独基线 hash。

**恢复预览冻结语义**：`get_preview` 保持「原样反序列化 payload，不重算」（`:96-108`）——返回的 items/counts/引用清单永远是预览当时的快照；apply 时才重放 `_analyze` 并按 v2 输入重算双 hash，任一不符 409（`:127-133` 机制不变）。前端「刷新后恢复预览」展示的即是冻结值。

**理由与证据**：`expected_preview_hash` 是应用前唯一防串台凭证（`schemas.py:3000-3008`），若 dataset_key/commit_mode 不入 hash，同一 hash 可在不同提交语义间复用，属安全缺口；manifest_hash 用 rel_path 是「根改名不换身份」的必要条件（否则 `:127` 的 manifest 比对会拒绝改名后重选的包）。v1→v2 兼容：`extra="forbid"` 且 `get_preview` 会反序列化存量 pending payload，v2 模型必须对 v1 payload 可校验——v2 全部新字段带默认值（dataset_key 可空 = legacy），schema_version 接受 `v1`/`v2` 双 Literal 并在读取时归一化。存量 v1 pending 预览的 apply 行为：重放会按 v1 归一化路径（旧 manifest_hash/preview_hash 算法、项目级 missing）计算，保证已存 hash 仍可匹配；仅在归一化无法成立时 409 要求重新预览，绝不静默改用 v2 算法比对 v1 hash。

**影响字段（冻结）**：`schema_version: Literal["world_worldbook_import.v1","world_worldbook_import.v2"]`（写入恒为 v2）；上述 hash 输入集合即冻结的指纹契约，任何后续字段变更必须再次升版本。

---

## 6. 跨请求状态：现有 suggestion + 页面 metadata 足够，不提 ORM/migration

**结论**：M1/M2/M3 全部跨请求状态沿用现有 JSON 承载，**本轮不提出任何新表或 migration**：
- 资料集成员资格与状态 → 每页 `page_meta_json.worldbook_import.dataset_key/rel_path/commit_mode`（页级即真相；资料集清单与成员聚合读取时按 dataset_key 分组构建，复用 `_existing_sources` 全扫模式 `:419-451`，项目内 bible 页数量级下可接受）。
- 预览与恢复 → `CreationSuggestion.payload_json`（现有，含 files 全量重放所需）。
- 并发/幂等 → `_claim_pending` 的原子 UPDATE CAS（`suggestion_queue_service.py:1249-1270`）+ apply 双 hash 重验 + 冲突队列 stale 替换（`conflict_queue_service.py:48-51`）。**CAS 覆盖范围声明（冻结）**：它只保证同一 suggestion 的重复 apply 产生一次结果（`SuggestionAlreadyProcessedError`）；**跨 suggestion 并发 apply 不在其覆盖内**——两个不同 suggestion（同 dataset、页面重叠）并发 apply 时都能通过各自双 hash 重验并 claim 成功，`update_draft` 默认无行锁无基线校验（`world_bible_lifecycle_service.py:543-557`），`require_active_project` 的共享项目锁不互斥（`project/services.py:657-658`），可交错写同一工作稿或对新建页重复建稿。TASK.md M3 的「并发重复 apply 只产生一次结果」不能靠现有机制达成，**M3 实现时必须补互斥**，方向二选一并在实现前定案：a) apply 事务内对本批 item 命中的既有 target 行（draft/page）逐个 `SELECT … FOR UPDATE`，新建页按 dataset 内 rel_path 唯一性兜底；b) 按 `dataset_key` 取项目级 advisory lock 后复验基线再写入。无论选哪个，都必须核对与 publish 链 page 行锁（`_lock_page_universe`，`world_bible_lifecycle_service.py:934`）的加锁顺序，避免新死锁。「跨 suggestion 并发 apply」列入第 7.6 节可测定义与 M3 验证矩阵。

**触发最小 migration 的条件（写明才提出）**：仅当出现 a) 需要按 dataset_key 的高效索引查询（资料集清单成为高频路径或单项目成员达数千页）；b) 需要 dataset 级跨页原子事务（成员集合同写同回滚）。届时方案也只是对 `page_meta_json` 的 dataset_key 建表达式索引/生成列（同步数据库文档），不是新表。当前证据（payload items 上限 4000、单项目 bible 页数百级、全扫已在生产路径运行）不满足触发条件。

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
- 契约行为：preview 返回 422（rel_path 归一化冲突），**不产生任何工作稿**；apply 重放同包同样 422。
- 失败判据：preview 通过，或 apply 产生 2 个相同 rel_path/标题的工作稿。

### 7.6 跨 suggestion 并发 apply（评审意见 5；M3 实现并验证，M1 仅落用例）

- 构造：同一 dataset、页面重叠的两个独立 suggestion（各自 preview 产生），在两个事务/连接上并发 apply。
- 现状对照：两者都能通过 `_claim_pending`（不同 suggestion 各自 claim 成功）与各自双 hash 重验，随后交错写同一工作稿——证明现有 CAS 不足（`suggestion_queue_service.py:1249-1270`；`project/services.py:657-658` 共享锁）。
- 契约行为：按第 6 条 M3 方案（target 行锁或 dataset advisory lock）实现后断言——两个 apply 一先一后串行生效或后者 409，最终每个页面只保留一个确定性结果，无交错半写、无重复建稿；与 publish 链 page 锁并发时无死锁。
- 失败判据：同页内容交错（后半覆盖前半的非预期字段）、重复建稿或死锁。

---

## 8. 冻结字段总表（M2/M3 不得偏离）

| 载体 | 字段 | 冻结语义 |
|---|---|---|
| Manifest v2 | `schema_version` | Literal，写入恒 `world_worldbook_import.v2` |
| Manifest v2 | `source_format` | `auto` 默认；`obsidian/llmwiki/wiki_markdown/generic` 显式生效 |
| Manifest v2 | `dataset_name` | 作者声明名，服务端派生 `dataset_key`，不收客户端 key |
| Manifest v2 | `commit_mode` | `full_snapshot`（默认）/`append`，决定 missing 判定 |
| Payload v2 | `manifest_hash` | `sha256(schema_version + dataset_key + [{rel_path, source_hash}])`，根名不敏感 |
| Payload v2 | `preview_hash` | `{manifest_hash, source_format, dataset_key, dataset_name, commit_mode, items, ignored_paths}` |
| Payload v2 | 新增 | `dataset_key/dataset_name/commit_mode`（v1 归一化为 legacy 默认值） |
| Payload v2 | `files[].path` | 与 item.path 统一为 rel_path；apply 重放不二次剥根 |
| 剥离规则 | rel_path | path ≥2 段去首段，单段整段即 rel_path；包内 NFC+casefold 唯一，冲突 422（preview 与 apply 重放均执行） |
| Item | `path` | rel_path（资料集内 POSIX 相对路径） |
| Item | `source_key` | `sha256(dataset_key\0rel_path)`（v1 路径保持旧算法） |
| Item | `link_summary` | 四态引用计数，纳入 preview_hash |
| page_meta | `worldbook_import` | 新增 `dataset_key/dataset_name/rel_path/commit_mode/dataset_root_name`；`source_missing` 写清/恢复语义不变 |
| page_meta | `worldbook_import.source_path` | 保留原始提交路径（含根名）不变；校验引擎 source_prefixes/清单消费（engine:409-417、service:1750-1752）不受影响；rel_path 只存新字段 |
| refs | `linked_asset_refs_json` | TargetRef 契约零改动；双链只写 `informs`；未发布目标用 `local:{dataset_key}:{rel_path}` |
| refs | `baseline_content_hash` | 物化 refs 的事务内按含 refs 字段组写入（导入流程授权口径）；其余路径禁止改写 baseline |
| 接续补写 | meta 补 dataset_key | 走 update_draft，接受 confirmation 失效 + 预览文案披露；不开 meta-only 窄 seam |
| 兼容 | v1 请求/payload | 行为与现状逐字节一致（auto 格式、项目级 missing、旧 source_key 算法） |

## 9. M1 完成判据与未决事项

- 本契约可审查即 M1 文档部分完成；六个失败场景（7.1–7.6）的用例落在 `backend/modules/world/tests/test_worldbook_import.py`（或同目录新文件），M1 收尾时在当前 HEAD 先断言现状对照行为；7.6 的互斥实现属 M3，M1 只落现状对照用例。
- M2 验收新增：已配置 `source_prefixes` 的 policy 页重导后校验结果不变（`source_path` 保留原始路径的直接回归）。
- M3 实现前定：第 6 条跨 suggestion 并发方案 a/b 二选一（含与 publish 链锁顺序核对）。
- 未决（不阻塞契约）：`wiki_markdown` 是否首版实现；`link_summary` 明细进 payload 还是仅预览响应（影响 payload 体积与 25 MiB 上限）；「接续旧来源」对已发布 page 的 meta 补写具体走 lifecycle 哪条路径（M3）；meta-only 窄路径作为可选优化，仅在作者验收反馈 confirmation 失效过频时再提，需同步 Evidence 侧语义。
- 边界重申：`source canonical` 不自动发布、导入元数据不自行升级权限（TASK.md 决策 5）；本契约不改变白名单、大小限制、路径规范化、owner/novel_id 门禁与事务边界。

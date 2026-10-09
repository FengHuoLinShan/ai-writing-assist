# RP 检索与编译重构：M1 实施契约

日期：2026-10-07（Asia/Tokyo）。状态：已实施；独立复审补齐匿名、容量、撤权和备份/恢复边界。
上游决策：[重构设计](2026-10-07-rp-retrieval-refactor.md)（五项调整与顺序）、
[第一阶段计划](2026-10-06-world-foundation-phase1.md) §5（D4/D5/D7）、
[ADR-0018 修订](../adr/0018-versioned-author-source-context-for-rp.md)（缓存例外）。
实测基线：[M0 实施笔记](../../.agent/tasks/2026/T-20261006-world-foundation-phase1-impl/TASK.md)。

本文把重构设计固化为可实施、可验收的模块内契约。实现事实以代码/迁移为准后回读更新；
与上游设计冲突时先回设计修订，不在这里静默改口径。M2 状态读取线的投影契约不在本文，
另行在 M2 启动前补充。

## 1. Evidence 内部五段分工

`compile_interaction_story_context()` 外部签名与语义保持；内部拆为五段，各段是
本模块内函数 + 有限数据结构，版本化边界如下（版本常量落在
`modules/evidence/indexing/__init__.py` 与 `compilation/contracts.py`，进缓存 key）：

| 段 | 职责 | 输入 | 输出 | 失败语义 | 版本键 |
|---|---|---|---|---|---|
| S1 查询规划 | 确定性生成语义输入、有界词法词项、metadata 参数；不调 LLM | 冻结 scope + 分区查询文本（当前输入/局面/人物/未决/必须记住/近期发展） | `RetrievalPlan`（§2） | 无外部失败；词法规划失败退化为词典命中项，不阻断 | `plan` |
| S2 候选召回与融合 | 词法/向量/metadata 三通道配额召回，合并去重、统一评分 | `RetrievalPlan` + 精确 manifest/截止/角色过滤 | `CandidateBundle`（候选+评分说明+各通道命中计数） | 单通道降级记录 warning，不冒充成功；无实质匹配返回空并保持 blocker 语义 | `retrieval`（词法索引数据版本另记 `index_version`） |
| S3 材料物化 | 经 Writing port 回读原文、执行 cutoff/知识边界/排除、激活次序与必需项，产出**完整预算前材料** | `CandidateBundle` + scope/visibility/manifest | `SourceMaterial`（§3.1） | 证明缺失/越界→现有 blocker 语义；hash/offset 校验失败丢弃并记 drops | `materialization` |
| S4 预算编译 | 按本次预算/tokenizer/渲染版本从完整材料裁剪编译 | `SourceMaterial` + `CompileSpec` | `CompiledPackage`（正文+指纹+included_refs+source_refs） | 必需项超预算→现有 blocker；非必需裁剪记录 | `render` |
| S5 使用记录 | 每次逻辑消费建本次 ContextSnapshot 与来源使用回执 | `CompiledPackage` + task/attempt 身份 | 现有 snapshot 契约（不变） | 沿现有 snapshot 失败语义 | 无（不缓存） |

段间只传上述结构；S2 以后不重新展开词项，S3 以后不重跑检索。非 RP 调用方
（作者检索、导入、地图、写作）逐条检查后适配共用 S1/S2 实现，输入语义不变。

## 2. RetrievalPlan（S1 契约）

- `semantic_input`：现有完整有界查询文本（embedding 消费），参与材料 key 的
  `semantic_input_hash`。
- `lexical_terms`：全查询总上限（建议 64 起步，待校准）的规范化去重词项数组。
  配额次序：冻结且可见的名称/别名 → 当前明确问题与关键动作 → 当前局面 → 近期发展；
  无词典命中的中文保留有界 n-gram。禁止简单取最前 N 项（较晚分区不得永久失去召回）。
  RP 使用 source revision 经截止/可见性/歧义筛选的目录，不用当前 World mutable 目录；
  通用作者检索仍用项目词典。
- `metadata_params`：`character_ids/chapter/cutoff/content_mode/source_manifest` 等现有参数。
- `candidate_params`：`top_k` 与三通道配额（初值 24–48/通道、融合上限 128，待校准）。
- 确定性：同输入逐字节可重建；规划内不读时钟/随机源。

必需身份/固定项不依赖词法召回，沿 S3 直接证明路径读取。冻结 `source_manifest` 的候选只按相同 chunk 身份去重，不按 embedding 相似度删除不同原文范围：相似措辞可携带不同人物语气、持有人或往事证据；通用检索沿原语义去重规则。

## 3. SourceMaterial 与缓存条目

### 3.1 SourceMaterial（预算前完整材料，敏感派生数据）

包含：身份边界块、激活引用块（key/reason/次序）、玩家知识块、原文证据 reads
（含 SourceRangeRefContract 与证明文本）、必需项集合、warnings、drops、
全部 proof 的来源引用集合。不含预算字段——预算只进 S4。

### 3.2 表设计：`context_interaction_source_cache`（evidence/compilation 归属）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `novel_id` | UUID FK→projects ON DELETE CASCADE | consumer 旅程项目；项目删除级联清理 |
| `source_novel_id` | UUID FK→projects ON DELETE CASCADE | 来源作者项目永久删除时级联清理缓存行 |
| `owner_id` | UUID | 冗余门禁字段；命中时与 consumer project 当前 owner 比对 |
| `material_key_hash` | CHAR(64) | §3.3 材料 key 的 sha256 |
| `material_key` | JSONB | 完整 key 字段；敏感项只存 hash（语义输入、玩家身份、策略均为 hash） |
| `material_body` | JSONB | SourceMaterial 序列化（含证明文本，敏感派生） |
| `material_body_sha` | CHAR(64) | 完整性校验 |
| `material_bytes` | INT | 容量核算 |
| `compiled_body` | TEXT NULL | 当前唯一编译正文版本；多预算写入替换 |
| `compiled_spec` | JSONB NULL | `CompileSpec`（§3.3 编译追加字段） |
| `compiled_sha` / `compiled_bytes` | CHAR(64) / INT NULL | 完整性与容量 |
| `method_versions` | JSONB | `{plan, lexical, retrieval, materialization, render, index_version}` |
| `expires_at` | TIMESTAMPTZ | 过期立即不可命中 |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

约束与索引：`UNIQUE(novel_id, material_key_hash)`（并发幂等：同 key 允许
`ON CONFLICT` 覆盖相同派生结果）；`(novel_id, expires_at)` 清理扫描；
`(source_novel_id)` 来源失效批量清理。256 KiB/条、32 MiB/consumer 为应用侧
写入门禁，按完整材料、compiled 序列化及其重复正文总字节核算（超限跳过缓存，不截断必需证据）；更新 compiled 同样受限。consumer 总额检查使用事务级 PG advisory lock，同 key 替换先扣除旧行，再计新行，DB 不设硬 CHECK（待校准参数）。
SQLite 单测窄适配（JSON 列同构），真实索引与性能以 PG 测试为准。

### 3.3 材料 key 与编译 key

材料 key 进 `material_key_hash` 的字段（任一实际影响材料内容的字段必须进 key
或被当场重验）：

- 身份与范围：`owner_id`、`consumer_novel_id`、`source_novel_id`、
  `source_revision_id`、`source_revision_fingerprint`、`manifest_hash`；
- 截止与视角：`cutoff_chapter`、`cutoff_offset`、`visibility_mode`（reader/character）、
  `viewpoint_target_hash`；
- 目录与知识：`reference_manifest_hash`（含知识条目）、`directory_fingerprint`
  （冻结目录整体指纹；无冻结目录的路径禁用缓存）；
- 策略：`player_identity_hash`、`reference_policy_hash`（固定/排除）、
  `ambiguity_resolutions_hash`；
- 查询：`semantic_input_hash`、`lexical_terms_hash`、`metadata_params_hash`、
  `candidate_params_hash`；
- 方法：`plan`、`retrieval`、`materialization`、`lexical`、`index_version`。

编译正文命中另要求 `compiled_spec` 一致：`budget_tokens`、`tokenizer_profile`、
`model_profile`、`render` 版本。预算不同→复用材料重新 S4；不得截短旧正文或从裁剪包
恢复证据。原作包 key 不混入私人 selection epoch；每轮生成与释放独立重验当前选中分支。

## 4. 命中、复验与失败语义

命中路径（同一入口服务初始编译与 Agent 补查；跨 worker/重启共用）：

1. 门禁重验：当前 principal/owner、consumer 与 source 项目活跃、source revision
   就绪、scope 一致。任一失败→fail closed（阻断，非 miss）。
2. 完整性：行未过期、`method_versions` 全匹配、`material_body_sha`/`compiled_sha`
   校验。失败→视为 miss 走原路径并标记损坏行待清理。
3. 证明重验：用材料内**全部** proof 引用（不止旧正文最终包含的来源）按现有
   hash/offset/可见性门禁重放；失败→miss（来源漂移）。
4. 正文 spec 匹配→直接返回；不匹配→S4 重编译（材料复用）。

失败语义：缺失/过期/损坏→原编译路径；撤权/归档/必需引用失效→失败关闭；
数据库故障向上抛出，禁止吞为 miss。同 consumer 并发以 PG advisory lock +唯一约束+短事务协调，
embedding/LLM I/O 不持数据库锁；重复填充幂等覆盖相同派生结果。
S5 每次消费独立建 snapshot/回执，不复制旧 attempt 成功资格。

## 5. 生命周期、隐私与运维

TTL 24h、256 KiB/条、32 MiB/consumer 为暂定值，M3 用真实编译尺寸校准后冻结并记录。
过期立即不可命中（查询条件），物理清理沿现有任务/维护机制，不新增常驻服务。
`public_demo_source=True` 匿名编译在共享入口禁用 fetch/store/touch，沿原编译路径；仅已登录私有 RP 可缓存。缓存行不进入项目导出、demo copy、公开 API、检索索引、日志与错误诊断；备份策略排除
本表数据；restore 在迁移后清空本表，兼容仍含缓存的旧备份，随后作冷缓存重建。回退：关闭缓存开关保留原编译路径与权威历史；应用回退
保留表结构；旧进程不消费未知 `method_versions`。

## 6. 验收与计量口径

- 延迟门禁按重构设计 §7：M 档 `search` p50<200ms、新查询暖态全链 p50<500ms、
  精确命中全链 p50<150ms；`search` 与 `embedding`（~200ms 计入全链）分开计量，
  不合并为 retrieve 单指标。p95/较大规模/并发目标补基线后冻结。
- 对照沿 M0 冻结样本族（`make eval-rp-cost-baseline`）+ 较大合成库/高频短词/并发；
  记录词项数、各通道准入/命中/候选数、EXPLAIN(ANALYZE, BUFFERS)、索引体积与回填
  耗时；A07–A12 场景按计划 §7.1 验收。
- 质量按 D7：关键证据召回、无答案行为、关键事实/身份/秘密/规则覆盖及固定/排除/
  同章 offset/不同角色/旧稿/归档/撤权对照；新旧检索允许结果变化，冷热同方法字节一致。

# 世界书完整闭环与校验能力内化（完善版）

> 基于 `PLAN (10).md` 完善（2026-08-21）。本文档保留了原计划骨架，补齐了：产品画像门禁、
> 事实对账（含 Vault 基线实测）、checkpoint 与 world-state schema 的 1:1 对齐、ReviewPacket
> 定义、任务/预算治理、数据模型与迁移、执行包拆分、风险与需用户确认项。
> 对账依据：仓库现状（只读探查，路径:行号可复核）、`worldbuilding-engine` 技能参考、
> 真名回响 Vault 实测（2026-08 时点）、`docs/product/user-personas.md`、AGENTS.md /
> CLAUDE.md / ADR 索引。

## Summary

- 在现有 `world` 模块内实现完整闭环：`seed → candidate → instance → 校验/审计 → 作者裁定
  → adoption package → canon → 依赖失效 → 下游复核`。
- 不把 Wiki Skill、worldbuilding-engine、WorldCheck 或 MCP 运行时直接嵌入产品；内化其状态
  模型、验证语义和审计流程，由现有确定性业务工作流编排。
- 支持两种目录导入：
  - Microsoft `llmwiki` 的 `.wiki/raw + .wiki/wiki + AGENTS.md` 三层结构；
  - 真名回响当前 Obsidian Vault schema，作为完整验收标准。
- 仅覆盖世界书闭环，不扩展到人物、故事总纲、Scene Contract 或正文生成。
- 目标画像仅为 **画像 A（长期创作作家）**；RP 用户（画像 B）路径不依赖世界书，本次不受
  影响（见"产品画像与体验门禁"）。

## 事实对账（计划假设 vs 实测现状）

> 本节是完善版新增。原计划大量依赖外部语义，以下为已核实的锚点；实现以仓库 ORM、
> migration、稳定接口和测试为准。

| 原计划假设 | 实测结论 |
|---|---|
| 复用现有 Generation Center、`CreationSuggestion`、core checkpoint、adoption package、Conflict Queue、Today/Attention Summary | 全部存在：`world_generation_center_service.py`、`suggestion_queue_service.py`、`POST /api/world/core-checkpoints`（`api.py:1127`，经 `adoption_package_service.save_checkpoint` 返回 `CreationSuggestionResponse`）、`conflict_queue_service.py`、`attention_summary_service.py`（已消费 `target_type="world_core_checkpoint"`）。 |
| schema_version / 建议类型约定 | 现有建议行以 `target_type`（8 个值：`core_entity`、`core_entity_draft`、`world_bible_page_draft`、`profile_field`、`entity_relation`、`entity_alias`、`world_core_checkpoint`、`world_adoption_package`，见 `suggestion_queue_service.py:998-1030`）+ `action_schema`（如 `world_core_checkpoint.v1`）表达类型与版本。新增类型沿用该约定：`target_type="world_design_checkpoint"` + `action_schema="world_design_checkpoint.v1"`、`target_type="worldbook_import"` + `action_schema="world_worldbook_import.v1"`（原计划 `worldbook_import.v1` 缺前缀，按现有风格统一）。 |
| 现有 adoption package 机制 | 已存在 `world_adoption_package.v1`（`schemas.py:3314-3340`）：item `kind∈{core_entity,entity_relation,world_bible_page}` × `disposition∈{include,open,rejected}` + `authority_kind`；apply 已实现 preview 零写入、`expected_preview_hash` CAS、锁后复验与 receipt（`api.py:1181`）。本计划是**扩展**（apply 增加可选 `validation_run_id`），不新建第二套采用机制。 |
| `linked_asset_refs_json` 增加关系类型 | 字段存在于 `WorldBiblePage`/`WorldBiblePageDraft`（`worldbuilding.py:149,292`），元素形状是 `{target_type, target_id, target_path}`（`shared/target_ref.py:14-57`，`target_type` 为 1–64 字符自由字符串，非固定枚举；`target_hash()` 提供 SHA-256）。扩展关系必须向后兼容：新增可选 `relation` 子字段并纳入 `target_hash()` 计算，不改变既有 refs 语义。消费方：knowledge graph、activation preview、synopsis、adoption package。 |
| `ReviewPacket` | 仓库中**不存在**该概念，是原计划未定义的新名词。本版第 2.2.4 节给出完整定义与 hash/覆盖账本语义。 |
| "WorldCheck/Ruby strict oracle" | 实为**三个工具**，边界不同，见下。 |
| 基线数字（296 pages、12,253 links、60 decisions、203 canon rules、12 principles、85 change records、35 physics claims、157 nodes、568 edges、0 errors、0 warnings） | **十项全部实测复现**（`ruby validate.rb --all` + find/rg/jq 独立复算）。但数字是"参考基线"，验收时必须用冻结快照重新生成（见 Test and Acceptance）。 |
| 六循环 / 22 切面 / 5 耦合链 / 12 压力测试属于"真名回响现有严格门禁" | **不准确**。这些维度定义在 Vault 页面 `wiki/syntheses/真名回响/社会真实度审查框架.md`（被 `世界观设计宪章.md` PHI-04、`世界观更新检查机制.md` 引用），机器可校验镜像在 `worldbuild.rb` 的 world-state.json schema；**Vault 的机器门禁（validate.rb）并不检查它们**。因此产品必须分两层：结构层对 validate.rb 语义，语义审计层对 engine 维度。 |
| 目录导入允许 Markdown/JSON/YAML | 与 AGENTS.md 硬约束的关系见下——是**全新上传面**，需 ADR + 用户确认。 |

### 0.1 三个 Ruby/CLI 工具的边界（验收 oracle 分工）

| 工具 | 位置 | 行为 | 在产品/验收中的角色 |
|---|---|---|---|
| `validate.rb` | Vault 内 `wiki/meta/真名回响/validation/` | `--all/--physics/--impact/--review`；只读；仅 Ruby stdlib（实测 2.6.10 可跑）；输出 `[ERROR]/[WARNING]` + SUMMARY 计数，**无 verdict**。`validate.sh --strict` 是 Vault 唯一正式全库门禁。 | 结构层验收 oracle。 |
| `worldcheck`（WorldCheck CLI/MCP） | `~/plugins/worldbuilding-engine/tools/worldcheck/` | `check/review/status`；verdict 枚举 `pass/mixed/fail/author-required/insufficient-evidence`；对 Vault 只读，状态写 Vault 外（`~/Library/Application Support/worldcheck/<project_id>/`）。 | verdict/finding 语义验收 oracle。 |
| `worldbuild.rb` | `~/plugins/worldbuilding-engine/scripts/` | `validate/audit/route/packet/template/init/invalidate`；仅 `init/invalidate` 为写操作；输入外部 world-state.json。 | engine 语义内化的对照参考（不直接调用）。 |

结论：验收必须**分别**对齐两个 oracle——结构计数对 `validate.rb --all`，verdict/finding
category 对 `worldcheck check`；"一致 verdict" 的说法只适用于 WorldCheck，validate.rb 只有
errors/warnings 计数。Ruby 仅作为本地只读验收 oracle，不进 Docker/生产运行时。

### 0.2 目录导入与 AGENTS.md 上传硬约束

- 现有文稿导入白名单在 `imports/parsers.py:38`：`.txt/.epub/.html/.htm/.mobi/.azw3`、
  单文件 50MB。AGENTS.md 明确"不得把例外扩展为通用文件上传"。
- 本计划的世界书目录导入（`.md/.txt/.json/.yaml`）是**另一条全新上传面**，必须：
  1. 作为 world 模块自有、owner + `novel_id` 门禁的受限面实现（参考世界对象图片受限例外
     的先例），**不复用、不放宽** `imports` 模块的文稿白名单；
  2. 在开工前形成 ADR（建议 ADR-0016）并取得用户确认（见"需用户确认项"）。
- 浏览器目录选择：File System Access API 在 Chrome/Edge 可用，Safari 受限。需要回退方案
  （`<input webkitdirectory>` 相对路径多选，或显式 zip 上传）——列为开放问题，由用户选定。

### 0.3 关键冲突与既定裁定（仓库现状提示的必须处理项）

1. **checkpoint 深度命名冲突**：现有 checkpoint 只有 `world_core_checkpoint.v1`，深度由
   `round_no` + `parent_checkpoint_id` 父子链表达，无 seed/candidate/instance 命名；
   `seed` 已被 `WorldAdoptionSeed`（`schemas.py:3158`）占用，`candidate` 与
   `ObjectStatus.candidate`（`shared/enums.py:48`）语义重叠。裁定：新 payload 增加
   `depth: Literal["seed","candidate","instance"]` 字段，语义取自 engine 的"最小充分深度"
   （`seed`=灵感方向/最小候选、`candidate`=系统完善档、`instance`=完整地区/文明/正典晋升
   档），与 `WorldAdoptionSeed`（采用包的种子引用）和 `ObjectStatus.candidate`（实体权威
   状态）**是三个不同概念**；README 与 schema 注释必须写明三者区分，validator 不得混用。
2. **adoption package 不重建**：`world_adoption_package.v1` 已实现 preview 零写入、
   `expected_preview_hash` CAS、apply receipt。本计划仅在其 apply 请求增加可选
   `validation_run_id` 门禁，不新造采用机制。
3. **Conflict Queue 目前只有一种类型**：`conflict_check_queue` 现有唯一触发来源是生成中心
   `semantic_inspection`（`conflict_queue_service.replace_semantic_inspection` 只处理该
   type）。目录导入的三方冲突需新增 `conflict_type="worldbook_import_conflict"`，并扩展
   `ConflictQueueService.list/resolve` 分派；不复用 semantic_inspection 语义。
4. **生成中心 semantic-inspection 与本计划的校验门禁是两回事**：前者是交互式"确定性错误
   阻断 + LLM 待处理检查项"，不持久化 run/verdict/receipt；后者是持久化、可复算、带
   门禁与签收的全量/定向校验。两者共存，语义检查发现的结构问题可作为 targeted run 的
   触发原因之一。
5. **LLM 同步/入队边界**：生成中心 chat/convergence/exploration/semantic-inspection/
   ask-world 是同步调用（1800s 上限）；建议任务/融合/别名关系/简介刷新/投影刷新走
   `@task_handler` 入队。校验 run（含语义审计）**必须入队**：提交时用
   `build_project_llm_execution_snapshot` 冻结 provider（secret-free），worker 恢复时用
   `restore_project_llm_execution_settings` 读取当前轮换后的 Key（先例：
   `world/tasks.py:182/201/322`）。
6. **新建议类型要进 attention 投影**：`attention_summary_service.py` 排除
   `world_core_checkpoint`；新增 `world_design_checkpoint` 同样排除（不可采用），
   `worldbook_import` 与 `world_adoption_package` 一样进入"待采用建议"attention，并同步
   前端 `todayIsland.js` 的 `attentionSuggestionIds` 路由。

---

## 1. 产品画像与体验门禁

> 原计划缺失本节；AGENTS.md 第 5 条与 `docs/product/user-personas.md` 第 4 节要求任何
> 用户可见功能在计划/Review 中明确回答。

```text
目标画像：画像 A——长期创作的专业/业余作家，尤其维护大规模世界书、已有 Wiki/Vault
          或 llmwiki 目录资料要导入的人。画像 B（RP）不涉及：RP 第一版不依赖世界书。
用户任务与情绪收益：世界变大后，"它现在健康吗、哪里矛盾、我该先裁定什么、导入会不会
          覆盖我的改动"仍然一眼可知；导入已有资料不丢来源；校验结果可行动而非问卷。
用户会喜欢的理由：一个"世界健康"入口同时给出生长进度、校验状态、待作者裁定与失效
          下游；导入有预览、冲突绝不静默覆盖；AI 只整理与质疑、不越权决定正史。
前端舒适度判断：高频路径短（导入→预览→应用；校验→看 findings→签收）；诊断细节进次级
          入口；全链路用户语言、无 raw ID/JSON/token；长任务按 operation receipt 原页
          恢复；晚到响应不覆盖新状态；空态/窄屏/误操作保护覆盖。
主要摩擦与风险：Safari 目录选择的回退体验；语义审计耗时与费用；author-required 数量
          失控会变成问卷式负担（必须控制"待裁定"条目数并按收益排序）；导入大目录的
          等待期。
验证方式：任务完成率（导入→预览→应用）、到达首次价值时间（导入到可读 World Bible）、
          warning 签收率、重复使用（每轮生长后主动跑校验）。当前无真实数据，均标记为
          产品假设，不伪装成用户验证。
结论：做（按画像 A 门禁通过；随附"需用户确认项"待开工前裁决）。
```

落地约束（贯穿实现与 Review）：

- 用户可见文案用作者语言：`pass→通过`、`mixed→需注意`、`fail→未通过`、
  `author-required→待作者裁定`、`insufficient-evidence→证据不足（需重跑）`、
  `stale→结果已过期`；不暴露内部枚举原文。
- "世界健康"渐进展开：首屏只给状态、下一步与最高收益的待裁定项；JSON、raw ID、token、
  Prompt 放诊断次级入口。
- 校验运行是作者发起的 AI 长任务：遵循 ADR-0013 operation receipt 模式（去重、最多两个
  attempt、只在原页恢复），符合 ADR-0009 附录 A（离开即卸载、不缓存活 DOM）。

## 2. Implementation Changes

### 2.1 世界观生长与导入

#### 2.1.1 checkpoint：与 world-state schema 1:1 对齐

- 复用现有 Generation Center、`CreationSuggestion`（表 `creation_suggestion_queue`）、core
  checkpoint、adoption package、Conflict Queue、Today/Attention Summary；新增
  `world_design_checkpoint.v1`（`target_type="world_design_checkpoint"`），不另建候选系统。
- checkpoint 增加 `depth: Literal["seed","candidate","instance"]`（语义见 0.3 第 1 条裁定，
  与 `WorldAdoptionSeed`/`ObjectStatus.candidate` 区分），`round_no` + `parent_checkpoint_id`
  延续现有父子链；payload 分区与 `world-state.schema.json`（schema_version 0.1.0）顶层区域
  1:1 对应（原计划遗漏部分已补）：
  - `project`：标题、种子、语言、模式（create/expand/audit/repair/promote/export）、状态；
  - `authority`：事实源、只读区、约束、锁定决策、作者必决、开放问题；
  - `premise`：核心差异、体验承诺、尺度、审美外衣、主题候选；
  - `knowledge_layers`：**作者真相 / 专家模型 / 公众信念 / 读者未知**（原计划"知识边界"
    不足以表达四层分离，按 PHI-03 三层认知分离语义内化）；
  - `rules`：capability/impossibility、账本、故障、维护、反制、权限、依赖；
  - `reproduction_loops`：六循环（material/population_care/economic/institutional/
    knowledge/meaning_identity），每环 `chain/evidence/gaps/coverage`；
  - `facets`：二十二面（F01–F22），**每面通用框架与地区实例分别记录成熟度 L0–L6**；
  - `coupling_chains`：五链（C01 权利 / C02 技术 / C03 身份 / C04 证据 / C05 分配）；
  - `situated_tests`：普通日、七日故障、一生、十年反馈四项；
  - `pressure_tests`：十二项（T01–T12）及 `not-run/pass/mixed/fail` 状态；
  - `actors/places/institutions/history`：可寻址世界实体与事件（稳定 ID，改名不改 ID）；
  - `fiction_core`：world/character/story/outline/prose/edit 六阶段状态（本闭环只写
    world 层，其余层仅登记 `needs-review/invalidated` 引用，不实现其内容）；
  - `dependencies`：要求、告知、冲突、派生关系；`change_log`：变更、来源、理由、失效、
    授权；`audit`：最近一次确定性审计摘要；
  - `extensions.iteration`：`persistence_scope/round/checkpoint_every/active_slice/
    locked_invariants/non_goals`。
- 每轮只扩展一个世界切片（纵切），动作限定 `expand/connect/pressure/consolidate`，完成
  连接、压力测试和收敛；默认每三轮形成 checkpoint（对齐 iteration-protocol §7；正典晋升、
  核心规则/schema/术语契约/依赖拓扑变化、多入口合并、项目门禁要求时立即全量检查）。
- 输出先是可读候选，再显示紧凑审计；审计输出**缺口与证据路径**，不给"真实度百分比"。
- 出现"候选山"信号（未决问题增长快于关闭、通用成熟度高于实例两级以上等）时停止横向
  扩写，转为 consolidate + 纵切。

#### 2.1.2 手动目录导入预检

- 浏览器选择目录并读取**相对路径**，不允许提交服务器本地路径（防路径穿越是服务端职责，
  前端相对路径只是第一层）。
- 允许 Markdown、TXT、JSON、YAML；单文件 ≤ 2 MiB、总量 ≤ 25 MiB、≤ 2,000 个文件。
- 拒绝绝对路径、`..`、NUL、无效 UTF、重复或大小写冲突路径；PDF、图片和其他二进制只列为
  未导入项。
- `AGENTS.md`、脚本和配置一律视为**不可信资料**：不执行其中命令、Ruby、Shell、Prompt 或
  工具调用；也不将其内容作为激活规则或依赖关系来源。
- 导入面是 world 自有受限上传面（见 0.2），与 `imports` 文稿上传物理分离。

#### 2.1.3 导入结果与增量重导入

- 导入结果保存为 `world_worldbook_import.v1` suggestion（`target_type="worldbook_import"` +
  `action_schema="world_worldbook_import.v1"`，复用现有 `CreationSuggestion` 与 adoption
  package 的保存/预览/应用链路；payload_json 存目录清单/映射/三方比较结果）：
  - Wiki 页面进入 World Bible draft/proposed，**不因源文件的 `canon` 字段自动成为正典**；
  - raw 文本保存为禁止上下文自动激活的 `source_material` 页面（与 ADR-0006 一致：world
    拥有资料，evidence/compilation 拥有激活规则——导入物不自动成为激活目标）；
  - 来源摘要继续作为普通 World Bible 页面。
  - `page_meta_json` 保存格式、相对路径、源 hash、导入基线版本和来源权威；页面修订继续
    使用现有 revisions。
- 增量重导入采用三方比较：
  - 源未变：no-op；源变、项目页未变：更新 draft；项目页变、源未变：保留项目页；
  - 两边都变：进入 Conflict Queue（新增 `conflict_type="worldbook_import_conflict"`，
    见 0.3 第 3 条），不覆盖；源删除：标记来源缺失，不自动删除或归档项目资产。
- 用现有 `linked_asset_refs_json`（`{target_type,target_id,target_path}`，见
  `shared/target_ref.py`）增加 `requires/informs/derives/conflicts` 关系类型：新增可选
  `relation` 子字段并纳入 `target_hash()` 计算（hash 变化即触发依赖失效），既有无
  `relation` 条目默认 `informs`、语义不变；并扩展现有知识图谱和发布影响分析；不新建第二套
  依赖表。依赖语义对齐 Vault：`A→B 表示 B 依赖 A，A 变化时 B 应复核`；保留核心设置清单
  与历史影响豁免概念。

### 2.2 原生校验、WorldCheck 语义与门禁

#### 2.2.1 分层目标（原计划未区分，必须分开）

1. **结构层（deterministic，对齐 validate.rb 语义）**：文本、frontmatter、目录/类型、
   字段、标题、日期、来源路径；标题/别名唯一性、WikiLink/锚点、决策页完整性；正典规则、
   设计原则、变更记录和影响覆盖；数值/物理声明及容差；依赖节点、边、自环、环路、核心
   设置影响遍历。输出 `[ERROR]/[WARNING]` + 计数。
2. **引擎层（deterministic + 语义审计，内化 engine 语义）**：
   - state-model §9 十条一致性不变量（canon 必须有来源/变更证据；covered/成熟度必须有
     证据；not-applicable 必须有理由；核心规则同时有 capability 与 impossibility；可重复
     能力必须有成本/失败/维护；上游失效下游不得保持未经复核的 valid；作者必决不得被自动
     删除或静默回答等）；
   - 审计九门序：结构门 → 本体门 → 知识门 → 社会门 → 体验门 → 历史门 → 反事实门 →
     叙事门 → 饱和门；
   - 风险分流动作：`CLOSE / SPLIT / KEEP-GATE / CANDIDATE / AUTHOR-REQUIRED`；
   - 全量交叉审计结论：`KEEP / SYNC / CANDIDATE / AUTHOR-REQUIRED / OPEN`。
   - 明确语义边界：**确定性校验不判定文学质量**；机器验证只证明已记录的结构与证据
     （对应 MCP 契约"工具成功 ≠ 文学通过"、semantic gate 由近读/作者裁定承担）。
3. **六循环/22切面/5链/12测**：在 Vault 中是散文级、不入机器门禁；产品内由 checkpoint
   结构化存储 + 语义 ReviewPacket 审计承担，不伪造为"现有门禁已覆盖"。

#### 2.2.2 验证政策生命周期

- 将 schema、正典规则、设计原则、数值声明和依赖配置保存为版本化 `validation_policy`
  World Bible 页面。只有作者采用的版本才激活；导入配置默认是候选。
- 政策版本进入校验输入 hash：任何相关页面、政策或依赖 hash 改变都会使旧 receipt 失效。

#### 2.2.3 确定性规则引擎与安全边界

- 生产实现使用 Python 和现有依赖；不把 Ruby 加入 Docker 或生产运行时。
- 规则仅支持固定的声明式操作符和允许列表函数；禁止 `eval/exec`、任意表达式、上传脚本
  和用户命令（对齐 MCP 契约：无状态只读计算、不接受任意文件路径、错误不暴露堆栈或本机
  敏感路径）。

#### 2.2.4 ReviewPacket 定义（原计划引用但未定义）

```text
ReviewPacket = 一次语义审计的分片载荷：
- run_id、policy_version、scope（targeted/full）、shard_index/shard_count；
- pages：分片内页面 manifest 条目（标题、类型、hash、状态，无 secret）；
- content：受限页面快照（仅审计所需正文；不含 API Key、任务上下文）；
- questions：由声明式 policy 生成的封闭问题集（九门 × 六循环/22面/5链/12测 × 路由
  问题的子集），每题要求 verdict + 证据定位 + finding category + 是否 author-required；
- outputs：每分片经 Pydantic schema 校验（不通过即该分片 failed）；
- coverage_ledger：每题"已答/证据可定位/跳过理由"；
- packet_hash = SHA-256(以上结构化内容)。
```

- 按确定性分页生成受限 ReviewPacket；每个分片经过 Pydantic schema 校验，最终汇总必须
  证明覆盖范围（覆盖账本并集）。预算不足、内容遗漏或 hash 变化均返回
  `insufficient-evidence/stale`，不得推进正典。
- 与 `writing/semantic_review.py` 的关系：复用其已验证的任务收据、task checkpoint session
  与超时/日志模式；**不复用**其正文语义与 Pydantic 契约（世界书语义自有 schema）。

#### 2.2.5 运行表、门禁与任务基础设施

- 新增唯一一张表 `world_validation_runs`（详情见第 3 节），持久化：
  `novel_id`、触发原因、targeted/full scope、页面 manifest、policy、dependency、
  ReviewPacket hash、`queued/running/completed/failed/stale`、
  `pass/mixed/fail/author-required/insufficient-evidence`、`pass/warn/block` 门禁状态、
  findings、omissions、覆盖账本、模型 snapshot、作者 warning receipt、attempt 计数、
  预算账本和时间戳。
- **任务基础设施（原计划缺失）**：校验 run 定义为 `@task_handler`（registry 注册，
  recovery_policy/max_attempts 明确）经 `enqueue_task`/`enqueue_coalesced_task`
  （ADR-0011 键控合并）入队，worker（`run_worker.py`）执行；使用
  `require_task_checkpoint_session` / task progress checkpoint（先例：
  `world/entity_fusion.py`、`world/tasks.py`、`writing`、`imports`）保证可恢复；超时、
  取消、stale 判定明确；同一 novel 同一时间只允许一个 full run（PostgreSQL partial
  unique index `WHERE status IN ('queued','running')`，先例：`import_workflow_runs`
  部分唯一索引 `imports/models.py:138-149`；SQLite 测试用应用层守卫）；作者发起的 AI
  长任务按 ADR-0013：receipt 去重、最多两个 attempt、只在原页恢复。
- **LLM 预算治理（原计划缺失）**：预算由确定性公式给出（按 manifest 页数 × 单价 +
  full 乘数），项目偏好可设置上限（默认保守值）；每分片超时与重试上限；超预算 →
  `insufficient-evidence` 硬阻断，并记录预算账本——**绝不静默部分通过**。
- LLM 提交时用 `build_project_llm_execution_snapshot` 冻结 provider/model（secret-free，
  只存 hash 与 key_configured），worker 恢复时 `restore_project_llm_execution_settings`
  以 snapshot 固定的 provider 读取当前轮换后的 Key（先例：`world/tasks.py:182/201/322`；
  `open_project_llm_client` 见 `project/llm_runtime.py:258`）；按确定性分页调用；model
  快照写入 run 记录。
- 分层门禁：
  - schema、安全、陈旧 receipt、阻断性冲突、`fail`、`author-required`、
    `insufficient-evidence`：硬阻断。
  - 普通 warning 或 `mixed`：作者查看具体 findings 并签收后可继续；签收记录保留证据
    （对应 MCP 契约 accepted_warning：保留 metric/位置/理由/SHA-256，只降级不删证据）。
  - `author-required` 不能用 warning 签收绕过，必须形成明确裁定并重新校验。
- 普通页面修改运行 targeted；世界核心、规则、政策、依赖、正典晋升和交接运行 full。任何
  相关页面、政策或依赖 hash 改变都会使旧 receipt 失效。
- draft publish 与 adoption package apply 增加可选 `validation_run_id`；存在激活政策且
  要求门禁时必须提交当前有效 receipt，否则返回结构化 `409 required_validation`。没有激活
  新政策的旧项目保持现有行为。

### 2.3 API、界面与兼容接口

- 新增（保持原计划清单，命名/形状按现有约定复核）：
  - `POST /api/world/bible/imports/preview`
  - `POST /api/world/bible/imports/{suggestion_id}/apply`
  - `POST /api/world/bible/validation-runs`
  - `GET /api/world/bible/validation-runs/{run_id}`
  - `GET /api/world/bible/validation-runs/latest`
  - `POST /api/world/bible/validation-runs/{run_id}/accept-warnings`
  - `POST /api/world/design-checkpoints`
- 保留 `/api/world/core-checkpoints` 及现有响应形状（`CreationSuggestionResponse`）；
  新 checkpoint 是向上兼容扩展，不迁移或删除旧 artifact。
- 所有接口执行 account owner、`novel_id`、Pydantic、hash/CAS 和任务权限门禁；API/facade
  只做适配与委托。`409 required_validation` 返回结构化 body；错误信息不泄露本机路径、
  堆栈或 secret。
- import preview 返回 manifest 摘要（文件统计、映射预览、冲突、不支持文件、hash），
  不回传全文；apply 前重算 CAS（manifest hash 未变才应用，防 preview/apply 之间的竞态）。
- World Bible 工作区增加渐进式"世界健康"入口：
  - 生长进度、校验状态、待作者裁定（按收益排序）、失效下游、历史 receipt；
  - 目录导入向导展示识别格式（llmwiki 三层 / Obsidian Vault 结构）、文件统计、映射预览、
    冲突和不支持文件；
  - 默认不暴露 JSON、内部枚举、Prompt、token、raw ID（诊断次级入口除外）。
- 前端实现走 Vue 3 SFC + `mountIsland` + bridge 的现有约定，不引入新基建：入口在
  `frontend-console/vue/views/world/`（`WorldView.vue`，`bible/WorldBibleTab.vue` 是现有
  World Bible 工作区）；"世界健康"作为 bible 子视图的渐进式面板（与现有"创设建议"/
  "冲突检查"按钮并列的入口按钮），组件经 `bridge/index.js` 的 `getApi/getRouter/
  getToast/getConfirm` 访问基建（现有用法见 `worldIsland.js`）；新增视图复用
  `mountIsland({viewName, component, load})` + `router.registerView` 模式。
- 校验长任务进度复用现有任务轮询模式（`GET /api/tasks/{task_id}` +
  `progress_events/acceptance_checks`；前端 `shared/workflowProgress.js` 与
  `views/world/workflowManagers.js` 的 `recoverActiveWorkflows` 模式）。
- 覆盖首次进入、空态、长任务进度、失败恢复、陈旧结果、冲突、离开恢复、误操作保护和窄屏；
  晚到响应不得覆盖新状态；签收与裁定为幂等操作（带 run_id + receipt hash）。

## 3. 数据模型与迁移（原计划缺失）

- `world_validation_runs` 表要点：
  - `id UUID PK`、`novel_id`（索引 + owner 可达性走现有项目门禁）、`trigger`、`scope`、
    `status`（queued/running/completed/failed/stale）、`verdict`、`gate`
    （pass/warn/block）、`policy_version`、`manifest_hash`、`dependency_hash`、
    `packet_hashes_json`、`findings_json`、`omissions_json`、`coverage_ledger_json`、
    `budget_ledger_json`、`model_snapshot_json`、`warning_receipt_json`、`attempt_count`、
    `created_at/started_at/finished_at`；
  - 单飞：PostgreSQL partial unique index `(novel_id) WHERE status IN
    ('queued','running')`；SQLite 测试走应用层守卫；
  - 与 `AsyncTask`/operation receipt 的关联字段按 ADR-0013 现有形状实现，不新造第二套
    进度表。
- 迁移：按 Alembic 现有约定新增 revision（命名 `YYYYMMDD_snake_description.py`，P0 时
  以当时最新 head 为准——当前为 `20260815_story_scene_assets.py`——新建
  `20XXXXXX_world_validation_runs.py`）；demo 阶段可重建开发库（AGENTS.md:77），但必须
  同步 ORM、Pydantic schema、调用方、测试和文档。
- 新 suggestion 类型通过现有 `CreationSuggestion`（表 `creation_suggestion_queue`）承载：
  `target_type="world_design_checkpoint"|"worldbook_import"` + `action_schema="<前缀>.v1"`，
  同步 `suggestion_queue_service` 的 target_type 分派、CAS/兼容影子与 attention 投影
  （0.3 第 6 条）；不新增 suggestion 表；`world_worldbook_import.v1` 的目录清单/映射/三方
  比较结果存 payload_json。
- `linked_asset_refs_json` 扩展：元素为 `{target_type,target_id,target_path}`
  （`shared/target_ref.py`），新增可选 `relation`（requires/informs/derives/conflicts）
  子字段；既有条目默认 `relation: "informs"`（保持现状语义不变）；`target_hash()` 把
  `relation` 纳入 hash（关系变化即触发依赖失效）；写入与读取均需迁移/兼容测试。

## 4. Test and Acceptance

- 后端单元/集成测试（`backend/modules/world/tests/`）覆盖两种目录适配、路径攻击、
  frontmatter/WikiLink/别名、规则与数值检查、依赖环、receipt 失效、warning 签收、硬阻断、
  CAS、owner 与跨 `novel_id` 隔离、单飞守卫、预算超限 → insufficient-evidence。
- 导入回归覆盖首次导入、重复 no-op、源单边修改、项目单边修改、双边冲突、删除、二进制
  忽略和中断恢复（task checkpoint 恢复）。
- 使用通用匿名 fixtures 覆盖完整流程；仓库和 CI 不包含真名回响正文、政策文件、路径或
  快照。
- **双 oracle 差分验收（原计划把两个工具混为一个，此处拆分）**：
  - 结构层：原生校验与 `validate.rb --all` 对同一冻结 manifest 得到一致的 errors/warnings
    计数与 finding 定位；
  - 语义层：原生门禁 verdict/finding category 与 `worldcheck check` 对同一冻结 manifest
    一致（verdict 枚举与 2.2.5 的五值 `pass/mixed/fail/author-required/
    insufficient-evidence` 一致；`validate.rb` 无 verdict，只比计数）。
  - 冻结 manifest = 当前 Vault 只读临时快照 + manifest 清单；验收后仅保留 manifest hash、
    统计和 receipts。
- 基线处理（原计划硬编码数字，此处硬化）：当前实测基线为 296 pages、12,253 links、
  60 decisions、203 canon rules、12 principles、85 change records、35 physics claims、
  157 nodes、568 edges、0 errors、0 warnings（2026-08 时点已实测复现）。验收时用
  `validate.rb --all` + find/rg/jq 脚本**从冻结快照重新生成**并记录生成命令与快照 hash；
  计划数字只作参考，不作为"当前"结论硬编码进代码或文档。
- 在临时副本注入预植缺陷，验证两边均正确阻断或降级。缺陷清单对齐九门审计序（原计划
  清单扩充）：悬空链接、别名冲突、政策变化、依赖遗漏、`author-required`、预算不足、过期
  packet，**新增**：知识层串层（作者真相混入公众信念）、capability/impossibility 缺失、
  无证据的 covered 声明、上游失效后下游未复核、not-applicable 无理由、canon 无来源证据。
- 允许专门验收任务把完整临时 Vault 内容发送给项目当前已验证 LLM；固定 provider/model
  snapshot，正文不进入日志，验收后仅保留 manifest hash、统计和 receipts。临时快照放
  Vault 外本地目录（Vault 位于 iCloud Mobile Documents，避免复制体触发 iCloud 同步）。
- 语义验收以覆盖账本和预植缺陷检出为准，不要求非确定性文字逐字一致；必须覆盖权威层、
  知识边界、六循环、22 切面、5 耦合链、12 压力测试和下游路由。
- 收尾运行 world/evidence 受影响测试、前端测试、E2E、prompt-contract、lint、完整
  regression，以及 `make docs-check BASE_REF=origin/main`。

## 5. 交付计划与执行包（原计划缺失；按 CLAUDE.md 拆分）

> 全部工作在隔离 worktree `codex/worldbook-full-validation`（基于最新 `origin/main`）进行，
> 不接触当前脏工作树。world 模块由单一 Agent 独占（AGENTS.md 并行约定）。每个包完成后由
> 主会话 review 再验收集成；执行交 sonnet 子代理（CLAUDE.md 模型分工）。

| 包 | 内容 | DoD / 门禁 |
|---|---|---|
| P0 基线与裁决 | 建 worktree；跑 `make docs-check` 记录基线；ADR-0016 草案（世界模块所有权、文本目录上传边界、验证政策生命周期、receipt/失效规则、LLM 预算与隐私、数据保留/永久删除、为何生产不引入 Ruby/MCP/自治 Agent）；"需用户确认项"先行裁决。 | 用户确认完成；ADR 入索引；docs-check 基线记录。 |
| P1 checkpoint 扩展 | `world_design_checkpoint.v1`（schema 19 区映射）、`POST /api/world/design-checkpoints`、Generation Center 每三轮 checkpoint 节奏、Attention/Today 汇总接入。 | world checkpoint 相关单测/集成；响应形状与 `core-checkpoints` 兼容。 |
| P2 目录导入 | 预检（0.2 约束）、preview/apply、`world_worldbook_import.v1`、三方比较、Conflict Queue 接入、`source_material` 禁激活、`page_meta_json`。 | 导入回归全绿；路径攻击/CAS/竞态测试。 |
| P3 校验引擎 | 确定性规则引擎（结构层 + 引擎层）、`validation_policy` 页面、`world_validation_runs` 表 + 迁移、ReviewPacket 语义审计、预算与单飞、门禁接线（draft publish / adoption apply 的 409）。 | 单元/集成含预植缺陷；receipt 失效/签收/硬阻断/预算测试。 |
| P4 API/UI | 校验与导入端点收口、世界健康入口（生长/校验/待裁定/失效下游/receipt）、导入向导、用户语言映射、receipt 原页恢复、空态/窄屏/晚到响应保护。 | 前端测试 + E2E；画像 A 场景验收；无 raw ID/JSON 泄漏。 |
| P5 验收与文档 | 冻结快照 + 双 oracle 差分 + 预植缺陷 + 语义覆盖账本验收；README、CONTEXT、`docs/modules/02_world.md`、`docs/01_数据库设计.md`、Prompt 体系、用户行为文档同步；ADR 进索引，本计划/验收作为历史参考不冒充当前架构清单；`make docs-check BASE_REF=origin/main`。 | 验收记录（hash/统计/receipts，无正文）；docs-check 全绿；完整 regression。 |

> 实施进度（2026-08-21）：P0–P5 已全部落地。产品运行时为原生 Python/Vue，
> Ruby 仅用于私有冻结快照验收。回执统计与 hash 见
> `docs/references/2026-08-21-worldbook-validation-acceptance.md`。

## 6. 风险、开放问题与需用户确认项（原计划缺失）

**需用户确认（P0 前裁决）**
1. 目录上传面：确认接受 world 自有受限上传面（.md/.txt/.json/.yaml ≤2MiB/文件、
   ≤25MiB/总、≤2000 文件）+ ADR；是否同时接受 zip 回退路径。
2. Safari 回退方案：`webkitdirectory` 相对路径多选 vs zip 上传 vs 只支持 Chrome/Edge。
3. LLM 预算默认值与项目偏好上限（涉及费用）。
4. 语义校验是否项目级开关（旧项目默认关闭，保持现有行为）。

**风险**
- 范围蔓延：以非目标清单（人物/故事总纲/Scene Contract/正文）为界，任何越界提案单独 ADR。
- 语义审计非确定性与成本：以覆盖账本 + 预植缺陷为验收口径；预算硬上限。
- Vault 隐私：临时快照放 Vault 外本地目录，避免 iCloud 同步副作用；正文不入日志/仓库。
- 脏工作树：全程隔离 worktree，不接触当前未提交改动。
- WorldCheck 状态写 Vault 外目录（`~/Library/Application Support/worldcheck/`）：验收脚本
  需声明并清理该 side effect。

**开放问题**
- 导入后 raw 的长期保留与清理策略（source_material 页面增长控制）。
- 校验历史（world_validation_runs）的保留窗口与清理。
- `validation_policy` 与既有项目/未来 llmwiki 导入政策的版本兼容期。

## 7. Assumptions and Delivery（继承原计划并修订）

- 实现从最新 `origin/main` 建立隔离的 `codex/worldbook-full-validation` worktree；开始先
  运行 `make docs-check`，不接触当前脏工作树。
- 增加 ADR（建议 ADR-0016），明确世界模块所有权、文本目录上传边界、验证政策生命周期、
  receipt/失效规则、LLM 预算与隐私、数据保留/永久删除，以及为何生产不引入
  Ruby/MCP/自治 Agent。
- 更新 world 模块 README、CONTEXT、数据库设计、Prompt 体系和用户行为文档。
- Ruby 仅作为本地只读验收 oracle（validate.rb 对结构计数、worldcheck 对 verdict），不复制
  第二套 Ruby 校验器；原生 Python 校验器是产品唯一运行时实现。
- 真名回响仅作为私有验收标准，不进入仓库、日志、迁移、fixtures 或公开文档。

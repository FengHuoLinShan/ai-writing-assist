---
id: T-20261004-ring-worldbook-import
title: 本机理法之环 Wiki 导入与增量维护
status: active
created: 2026-10-04T18:53:23+09:00
updated: 2026-10-04T20:05:00+09:00
---

# 本机理法之环 Wiki 导入与增量维护计划

## 恢复快照

- 实际完成：计划落盘并开始实施。已建任务主题分支 `codex/ring-worldbook-import`（HEAD 仍为 229491796b9b05fb753c02b8aa2168cbb11c04e4，本任务尚无提交）；M1 契约草案 r2 落盘至同目录 `m1-contract.md`：现状事实基线（api/service/schemas/validation engine/lifecycle 逐条行号）、六项冻结决定（显式 source_format、dataset_key 身份与 rel_path 剥根、commit_mode 两种提交语义、Wiki 引用四态与 TargetRef 物化、v2 预览指纹、JSON 承载不提 migration）、7.1–7.6 失败场景可测定义与冻结字段总表。业务代码、数据库和 Vault 均未修改。
- 当前里程碑：M1 进行中——契约文档部分完成（r2 待审查）；失败用例（7.1–7.6 现状对照）尚未落入 `backend/modules/world/tests/`。
- 下一步：审查 `m1-contract.md`（重点核第 2 条接续补写的 confirmation 失效披露与第 5 条 v1 归一化路径）；通过后把 7.1–7.5 及 7.6 现状对照用例落入 `backend/modules/world/tests/test_worldbook_import.py`，在当前 HEAD 复现现状行为。
- 阻塞：无硬阻塞。契约第 9 节记录三项未决（wiki_markdown 是否首版实现、link_summary 明细存放位置、接续对已发布 page 的补写路径），均不阻塞契约审查；目标作者项目、实际导入范围和付费模型预算尚未指定，真实写入或模型验收前必须确定。
- 工作区：分支 `codex/ring-worldbook-import`，HEAD 229491796（与 main 的 merge-base 相同，无本任务提交）。writing.md、WritingView.vue、WritingEditor.vue、writing-desk.css 属其他任务 WIP，保留不动。本任务未提交改动仅 `.agent/TASKS.md` 索引行与本任务目录（TASK.md、m1-contract.md）。
- 最后核实：2026-10-04T20:05:00+09:00；恢复时重新核对 HEAD、WIP 和资料清单。

## 目标与验收

让作者把本机“理法之环”及选定关联 Wiki 页面完整、可追溯地带入 NovelCraft 世界书，经预览形成工作稿，再沿既有校验与发布流程成为正式设定；后续可安全重导入同一资料集。

完成条件：

- 不需要选择整个 Obsidian Vault，也能明确识别选定 Wiki；原正文逐页保留，frontmatter 与来源指纹可追溯。
- 预览展示实际纳入、排除、未解析引用、名称歧义和三方差异；未确认前不创建世界书工作稿或正式设定。
- 唯一且同项目的 Wiki 引用可导航到对应资料，循环互引正常；未知或竞争目标保留原文并提示，不按同名猜测身份。
- 来源未变保留项目版本；仅来源变化更新工作稿；双边变化进入冲突；局部补入和其他资料集互不产生错误缺失标记。
- 工作稿、正式发布、作者 AI 上下文消费分别有可核查结果；不把导入成功等同于已发布、已激活或语义审查通过。
- 正常流、取消/失败恢复、过期预览、并发重复应用、owner 与 novel_id 隔离均有对应验证。
- 真实 Wiki 验收记录原文之外的清单、hash、覆盖与差异结论；原始资料、请求、输出留在仓库外私有目录。

非目标：自动修改本机 Wiki、常驻同步、上传整个 Vault、执行 Vault 脚本、重新建设导入模块、自动世界对象抽取、自动发布、RP 接入、部署。世界书引用与 EntityRelation 是不同语义，本轮不将 Wiki 链接转成对象关系。

## 上下文与边界

### 关键路径与来源

- 本机路径以 Obsidian 实时 registry 解析结果为准；已核实入口为 Wiki 的 `concepts/真名回响/理法之环.md`，其 `canon_status` 为 canonical。该标记只说明外部来源声明，不代替站内采用。
- `backend/modules/world/services/worldbuilding/worldbook_import_service.py`：格式识别、文件映射、preview/apply、来源比较及 missing 标记。
- `backend/modules/world/schemas.py`、`backend/modules/world/api.py`：导入 manifest、suggestion 和 preview hash 契约。
- `frontend-console/vue/views/world/bible/WorldbookImportPanel.vue`、`WorldBibleTab.vue`、`frontend-console/api.js`：目录选择、预览、应用与工作稿导航。
- `backend/modules/world/services/worldbuilding/world_bible_lifecycle_service.py`、World Canon authority：工作稿、发布、历史和来源重验。
- `backend/modules/evidence/compilation/`：上下文选择、可见性、confirmation 与失效；只经 facade 接入。
- 规范与旧设计：根及 World 的 AGENTS.md、ADR-0016、ADR-0017、`docs/references/2026-08-21-worldbook-full-validation-plan.md`。旧设计作为历史背景，当前代码为事实。

### 授权与数据边界

用户已授权实施：把本机理法之环等选定 Wiki 页面经预览、工作稿、发布流程导入世界书并支持安全重导入（M1–M5）。实施在任务主题分支 `codex/ring-worldbook-import` 进行；本任务不执行 git commit/push，提交由专门提交者统一执行，不合并 main。目标作者项目、真实导入范围与付费模型预算仍待指定，真实写入或模型验收前必须确定。

离线测试使用合成 Wiki 和专用可丢弃数据库；真实本机资料默认只读，不接入持续保留的诡秘之主验收项目。真实应用必须绑定指定作者项目与来源范围，外发给模型另行确定授权及预算。

现有文件白名单、大小限制、路径规范化、控制文件过滤、owner 与 novel_id、事务、预览指纹、冲突及 Canon 门禁继续有效。产品端不读取服务器任意本机路径；资料由浏览器明确选择后提交。

## 决策、发现与待核查

1. 当前格式识别依赖 `.obsidian` 或 llmwiki 目录标记。仅选择概念子目录会进入 generic，Markdown 映射为 source_material。增加受 schema 限定的格式选择；保留 auto 默认，不通过伪造配置文件解决识别。
2. source_key 当前由 source_format 与相对路径生成。根目录或格式变化会改变身份；需要稳定的资料集身份与根内相对路径，不能把本机绝对路径作为远端身份。
3. 当前 `_existing_sources()` 按项目取来源，分析把本次未出现的来源统一判作 missing。新增资料集范围和提交语义：局部追加不判断缺失，同一资料集完整快照才判断缺失；不同资料集隔离。现有无范围来源不能默默绑定或批量改写，保留旧契约并提供显式接续/重新建集选择。
4. 当前正文和 frontmatter 保留，但 apply 未物化 Wiki 引用。引用图可循环，不能把 `related` 或双链自动当作需要无环的因果依赖；只有明确声明的有向依赖进入既有依赖校验。
5. 理法之环原页混合作者真相、文明解释与角色认知。第一版按作者资料接入；沿 Evidence 查证工作稿、已发布页和 source_material 的实际消费条件。无法证明允许范围时保持排除，不靠导入元数据自行升级权限。
6. 资料集、链接映射和发布都是跨请求状态，优先使用现有 suggestion 与页面 metadata。M1 必须验证并发/CAS及完整快照身份能否可靠实现；若 JSON metadata 不足，才提出最小 ORM/migration，同步数据库文档。
7. 2026-10-04：M1 契约草案 r2 落盘（同目录 `m1-contract.md`），六项决定已冻结：manifest 显式 `source_format`（默认 `auto`，不伪造控制文件）；`dataset_key` 由作者声明名派生，页级 `source_key` 改挂 dataset 内 `rel_path` 且包内归一化唯一；`commit_mode=full_snapshot/append` 决定 missing 判定范围与资料集隔离；Wiki 引用四态解析（resolved/ambiguous/unresolved/unselected，同名不猜身份），resolved 目标沿既有 TargetRef 物化（双链只写 `informs`，未发布目标用 `local:` 约定，不产生 EntityRelation），baseline 按含 refs 口径随物化写入；预览指纹升级 `world_worldbook_import.v2`（dataset/commit_mode 入 hash，恢复预览保持冻结语义）；跨请求状态沿用 JSON 承载，本轮不提 migration。已知缺口：跨 suggestion 并发 apply 在现有 CAS 覆盖外，M3 实现前须在 target 行锁与 dataset advisory lock 间定案并核对 publish 链锁序。证据全部为 `m1-contract.md` 第 0 节的行号引用。

## 里程碑与实施顺序

### M1 — 固定来源范围与失败用例

- 沿实际导入、发布、上下文调用链核对接口，不复写旧闭环计划。
- 明确资料集生命周期、稳定相对路径、格式、追加/完整快照模式、旧来源兼容与重命名行为；冻结所有影响预览的字段。
- 构造最小合成 Wiki，先覆盖子目录被误识别、另一资料集误报缺失、根名变化造成重复、两边编辑冲突四个失败场景。
- 完成条件：契约与兼容策略可审查，失败用例可复现；无真实资料写入。

### M2 — 选择资料与预览

- 在既有导入面板增加明确格式及“新资料集/继续维护”选择。浏览器在已选择目录内读取资料，预览前保持本地。
- 首批默认以理法之环为入口，展示直接关联及未纳入引用；作者可扩展层级和选择页面。每次扩展显示文件数/大小，避免无界递归导入全库。
- 支持 `[[名称]]`、`[[名称|显示文本]]`、`[[路径#段落]]` 和 frontmatter related 的引用扫描；按明确路径优先，唯一标题次之。同名歧义与未选择资料只提示。
- 原始文件与正文不改写；导入包使用稳定相对路径，复制包和原始材料放仓库外。控制文件不作为作品内容发送，格式不依赖它们。
- 完成条件：作者能看清实际范围、排除项与引用缺口，取消与读取失败不改变站内资产；应用范围严格等于预览范围。

### M3 — 安全应用与站内引用

- 扩展现有 World schema/service/API 与前端 wire，format、资料集、提交模式和目标基线全部纳入预览指纹；恢复预览仍使用冻结语义。
- 三方比较仅在对应资料集中执行；完整快照缺失项保留历史，不删除资产，局部追加不产生 missing。
- 应用前重验来源身份、目标基线和项目权限；并发重复 apply 只产生一次结果，过期返回冲突。沿既有项目/领域锁顺序实现并验证。
- 先取得本批工作稿身份，再用既有稳定 TargetRef/引用契约建立站内引用；查证 draft 到 published page 的迁移规则。未发布目标指向工作稿或显示“待发布”，不得生成假正式页 ID。
- 保留链接原文、别名与段落信息；不产生 EntityRelation，不凭名称融合既有页面。显式依赖复用已有校验和失效机制。
- 完成条件：幂等、隔离、冲突与两种提交语义均通过；引用在创建、发布、重导入及目标缺失后仍可解释。

### M4 — 发布、作者上下文与端到端体验

- 使用现有校验、作者签收及 Canon 发布门禁；源 canonical 不自动发布。
- 经 Evidence 确认作者 AI 实际消费的版本、引用、排除项与上下文指纹；工作稿预览与已发布资料分别显示真实状态。来源更新使旧 confirmation/回执按既有机制失效。
- 确认 reader/character 路径不因导入新增作者隐藏真相；RP 仍不在本轮接入范围。
- 体验覆盖目录选择、预览、创建/更新、冲突处理、返回工作稿、失败后重试、刷新恢复预览和窄屏；费用及隐藏细节放次级诊断。
- 完成条件：合成资料的真实 API/数据库/浏览器闭环通过，能证明发布前后消费了哪一版本。

### M5 — 本机资料验收与交付

- 指定目标作者项目、文件清单和发布范围后，对本机资料做只读扫描，先预览再应用；保留原 Vault 和其他项目。
- 首批覆盖理法之环、关系信息实在论、星锻环、双月节点阵列、魔法 API、魔法传输链路、后台异步巡检、实例保全降扰模式；按实际引用清单补足或明确排除其他页面，不将此示例当作完整清单。
- 以临时副本修改一页验证增量、双边冲突、追加不报缺失、完整快照缺失不删除和重导入无重复；不修改原 Wiki 来制造测试。
- 免费离线验收先完成。真实模型如获授权，抽查本体定位、物理边界、智能边界、文明认知层四项，核对引用与未知项；单列模型、预算、覆盖和作者质量结论。
- 完成条件：交付去原文的验收清单、问题与范围说明；分开报告工程、真实资料、真实模型及作者验收。未完成真实验收时明确剩余项，不宣称全闭环完成。

## 验证矩阵与门禁

| 验证层 | 必须证明的行为 |
|---|---|
| Backend | 合成 Wiki 的 format/路径/大小/YAML、资料集隔离、两种提交模式、三方比较、旧来源兼容、重名/改名/缺失及引用解析 |
| PostgreSQL/API | 同项目并发 apply、预览后编辑与发布 CAS、跨 owner/novel 拒绝、失败事务回滚、响应后的跨 session 可见性；只用专用库 |
| Frontend | 范围/格式选择、预览与应用严格一致、恢复预览、异常重试、关闭/切项目期间异步结果归属、状态文案与可访问性 |
| Evidence/Canon | 默认未发布、source_material 不被激活、作者资料不进入角色视角、版本绑定、来源更新与旧 confirmation 失效 |
| Browser | 目录选择→预览→应用→工作稿→发布→作者资料选择→增量→冲突；桌面和窄屏，结果由 API/数据库验证 |
| 本机资料/模型 | 逐页内容完整性与引用覆盖单列；模型事实/引用质量和作者接受度分别记录 |

- 实施前和收尾运行 docs-check；收尾使用 `BASE_REF=origin/main` 并运行 `git diff --check`。
- 受影响 World 后端测试与 lint、导入面板/API 的 Vitest、前端 lint/build；变化涉及 Evidence/Canon 时补相应模块回归。
- 涉及迁移/并发时完成对应 PostgreSQL 及项目必需合并门禁，不以 SQLite 替代并发证据。执行命令以 development-guide.md、testing-guide.md 和当前 Makefile 为准。
- 同步 World README、`docs/modules/02_world.md` 与用户操作文档；仅在模型/跨域边界变化时补数据库设计、Evidence 文档与 CONTEXT.md。本计划不是现行公共契约。

## 里程碑进度

- [x] 当前实现核查与计划落盘。
- [ ] M1 来源契约与失败用例。（契约草案 r2 已落盘待审查；失败用例未落）
- [ ] M2 资料范围与预览。
- [ ] M3 应用、增量与引用。
- [ ] M4 发布、上下文与端到端体验。
- [ ] M5 本机资料验收与交付。

## 验证证据

- 2026-10-04：实施前 `make docs-check` 通过。该结果仅证明当前文档完整性，不证明本计划中的功能已实现。
- 2026-10-04T18:56:35+09:00：`make docs-check BASE_REF=origin/main` 与 `git diff --check` 通过；任务章节与开放索引链接检查通过。差异检查提示其他 writing WIP 的用户行为文档复核，本任务未改动该部分。
- 2026-10-04T20:05:00+09:00：文档同步轮。核查命令：`git status --porcelain`（工作树仅含其他任务 writing WIP 四文件与本任务笔记）；`git log main..HEAD` 为空、`git merge-base main HEAD` == HEAD == 229491796（确认分支无本任务提交）。`make docs-check BASE_REF=origin/main` 通过（输出 "Architecture documentation checks passed"；NOTE 提示 frontend-production 用户行为文档复核，属其他任务 writing WIP，本任务未涉及）；`git diff --check` 通过。
- 本轮未运行业务测试、前端测试、lint/format、真实导入、发布或模型请求：本任务至今零代码改动，无可测对象；上述门禁仅覆盖文档改动。

## 交付结果

- 已交付：主计划（本文件，含范围、已证实缺口、实施顺序、逐阶段完成条件与验收边界）；M1 契约草案 r2（同目录 `m1-contract.md`，待审查）。
- 未交付：M1 失败用例落地与 M2–M5 全部实现、验收。
- 交付边界：全部为本地未提交文档；分支 `codex/ring-worldbook-import` 无本任务提交，无推送、PR、合并或部署。
- 后续可选：世界对象/关系结构化、经明确知识范围授权的 RP 接入；均不计入本轮完成条件。

# NovelCraft 当前能力、工程风险与下一步开发依据

原始评估日期：2026-10-13；复核更新：2026-10-14。主工作树代码基线 `4116b657d38f8b7b45c2e18e091274a9c5fbc773`；原始远端基线 `974f0f5080d43472bc599d1d74782913c725057b`。二者差异为规则/任务文档。10 月 14 日核实远端 main 已更新为 `22bb499789cba89fea92e918fd853ab768688e07`（PR #222），当前主工作树及本地 origin/main 引用尚未同步。下文第 2–7 节保留原始基线事实并附更新说明；今日判断优先读第 0 节。其它工作树中的未提交实现不能算作主干能力。

项目已经形成具有来源、确认、版本和恢复机制的作者工作台，远超过单次 Prompt 写作工具。最成熟的基础是项目隔离、正文保存与版本、候选采用、确认上下文、任务回执和部署保护。原始评估建议先收敛运行时与验收证据、修复夜间门禁、证明长篇质量，再按作者任务完善反馈；其中夜间失败的修复已于 10 月 14 日合入，剩余优先项见第 0 节。继续同时扩张更多实验入口会增加验证负担。

目前不能据工程测试宣布“全书自动理解可靠”“连续性检查完整”“Codex 业务运行时已集成”“全部图片可灾难恢复”或“所有实验能力默认可用”。这些分别受长篇质量证据、消费者覆盖、在途代码、对象存储备份和功能开关限制。

本文及本轮复核只更新审计文档与图解，未修改业务代码、清理 WIP、调用真实模型或部署。PR #222 是另一个任务已完成的工程修复与合并，不能算成本轮执行。

## 0. 2026-10-14 复核更新：先看今天的分界

### 0.1 基线、合并与验证身份

- 已通过远端引用、GitHub PR 与固定 SHA 文件回读确认：[PR #222](https://github.com/FengHuoLinShan/ai-writing-assist/pull/222) 于 **2026-10-14 09:40:41（Asia/Shanghai）**合入 main，merge commit 为 `22bb499789cba89fea92e918fd853ab768688e07`。本工作树仍为 `4116b657d38f8b7b45c2e18e091274a9c5fbc773`，本地 `origin/main` 仍为旧基线；本轮没有 fetch、切换或写 Git 引用。
- PR 最终 head `7903bd03186bb8018a5834b7a96cb38519286963` 的 19 条 check-run 记录均 success（包含重复命名的文档检查）；这不是 19 种测试套件。合并 SHA 的新 push CI 在本轮读取时仍有检查运行中，不能把 PR-head 绿色等同于 merge-SHA 全部检查通过。最近已完成的 nightly 仍属于旧 SHA，不能代表新主干修复后的结果。
- 本轮对固定 merge SHA 的 27 个源文件/任务工件回读，并重算原始 CSV 的计数；这属于定向复核，未重新运行业务 test-ci、完整 PG、真实模型、作者验收或生产恢复。原始 3994 路径覆盖账本和测试结果保持快照身份。
- 完整修复与验证记录见固定 SHA 的 [DELIVERY.md](https://github.com/FengHuoLinShan/ai-writing-assist/blob/22bb499789cba89fea92e918fd853ab768688e07/.agent/tasks/2026/T-20261013-capability-tail-fixes/DELIVERY.md) 和 [ITEMS.csv](https://github.com/FengHuoLinShan/ai-writing-assist/blob/22bb499789cba89fea92e918fd853ab768688e07/.agent/tasks/2026/T-20261013-capability-tail-fixes/ITEMS.csv)。本轮核对快照见 [REVIEW-EVIDENCE.json](REVIEW-EVIDENCE.json)。

### 0.2 哪些原建议已经变化

| 原批次/候选 | 10 月 14 日核实的状态 | 仍须区分的边界 |
|---|---|---|
| A1 / C26 夜间两项失败 | offset 断言新增 known 依据、受影响 Scene 与未受影响反例；World/审查输入规范化后关系历史测试全部复用，总调用 **8**，不是改成 11 | 修复任务记录完整非真实模型 PG E2E 287 passed / 7 deselected；本轮未重跑，新 merge SHA nightly 尚无本轮已核实的完成结果 |
| A3 / C27 文案、保存影响、编辑排除 | 本机文本说明已纠正；覆盖未知转次级详情，真实失效保留；章节勾选替代裸 chapter 输入，补前导零、超过 200 项和迟到请求反例 | 原合成截图仍是修复前状态；日常完整作者闭环和真实价值未验收 |
| A4 / C01–04 私有清理 | 四个私有函数及两项常量已删除 | 54 行是原始候选函数体范围，不是整个 PR 的删行收益 |
| C13 / C17 / C18 职责与同域收敛 | 章锚解析、RP 同域指纹已收敛；Writing、Interaction、Scene 按职责拆分 | 入口 services 由 4554/3287/3081 行变为 108/1999/1725 行；实现移到领域文件，不是等量删除业务功能 |
| C14 / C15 / C16 / C19 CSS、查询、环境 | 55 组早期重复 CSS 已处理；索引状态 SQL 聚合、别名字典字段投影、独立 `.venv-eval` 已合入 | CSS 290 行仍是原候选上界；投影不等于消除所有来源扫描，查询/内存收益不等于 p95 或生产容量 |
| A2 / C10 运行时和评测 | 旧独立真实 eval 暂停门与前置校验已合入；避免在暂停检查前访问项目、耗 SUT 费用或占 holdout，旧 DeepSeek 绕行已关闭 | 新 Codex owner/provider 仍未在此 merge 接入；Project 迁移、Luna 校准、冻结 holdout 和真实长篇实测未完成 |
| B4 / C05–08 旧路径 | 私有 window adapter 已清理，直接旧文本 snapshot 分支被拒绝 | window 试验类/schema、历史 jobs/receipts、图片、公开 renderer 与 legacy GET 保留；整簇退役不能标为完成 |
| B1 / B2 / B3 / C1 / C3 | 部分工程前提改善，长篇质量、完整日常作者闭环、图片异地恢复、地图/正典登记、formal family/更多蓝图仍待处理 | 没有真实模型/作者评测、生产图片备份、生产代理拓扑或部署证据；默认关闭与 formal-disabled 边界保持 |

### 0.3 最新测试记录与原审计结果不混算

| 证据身份 | 已记录/已核实的结果 | 本轮限制 |
|---|---|---|
| 原审计：旧基线 | 后端 7736 passed / 2 skipped，86.76%；前端 2968 tests；PG critical 95；失败文件本地 2 failed / 21 passed | 保留第 3 节，不改成修复后的数字 |
| 修复任务：最终本地记录 | 后端 7746 passed / 2 skipped，86.8%；前端 237 files / 2977 tests；完整非真实模型 PG E2E 287 passed / 7 deselected；部署脚本 272 | 回读合入的证据与原日志，未在本轮重新运行；PG critical 95 与 full E2E 287 属不同集合，不能相加 |
| 修复任务：PR 最终 head | 19 条 GitHub check-run 记录均 success；WebKit/Chromium 移动核心各 11 项本地记录通过 | 不等于真实设备/IME、生产恢复或文学质量通过 |
| 合并 SHA 新 CI | 读取时文档、repo-gates、Backend CI、Production Image CI 与 CodeQL 完成成功；Frontend CI 仍在运行 | 状态是读取时快照；本轮不声称新主干全门禁已完成，也不创建监控 |

### 0.4 统计与引用修正

原始 3994 路径分级 91/1591/1708/604、历史 356 行/301 唯一 ID、旧命名空间 67 行与 CSS 55 组/290 行上界均与 CSV 一致。原 840591 行是 `.py/.js/.vue` 合计，未含 CSS 22544 行；本版以 `.py/.js/.vue/.css` 的 **863135 文本行**作为源码登记量，包含测试、工具、历史代码、注释与空行，不是生产代码净量。二进制的换行计数不纳入此量。

原报告两处路径简写补全为 `backend/tests/e2e/test_p2c_invalidation_recompute.py` 和 `backend/modules/world/services/worldbuilding/world_authority_service.py`。原覆盖 CSV 仍保留其登记时的方法，不因这次补读反向提高 10/13 覆盖深度。

本轮只读登记 **26 个 worktree**，其中 **8 个**包含 backend/frontend/deploy/Makefile/.github 范围的未提交或未跟踪改动，已不止原报告的 3 个；多个工作树可能是同一改动的副本，不能将数量解读为独立功能数。它们仍由原任务持有，不归档、合并或覆盖。

### 0.5 更新后的开发顺序

**优先 A2：收敛新 Codex 候选版本、Project 连接与授权、unknown 不重放、多 worker 容量及真实评测合同。** A1 的工程修复已合入，下一步核验新主干的全量门禁结果，不重新立项旧失败。随后用 B1/B2 的长篇与日常作者任务验证质量，并在扩张图片/公开内容前完成 B3 的备份与恢复。C1 地图/正典来源登记仍是明确缺口；A3/A4 和已处理的 C2 子项不再重复开发。

以下第 2–7 节保留原审计的能力、失败与候选依据；带“10/14 更新”的地方优先按更新阅读，原开发表是来源账本而非全部未完成清单。

## 1. 原审计范围与证据口径

### 1.1 已覆盖什么

机器清单确认 12 个业务模块、152 张 ORM 表、60 个任务 handler、16 个前端路由、40 个 ADR 文件。对审计开始时的 **3994 个 tracked 路径**建立 hash、大小、行数和方法登记，见 [COVERAGE.csv](COVERAGE.csv)。源码登记为 `.py/.js/.vue/.css` 文本行合计 863135；原 840591 未计 CSS 的 22544 行。该量含测试、工具、历史代码、注释和空行，不等于生产代码净量。

覆盖分级：91 个路径进行了定向区段阅读/调用链追踪；1591 个路径只达到 Python AST 与词法引用清点；1708 个路径达到文本引用/路径清点；604 个路径只有 hash 与路径分类。CSS 另用 PostCSS 比较规则、声明和媒体作用域。部分长文件只阅读关键区段；不宣称 3994 个文件逐行语义审计，也不把测试总数当成全部功能验收。

重点检查 owner/novel_id → facade/DI → confirmation/snapshot → provider/worker → 候选/采用 → 来源失效/恢复的链路，以及正文编辑、世界、结构、地图、导入、检索、RP、助手、有限协作、账号、运行时、存储、测试、发布与历史工件。

### 1.2 评估假设

面向独立作者持续写长篇，同时考虑多账户 API、后台任务和恢复。没有生产容量、峰值用户量、SLO 或预算数据，因此不给出可支撑多少用户、节省多少费用或 p95/p99 的数字。大文件、调用边和重复行只是维护成本信号，不能直接证明性能故障。

原审计只执行免费、合成、非真实模型验证；真实模型、真实作者、受保护稿件、生产环境与正式部署未执行。浏览器使用新建隔离 PostgreSQL 库、18474/18475 端口和脚本化 provider，经真实本地 API/worker 走流程，未使用真实 Key。“离线实验”指无真实模型 I/O，不表示所有步骤均无网络。脚本输出只能验证状态和权限流程，不能评价文学质量。

### 1.3 决策时应区分的四类事实

| 类别 | 本次证据 | 可以据此做的决定 |
|---|---|---|
| 当前实现 | 固定主干代码、ORM、路由、调用方 | 哪些功能已有、哪些兼容路径仍活跃 |
| 工程验证 | 本轮单元/集成、PG critical、生产资源构建 | 工程回归与隔离运行是否通过 |
| 作者体验 | 合成浏览器走查；覆盖范围见第 4 节 | 保存与失败提示、入口摩擦的小改动 |
| 产品质量 | 本轮未做真实模型/作者评测；旧证据单列 | 暂不能确定模型质量、全书覆盖或用户价值 |

## 2. 原始基线能力与缺口（附 10/14 更新）

### 2.1 账户、项目与模型配置

> **10/14 更新：** PR #222 未新增 Codex text provider/owner 连接；A2 的接线与真实校准仍待原任务收敛，旧文本直连分支另加拒绝门。

**已有能力。** 账户管理文本模型连接，项目提供非 secret 工作流设置；业务 LLM 通过 Project facade 获取 owner 当前已验证连接，可恢复任务保存 secret-free snapshot，并在恢复时读取轮换后的 Key。公开浏览器业务路径同时检查 account principal、owner 与 novel_id；归档/非活跃项目门禁与项目读写锁分开管理。账号清理已登记写作、世界资料、章序等本地草稿前缀，旧审计关于跨账号残留的缺项不能直接沿用。

**边界。** 当前主干并没有在途 worktree 中的新 Codex text provider/连接迁移。开发规则已要求 Luna/max 业务实测，不等于主干自动具备该连接。当前 local_agent 仅保留图片用途，项目恢复入口拒绝旧文本 local_agent snapshot；README 中“可用五种 CLI 执行作品 Agent 文本任务”的宣传已过时。

**下一步。** 先形成一个可评审的 Codex 候选版本，验证 owner 绑定、当前授权、请求包装、未知费用/结果恢复和轮换，再校准评测入口。不得通过回退旧付费模型绕开本次模型约定。

证据：`backend/modules/project/llm_runtime.py`，尤其 :208 附近；`backend/modules/account/settings_service.py`；`frontend-console/shared/accountStorage.js`；`backend/modules/local_agent/README.md`；第 5 节。

### 2.2 正文编辑、版本与生成

> **10/14 更新：** 保存影响提示与编辑排除已修，Writing 入口已拆至 108 行，真实候选质量仍未验收。下述 4554 行与空项目截图是旧基线。

**已有能力。** 正文工作稿、版本历史、发布、选段批注、候选生成/采用、独立审查、定向返修和冲突建议已有完整入口。保存及发布维护正文来源；候选写入绑定生成时的确认上下文与来源指纹，过期时拒绝采用。候选建议与正式正文分离，AI 流程不因返回文本就静默改稿。章节锁、版本与来源 CAS 是实质保护，不应为“简化服务”删除。

**已验证体验。** 新建首章、标题/正文保存、刷新后回读正常；断网保存时明确说明工作稿未保存，保留本地备份及导出/重试，网络恢复后同一 62 字内容成功保存。桌面及 390×844 编辑页面可操作；未验证移动设备键盘、中文 IME、Safari 和完整跨标签冲突链。

**缺口。** 空项目首次保存就出现地图集/正典依赖尚未核对的显著警示，既无地图又无旧演化结果时仍占用主编辑空间。当前服务文件约 4554 行，是后续修改的高成本点，但没有依据做一次机械拆分。真实候选的文学质量与作者采用率本轮未验证。

**下一步。** 按实际资产与消费者状态表达保存影响，未知覆盖放次级信息，真实已失效资产仍显著提示。下一次实质修改时按“保存/版本”“候选生命周期”“检查”拆出领域职责；保留事务与确认边界。质量验收应同时检查正常生成、来源漂移、拒绝/部分采用与作者修改后的恢复。

证据：`backend/modules/writing/services.py`、`semantic_review.py`、`conflict_ai.py`、`recompute.py`；合成浏览器截图；CI 中 Writing/Evidence 测试。

### 2.3 世界资料、人物、关系与正典

**已有能力。** 世界实体及类型档案、别名、关系、主题/分组、世界书页面工作稿/发布、采用与历史、对象图片、来源证据和待处理建议已存在。实体抽取倾向长期创作资产，别名附属于对象；身份解析的精确证据与待作者消歧分开。Canon 页面与选定来源清单已有实际实现。

**关键边界。** “有 Canon 页面”不等于通用事实断言推理系统已完成。World authority 的五个 formal family 当前都是 `formal-disabled`；AssertBatch 对相关 statement kind 拒绝，FamilyCutover 仍要求 accepted spec。该部分是有意冻结的能力骨架，不是可直接删除的垃圾，也不能宣传为正式多族断言引擎。

**已验证体验。** 空资料库、新建人物“林舟”、概要保存和详情页已采用状态正常。图片上传/清洗依赖对象存储，本次未接生产存储或运行图片模型。

**下一步。** 先验证人物/关系的来源、同名消歧、冲突不自动采用、修订保留历史。若正式断言是核心产品目标，按一个 family 的作者任务设计端到端闭环；否则保持冻结和清晰状态，不扩大空骨架。World 生产目录约 81781 行含多子域，不能把模块总量直接视为一个应拆的巨石。

证据：`backend/modules/world/authority.py:660`、`backend/modules/world/services/worldbuilding/world_authority_service.py:380` 附近；World README/facade；`backend/modules/evolution/identity.py`、`world.py`。

### 2.4 故事结构、Scene、连续性与伏笔

> **10/14 更新：** Scene workbench 按职责拆至 1725 行，章锚解析统一；叙事质量、地图/正典消费者缺口仍在。

**已有能力。** 故事 premise/方向、篇章与剧情线、Scene、Scene Contract、章节卡、结构生成/预览/采用、伏笔与揭示、滚动窗口及连续性子域已实现。Scene 的来源、章内位置和作者采用状态参与后续生成与重算。连续性已有六维状态及消费体系，不能继续沿用旧“只有人工 memory 空壳”的结论。

**边界。** 结构完备和规则测试通过不能证明剧情因果、人物弧、信息释放、节奏和读者体验正确。历史版本也不等于所有更改都能自动重放到所有消费者；地图/正典依赖仍有未登记面。`scene_workbench.py` 约 3081 行，编排重但不是纯转发。

**下一步。** 把“作者选择总纲 → Scene 细纲 → 正文 → 改稿 → 影响检查”的一个完整任务作为主验收，增加新/旧来源、跨章 Scene、改章序、拒绝建议等失败证据，再扩自动编排。保留规则未覆盖时的明确 coverage，而不是输出“检查通过”。

证据：`backend/modules/story/outline_state/scene_workbench.py`；`backend/modules/story/continuity/`；Story README；本轮 fast + PG critical。

### 2.5 文稿、世界书与表格导入

> **10/14 更新：** 四个私有函数/常量及私有 window adapter 已清理；window 试验 schema、deep_import、格式和历史恢复合同保留。

**已有能力。** 文稿解析、深度整理、Scene 切分/丰富/融合、实体/别名/关系、作者审查与采用、进度、恢复、取消和显式回收站均有实现。世界书导入带版本化来源范围。表格迁移只走独立 `.xlsx/.csv` 入口，预览后作者确认，再通过 World/Story 窄 facade 写入；只补空字段、冲突不落地、回执可撤销，不执行公式/宏。

**格式边界。** 文稿服务白名单含 TXT/EPUB/HTML/HTM/MOBI/AZW3，50MB 上限及内容/路径/压缩校验存在；锁定依赖与真实文件验收仅能证明前四种。前端对应只显示已验证类型。MOBI/AZW3 不能因枚举存在就计为已支持。

**旧路径。** 当前 deep_import 编排仍活跃，Evolution legacy adapter 只做请求映射，尚未接旧路由重定向。Phase2WorldExtractor 的 window 路径与私有 adapter 目前只由测试实例化，是独立退役候选；`scene_fusion.py` 已是活跃共享 schema，不能把旧 reducer 清理建议套在整个文件上。

**下一步。** 长篇能力优先处理批次容量、关系新对象引用、审查覆盖、进度与重复付费保护；这些正在其它 worktree 改动，先收敛而不重复实现。评估是否退役 window Phase2 路径，并保留被 eval/probe 使用的转换 helpers。导入与 Evolution 的统一迁移必须保留旧运行恢复和采用回执，不能只接新开始按钮。

证据：`backend/modules/imports/orchestrator.py`、`workflow.py`、`workflow_entity_phase.py`、`phase2_world_extraction.py`、`spreadsheet_migration/`；Imports README；CODE-CLEANUP C05/C12。

### 2.6 Evidence、检索与确认上下文

> **10/14 更新：** summary/freshness 已改 SQL 聚合，别名字典已改字段投影；全范围来源扫描、真实检索质量、公开 renderer 兼容仍不能算完成。

**已有能力。** source-bound grep/search/read/inspect/trace、候选回读、索引状态与租约、来源版本冻结、编译 Context、预算裁剪、selected/excluded、确认重物化、Scene 截止和角色知识过滤均已有工程闭环。旧 chunk 保留用于显式历史 revision 回读，不能当作脏索引一刀清空。编译后的实际保留项与遗漏项分开记录。

**边界与成本。** Reranker/Query Planner 默认开关与普通确定性检索分开，不能声称线上全部开启。索引状态 summary/freshness 仍加载项目全量状态再 Python 计数。导入每 Scene 的世界输入准备存在较宽对象/词项扫描；尚无长篇查询数、p95、内存证据。旧 bundle Markdown renderer 仍公开导出但正常编译消费者已用新 renderer，是兼容退役候选；bundle 本身仍有活跃消费者。

**下一步。** 优先固定真实问题集和 source/visibility 反例，证明引用质量与遗漏覆盖。性能改动先记录 SQL 数和规模曲线，再只优化候选准备/聚合，不取消最终来源回读。角色过滤与作者排除资产的反例是门禁，不能为吞吐省略。

证据：`backend/modules/evidence/compilation/services/confirmed_ai_action.py`、`confirmation_service.py`、`import_activation.py`；`backend/modules/evidence/indexing/index_state.py:723`、:755；`compilation/markdown_renderer.py`；技术实验结果与 PG issue209 scale。

### 2.7 Evolution、失效与局部重算

> **10/14 更新：** 两项失败已修复并合入；关系历史场景当前断言总调用 8，全部重算步骤复用。地图/正典消费者仍未登记。旧失败和成本分析保留在第 3 节。

**已有能力。** bootstrap/append/revise/scoped_recompute、顺序 Scene 提交、来源 manifest、observation/statement 区分、身份消歧、冻结调用、付费回执、待核对、不盲重试、ledger/discovery、独立审查与补充审查已有实现。选择性复用绑定实际消费者 read-set 与完整请求契约；旧证明缺失时失败关闭。后缀继承仍有保守停止条件，是已知范围限制。

**已测改善。** #209 对应 freshness 缓存/分页改动已经在主干。隔离 PG 在 1/10/100 Scene：warm 查询均 5；source check 分别由 5/50/500 降为 0；分页查询由 34/519/40908 变成 128/128/128。小场景 34→128 是有界分页的代价，不能只展示大场景收益或把开着的 Issue 当作未实现。

**未闭环。** 自动依赖注册仍明确不覆盖 `map_atlas` 与 `world_canon_revision`。当前夜间 E2E 两项失败见第 3 节；其中一个是新的 offset reason 与旧断言冲突，另一个是重算 World 请求指纹变化导致实际不复用，不能仅把调用数改为 11。现有安全保守门禁不等于最低成本重算已证明。

**下一步。** 先修验收契约和成本证明，再逐一登记地图/正典来源。对消费者证明不要只比较 scene_state hash，要比较真实输入与绑定来源；同一语义不同回执 ID 可以规范化，真实资料变化必须保守重算。

证据：`backend/modules/evolution/consumer_reuse.py:141`、`pipeline.py:1191`、`consumption.py:411`、`invalidation.py:57`、`workflow.py:842`；本轮 PG 日志与夜间复现。

### 2.8 项目助手、编辑台、引导流程与试改

> **10/14 更新：** 编辑台已改章节勾选，并补前导零、200 项与迟到响应反例；完整高频闭环与各默认关闭实验的作者价值仍未验收。

**已有能力。** 讨论、查证、注册工具、提醒、编辑台、任务提案、作者采用/拒绝、guidance、forecast/trial 等有实现。操作 schema、授权范围、来源重验、逐原子组应用与回执是业务保护；项目助手不是可以任意执行工具或跨项目写入的自由 Agent。

**开放状态。** Assistant 总开关及 editorial/automatic、guided flow、deep review/world stress/cross revision/research/import consult/blind reader 等开关默认关闭。浏览器 harness 本次显式打开的入口只是隔离验证，不代表生产默认已可用，也不代表每个蓝图都已完成作者验收。

**已测体验。** 合成讨论经过真实 API/worker 返回脚本化提案，UI 显示待作者确认；“暂不采用”后可以继续。编辑台明确“没有提醒不等于全书已检查”；作者编辑约定、保留项、检查范围和只用已保存正文的提示可见。网页检索未配置时明确禁用。脚本答复不针对本次内容，不能用来评价助手理解质量。

**缺口与下一步。** 多入口与多个实验模式会增加作者选择成本；编辑台排除资料仍要求输入 `chapter:12` 这类内部表达，宜改为章节选择。优先验收一条日常高频闭环（保存正文→编辑意见→作者处置→恢复），再决定开哪些模式；按工具成本/失败率记录价值，而非以工具数评价能力。

证据：`backend/modules/assistant/service.py`、`sessions.py`、`operations.py`、`editorial/`、`guided_flow/`；`backend/core/config.py:294` 附近；本轮浏览器与技术实验。

### 2.9 有限协作与合并

**已有能力。** ADR-0027 允许已注册业务蓝图的有限协作，单宿主、有上限成员、独立资料/历史和共享根预算/租约。case/grant、read-set、prepare/apply、项目独占锁、revision 校验、receipt/outbox、试运行与反向回滚都有实现。它并非实时多人共同编辑产品，也不授权开发代理自由组队。

**边界。** 原子组提交不等于全计划全局事务；用户部分采用/部分失败的产品语义需要显式呈现。离线团队实验只证明机制，不证明多成员比单 Agent 质量好或成本低。

**下一步。** 仅对单 Agent 确实失败的已量化作者任务比较协作，使用同输入、根预算和独立盲评。不要为证明技术可行新增成员自由通信或任意工具。

证据：`backend/modules/collaboration/merge.py`、模块 README；`backend/evals/collaboration_comparison.py`；technical-coverage。

### 2.10 RP、互动来源与长期记忆

> **10/14 更新：** Interaction 入口按职责拆至 1999 行，RP 同域指纹合并；真实 RP/长期记忆质量仍未验证。

**已有能力。** 私人旅程、选中路径、不可变故事节点、来源 revision 冻结、selection epoch、增量事件/SSE、知识边界 hold、摘要、分支选择、主动跟进与撤销授权已有实现。ADR-0018 的同 owner author→consumer 来源引用限定为只读，互动写入属于 consumer 项目。开局目录只列 owner 可用来源；匿名路径尚未共享同一目录。

**已走查。** 直接描述世界→角色/开场→创建旅程的步骤清晰，UI 告知私人分支不回写原作。脚本化 provider 未覆盖本次 RP guard 的有效判决，生成进入“未通过知识边界审查”且正文未释放；这是隔离替身不能完成此内容链的限制，不能当成真实 RP 模型缺陷，也不能称 RP 成功全验收。本次没有反复重试或调用真实模型。

**下一步。** 长篇记忆需按路径、时间、来源与 speaker 分别评测：错误来源/未来信息/被撤销分支的反例比“记得事实”分数更关键。先统一开发运行时并冻结评测，再测 50/100 轮、选择切换、断线重连、摘要更新和离开后授权撤销。主干 `services.py` 约 3287 行，在改变 attempt 生命周期时按职责小步拆。

证据：`backend/modules/interaction/services.py`、`generation.py`、`tasks.py`、`proactive.py`；Interaction README；本轮浏览器；离线 memory compile 不等于真实记忆质量。

### 2.11 地图、空间与对象图片

**已有能力。** 作者地图/空间示意、图层和位置绑定、Map Atlas 来源清单、保存 revision/CAS、图片专用上传、对象存储鉴权、对象配图与本机图片生成入口存在。World 图片仅 PNG/JPEG，<6MiB、4096×4096，去元数据转 WebP；不是任意文件上传。

**已走查。** 对象存储未配置时页面说明图库不可用，上传禁用，空间示意仍可编辑。没有静默显示图片已备份。

**缺口。** 图片依赖单盘 MinIO，首版明确没有外部图片备份；磁盘故障会丢失地图册和对象图片，数据库备份不能恢复它们。地图/正典尚未进入统一失效回执。空间关联规则不是全书路线和时间推理正确的证明。

**下一步。** 在扩张图片和公开内容前补对象图片备份与隔离恢复演练，定义接受的 RPO/RTO；之后登记地图来源失效。不要把本机 CLI 的目录限制宣传成 OS 沙箱。

证据：`backend/modules/world/world_object_images.py`；World map/atlas 子域；`deploy/README.md:94`；本轮地图空态。

### 2.12 本机 Agent、供应商与运行时

> **10/14 更新：** 本机文本说明已纠正，task_snapshot_client 直接文字分支已 fail-closed；历史 jobs、图片和公开恢复兼容保留，不是整个模块退役。

**已有能力。** 项目 owner 配置、provider schema、超时与受控重试、快照、运行回执、预算、授权与设备绑定存在。local_agent 仍用于本机图片与历史运行；本机能力不等于常驻任意文字 Agent。

**过时逻辑。** 文本 CLI client/runtime、task_snapshot_client 的 `_local_agent` 分支、companion 文本 job 和相关调用方尚存，而正常 project snapshot 恢复明确拒绝它们。这是跨层退役尾巴；必须保留历史结果显示、设备配对、图片和图片授权，不可直接删除整个模块。README/RP README 宣称文本能力与当前运行时不一致，应先修文档。

**下一步。** 与新 Codex provider 收敛同步完成文本退役清单，确认旧 pending job 如何终止/解释、历史 receipt 如何读取，再删除生产不可达路径及只为旧路径服务的测试。对新 Codex 不确定结果仍保持“不自动重放”，并验证多 worker 的全账户容量；单进程并发 2 不能视为部署级限制。

证据：`backend/modules/local_agent/client.py`、`runtime.py`、`executor_service.py:69`、`companion.py:222`；`backend/modules/project/llm_runtime.py:208`；在途代码第 5 节。

### 2.13 安全、数据隔离与输入边界

当前代码和工程门禁已建立 owner+novel_id、活动项目、CSRF/XHR、允许来源、输入 schema、HTML 转义、受控上传和公开网页 SSRF 防护。研究抓取限制公共 IP、DNS/连接目标、重定向、响应大小；前端 Vue 默认转义，动态 HTML 使用既有 esc。任务 handler 重新校验身份与项目，不接受浏览器伪造 system/worker 访问。

本轮没有复现跨项目泄漏、鉴权绕过或 P0 数据破坏；这不构成全面安全认证。外部认证、真实账号多会话、邮件、生产代理与网络 ACL 未测。Dockerfile 的 `forwarded-allow-ips=*` 仍是历史暂缓项，风险取决于真实代理拓扑，不能只凭此断言可被远程绕过。

建议保留这些门禁，优先以真实公共部署路径确认代理 peer、外部入口和账号连接隔离。不要为减少重复代码取消 fail-closed、确认重验、来源回读或事务锁。

证据：`backend/app/main.py`、`backend/core/dependencies.py`、Project gates、`backend/infrastructure/llm/web_search.py`、`backend/Dockerfile:47`；secret/依赖/import gates。

### 2.14 架构、边界与维护成本

> **10/14 更新：** 三处大服务、章锚解析、RP 指纹及一批确定私有清理已合入；下面旧行数与原门禁预算属于 10/13 基线，不代表今日新增缺陷。

架构优化已经实际合入主干：无顶层跨域直引，thin-facade、项目 LLM facade、api namespace、DI ports 等有机器门禁。当前导入检查通过：65 条有向边/预算 65，9 对双向边/预算 9，函数级跨模块 import 524/预算 524；World core→worldbuilding 为 0，反向 26/预算 26。达预算上限说明后续跨域新增调用要谨慎，不等于运行时性能故障。

生产大文件和大模块仍存在：Writing services 4554、Interaction services 3287、Scene workbench 3081；World/Story/Imports/Evidence 的总规模分别约 81781/44879/41717/37117 行。这些应在实质需求修改时按稳定领域职责拆，不适合为行数全面重写。API/facade 的真实协议转换保留，有业务编排的地方下沉至所属领域即可。

建议先完成少量确定清理，保持 hash 字节兼容、公开契约和测试覆盖，再对真正影响修改的职责做定向拆分。完整候选见 [CODE-CLEANUP.md](CODE-CLEANUP.md)，不能把旧 700/1400/780 行收益继续当作当前估计。

### 2.15 测试、评测与开发工具

> **10/14 更新：** 旧独立真实评测暂停检查已前移，DeepSeek reviewer 绕行已移除，技术实验使用独立 `.venv-eval`；Luna 校准与 Project 迁移仍未完成。下述环境干扰属于原审计记录。

工程测试较广：fast 覆盖率 86.76%，账户偏好与 eval 确定性测试已经进入默认门禁；旧审计的“测试完全不跑”已失效。PG critical 95 项通过；但夜间全量仍红。前端 Vitest 使用 DOM 模拟器，不能替代浏览器、真实 API 和设备。

真实评测存在模型合同漂移：Ask World teacher 固定 `gpt-6.1-sol`，部分 review/scene-gold CLI 仍限制旧模型/默认 `gpt-5.3-codex-spark`。testing-guide 已要求相关真实评测暂停至 Luna 校准。直接改模型名字会改变判分与历史可比性，必须重新校准并冻结 holdout。

另外 `eval-technical-coverage` 固定 Python 3.13，并复用默认 backend/.venv；本次运行实际替换了 CI 的 Python 3.14 环境，影响已启动的本次浏览器服务依赖路径。已恢复 3.14.7，并把浏览器移到独立临时 venv。该目标本身通过，暂态服务错误属于本次环境相互干扰，不计产品缺陷。建议显式 `UV_PROJECT_ENVIRONMENT` 按任务隔离。

下一步先修夜间门禁、评测模型/数据合同与环境隔离；再针对高风险边界而非实现镜像补测试。ResourceWarning 和 Pydantic OpenAPI warning 应定向治理，不能据测试进程 warning 宣称生产连接泄漏。

### 2.16 部署、备份、观测与运维

固定 SHA、origin/main 可达、干净工作树、detached checkout、发布状态、锁、迁移兼容、数据库备份配对与恢复脚本已有门禁；本轮部署测试 272 项通过。容器已有非 root、read-only、cap_drop 和 no-new-privileges，旧 AO 文档的“容器加固未实施”不能当作当前 Dockerfile/Compose 不具备保护。

边界是：未构建/启动生产 Docker 镜像、未查询生产 current-commit、未执行真实恢复演练或部署。MinIO 备份缺口仍明确存在。现有日志可观察任务/来源/用量，不代表生产监控告警、容量隔离和排队 SLO 已达标。

在多用户开放前，应确定图片灾难恢复、真实代理信任、worker/account 调度容量、任务 unknown receipt 的人工处置与可观测指标；保持发布授权与固定 SHA 门禁。

## 3. 原审计验证与实际失败（旧基线）

> **10/14 更新：** 两项失败修复已合入 PR #222；以下数字、日志及失败解释保留原审计身份，修复后验证见第 0.3 节。本轮没有重新运行这些业务检查。

| 检查 | 当前结果 | 证据与限制 |
|---|---|---|
| `make test-ci TEST_WORKERS=2` | 通过 | docs、secret hygiene、146 包后端依赖审计无已知漏洞、npm audit 0、ruff；部署 272；后端 7736 passed/2 skipped/13 warnings，86.76%；前端 237 files/2968 tests |
| 新建 PG17 隔离库完整 Alembic upgrade | 通过 | head `20261010_evolution_source_epoch`；未触碰既有库 |
| `make test-postgresql-critical` | 95 passed，92.89s | 明确 DATABASE_URL/E2E_DATABASE_URL；只本次库 |
| `scripts/check_module_imports.py` | 通过 | 边界及 thin-facade budgets 均符合当前门禁 |
| `make eval-technical-coverage` | 14 passed，2.26s；实验产物已生成 | 合成 retrieval/tool/collaboration/memory/MCP，未调用真实模型 |
| `npm run lint && npm run build` | 通过 | 444 modules transformed；16 local refs、59 JS bundles、96 published asset paths 验证通过 |
| 夜间失败的两个 E2E 文件本地复现 | 2 failed / 21 passed，13.95s | 下述同样断言失败；不是修改业务代码造成 |
| 本地浏览器 | 部分关键流程通过 | 合成项目、脚本 provider；RP guard 未完成有效结果链；未跑全矩阵 |
| 文档收尾门禁/保护校验 | docs-check BASE_REF=origin/main 与 diff-check 已通过；最终 hash 校验见 TASK.md | 不把未运行的检查填成通过 |

本次临时 API/Vite/PostgreSQL 已停止，合成数据与证据保留。原始日志、hash 清单与截图保存在仓库外 `/tmp/novelcraft-capability-audit-20261013`；该路径是本机临时证据，之后系统清理可能删除。去原文的计数与方法快照保存在 [EVIDENCE.json](EVIDENCE.json)。

### 3.1 夜间失败一：旧失效 reason 断言不接受 offset 命中

GitHub 主干夜间运行 [38324736239](https://github.com/FengHuoLinShan/ai-writing-assist/actions/runs/38324736239) 结果为 **2 failed、283 passed、7 deselected**；push 工程 CI 成功不覆盖此失败。

`backend/tests/e2e/test_p2c_invalidation_recompute.py:182` 只接受 `anchored_chapter_edited`/`conservative_expansion_unregistered`，实际回执也含 `offset_window_hit`。当前 `consumption.py:411`–:440 确有按已登记 offset 区间命中生成该 reason 的生产路径，因此旧断言与新增精确消费契约不一致。

最小后续：按被编辑来源及消费者实际读区间断言具体影响，并保留未命中/旧不透明来源保守扩张反例；不是简单把任意 reason 都放行。修复后运行整个对应 E2E 文件和 PG critical。

### 3.2 夜间失败二：关系历史场景的重算调用数与预期不符

`test_understanding_owner.py` 的 `[history]` 调用共享场景 `modules/evolution/tests/test_world.py:1669`，预期 10 次，实际 11 次。该场景先处理两 Scene、人工更改当前关系，再局部重算第二 Scene；历史描述仍从真实前缀读取，未被人工后文污染的断言已经通过。

额外诊断只记录 schema/request hash 和 read-set，未改变调用行为或断言：两次原处理各为 sample、entity、relation、audit 四次；重算复用 sample，但 entity、relation、audit 三次重做，总数 11。旧/new sample 的 read-set 一致，World/relations 的 `request` 与 `request_contract` 指纹不同。代码 `find_reusable` 明确要求证明完全一致才复用，所以不能先认定这是盲目重付费或缓存失效 bug。

最小后续：解释 World 请求差异来自真实候选/来源变化，还是无语义回执变化；前者应保守重算并更新成本预期，后者应补消费者安全规范化及反例。不要只把 `10` 改成 `11` 隐藏语义/费用回归。临时诊断 hook 的连接清理 warning 单独留在诊断日志，不当成正常生产路径问题。

### 3.3 非阻断 warning

fast 中 13 个 warnings 包含 Pydantic 对 OpenAPI query default 的序列化提示和若干 SQLite 连接清理 ResourceWarning。构建报告旧非 module script 由既有资源发布管线处理，最终资源验证通过。均需按实际调用影响决定治理，不是当前 P0；本轮未改变断言或隐藏 warning。

## 4. 原审计浏览器实测与未执行范围

> **10/14 更新：** 原截图是修复前状态；空项目影响提示与章节排除已在 PR #222 改善，另有 3 项编辑台浏览器记录，但本轮未重跑这些业务浏览器流程。

隔离项目“审计合成·渡口来信”，人物/正文均为本次原创合成，保护持久《诡秘之主》验收项目及既有数据库。走查记录：

| 作者任务/状态 | 观察到的行为 | 判定 |
|---|---|---|
| 首次选择作者工作区、新建空项目、首章 | 空态与创建入口可见 | 通过当前路径 |
| 正文保存/刷新回读 | 标题、4 段 62 字内容、工作稿状态保留 | 通过 |
| 断网保存 | 明确未保存、本地备份、导出/重试；未显示假成功 | 通过 |
| 恢复网络并重试 | 原内容成功保存 | 通过 |
| 390×844 编辑器 | 主操作可触达，未观察到页面横向裁切 | 通过此视口；无设备/IME 证明 |
| 空项目保存影响 | 不存在地图等资产时仍有显著未知覆盖提示 | 产品摩擦，应定向改善 |
| 世界资料库/新建人物/回读 | 已采用详情、概要可见 | 通过 |
| 故事结构空态 | 手工与 AI 预览入口、采用边界可见 | 只检空态，未运行生成 |
| 地图未配存储 | 明确存储未配置，上传禁用，空间示意仍可编辑 | 通过失败/配置状态 |
| 项目助手提案/拒绝 | worker 完成，方案等待作者，拒绝后可继续 | 通过机制，脚本结果无质量意义 |
| 编辑台 | 约定/范围/已保存正文、空意见书与未开启主动跟进明确 | 通过入口和空态 |
| RP 建立私人旅程 | 完成输入/创建；脚本结果未通过 guard，正文未释放，显示重新生成入口 | guard 阻断可见；内容链未验收 |

截图位于仓库外：`writing-desktop.png`、`writing-mobile.png`、`writing-offline.png`。未执行真实模型生成/编辑意见、完整导入与采用、图片上传、所有取消/冲突/恢复组合、浏览器全回归、Safari、生产账号和公开匿名路径。本轮通过不能扩展成这些路径的用户验收。

## 5. 原审计在途实现与主干的分界

> **10/14 更新：** 原 20 个/3 个是登记时快照；本轮为 26 个/8 个含生产路径改动的工作树。PR #222 已合入的工程修复与仍在途的 Codex/Luna 增量必须分开，不把原任务材料当成这次真实实测。

本次登记 20 个 worktree。除当前分支外，登记的 HEAD 多已是 origin/main 祖先，但 **3 个工作树仍含大批未提交生产代码**：codex-luna-runtime、codex-luna-timeouts、guimi60-bottleneck-final。它们有共同修改和新的 migration/provider/eval 文件；分支可达不代表 WIP 已集成，不能直接归档/删除。

只读看到的增量包括：Codex owner 连接与宿主 provider、包装/快照 hash 与未知结果不重试、进程内并发上限；Luna timeout/冻结来源；delta category 扩为 Text；关系 new_N 引用；discovery 候选容量与分组审查上下文；Scene 任务并发与阶段进度 UI。主干尚不能按这些描述签收。

在途验收材料曾记录某个冻结真实单元候选容量从 324 批降到 51 批、oversized 从 189 降到 0，这是已有材料中的局部结果，**本轮未重跑，不能代表 60 章全流程/最终 SUT/作者质量已过**。正在进行的比较仍由原任务维护；本任务不改其记录、不续跑模型、不重放 unknown 请求。

建议先由原任务收敛三个工作树至一个候选版本，固定代码/模型/数据/授权/冻结单位，再做差异评审、全工程门禁与单列质量验收。主工作树原有的 `T-20261012-guimi60-codex-comparison/TASK.md` 保留原状，不纳入本审计写入范围。

## 6. 原始清理候选与最新处置

> **10/14 更新：** 四私有函数/常量、55 组 CSS、索引聚合、投影和三服务拆分已合入；旧公开合同、试验和历史材料仍保留。下面是原候选来源，不能继续全部当作待开发/待删清单；逐项最新处置见第 0.2 节与 PR #222 ITEMS.csv。

完整清单、处理方式、依赖、验证与回退见 [CODE-CLEANUP.md](CODE-CLEANUP.md)。结论分为：

- 四个无 tracked 调用的内部私有函数，54 行函数体范围，加两项只被废弃函数消费的 Phase0 默认常量，是小批清理候选。
- Phase2 window 抽取、旧文本本机 Agent、旧 bundle renderer、legacy GET 等是跨层/公开兼容或测试维持的旧路径；必须先明确退役与恢复合同。
- CSS 当前 55 组同规则/同作用域重复，290 行是删除上界；中间覆盖规则会影响 cascade，不能一键删重复。
- 大文件、索引聚合/输入扫描、指纹重复属维护/性能候选，先测或随真实修改处理。
- 深度导入主流程、历史 source chunk、失败关闭、确认、图片模块、付费证据、设计稿与未提交 WIP 必须保留。

历史审计并非今天的待删清单。机器收录 unit 文件中的显式 ID 标题/表格提及 356 行、301 个唯一 ID（包括 cross-ref 和重复槽位），见 [HISTORICAL-CANDIDATES.csv](HISTORICAL-CANDIDATES.csv)。这不是历史 241 个问题的复算，也不是 301 个当前缺陷。未取得现况证据的条目标记 `historical_not_revalidated`，不能执行其旧命令；本轮高价值复核与当前候选单独详细列出。更早的简化审计还按独立命名空间保留 67 个显式 ID 引用，见 [OLD-AUDIT-REFERENCES.csv](OLD-AUDIT-REFERENCES.csv)；不能与后来的同名 X1 ID 混为同一发现。

## 7. 原始开发批次与验收（最新顺序见第 0.5 节）

规模为粗粒度相对估计：XS 单个小文档/函数清理，S 单链修复，M 跨层集成，L 新增领域闭环；不是工期承诺。

| 顺序 | 工作 | 为什么优先 | 依赖/规模 | 完成标准与回退 |
|---|---|---|---|---|
| A1 | 修两项 PG nightly 失败，明确 offset 与消费者复用契约 | 现有门禁实际红，直接影响发布可信度与成本判断 | S–M；先查 World 请求语义差异 | 固定 HEAD 全 nightly E2E 与 critical 通过；未命中/变化输入反例保留；代码/测试同时回退 |
| A2 | 收敛 Codex 在途实现、规则/评测模型与独立运行环境 | 当前模型规则与主干接线、评测合同不一致 | M；原任务 WIP 保护 | owner/snapshot/unknown 不重放/超时/多 worker 容量证据；单一候选版本；真实测试另获适用授权；旧回执可解释 |
| A3 | 修本机文本能力过时文档与空项目影响提示 | 直接误导作者选择与正常写作 | XS–S；不隐藏真实失效 | README 与运行时一致；空项目、已有地图/正典、已失效结果三种状态浏览器确认；可独立回退 |
| A4 | 小批确定清理：四私有函数、对应常量 | 低风险降低维护噪声 | XS；确认无外部/动态消费者 | 实际模块测试、ruff、引用核对；保留有效断言；独立 revert |
| B1 | 完成长篇导入→演化→世界/结构→写作验收 | 当前技术覆盖强于实际长篇质量证明 | M–L；A1/A2，固定数据与模型 | 分母含 dropped/omitted，来源/时间/身份/关系误配反例；费用、unknown、作者处置单列；不以 green tests 代替质量 |
| B2 | 统一作者保存→审读→处置→恢复日常路径 | 减少实验入口选择成本，验证实际价值 | M；B1可并行离线设计 | 首次/空态/失败/冲突/离开恢复/部分采用/390px；记录作者完成率与建议采用原因 |
| B3 | 图片异地备份与隔离恢复 | 现有明确单盘数据丢失风险 | M；存储/成本/发布授权单独处理 | 两 bucket、元数据和权限恢复，实测 RPO/RTO，不把 DB备份冒充；失败回退旧发布但不丢对象 |
| B4 | 退役旧文本 CLI、window Phase2、bundle renderer | 减少双轨和虚假测试保障 | M；依赖退役与历史兼容合同 | 主入口/恢复/历史读取/公开契约可解释；先缩面再删；逐簇 revert |
| C1 | 地图/正典消费者接入失效账本 | 补当前明确覆盖缺口 | M–L；来源合同/版本绑定 | 改图/改章/改正典触发正确消费者；后文不回流当前 Scene；未知保持显式 |
| C2 | 查询聚合、导入输入扫描、CSS 和职责拆分 | 改善已量化瓶颈与维护点 | S–M；先 SQL/内存/浏览器基线 | 同一输入与语义，查询/渲染收益记录；不改 visibility/hash/确认；无收益不改 |
| C3 | formal authority family、更多实验蓝图或协作 | 产品目标明确后再扩展 | L；真实作者价值与 accepted spec | 单 family/单蓝图端到端作者采用、冲突和回退；可冻结开关，不传播为默认能力 |

原始审计建议 **A1+A2：把当前运行与验收收敛到可信的固定版本**；10/14 A1 修复已合入，现在优先 A2 并核验新主干门禁，不重复实现 A1。之后以 B1/B2 的完整作者任务决定扩能力还是继续简化。避免先全库重构、切新栈、换存储/队列、批量删除历史目录或同时开启全部实验功能。

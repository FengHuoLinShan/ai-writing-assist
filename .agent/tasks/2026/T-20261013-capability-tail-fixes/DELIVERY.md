# 自主收尾交付

目标：按能力审计报告逐项完成无需用户决策的代码、文档与工程验证，并完成三个大文件的职责拆分。32类处置见 [ITEMS.csv](ITEMS.csv)。这份交付不把公开契约退役、新产品能力、真实模型质量或生产操作自动算作已完成。

## 已实现

- Imports 删除四个无消费者私有函数、两常量及 unused imports；另删除私有 window LLM adapter 与专属配置读取。当前按 Scene 主链、schema/probe/转换和冻结 window 试验保留。
- World/relations 采用既有 sampler 的语义 manifest 口径，排除宿主运行标识，保留来源、事实与前缀读集；相同输入的抽取和审查可复用，结果在新 attempt 重物化，采用前继续来源重验。PG历史测试验证四种消费者的 reused_from 以及真实前缀未被篡改；offset失效保留前章不受影响、后续保守扩大和章级消费者。
- 索引 summary/freshness 改SQL聚合，保持NULL相等、成功状态、novel隔离和章节范围；600行测试的原660次对象hydration降到0。别名词典只投影id/name/type/status/aliases，保留原排序及数量上限后再过滤状态。投影测试含30万字符无关字段、退役别名、review与空值，并在PG复验。未宣称长篇p95或生产容量改善。
- Writing原4554行分为draft_service、conflict_check_service、generation_service与service_support，原services稳定导出仍在。Interaction原3287行按主编排、journey_views、journey_overview和support拆分；Scene原3081行按主编排、fusion、health和support拆分。各class的实例、repo、状态与外部调用保持，264个方法参数/装饰器/async形态逐一与基线对拍一致。Prompt绑定与静态安全门禁查实际新文件，未降低assert或依赖基线。
- 章节锚由Story合同提供，Writing复用既有延迟facade避免循环；RP两个同字节指纹共用同域helper，历史Unicode/UUID/JSON空格有golden保护。其它编码与读集合同不跨域机械合并。
- CSS只删除55条更早相同规则（selector、声明及完整at-rule作用域均相同），保留最后规则。编辑台按章名勾选，保存/刷新恢复/撤销，保留旧非章节排除项并可重新纳入；列表失败保留已有选择。保存回执中的纯资料核对及明确零计数动作折叠到详情，未知覆盖仍可查看；实际失效、缺失计数和未知字段保持显著提示。
- 修根README/RP能力说明、adapter提前弃用宣称和失效docstring。旧文字settings直接调用task_snapshot_client也拒绝，图片及历史读取保留。
- 评测独立.venv-eval（3.13.5）与CI .venv（3.14.7）；离线技术评测通过。独立旧Codex eval新调用暂停于spawn前，冻结模型标记/配置hash/cache不更名。当前Luna/max教师质量和恢复Project执行另需校准。

## 初轮实现验证（review修复前）

| 范围 | 结果 | 说明 |
|---|---|---|
| 完整test-ci | 退出0 | docs/secret/依赖/lint/部署脚本/全量后端覆盖率/前端全部完成 |
| 全量后端覆盖率门禁 | 7743通过、2跳过；86.80% | make test-fast-coverage，RuntimeWarning作为错误；门槛85% |
| 完整PG非真实模型E2E | 287通过、7未选 | 本任务PG17/合成专用库；含critical文件与两原nightly失败，无provider调用 |
| 最后受影响模块回归 | 1730通过、2跳过 | Interaction/World/Local Agent/Project/导入上下文/Story章锚/evals |
| 前端全量 | 237文件、2974通过 | 最新提示逻辑及章节选择后重跑 |
| 浏览器编辑台 | 2通过 | 保存、恢复、撤销、390px，以及真实零计数回执折叠/未知详情 |
| 浏览器世界与移动 | 31通过 | 数据切换、编辑器恢复、移动流程等 |
| 对象图片浏览器 | 内存存储复验1通过 | 原未配置存储桶失败单列，图片存储替身仅在仓库外私有测试app注入 |
| 生产前端build | 通过 | 16本地引用、59JS bundle、96发布资源路径 |
| ruff/ESLint/diff | 通过 | 本次50个Python文件格式通过；全库额外format存在约159个未修改存量差异，不擅自全库格式化 |
| 文档/模块/Prompt | 通过 | docs-check BASE_REF=origin/main；65/65边、9/9双向、0顶层循环、524/524函数导入；26 Prompt contracts |
| 依赖审计/部署脚本测试 | 通过 | backend/frontend均无已知审计漏洞；部署脚本272通过，仅本地测试 |
| 离线技术评测 | 通过 | 固定独立eval环境；14个实验测试及相应编译输出，非真实模型质量证明 |

make test-ci首轮因静态旧路径/顶层依赖/测试替身lookup失效；已修正，最后一轮完整make test-ci TEST_WORKERS=2退出0（7743后端、86.8%覆盖率、2974前端，以及依赖/lint/272部署脚本等全套门禁）。全库可选格式检查不是test-ci门禁，存量差异另记。UI图片真实S3/MinIO未配置，仍未验证生产图片存储、异地备份或恢复。

## 明确保留及依赖决策

- C05 window试验与C06历史文字jobs/receipts/schema：私有死adapter和绕行入口已清理；整体退役需先确定冻结试验、历史恢复与兼容处置，不删除真实历史。
- C07 renderer和C08 legacy GET仍是公开导出/API合同；无仓内调用不能证明没有外部消费者。保留直到明确迁移与回退方案。
- C16候选全范围读取与C18跨域哈希是来源/历史字节合同，不再按“相似代码”盲目收敛。
- C21/C22/C23 formal族、地图/正典失效消费者、新实验开放属于新增能力与产品取舍，未擅自扩展。
- C24/C25 图片生产备份、代理真实拓扑和C10真实模型校准需要外部证据/费用/生产范围；本次不调用模型、不发布。
- C12/C20/C28–C32含格式白名单、活跃基础设施、设计档案、付费证据、用户WIP、其它真实Codex任务与历史审计，均按实际用途保留。历史候选不是当前已复现缺陷。

## 初轮Git与环境快照（review续办前）

基线origin/main@974f0f5080d43472bc599d1d74782913c725057b，独立codex/capability-tail-fixes工作树。本地未提交、未推送、未创建PR、未合并或部署；原根目录WIP及其它Codex任务未写。PG与浏览器仅使用本任务专用合成库，未使用guimi。私有日志位于/tmp/novelcraft-tail-fixes，不提交原稿或Key。

回退按Imports私有清理、语义manifest、SQL投影、三个服务拆分、UI/CSS、eval门、文档分组恢复对应改动；无需真实数据迁移。新增支持文件与原稳定导出须一起回退，不只删新文件。

临时PG18482已停止，数据目录保留；浏览器测试自建API18484/Vite18485已退出。正式test-ci最后一轮已完成并退出0，代码内容指纹复核不变。

## 2026-10-13 全面review续办

本轮用户授权review后直接修复、验证后提交并创建PR。两路独立审查及32项复核见[REVIEW.md](REVIEW.md)。C10新增暂停预检保护SUT费用与holdout，并关闭旧DeepSeek reviewer绕行；C27修前导零撤销、200项拒绝反馈及迟到请求覆盖。旧holdout有效断言与历史meta/hash保留，显式cache-only不改，专门review-model命令不宣称有cache-only。

最终评测回归61、编辑台组件14、隔离PG全量287/7未选、实际编辑台浏览器3条通过（桌面/390px、保存/恢复/撤销、历史前导零）。前端lint/build、53个本次Python格式、diff、docs BASE_REF、模块依赖及26 Prompt契约通过。完整test-ci最终退出0：后端7746通过/2跳过、覆盖率86.8%；前端237文件2977通过；依赖审计、lint、272部署脚本测试通过。此前世界/移动31和内存图片UI1为初轮共享CSS证据；review未修改CSS。无真实LLM、生产库或受保护guimi访问。

当前仍在主题分支准备提交与PR，合并/部署不在授权内。Git发布状态以本任务TASK.md的最后恢复快照及PR为准，以上初轮未提交描述不作为本轮终态。

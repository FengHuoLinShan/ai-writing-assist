---
id: T-20261014-audit-first-batch
title: 能力审计首批实施与集成验收
status: active
created: 2026-10-14T11:30:04+08:00
updated: 2026-10-14T15:02:48+08:00
parent: T-20261014-audit-followup-batch
---

# 能力审计首批实施与集成验收

## 恢复快照

- 用户明确指派 GPT-6.1 Sol / medium 子代理并行执行首批 G3①、G3③a、G4a、G8a；G1 已签收，G2 由原聊天单一写入者执行。
- 集成树 `.worktrees/audit-first-batch` / `codex/audit-first-batch`。初始基线 22bb499789cba89fea92e918fd853ab768688e07；已 fetch 并入新主干 e02137f79fc4e8f5ba4f79f541b66b5dbaa47a05，模型规则 PR #225 于2026-10-14T04:02:06Z合入；合并新基线只变6份规则文档。
- G3① 已集成本地两阶段 commit 131b4a515、00ba86b3c；G3③a 本地 commit fc94fcfca。G4a本地 commit 1b0f067d6；G8a本地 commit 89efddc6b；新main并入 commit bc16a29f2。各切片实现已审查、集成，最终增量门禁通过。
- 主审容量问题均已闭合：G4临时PG数据用本次匿名私有卷，保留无网络/CPU/RAM限制和仅本次卷清理；G8历史来源只读六字段SQL投影，不加载正文或完整provenance。
- 集成初轮后端36失败已定位：2个导入棘轮叠加调整至522；34个旧测试fixture缺真实Project或作者principal，已只修3份fixture，原断言与production owner门禁不变。子分支完整fast7755通过；父集成默认locked完整fast7748通过、coverage86.81%，两树范围不同，不混用分母。
- 下一步：已整合最新main fdd3ec598（合并提交2e50e24ca，仅3份文档追加冲突、两边内容均保留），补修正式ops镜像标签与Protocol契约位置。最终7964后端/2985前端/314部署及双桶+作者ZIP恢复通过；提交推送补修，再请三路独立Sol/xhigh审查者复核新固定head与CI，暂不合并。

## 目标与验收

- 权威计划：`/Users/tywww/Desktop/项目/ai-writing-assist/.worktrees/audit-followup/docs/plans/2026-10-14-audit-followup-batch.md`，首批完成实现、必要文档、模块/集成/失败路径验证，保留切片可独立回退的commit。
- renderer需固定IR输出/hash不变；本机文字入口fail-closed且图片和历史回执保留；G4需两个bucket真实隔离恢复、权限/元数据/缺图/中断/30天老化证据；G8需章级地图提示、owner+novel隔离、真实SQL失败SAVEPOINT、Scene语义不变与390px浏览器证据。
- 测试通过仅代表合成工程验证，不能称为文学质量、真实作者或生产验收。本批不合并main或发布；模型规则的main合入单独由用户明确授权给G2原线程。

## 上下文、分工与授权

- 3名子代理均GPT-6.1 Sol/medium：renderer完成G3①后复用执行G8a，local_text执行G3③a，object_backup执行G4a。主代理单一写入集成树与本记录，不改根目录/规划树/原8个运行时worktree WIP。
- G2原聊天 `01a13096-d6d0-70e1-b7bb-7ad113020f67`，标题“世界演化系统现状评估”，已转交计划§4：unknown只读诊断/脱敏证据、7树逐文件对拍、W8迁入最新main、owner/授权/snapshot包装版本/unknown/timeout/cancel/Key轮换/多worker全账户上限验收、单一PR含ADR-0033与迁移。未恢复原全量评测/unknown重放/后台自动化。
- G2独占provider/migration/W8及四README；G8只提供evolution README来源核对块，由集成按块保留。G4独占部署脚本；G8独占DI/ADR-0031/import gate，G3③c须等其合入。
- 开发库计数：root backend/.env指向受保护Guimi库，自动审批曾拒绝凭据复用。用户对明确提出的仅5207/ai_novel_engine只读计数回答“全部授权”后，在READ ONLY事务中统计旧pending文字task 0、invocation 0、相关旧文字snapshot 0。Guimi未查询、未读正文、无凭据输出；此授权不扩大为合并/发布或全量恢复。
- 第二波前置以计划为准：G3②/G6/G7等待G2，G4b等待G4a合入，DI删除等待G8a合入。G5合成部分可提前但不并入首批；B2/G4c授权/G9和正典降级语义仍留用户届时裁定。

## 里程碑

- [x] 计划/handoff/工作树与WIP核对；独立切片和集成树；起始docs-check。
- [x] G2原聊天转交；模型规则PR #225已核实MERGED。
- [x] G3①实现、固定IR证明、活跃6定义AST全等，两个阶段commit。
- [x] G3③a实现、合成验证、标准浏览器、开发库计数，本地commit。
- [x] G4a最终实现审查与实际无网络合成对象恢复。
- [x] G8a最终实现审查、SQL投影、完整测试fixture修复。
- [x] 集成最终fast/浏览器、G4/G8本地提交、新main基线和增量门禁。

## 关键实现与主审结论

- G3①删除约596行旧renderer，StructureContextBundle及活跃编译/渲染/DI不变；隐藏真相断言迁JSON，overdue线程断言保留。固定IR967 bytes、SHA256 6af9283cc8145bef1fe15466992580a07fa3d3474dadea7e78b86e2212d10d74不变。
- G3③a仅两类图片task可pending/approve；claim只下发mode=image，旧文字/未知模式失败关闭；RP旧local_agent快照拒绝，真正新尝试走当前账户快照。图片执行器不再充当文字连接，历史回执保留。
- G4a独立同机0700/0600目录、fresh dump配对manifest、从同份dump取引用、两私有bucket只读备份用户、30天清单与镜像老化、restic keep-within30d。server_snapshot须DB配对；author_export允许无DB配对并直接ZIP恢复，目标DB的owner/novel/key引用核验防跨作品。有效缓存GET=0、坏缓存重取、缺图/中断incomplete、重复引用一致性有证据。
- G4标准make演练首次因全局python无Pillow失败，尚未建资源。主集成改用既有BACKEND_LOCKED_CI_RUN，不新增依赖/配置；复跑成功。临时PG匿名卷成功及失败仅rm本次容器+卷，既有MinIO/DB不清理。
- G8a按同owner/novel章真实历史canonical身份/hash重验，只扫≤200个saved current head与≤1000条source refs，旧历史/撤回引用也可提示；working/current未变不提示。真实SQL错误SAVEPOINT降级为“地图册未核对”，主回执及正文保存继续。地图状态/Scene窗口/登记/重算选项不改；对象/世界书页/候选与正典残余未覆盖保持显式。
- G8查询仅id/chapter/version/hash/status/deprecated_from_status六字段，实际百万正文+百万JSON测试证明无大字段返回；router核对跳转修为现有桥支持的编码query字符串。技术合同归22_evolution，其余模块摘要链接；architecture README过时闭包描述已修。
- 初轮34个NotFoundError不是弱化owner守卫的理由：Writing/Imports fixture创建真实Project，公开demo在真实source owner作者principal下发布并finally恢复；保留Writing206/public_demo57原断言。

## 验证与证据

- G3①子树470回归、26prompt合同、lint/gates/doc说明通过；父树AST对拍6定义全等。G3③a子树53local_agent/201interaction/2977frontend/5PG/95PGcritical/6browser通过，父树标准config浏览器6 passed/29.9s。
- G4子树部署301项最终版本由父集成test-ci执行通过；直接作者ZIP真实shell+Compose恢复、匿名卷success/failure、增量GET=0和元数据/权限反例另有日志，见子任务记录。
- 父树 `make test-ci TEST_WORKERS=2`：起始docs/secret、146锁定依赖无advisory、lint、deploy301passed/126.49s、frontend audit0通过；fast7712passed/36failed后停止，失败已按上述fixture/ratchet修复，未将这次总命令记成通过。日志 `/private/tmp/audit-first-batch-test-ci.log`。
- 父树PGcritical95passed/163.48s；P2-C+新SQL SAVEPOINT+local-agent图片专用9passed/3.92s。日志 `/private/tmp/audit-first-batch-pg-critical.log`、`audit-first-batch-focused-pg.log`。
- 父树frontend237文件/2980passed/31.12s，日志 `/private/tmp/audit-first-batch-frontend.log`；最终26prompt合同和frontend ESLint通过。
- 父树 `make test-object-restore-drill-real` 标准locked runner实际成功：7合成对象/2bucket/networknone，缺图与中断反例通过，RPO2.894s/RTO4.803s，dump SHA e58d94d8398ec7d7707771a734fe4ee1579d47c13b7f6c3178f0fccdd58b21c9。日志 `/private/tmp/audit-first-batch-object-drill.log`；仅此次小合成集，非生产SLA。
- G8 fixture专项174passed；子树完整默认uv locked7755passed/2skipped、coverage86.80%（门槛85%）。第一次共享python runner override导致make -n字面合同1失败，未改测试，默认runner复跑通过。父树最终完整层7748passed/2skipped/12warnings、coverage86.81%/173.16s；RuntimeWarning门禁和默认locked runner通过。
- 父树提交后的repo-gates通过：0二进制增量、18production files大小通过、release-evidence通过、实际522函数级导入/65边/9双向。默认docs-check BASE_REF列出总览待复核；已修CONTEXT/00/开发/测试指南的过时本机文字描述、添加G4/G8简要边界，余下6文档按具体不变事实说明通过现有no-change-reason合同，未修改gate。

## 环境与清理

- Docker原先未运行，正常启动后可用；既有ai-novel-db:5207/ai-novel-minio:9000等受保护服务保持。
- 本次唯一共享合成PG容器audit-followup-pg-20261014（label codex.task=audit-followup-20261014），回环18647，PG17+pgvector；3个audit_*_test库仅测试夹具。最终测试结束可仅删除该容器和本次匿名卷，保留所有工作树/原WIP。
- G4所有audit-g4a-*隔离演练容器已清理，缓存runtime镜像保留；截图/trace和私有运行日志在/tmp，非真实稿件。

## 交付边界

本批工程实现与验收完成，分支 codex/audit-first-batch；draft PR发布及CI状态从该分支关联PR实时核对，不据本地绿推断远端CI。未合并本批/部署。G2运行时收敛与第二、三波未宣称完成。
同机备份无法抵抗整盘故障；生产启用前磁盘容量、实际对账及性能仍未验证，需发布授权。

## 最终父树验证补充

- G8标准functional浏览器2passed/12.9s，390px提示、刷新恢复、正确地图跳转及查询失败保留正文；与此前G3标准6例合计8个受影响浏览器用例。前端build通过（16引用/59JS bundle/96资产），ESLint与Ruff通过，26prompt合同通过。
- 文档复核：CLAUDE仅导入AGENTS；Evidence根已只描述活跃renderer，IR/AST证明不变；indexing可见性/确认/队列不变；文档维护权威归属/流程不变；drawio/html的12模块和API/worker/MinIO常驻拓扑不变，G8复用既有依赖方向，G4为ops一次性程序/timer，细节由已更新deploy/12_infrastructure/ADR-0034维护。具体说明同时用于PR模板第三项。
- 本目录artifacts保存最终父树日志，旧失败总日志保留/private/tmp及以上分类；归档日志仅去行尾空白/EOF空行以通过diff-check，原始日志仍在源子树或/private/tmp，IR与source inventory不改。任务记录只提交合成工程日志，不含真实稿件/原始模型请求或凭据。
- 未做真实CLI生图或文学质量验证，未开通B2、自动同步或多用户运维，未部署或恢复原诡秘60章评测。

## 远端交付状态

- 已完成本地实现/验收，代码HEAD b532c3f92，工作树在推送前干净；PR正文已存PR_BODY.md供审查。
- 自动审批拒绝 git push origin codex/audit-first-batch：认为私有仓库代码和验收资料将外发到origin，缺少这次具体推送/可信目的地的明确授权。没有通过其他工具或间接方式绕过。已向用户聚焦请求授权推送到本仓库origin并创建draft PR，不合并/部署；回答前仅继续本地工作。用户随后明确回答“授权推送并创建 draft PR”，本仓库origin已获该次外发授权，继续交付；此前“全部授权”只针对开发库只读计数。
- 所有验证已结束，标签codex.task=audit-followup-20261014的本次合成PG容器已停止；保留数据卷和全部工作树，既有Guimi/MinIO不停止或清理。复验可docker start该容器，再用明确18647合成库参数运行。

## 远端CI发现后的验收纠正

- 用户明确授权后已推送15d4dae64，draft PR #227已创建并附当前聊天。base e02137f79，未合并/部署。
- 本地实现及定向验收通过，但首次远端Frontend functional两个shard失败，聚合门禁失败；文档、PG critical、前端unit、镜像、repo-gates、CodeQL均通过，Backend quality当时仍运行。不能把本地8例当全量浏览器验收。
- 因新远端失败证据，按协议纠正已关闭工程记录为active，恢复开放索引；下一步读取38514515133失败日志，分类新回归/基线/环境，定向修复，不删除断言或削弱门禁。

## 初始化调用方修复

- 精确错误：38514515133两个shard都在初始化步骤报Separate MinIO backup credentials are required，所有浏览器suite skipped。分类为本批新增必需参数未同步调用方的新回归，不是随机环境或页面失败。
- G4原Sol/medium子代理仅补frontend-ci.yml与根docker-compose.yml的独立合成备份身份，新增test_minio_initializer_callers.py动态核对全部tracked YAML的实际初始化环境、必需字段和root/app/backup分离。生产门禁/policy未改，没有真实.env/MinIO操作；157相关+7既有CI/dev回归与语法/Compose通过。
- 父集成已审查应用仅3文件小补丁；完整test-deploy302passed/118.62s，新调用方检查实际执行。既有7,748后端/2,980前端/PG95的生产代码未变，不为配置修复机械重跑，远端browser必须实际执行后再关闭。

## 最终远端签收

- PR #227保留draft，head4acf184c4426adca5d1f5bc883e2d7ab1ce75047；18项检查全部SUCCESS，含两个Frontend functional browser shard及聚合门禁、Backend quality/PG、镜像、前端unit、文档、repo-gates、CodeQL、GitGuardian。快照artifacts/ci-final.json；frontend run38516182906。初始化成功后浏览器实际执行，非skipped。
- 用户授权范围是推送和draft PR；本批未合并main/部署。已提交推送的实现与修复保持4acf184c4；本段CI收尾记录和导航关闭在本地保存，不再为仅记录更新触发整套CI。
- 首批G3①/G3③a/G4a/G8a完成工程验收。G2最新原线程状态：两路复核通过、三项问题闭合，PG/前端unit/镜像/文档通过，后端全量与浏览器仍待结束；不接管其工作或扩展合入授权。第二/三波依权威计划前置，不恢复真实评测。

## 独立审查纠正

- 2026-10-14T14:12:59+08:00：用户要求独立子代理 review，三名全新 GPT-6.1 Sol / medium 审查规范、计划和备份专项，固定 PR #227 head4acf184c4，排除未提交收尾记录。报告 [REVIEW.md](REVIEW.md)。
- 规范轴无确认 P1/P2；计划轴 G3/G8 无确认 P1/P2，19 项定向合成测试通过。G4 专项经主 Agent 实际函数反例复核，确认 P1 正式备份入口临时名被 publisher 拒绝、P2 清单发布中断阻断后续新备份。原 completed 状态因新事实纠正为 active，既有 CI 全绿不能代替这两条调用链验证。
- 第三个错误 DB 配对候选违反文档恢复前置，仅列非阻断防护建议；不声称正确配对也会缺图。本轮只增加报告与事实纠正，产品代码不改、无真实数据/模型、无提交/推送/合并/部署。
- 审查文档与diff-check通过；增量docs-check沿用本PR已有逐项无影响说明，以官方--no-change-reason入口通过。报告中保留裸make的提示及实际验证边界。

## 两项问题修复与再审

- 用户明确授权修复 P1/P2、补齐回归测试并更新 PR #227，之后派独立 GPT-6.1 Sol / xhigh 子代理 review，暂不合并。该授权允许本任务分支提交、推送和 PR 更新，不扩展到生产或真实数据/模型。
- 主 Agent 单一写入修复：backup_objects.sh 复用 .backup-stage/.backup-checksum-stage；历史损坏清单不提供缓存且脱敏告警，新镜像可继续生成。垃圾回收校验保持不变，清理失败退出 1 并分别报告新备份与保留清理结果。
- 六项新增回归在修复前全部失败（2 个真实 shell 入口合同、4 个历史损坏反例），修复后 6 passed /31 deselected；场景包括复制成功/失败、空遗留目录、SHA 缺失/不匹配、错误权限，连续两次新快照可读且旧老化对象不误删。另补合法历史 hash 冲突仍失败关闭的保护回归。
- 继续使用现有 uv locked runner；缓存 sandbox 拒绝后经正式 require_escalated 审核运行，无权限绕过。新审查仅在提交推送后派全新子代理，不复用旧审查者/实现者。
- 最终备份专题 41 passed /17.69s，完整部署 309 passed /123.31s；项目 Ruff 通过。额外将 backend lint 配置应用于部署文件发现 16 项既有问题，与4acf184c4逐项比对无新增，不伪称这项扩展检查全绿。shell语法、diff和文档库存检查通过。
- 最终隔离无网络实恢复：7合成图片/2桶，缺图与流中断反例、元数据/权限/hash/size/解码通过，RPO2.586s/RTO4.774s；仅小合成集，非生产容量。日志 /private/tmp/audit227-repair-{deploy,focused,object-drill}.log，全部演练资源由原harness清理。
- 收尾增量docs-check按现有无影响说明合同通过，保留裸make要求六份既有文档复核的提示；部署README、ADR-0034及12_infrastructure已同步损坏缓存与清理失败行为。shell收尾摘要改为operation incomplete，避免将只失败的保留清理误报为新快照不完整。
- 19faa270c已推送本仓库origin，PR #227正文已更新。提交后的secret、repo-gates通过，二进制增量0、18生产文件尺寸、release证据、导入522/65边/9双向均通过。审查者为review_227_xhigh_standards/spec/backup，均全新Sol/xhigh、fork_turns=none、只读，不复用旧审查者；固定完整diff e02137f7...19faa270c及修复diff4acf184c4...19faa270c。
- 三路19faa270c审查已完成：规范无P1/P2、仅P3 Protocol声明未放contracts.py；Spec无P1/P2，27项独立定向测试及IR固定hash通过；备份原两项已闭合，但发现新P1，两个正式ops入口未load_release_id，会选未发布的:local镜像。主审已读实际Compose/发布/状态helper并复现缺标签exit125、正确标签exit0的合成反例，继续修复正式入口及backup/restore镜像合同。
- 最新远端main已是fdd3ec59886e29cc5c9189a1c0fefa225cdc997f（#226运行时、#228收尾）；PR当前CONFLICTING，新head只有GitGuardian，无Actions run，不能说CI全绿。下一步先在本主题分支整合已合入主干、手动保留两边改动，再完成入口标签修复/回归和独立再审；不会合并PR或改原G2工作树。
- main已整合到主题分支，三个追加文档冲突人工保留两边段落；生产代码无合并冲突。规范P3已将MapChapterConsumptionPort移入evolution/contracts.py，更新唯一内部调用方并删除原仅含Protocol的模块，DI键/注册/行为不变，导入522/65/9不变。
- 两个正式对象ops入口在任何Compose前load_release_id，复用现有已完成部署状态/可达main校验，未引入环境兜底。7个真实shell镜像/状态反例修复前全失败、修复后全通过，原两个发布器入口用例移至已有finalized-state夹具并保留全部有效断言；新增5项（目录/ZIP镜像2、非法状态3）。HEAD漂移和错误外部RELEASE_ID均不能覆盖已完成发布标签。
- 原作者ZIP实演练调用方也补齐私有合成Git/发布状态；第一次因macOS临时路径别名被既有状态边界拒绝，夹具Path.resolve后实际正式shell解包/verify/restore7图通过，不放宽状态校验。标准双桶恢复7图/2桶同样通过（RPO3.609s/RTO6.672s，仅小样本）。
- 最终整合后本地默认locked fast：7964passed/2skipped、coverage86.85%、RuntimeWarning门禁通过/209.82s；前端237文件/2985passed/37.17s；完整部署314passed/148.01s；项目Ruff、shell、diff、文档库存、导入门禁通过。日志/private/tmp/audit227-integrated-{backend,frontend,deploy,object-drill,author-drill}.log。未访问真实数据或模型，未启动/更改原G2任务或生产服务。

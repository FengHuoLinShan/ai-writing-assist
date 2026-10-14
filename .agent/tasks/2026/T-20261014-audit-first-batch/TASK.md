---
id: T-20261014-audit-first-batch
title: 能力审计首批实施与集成验收
status: completed
created: 2026-10-14T11:30:04+08:00
updated: 2026-10-14T12:55:05+08:00
parent: T-20261014-audit-followup-batch
---

# 能力审计首批实施与集成验收

## 恢复快照

- 用户明确指派 GPT-6.1 Sol / medium 子代理并行执行首批 G3①、G3③a、G4a、G8a；G1 已签收，G2 由原聊天单一写入者执行。
- 集成树 `.worktrees/audit-first-batch` / `codex/audit-first-batch`。初始基线 22bb499789cba89fea92e918fd853ab768688e07；已 fetch 并入新主干 e02137f79fc4e8f5ba4f79f541b66b5dbaa47a05，模型规则 PR #225 于2026-10-14T04:02:06Z合入；合并新基线只变6份规则文档。
- G3① 已集成本地两阶段 commit 131b4a515、00ba86b3c；G3③a 本地 commit fc94fcfca。G4a本地 commit 1b0f067d6；G8a本地 commit 89efddc6b；新main并入 commit bc16a29f2。各切片实现已审查、集成，最终增量门禁通过。
- 主审容量问题均已闭合：G4临时PG数据用本次匿名私有卷，保留无网络/CPU/RAM限制和仅本次卷清理；G8历史来源只读六字段SQL投影，不加载正文或完整provenance。
- 集成初轮后端36失败已定位：2个导入棘轮叠加调整至522；34个旧测试fixture缺真实Project或作者principal，已只修3份fixture，原断言与production owner门禁不变。子分支完整fast7755通过；父集成默认locked完整fast7748通过、coverage86.81%，两树范围不同，不混用分母。
- 下一步：审查 codex/audit-first-batch 的draft PR及远端CI，取得主干合并授权后再满足第二波对应开始条件；G2原聊天继续单独交付运行时PR。首批本地工程验收完成，不代表整份计划、生产启用或真实模型验收完成。

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

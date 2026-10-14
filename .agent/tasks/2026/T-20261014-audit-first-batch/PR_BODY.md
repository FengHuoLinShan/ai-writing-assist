## 变更

旧本机文字任务仍可进入批准/领取入口，RP 还会把图片执行器误判为文字连接。本批将这些入口限制为图片，旧文字快照明确失败并保留历史回执；RP 文字能力只读取当前账户连接。

服务器图片现有数据库配对的备份/恢复路径，图片与数据库 restic 保留期统一为30天。修改已发布章节后，写作回执列出引用旧稿的当前已保存地图及核对入口；查询失败明确披露，正文保存、地图状态与 Scene 重算范围保持原契约。

- G3①：两阶段退役旧 bundle Markdown renderer；保留活跃编译器/IR与渲染，固定输出/hash和隐藏真相断言迁移有证据。
- G3③a：pending/approve/claim仅图片，旧文字task/invocation/snapshot失败关闭；图片正常、拒绝、取消、防重和owner隔离保留。
- G4a：同机独立目录、最小只读备份用户、同份dump取对象清单、增量校验、缺图/中断报告不完整、30天老化；目录或作者ZIP运维恢复，ADR-0034。临时PG匿名数据卷仅清理本次资源，标准make演练使用既有locked runner；开发Compose/CI初始化均提供独立合成备份身份，动态核对全部实际YAML调用方。
- G8a：同owner/novel真实历史来源ID/章/version/hash重验，只扫有限saved current head；SQL身份投影不读正文/大JSON，SAVEPOINT降级。旧测试只补真实Project/作者principal，保留原隔离/404/幂等断言。

- 影响模块：Evidence compilation、LocalAgent、Interaction、Evolution、World、Writing、部署运维与相关作者UI。
- 稳定接口 / API / schema / wire 风险：退役明确无生产调用的旧renderer导出；旧文字入口不再批准/派发；新增地图失效回执键与窄DI口，无表/列/migration/outbox。恢复核对目标DB中的owner/novel/bucket/key引用，不导入跨项目数据。
- 验证：
  - 父集成默认locked后端：7748 passed /2 skipped，coverage86.81%，RuntimeWarning门禁通过。
  - 父集成PG critical95、P2-C/地图SAVEPOINT/图片CLI专用9通过。
  - 前端2980通过、ESLint/build通过；标准functional浏览器G3六例+G8两例，含390px、恢复和失败路径。
  - 部署302通过；真实无网络合成恢复7对象/2桶，缺图和中断反例、解码/hash/size/权限/元数据通过。RPO2.894s/RTO4.803s只代表小合成集。
  - 固定IR967bytes/hash不变、活跃6定义AST全等；26prompt合同、Ruff、secret、repo-gates/diff通过；实际导入预算522。
  - 已授权本机ai_novel_engine READ ONLY盘点三类旧待处理数量均0；未查询Guimi或正文。
  - 首次test-ci的36失败已按2项棘轮与34项fixture根因修复；总命令未冒称全绿，最终各受影响本地门禁独立复验通过。首次远端浏览器因初始化调用方缺备份参数而尚未执行；本次已补齐，须待远端实际浏览器验收，不将跳过视为通过。

完整恢复快照和父树日志：[首批TASK](.agent/tasks/2026/T-20261014-audit-first-batch/TASK.md)。

## 架构文档影响

- [x] 已运行 `make docs-check BASE_REF=origin/main`
- [ ] 检查列出的当前文档已全部更新
- [x] 已逐项核对未更新文档，确认无当前架构影响

无影响说明（勾选第三项时必填）：已逐项核对：CLAUDE.md仅导入AGENTS，权限规则未变；Evidence根README已只描述render_compiled_context，固定IR/活跃编译AST字节证明不变，indexing的检索、可见性、confirmation与任务语义不变；documentation-maintenance的权威归属/检查流程未变。drawio/html展示的12模块及API/worker/MinIO常驻拓扑不变，依赖仍65边/9双向；G8复用已有Evolution-World方向增加窄只读DI口，G4仅新增ops一次性备份/恢复和timer，运维合同已更新deploy README、12_infrastructure与ADR-0034，不新增常驻服务或更换存储。CONTEXT/00/开发与测试指南中的过时本机文字描述已实际修订，保留Luna规则PR225，不以笼统内部改动豁免。

## 合并检查

- [x] 受影响测试和适用 lint 已通过
- [x] `novel_id`、account/owner、Schema guard 和 API Key 边界未放宽
- [x] 用户可见功能已覆盖适用的空态、失败/冲突、保存反馈、恢复和窄屏
- [x] 危险操作仍保留确认，未直接提交到 `main`

本PR是首批候选，保留每切片独立回退commit；已并入main上的模型规则PR #225。G2运行时仍由原聊天单独收敛，不在此PR重复写入。第二/三波按前置继续，未合并本批、部署、开通B2或恢复真实评测。同机副本不能抵抗整盘故障，生产容量/只读对账与启用需发布授权。

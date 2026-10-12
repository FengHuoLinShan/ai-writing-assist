# BR-3/4/5/6 整改验证（2026-10-12）

验证对象：`codex/guided-flow-integration` 本地提交 `af731b0392e8df2012741d14d8d9d3f942f570e5`；基线 `ebd3bac3732c16641e96ce4690014779acf60a98`。原 [验证报告](VALIDATION-20261012.md) 保持原文。代码在检查时与提交相同；全量 CI 后新增一条跨章选择参数化测试，另以受影响套件验证。

## 检查结果

| 检查 | 结果 | 证据 |
|---|---|---|
| `make test-ci TEST_WORKERS=2` | 通过；后端 7,675 passed、2 skipped、13 warnings；覆盖率86.72%；前端2,964 passed/237文件；部署脚本272 passed | `/tmp/guided-remediation-full-ci4.log` |
| 最终受影响后端 | 617 passed | `/tmp/guided-remediation-targeted-final3.log`；Assistant/Story P20/结构助手/Writing批注/操作目录 |
| `make test-postgresql-critical` | 91 passed | `/tmp/guided-remediation-pg-critical.log`；包含新增6条双连接开始竞争 |
| 双连接开始三种UUID表示 | 6 passed | `/tmp/guided-pg-concurrency-final.log`；同输入唯一run、不同输入冲突 |
| 真实TaskWorker付费故障恢复 | 3 passed（包含在最终套件） | `/tmp/guided-final-failure-paths.log`；有效检查点/失效指纹/响应后冻结前失败，生成替身仅调用一次 |
| 真实三层领域串联 | 1 passed（包含在最终套件） | `/tmp/guided-real-chain4.log`；真实Evidence确认、来源冻结、P20采用与ORM，三次来源不同；生成与审查合成 |
| 开篇/恢复相关组件 | 64 passed，后续全前端通过 | `/tmp/guided-final-ui-target.log`；含storage失败、重读恢复、在途禁用、名称保持与非空项目latest |
| 桌面浏览器三spec | 6 passed | `/tmp/guided-remediation-browser-desktop2.log` |
| 同三spec 390×844 | 6 passed | `/tmp/guided-remediation-browser-narrow.log`；临时配置 `/tmp/guided-flow-narrow.config.mjs` |
| Ruff、ESLint、生产build、secret/deps audit | 通过 | test-ci日志；`/tmp/guided-final-eslint.log`、`/tmp/guided-remediation-build-final2.log` |
| 最终commit repo-gates | 通过，保留既有超长文件警告 | `/tmp/guided-remediation-repo-gates-final.log`；import ratchet524/524 |
| inventory与主干差异文档检查 | 通过，有逐项不变理由 | `/tmp/guided-remediation-docs-inventory-final.log`、`/tmp/guided-remediation-docs-final.log` |
| 原WIP与旧报告保留 | 57文件/HEAD/status/staged diff完全相同，旧两报告hash相同 | `/tmp/guided-remediation-original-wip-verification.json`，执行前两个私有摘要 |
| 最终双轴复审 | Standards、Spec均通过，原9项关闭 | [整改复审](REVIEW-REMEDIATION-20261012.md) |

## 验证范围与限制

浏览器使用任务独占PostgreSQL合成项目、真实宿主/组件与接口路由替身；新增断言覆盖骨架修改/排除→CAS保存→指纹采用→刷新恢复→确认撤销及已编辑对象保留，本层完整资料确认的full/0预算/窗口参数，重叠修订先禁用后显式确认。领域采用正确性由真实后端串联、HTTP及ORM测试补足。浏览器替身不证明真实模型输出质量或作者接受度，390×844不证明实体手机体验。

真实并发与付费恢复使用数据库/worker，模型仅合成替身。已安全冻结结果可复用；模型已发起、结果尚未冻结的故障窗口只能保留调用标记并失败关闭，不宣称能恢复不存在的输出，不自动第二次付费。没有真实稿件、付费模型、外部用户数据或共享库写入。

PostgreSQL17.10+pgvector任务集群 `/tmp/codex-guided-flow-20261012-pg`，端口18432，库 `guided_flow_integration_test`；已停止，未修改5432共享集群。浏览器服务器结束后退出。未运行Docker生产镜像/恢复演练或真实模型门禁；未推送/远端CI/PR/main/部署。

## 失败与纠正

- 初轮针对性失败含旧同步方向卡、两层规划、完整包采用与旧任务身份契约；同步调用方/替身，修复真正自动步分发遗漏，保留安全断言。
- 两次全量准备因新文件lint排版失败；修复后没有隐藏门禁。首次全量后端两项失败：旧批注重叠fixture缺确认、操作目录冻结快照未同步；改为显式确认并更新新版本/schema快照，最终test-ci全绿。
- 初轮桌面浏览器旧修订用例缺重叠确认，按钮按新契约禁用；补禁用断言、显式勾选和请求范围/overlap断言，两种viewport均通过。
- 主干差异文档门禁需要额外8份文档核对；读取后保留无当前变化文档并使用检查器已有 `--no-change-reason` 逐项说明：CLAUDE只导入规则、Evidence indexing检索/嵌入未改、12模块拓扑/基础设施未变、Memory与Map稳定接口/来源/知识边界未改。实际owner文档均已同步，未改检查器或棘轮。

## 恢复命令

1. 隔离worktree内 `make test-ci TEST_WORKERS=2`；最终受影响套件见617项日志。
2. 仅启动上述独占PG集群（18432），设 `E2E_DATABASE_URL=postgresql+asyncpg://guided_flow_test@127.0.0.1:18432/guided_flow_integration_test` 后 `make test-postgresql-critical`。
3. frontend-console内剥离HTTP(S)/ALL代理，设同库DATABASE_URL、PW_REUSE_EXISTING_SERVER=0、APP_ENV=test、BACKEND_PORT=18000、FRONTEND_PORT=18080、API_HOST=http://localhost:18000，执行 `npx playwright test guided-flow-continue-writing.spec.js guided-flow-tails.spec.js editorial-revision-bridge.spec.js --config playwright.editorial.config.js --workers=1 --retries=0`；窄屏用上述临时配置。
4. 文档影响检查以 `backend/.venv/bin/python scripts/check_architecture_docs.py --base-ref origin/main --no-change-reason '<上文逐项理由>'` 执行。不把带理由通过写成裸 `make docs-check BASE_REF=origin/main` 自动通过。

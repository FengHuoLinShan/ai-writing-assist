# Agent Teams 本地工程交付

本地实现与适用工程门禁已完成。原 main 和其未提交工作保持原状；当前交付在 `codex/agent-teams`
隔离 worktree，尚未提交、推送、合并、运行远端 CI 或部署。质量准入未通过，八项开关仍默认关闭。

## 功能与权威归属

| 功能 | 实现与入口 | 关键边界 |
|---|---|---|
| F1 深度审稿 | 写作检查菜单 → 三专项调查 → 原 Writing 语义报告 → 助手汇总 | 不改稿；未查不当通过；汇总失败保留领域报告并标部分完成 |
| F2 世界压力测试 | World 当前资料 → 情境报告、作者决定、定向重测与历史对照 | 无效反例/有意缺陷保留；全部关联来源变化使报告失效；报告不可直接采用 |
| F3 跨章修订 | World 影响讨论 / 助手方案 → 最多三套 diff → 选择一套 → 原确认批次 → 后续复核任务 | 冻结可枚举正文范围、显示未读章节；旧方案漂移拒绝；复核与写入分别计量 |
| F4 Scene 排演 | Scene 工作台选择人物/回合 → 观察事件 → 原剧本预览 / 分叉 | 每次一至三轮、最多三人；同回合不偷看意图；回放复用不可变回合；采用仍原流程 |
| F5 RP 多角色 | 已登录、绑定冻结作品资料旅程的演绎方式 | Project 签名 v3；仅选中祖先状态；完整正文通过 held 后与 actor 状态一起提交 |
| F6 盲读 | 助手选择盲读与截止章节 → 冻结认知轨迹 | 最多八章；读者阶段不见标题、作者目标与后文；历史猜测不可改写 |
| F7 专题研究 | 助手选择研究并明确本次联网 | 原搜索/读取、SSRF、隐私与额度门禁；搜索摘要不能作引文，无原文明确遗漏 |
| F8 导入会诊 | 原导入疑难组“深入查证这一组” → 独立调查与原组采用提案 | 只物化该组，只能准备该组当前 fingerprint 的 imports.accept_review，原作者裁定与领域采用门禁不变 |

## 原实施验证结果（修复前历史记录）

- `make test-ci TEST_WORKERS=2` 通过：后端 5,867 passed / 13 skipped，覆盖率 86.02%；前端 2,511 passed；部署脚本 270 passed。后端 12 项既有测试资源/标记警告保留，没有隐藏；依赖审计无已知漏洞，langchain-community 的 archived 状态仍被报告。
- 最后补强后的 World 全来源失效与团队只读/导入组边界：6 passed；助手域回归 61 passed。上述补强没有用测试绿色冒充文学质量通过。
- 专用 PostgreSQL：`test_agent_teams_runtime.py` + `test_team_history.py` 共 6 passed，覆盖实际 worker/计量/取消/致命异常/汇总失败、连接回收、20 节点选中祖先、分叉和数据库不可变/跨项目约束。
- Scene 排演持久回放/分叉和 RP 完整生成/中断路径通过；RP 模型为 DI 替身，20 节点轨迹是状态与分支测试，不是 20 轮付费自然性盲评。
- Playwright `agent-teams.spec.js` 仅覆盖 F1：真实 UI 原位开始、跨页恢复、刷新、部分完成、390px 对话框和原报告导航。团队提交、轮询、运行/讨论回执与领域报告 API 使用浏览器路由替身；不是 provider-only 的真实 worker 链路，也不代表 F2–F8 浏览器已覆盖。截图已人工查看。
- Ruff、ESLint、secret hygiene、`git diff --check` 通过。`make docs-check` 完整性通过；`make docs-check BASE_REF=origin/main` 要求核对五份未改文档，使用同一检查器支持的 `--no-change-reason` 逐项说明后影响门禁通过。具体理由保留在 docs-impact.log。
- 两条迁移已在专用新库应用。`alembic check` 仍报告原有 Story/WorldLibrary 等索引/FK/空值漂移；基线 metadata 只读对比确认相同旧项，新三张表没有新增差异。未为过检修删无关表。

## 计划适配与明确限制

- 工作板使用已有 AssistantRun 的有界 JSON（12 工作项、1 MiB）及单写 checkpoint，没有实施计划中 Assistant v2 的两张转存表；在当前固定蓝图规模内已具备恢复、hash 和依赖失败语义。Story/RP 的分叉历史新增三张表。此差异是实现选择，不把不存在的表称为已交付。
- F5 当前只接受已登录且绑定冻结作品资料的旅程；普通、无来源和匿名模式不自动升级。
- F3 显示声明范围与实际回读差异，不承诺全书穷尽；无法由原复核覆盖的 Story 文学/结构影响继续明确标为未检查。
- 不含可选异构顾问、不发布生产、不迁移或清理真实 Guimi 数据。
- 真实 DeepSeek 共 80 次 generate 请求，其中两次用量未知；输出额度限制与结构化失败使样本不足，未运行留出/人工盲评。详情见 [QUALITY.md](QUALITY.md)，不宣称团队优于资源相近单 Agent。

## 重现与证据

依赖由锁文件固定。常规门禁：`make test-ci TEST_WORKERS=2`；前后端 lint；文档检查。
PostgreSQL 使用专用 `ai_agent_teams_e2e_20260920`，显式设置 E2E_DATABASE_URL 后运行：
`RUN_E2E_TESTS=1 uv run pytest -q tests/e2e/test_agent_teams_runtime.py tests/e2e/test_team_history.py -m e2e --no-cov`。
浏览器使用专用数据库及独占 18160/18180 端口，运行
`npm run test:e2e:functional -- agent-teams.spec.js --workers=1 --retries=0`。

证据在 artifacts：ci-final.log、pg-final.log、browser-final.log、docs-impact.log、validation-files.json、
team-review-mobile.png；付费探索原始脱敏记录在 live-*。validation-files.json 记录本地未提交代码的文件 hash，
不是发布 commit。开关/回退按 development-guide，仅关闭新入口并保留历史，不运行破坏性 downgrade。


## 2026-09-20 审阅问题修复验收

本节对应修复后的本地工作树；上方全量 test-ci 数字为原实施历史，本轮没有全量重跑，也未重新测覆盖率。

- P1 蓝图粘滞：成功提交或找回原回执后消费一次性蓝图及重测范围；普通追问不再触发团队。
  不确定提交仍复用原授权/operation_id；旧格式粘滞草稿不恢复团队授权，未提交文字保留。
  首次创建讨论时迁移草稿，不留可被再次使用的 new 草稿。
- P1 成员失败：LLMInvalidResponseError 归为 invalid_output，LLMContentFilterError 归为 content_filter，
  独立成员继续执行；认证、额度与限流错误继续停止整组。共用调度器保留依赖阻塞与回执恢复语义。
- P2 迁移/历史：两条 downgrade 对称删除新增表、字段、约束及触发器函数；历史表拒绝 UPDATE/直接 DELETE，
  沿用仓库父对象永久删除级联例外；两张不可变历史表加入 IMMUTABLE_TABLES 并验证其 UPDATE/DELETE 护栏。
  日常应用回退仍保留历史，不运行 destructive downgrade。
- P2 关闭开关：新方案物化和修改后新复核复用蓝图/总开关检查；已物化批次仍走原确认，关闭后修改成功但明确未复核。
  regression 查 run 改用 novel_id + run_id 的既有 require_run，缺失批次明确 404。
- P2 RP 分层：复用 workflow 的已验证祖先读取入口，来源可见性提供同模块公开方法，ensemble 不再穿透三层私有成员。
- P2 报告竞态：切换报告重置 busy 并清空旧报告，旧请求不得覆盖新状态；读取/保存/重测互斥。
- P2 forkRound 旧桥：当前源码不存在该旧桥调用；SceneRehearsalPanel 以 run 事件传递 parentId/forkRound/parentHash，
  useStorySceneWorkspace 接入已有模拟任务。现有分叉事件测试通过，不添加无依据兼容层。
- P2 覆盖口径：浏览器仅 F1；团队 API 为 route 替身，真实 worker + provider 层替身另由 PostgreSQL E2E 验证。

本轮实际验证：

- 后端定向第一组 87 passed：Assistant 全模块、project/test_demo_copy_table_order、Story rehearsal/simulation、World team_stress、LLM collaboration。
- 后端定向第二组 178 passed / 2 deselected：Interaction 全模块与 project/test_demo_copy_table_order（两组有重叠，不相加）。
- 前端 Assistant + Scene 115 passed；最后补充首次建讨论草稿消费断言后，useProjectAssistant 17 passed。
- 新建专用合成数据库（名称见 artifacts/remediation-db.txt）：upgrade head → downgrade 20260914_anonymous_rp_accounts
  → upgrade head 通过；回退后断言三张表、两条函数及 generation_mode 列消失。
- PostgreSQL `test_agent_teams_runtime.py` + `test_team_history.py`：11 passed；包含真实 worker 的局部/账户级错误、
  取消、终检失败、计量/连接回收、不可变更新/删除、跨项目约束、20 节点分支历史与项目删除级联。
- Playwright F1：1 passed（retries=0，新服务端 18162/18182），新增审稿结束+刷新后的普通追问无 blueprint，
  验证普通讨论响应显示；保留原导航/恢复/窄屏断言。截图已查看。F2–F8 浏览器仍未覆盖。
  扩展用例前两次失败来自测试替身：新 run 未供轮询读取、session 未提供结果消息；已补齐协议后通过，没有删除功能断言。
- 后端全量 Ruff、受影响前端 ESLint、secret hygiene、git diff --check 通过。
- make docs-check 通过。BASE_REF=origin/main 的原始影响门禁仍提示五份未变化领域文档；逐项核对无影响，
  使用检查器支持的 --no-change-reason 通过（Evidence indexing、Memory、Outline、Map、文档维护机制均未改）。

证据：artifacts/remediation-browser.log、remediation-mobile.png、remediation-files.json。
所有功能继续默认关闭；没有付费模型调用、真实 Guimi 数据操作、提交、推送、合并、远端 CI 或部署。
原 main 工作树的 README/宣传录制任务/未跟踪文件保持原状。

# T-20261006-architecture-optimization

- id: T-20261006-architecture-optimization
- title: 架构优化计划实施（AO-1~AO-14、AO-17，coder 子代理批）
- status: active
- created: 2026-10-06T00:00:00+08:00
- updated: 2026-10-06T21:56:32+09:00

## 目标

按 [`docs/plans/2026-10-06-architecture-optimization.md`](../../../../docs/plans/2026-10-06-architecture-optimization.md)
实施可本地交付的全部工作项（用户 2026-10-06 指令：规划 coder 子代理执行计划，全部完成后做一轮
review）。本记录即计划 §7 要求的主任务记录。

## 授权与边界

- 用户指令构成 AO-1~AO-14 的"明确开始实施"授权；AO-12 为已裁定正确性修复。
- AO-15（容器加固）、AO-16（MinIO 备份）涉及生产发布与数据，**未实施**，待发布授权。
- AO-7 按计划明确"下次实质改动时拆分"，本批跳过（writing/services 4168 行等仍 >3000 告警）。
- 全部本地分支+提交，未推送、未开 PR、未合并 main；合并待用户在 review 后授权。

## 交付形态（分支拓扑，重要）

- `codex/architecture-optimization`：19 个提交（da9d3046e..e2484606d），基于 main 77620459d。
- `codex/event-soft-delete`：**rebase 到架构批之上**（单个提交 221ef2339），包含全部成果。
- 合并顺序：先 codex/architecture-optimization 入 main，再 codex/event-soft-delete（届时为
  单提交快进）。若先合 event 分支会带入架构批全部提交，属可接受但不符"AO-12 单独交付"。
- 本地 dev 库已推进到 20261006_event_soft_delete（AO-12 迁移）。

## 关键决定

- AO-12 期间出现"并发写入者"（疑为用户另一会话，11:21-11:31 落下同计划实现）：coder 转入对照
  审查+补缺，主会话复核后采纳；此后未再出现。
- AO-3：require_operation_targets 实测有跨域副作用，不能进 contracts，走 DI port。
- AO-4：smart_dedup 调用方证据表明 owner 即 project 工作台，原址 DI 反转不迁移。
- AO-5 三批：ADR-0031 逐对裁定；插件 OPERATIONS 改纯数据 spec + 组合根物化（46 操作逐字段
  等价有快照测试）；双向对 33→9（超计划 ≤15），顶层双向 17→0。
- AO-11：作者迁移三处协议评估结论=不抽象（回执模型/逆序回滚引擎已共享，余为领域语义差异）。

## 验证（终态全绿）

- 后端全量默认层 7123 passed（含修 1 个跨提交遗漏 a4b3272bd 后）；前端 2790 用例+lint+build；
  repo-gates 四门（binary/file-size/release-evidence/module-imports 含方向棘轮+facade 薄层+
  动态导入规则）；make test-deploy 271；PG critical 58（一次性 e2e 标记库，已删）；
  prompt contracts 26；alembic check 零漂移（架构分支与 AO-12 合并态各自验证）。
- 六指标：directed_edges 90→65、bidirectional_pairs 33→9、top_level_bidirectional 17→0、
  function_level_imports 572→525、world core→worldbuilding 23→0。
- 整轮 review（3 个只读子代理按焦点分区）：无 P0/P1；2 个 P2（动态导入绕过、AO-12 分支脱节）
  与 5 个 P3 已全部修复（e2484606d + rebase）。

## 未完成项

- AO-15/AO-16：需发布授权，未动。
- AO-7：按计划推迟（writing/services.py 4168、interaction/services.py 3287、
  scene_workbench.py 3081 仍在 >3000 告警清单，等下次实质改动）。
- 剩余 9 个函数内双向对与 525 条函数内导入的持续棘轮下调（ADR-0031 已记录候选）。
- 项目助手 Playwright 浏览器套件未在本机跑（工具层等价路径已被模块测试覆盖）。
- review P3 备注未采纳项：vite 解析器注释不对称（fail-closed 可接受）、ESLint 计算属性
  绕过（防呆定位）、registry 函数身份断言（可选）、AO-6 commit"按原顺序聚合"措辞失实
  （行为已证等价，不改历史）。

## 2026-10-06 独立 review 与修复（用户重新开启）

- 授权：review `codex/architecture-optimization` 并修复发现的问题；不含提交、推送、合并或发布。
- 固定审查基线：`77620459d872a509e66e2d78ea4f344aedfa714b`；原始 HEAD：
  `e2484606d2cb30cd8b6ff05d1852969d7ec1e081`。19 个提交、340 个文件。
- 工作区：`/Users/tywww/.codex/worktrees/architecture-review/ai-writing-assist`，
  在目标分支上修复；原工作区的事件软删除分支与全部未跟踪文件保持原状。本记录复制原任务
  到新工作树后续写，保留此前实施/验证声明，当前 review 不视这些声明为当前证据。
- code-review 技能要求两个只读子代理：Standards/Spec 独立核查；主 Agent 负责修复与验证。
- 已确认：`manage_accounts.py` 独立 CLI 未装配新 DI，封禁与生产维护清理会 KeyError；
  `container_scope` 把存在的 None 注册误判为缺失；五个 Project Key 静态类型绕过已有消费方
  Protocol、绑定实现类。已补修复，准备运行 cold-container 与嵌套 scope 回归。
- 已验证：开始前 `make docs-check` 通过；None 注册复现探针确认回归。
- 下一步：定向回归后运行跨栈 test-ci、repo-gates 与专用 PostgreSQL/浏览器层；复核子代理证据。
- 阻塞：无。真实模型/作者质量/生产发布不在本次验收范围。

- 后续发现并已修复：独立 Evolution 规模 harness 漏装配 DI；性能 probe typed key 比较失效；
  AO-1 仅比计数允许删旧边换新方向；AO-8 漏扫直接 session 写与 `*_facade.py`。
  facade 检出的 local_agent 配置提交、World 别名 metadata 与地图查询原样下沉服务。
- 真实 functional 首次启动暴露 AO-13 的 `/api/*.js` 与 Vite proxy 冲突，页面 API 模块 404、
  `ReferenceError: api is not defined`。已收窄 dev proxy 并加入 REST/源模块路径矩阵回归。
- 当前验证：定向后端 162 passed；前端 lint/build 通过；PG migration/alembic check 零漂移；
  critical + Evolution cold-container 59 passed。完整 test-ci、修复后的functional在跑。
- 文档差异门列出未更新文档，正在按维护协议逐项核对并保存本地无影响说明；不改门禁。

- 本轮 test-ci 全绿：7129后端、2790前端、272部署，覆盖86.30%；实际OpenAPI与origin/main精确相等（559 paths/857 schemas）。
- 本轮完整修复说明见 [review.md](review.md)，文档无影响核对见 [docs-impact.md](docs-impact.md)。
- 恢复下一步：等待本次306例functional结束；失败时先判定与固定基线差异，修复真实回归；结束后只清理本任务专用数据库与两个bucket并关闭任务。

## 本轮最终恢复快照

- 已完成：固定架构分支review，确认8项（Standards 3 / Spec 2 / 主Agent 3）并全部本地修复；两个只读review轴已复核修复diff。
- 验证：test-ci（7129后端、2790前端、272部署，86.30%覆盖）；专用PG critical+冷启动59；完整functional 304 passed/2 skipped（默认关闭的100/1000份长资料库性能）；OpenAPI与main精确相等（559 paths/857 schemas）；lint/build/repo-gates与docs完整性、差异复核通过。
- 保留告警：12条SQLite ResourceWarning；未隐藏，未把它们宣称为已修复。P8固定head门覆盖原分支，当前新增/扩充源码均小于3000行。
- 清理：仅本任务architecture_review_e2e_20261006及fresh-migration子库、两个architecture-review-e2e bucket（清理4个残留合成图片）已移除；18106/18107不再有本任务监听。受保护作品库和原工作区未动。
- 交付：工作树仍在codex/architecture-optimization，HEAD e2484606d不变，修复未提交；新增executor_service.py、CLI回归及本任务记录均仍未跟踪，后续提交须包含它们。未推送、开PR、合并或发布。
- 报告：[review.md](review.md)；文档影响：[docs-impact.md](docs-impact.md)。
- 下一步：用户如要求交付Git，先复核该工作树diff与相关分支状态，再提交/推送/PR；实际创建PR时纳入文档核对checkbox与原因。本记录不构成提交、合并或发布授权。
- 阻塞：无；当前review+本地修复结果已验收完毕。AO-7延后、AO-12独立分支和AO-15/16授权边界仍按原计划。

## PR 合并阶段（用户重新开启）

- 当前授权：用户要求“pr合并”，包括本架构分支的提交、推送、创建PR与合入main；不包含事件软删除分支、生产发布和无关worktree清理。
- 实际状态：已重新核对目标worktree、未提交修复和远端；origin/main仍为77620459d，已是目标分支祖先，无需更新基线。尚未提交和创建PR。
- 门禁：main实时规则要求Architecture docs、Backend quality、PostgreSQL critical、Frontend unit quality、Frontend functional browser、Production image contract六项必需检查及CodeQL；按固定提交验证并以match-head-commit合并，不使用管理员绕过。
- 下一步：提交8项review修复与文档记录，复跑固定head的repo/docs门，推送并创建PR；等待必需CI全绿后合并。
- 阻塞：无；上轮本地验证证据保留，真实模型/作者验收和生产发布不在本次范围。

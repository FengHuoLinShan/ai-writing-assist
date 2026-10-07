# codex/architecture-optimization 独立 review 与修复

固定基线：77620459d872a509e66e2d78ea4f344aedfa714b；原始被审 HEAD：e2484606d2cb30cd8b6ff05d1852969d7ec1e081。19 个提交，340 个文件。按 code-review 技能分 Standards/Spec 两个只读轴；主 Agent 复现、修复并复核调用链。以下 8 项均已本地修复并完成相关验证。

## Standards

- **P2 独立规模 harness 漏装配**：Writing 来源失效改 DI 后，`backend/tools/evolution_scale_harness.py` 仍只注册 ORM；首个 `create_draft_only` 抛缺少 `evolution.record_writing_source_change` 的 KeyError。入口复用 `register_container_services(ignore_existing=True)`，新增 PG cold-container 真链回归。
- **P3 静态 Key 绕过消费方协议**：五个 Project Key 直接绑定 World/Story/Writing adapter，违背 ADR-0031 的消费方 SPI；World extraction 和 Assistant session 也已有 Protocol 可用。7 个 Key 改用已有协议，无新抽象，运行期对象不变。
- **P3 性能 probe 丢失阶段**：tracer 以字符串比较 typed Key，`activity` 与两个后续阶段静默消失。改为 `str(name)`，兼容字符串和 ServiceKey。

本轴 3 项；最严重为独立规模验证无法启动（P2）。未报告只有启发式依据的代码 smell。

## Spec

- **P2 AO-1 冻结数量没有冻结方向**：要求“新增边或新增顶层双向对即失败”，门禁却只比六项计数。内存负例将唯一 imports→account 换成 imports→local_agent 后，计数与形态校验均通过。新增实际65条边的冻结集合，main消费明细；新增一删一换、计数不变的失败测试。
- **P2 AO-8 facade 门覆盖不足**：要求不得直接session写入，但 add/flush/commit通过，且 *_facade.py 不扫描。扩展扫描、识别SQL别名与session写，保持service.update/commit、集合.add和字典.update合法。实际检出的 Local Agent 配置事务、World 别名metadata与地图读取编排原样下沉领域服务；公共出口保留，新增负例验证。

本轴 2 项；均为承诺的架构门禁未完整执行（P2）。独立 AST核对 World API 184个端点、schema、generation center 及前端552个领域方法；24次hash固定输入比较通过。

## 主 Agent 补充

- **P1 开发前端无法启动**：AO-13新增 `/api/<domain>.js` 被Vite后端代理截走，真实浏览器报模块404和 `ReferenceError: api is not defined`；单测/build未发现。代理排除一级JS源模块、保留嵌套REST路径，新增路径矩阵测试。修复后完整functional已能启动。
- **P1 生产账户维护 CLI 失败**：Account lifecycle新DI未同步 `scripts/manage_accounts.py` 独立入口；封禁和定时purge-maintenance均KeyError，连空到期清理也会触发。业务前装配组合根，新增三个cold-container CLI回归。
- **P3 None注册恢复丢失**：删掉 `_Registration` 包装后，container_scope以None当missing，退出会删除原有None注册。用键存在性恢复，回归覆盖嵌套覆盖与异常退出。

主 Agent 3 项；最严重为页面启动和生产维护中断（P1）。

## 修复后复核与当前验证

- Standards再次只读AST核对搬迁函数、公共出口对象identity、4个独立cold import：通过；没有新循环，查询、owner/novel_id、异常和事务正文保持原样。
- Spec再次独立核验门禁：集合与实际65边完全一致，路径与session负例失败、普通委托通过；9例轻回归通过。指标仍为65边/9双向/0顶层/525函数内/core→worldbuilding=0。
- `make test-ci TEST_WORKERS=2 ARGS=-q FRONTEND_ARGS=--reporter=dot`：通过；后端7129 passed、3 skipped，覆盖86.30%；前端2790 passed；部署272 passed；Ruff/secret hygiene/依赖audit通过。12条SQLite数据库未关闭的ResourceWarning保留，未吞掉；没有RuntimeWarning错误，不宣称零告警。
- 专用PostgreSQL17/pgvector：新库迁移至head；alembic check无新操作；critical+Evolution cold-container共59 passed。
- 实际 `app.openapi()` 与 origin/main 精确相等：559 paths、857 schemas（独立导出基线代码、双进程运行，不依赖AST推断）。
- 前端lint和build通过；代理定向测试3 passed。
- `make repo-gates BASE_REF=origin/main`：通过。P8按固定Git head比较；当前未提交新文件小于规模阈值，不把该门宣称为已覆盖未来提交。
- `make docs-check`：通过；差异影响门以正式本地 `--no-change-reason` 入口通过，逐项说明见 [docs-impact.md](docs-impact.md)。原始make base入口因无PR说明失败这一事实保留。
- 完整functional浏览器：304 passed / 2 skipped（8.1分钟，workers=1/retries=0）；两例跳过为默认关闭的100/1000份长资料库性能用例。首次基线因API源模块代理故障被停止，修复后从头执行全部306例，无失败。

## 交付边界

修复在 `/Users/tywww/.codex/worktrees/architecture-review/ai-writing-assist` 的目标分支工作树，尚未提交、推送、合并或部署。原工作区事件软删除分支及全部未跟踪WIP未改。仅使用合成资料与本次专用数据库/图片bucket；真实作品数据库未进入夹具。未运行真实模型、人工文学/视觉验收、生产发布或生产图片构建。

本次专用数据库/fresh-migration子库、两个图片bucket及测试服务已清理，未触碰原工作区或真实作品库。新增与扩充的代码文件最大1610行。最终代理/清单/API合同定向20例通过。

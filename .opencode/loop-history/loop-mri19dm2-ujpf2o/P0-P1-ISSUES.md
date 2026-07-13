# P0 + P1 审计候选清单（已复核分诊）

**来源**: 20 轮审计 + 并行 sub-agent 验证  
**原始生成日期**: 2026-07-13  
**当前代码复核**: 2026-07-13（只读；以当前 `main`、模块 README、测试与 GitHub 仓库设置为准）  
**原始表格统计修正**: 8 P0 + 8 Top 项 + 8 安全 + 6 测试 + 5 部署 + 7 UX + 5 运维 = **47 项**，不是 49；“Top 20”一节实际只列出 8 项。

> 本文下半部分保留原始审计条目，便于追溯；它们不再都表示“当前已验证的
> P0/P1”。路径在后续重构中已有迁移，优先以模块 README、稳定接口、当前实现和
> 测试为准。

## 复核结论与当前阶段分诊（2026-07-13）

项目当前仍是 demo / 本地开发阶段。以下分诊区分现阶段的代码约束、服务暴露前的
上线门槛和普通 backlog；不得把后两类当作阻塞当前功能迭代的 P0。

### 当前必须收口

| 原始项 | 复核结果 | 当前动作 |
|---|---|---|
| #2 零 CI/CD + 无分支保护 | **成立**。公开 GitHub 仓库的 `main` 分支未受保护，且无 `.github` workflow。 | 建立最小 lint + fast-test CI 后，在 GitHub 要求 PR 与通过状态检查。此项需要仓库设置权限，不是代码内的静默改动。 |
| #3 Mock-in-production | **成立且违反项目硬约束**。当前生产目录仍有 4 个 `Mock` import、9 处 `isinstance(..., Mock)` 分支。 | 下一批代码改动前改为依赖注入的测试替身；不得继续扩大该模式。 |

### 服务不再严格限于本机时的上线门槛

| 原始项 | 复核结果 | 说明 |
|---|---|---|
| #4 无 HTTP 速率限制、#5 安全响应头缺失 | **成立**。当前只有请求耗时头，无通用限流或 HSTS / X-Frame-Options / X-Content-Type-Options。 | 单机 demo 不阻塞；局域网、多用户或公网暴露前必须处理。 |
| S3 上传 MIME/幻数验证、S4 LLM RPM 默认 0、S5 sessionStorage Bearer token | **成立**。上传目前按扩展名选择解析器；`LLM_RATE_LIMIT_PER_MINUTE` 默认禁用；封闭测试 token 存在 sessionStorage。 | 在任何非受控部署前作为同一安全批次处理；S3 还应考虑压缩包/解析器资源限制。 |
| S2 CSP `style-src 'unsafe-inline'`、S7 迁移/运行时共用 DB 用户 | **方向成立，但不是当前 demo 阻塞项**。 | 绑定正式部署设计统一收口，避免在现有大量内联样式下零散收紧 CSP。 |
| #8、D1、D3、D5 | **部署能力缺口成立**。 | Dockerfile、多 worker、反向代理和 `.dockerignore` 应作为一次部署方案交付，不拆成当前功能修补。 |

### 下一轮小型硬化（不应标为 P0）

| 原始项 | 复核结果 | 建议范围 |
|---|---|---|
| #6 `except Exception: pass` | **成立**，但其中上下文失效和词典扩展是有意的 best-effort 降级。 | 保持降级语义，补结构化 warning / `exc_info`，不要改成阻断主写入。 |
| #7 pg_trgm fallback 缺 rollback | **成立**。异常后的 PostgreSQL session 不能直接继续执行 fallback。 | 修复并补回归测试。标准 migration / Docker 初始化已创建 `pg_trgm`，因此不是当前高频 P0。 |
| #10 `detail=str(exc)` | **部分成立**：当前模块 API 中有 18 处，不是报告声称的 50+。 | 优先消除会把未知异常包装成 500 的路径；保留经过领域校验的 4xx 用户消息。 |
| #13 两个 dict body、S8 `APP_DEBUG` 漂移 | **成立**。 | 用保持 wire shape 的 Pydantic 请求模型替换；统一 `.env.example` 与实际读取变量。 |
| T2 async fixture 装饰器、U3/U6/U7、O4 DomainError 不记录日志 | **需要专项验证或小范围修复**。 | 不与当前功能交叉重构；先为实际用户路径补回归测试。 |
| D2 `start.sh` 未启动 worker | **仅旧脚本成立**。 | 当前 `make dev` 使用 `scripts/dev_stack.py`，会启动 worker；若仍保留 `start.sh`，更新或标记为弃用。 |

### 已失效、被夸大或需重新立证的原始项

| 原始项 | 复核结论 |
|---|---|
| #1 API Key 曾提交 | 历史中确有已删除的 `sk-placeholder`，但当前 `backend/.env` 未跟踪且已忽略；不是泄露真实密钥的当前事件。不要仅为占位符重写公开历史；可在 #2 的 CI 中增加 secret scanning 防回归。 |
| #9 领域事件机制、#11 `showModalHtml`、#14 embedding cache key、#16 骨架屏 | 都是设计/质量改进，未证明阻塞当前主流程。`showModalHtml` 仍要求调用方转义，应在发现未转义动态输入时按安全缺陷处理，而不是机械重构全部调用点。embedding cache 的模型切换影响也须先证明存在不重启的动态切换路径。 |
| #12 LLM 前端 15s 超时 | **已修复**：当前 LLM 请求使用 90 秒 timeout。 |
| #15 无删除撤销系统 | **原始描述已过时**：writing 删除为软废弃且保留版本历史；Scene 工作台的权威删除语义是 `deprecated`；地图硬删除是文档记录的 demo 例外并有二次确认。不要为此新建通用 undo 系统。 |
| S1 CSRF 仅依赖 `X-Requested-With` | 论证不准确：当前不是 cookie 会话，且该头不能抵御同源 XSS。将来若改为 cookie 身份体系，再单独设计 CSRF 防护。 |
| S6 rag/metrics 无路由级认证 | 已由全局 access-token 中间件在配置 `APP_ACCESS_TOKEN` 时覆盖；是否需要额外路由级限制取决于未来指标暴露策略。 |
| T1、T3–T6、U1/U2/U4/U5、O1–O3/O5、D4 | 多数是测试覆盖、体验或运维成熟度建议。保留在 backlog，按真实故障、用户反馈或正式部署计划重新排序。 |

### 排期结论

1. 先处理 **#2（仓库门禁）与 #3（生产 Mock）**。
2. 若服务会超出单机受控环境，先完成 **#4/#5/S3/S4/S5** 再暴露。
3. 然后以一轮小型 hardening 处理 **#6/#7/#10/#13/S8**，不要顺带重构领域事件、通用 undo、CSP 或完整部署栈。
4. 其他条目进入按需 backlog；任何重新启动的工作须针对当前代码路径重新验证。

---

## P0-CRITICAL（8 项）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| 1 | API Key 曾提交至 Git 历史 | `backend/.env` | 占位符密钥 `sk-placeholder` 在 `ee3290966` 提交，后于 `87144222a` 删除。非真实密钥但环境文件进历史是不安全实践 | 2h |
| 2 | 零 CI/CD + 无分支保护 | 项目根 | 任何变更直接合入 main，无测试/审查门禁 | 4h |
| 3 | Mock-in-production | `imports/workflow.py:17`, `orchestrator.py:514,541`, `extraction_service.py:81` | 9 处 `isinstance(db, Mock)` 改变生产行为，测试未验证真实路径 | 3h |
| 4 | 无 HTTP 速率限制 | 全局（FastAPI 应用） | 任何客户端可耗尽连接池、压垮 LLM | 3h |
| 5 | 后端完全缺失安全响应头 | `main.py` 中间件 | 无 HSTS/X-Frame-Options/X-Content-Type-Options | 2h |
| 6 | 3 处 `except Exception: pass` | `rag/query_expansion.py:65`, `world/entity_alias_service.py:181`, `world/suggestion_queue_service.py:680` | 纯 `pass` 掩盖错误，无日志记录 | 2h |
| 7 | pg_trgm fallback 缺 `db.rollback()` | `world/repositories.py:158-165,725-728` | 错误后直接 fallback，session 处于错误状态 | 2h |
| 8 | 无 Dockerfile | 项目根 | 零容器化部署路径 | 4h |

### P0 快速修复总工作量: ~22h

---

## P1-HIGH（Top 20）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| 9 | 领域事件机制缺失 | `writing/tasks.py` publish_chapter handler | RAG 索引→内存快照硬编码顺序，无法扩展 | 8h |
| 10 | 50+ 处 `detail=str(exc)` 泄露异常 | 7 个 api.py 文件（21 处） | 暴露 SQL/路径/内部细节给客户端 | 3h |
| 11 | `showModalHtml` 依赖调用方转义纪律 | `modal.js:107` | 74 处 innerHTML 中大部分已转义，但无法强制 | 2h |
| 12 | LLM 生成 API 前端 15s 超时 | 前端 `api.js` | AI 生成需 60-120s，前端超时远低于实际 | 1h |
| 13 | 2 个 dict body 端点 | `imports/api.py:281,308` | `body: dict = Body(...)` 绕过 Pydantic 校验 | 2h |
| 14 | 嵌入缓存 key 缺模型名 | `embedding/cache.py:28-30` | 切换模型最多 1h 返回旧结果 | 1h |
| 15 | 无删除撤销系统 | world/outline/writing 模块 | 章节/场景/剧情线/伏笔/揭示硬删除 | 12h |
| 16 | CSS 骨架屏已定义但零使用 | `styles.css:3165-3186` + 各视图 | 5 个视图用"加载中..."文本，骨架屏完全浪费 | 2h |

### P1 Top 20 修复总工作量: ~31h

---

## 🔒 安全 P1-HIGH（8 项）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| S1 | CSRF 仅依赖 X-Requested-With | 全局中间件 | 同源 XSS 可绕过 | 3h |
| S2 | CSP style-src 'unsafe-inline' | `index.html:6` | 削弱 XSS 防御 | 1h |
| S3 | 文件上传无 MIME/幻数验证 | `imports/upload` | `.exe` 重命名即接受 | 2h |
| S4 | LLM_RATE_LIMIT_PER_MINUTE=0 | `config.py:141` | 默认无限流 | 0.5h |
| S5 | Bearer Token 明文存 sessionStorage | 前端认证 | XSS 可窃取 token | 4h |
| S6 | rag/metrics 端点无路由级认证 | `rag/api.py:143` | 仅依赖可选全局中间件 | 1h |
| S7 | 数据库单用户运行迁移和运行时 | `alembic.ini` + config | DDL+DML 共用同一账号 | 2h |
| S8 | APP_DEBUG vs DEBUG 不匹配 | `config.py:234` + `.env.example:23` | .env.example 的 APP_DEBUG 从未被读取 | 0.5h |

### 安全修复总工作量: ~14h

---

## 🧪 测试 P1-HIGH（6 项）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| T1 | core/shared 层测试覆盖不足 | `core/dependencies.py`, `shared/` | core 有部分测试但 dependencies.py 和整个 shared 零覆盖 | 6h |
| T2 | 10 处 `@pytest.fixture` + `async def` 误用 | e2e + unit 测试文件 | 应与 `@pytest_asyncio.fixture` 一致 | 1.5h |
| T3 | 无 pytest-xdist 并行 + pytest-timeout | `pyproject.toml` | 串行执行、无挂起防护 | 1h |
| T4 | Memory/RAG 无 API 层测试 | `modules/memory/tests/`, `modules/rag/tests/` | 两个模块缺少 `test_api*.py` | 4h |
| T5 | 跨模块 E2E 串行场景缺失 | E2E tests | 各模块有碎片化 E2E 但缺完整流程（导入→生成→发布→检索） | 6h |
| T6 | 无 pytest-cov 阈值/报告配置 | `pyproject.toml` | 已安装 `pytest-cov` 但未激活 | 1h |

### 测试修复总工作量: ~19.5h

---

## 🚀 部署 P1-HIGH（5 项）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| D1 | 无 gunicorn/多 worker 配置 | 项目根 | 零生产级启动配置 | 3h |
| D2 | start.sh 未启动任务 worker | `start.sh` | 后台任务不处理 | 0.5h |
| D3 | 无反向代理（nginx/Caddy） | 项目根 | 无 TLS/静态文件服务 | 4h |
| D4 | POSTGRES_PASSWORD 明文硬编码 | `docker-compose.yml:14` | `novel_dev_pass` 明文 | 0.5h |
| D5 | 无 .dockerignore | 项目根 | 构建上下文过大 + 含 .env | 0.5h |

### 部署修复总工作量: ~8.5h

---

## 🎨 用户体验 P1-HIGH（7 项）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| U1 | HTTP 409 未在前端 errorMap 映射 | `api.js:202-210` | 显示"请求失败 (409)"而非业务消息 | 2h |
| U2 | 11 处 `setTimeout` 竞赛条件 | 各 View.js | 依赖微任务调度，重复绑定/丢失绑定 | 6h |
| U3 | 大纲子视图错误静默吞掉 | `outlineView.js:207-240` | 4 处 `.catch` 仅清空数组，无 toast/内联错误 | 2h |
| U4 | 模态框 ARIA 三重缺失 | `index.html:165` + `modal.js` | 无 role="dialog"、无焦点陷阱、无 aria-labelledby | 3h |
| U5 | 编辑器中无脏状态保护 | `worldView.js`, `outlineView.js` 表单 | 取消/关闭即丢失输入 | 4h |
| U6 | router.js 快速导航竞态 | `router.js:276-306` | A→B→A 时慢请求覆盖新项目。无 AbortController | 3h |
| U7 | generateView localStorage 无大小限制 | `generateView.js:1093-1150` | 无 LRU/大小限制，超限时用户数据静默丢失 | 2h |

### UX 修复总工作量: ~22h

---

## ⚙️ 运维 P1-HIGH（5 项）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| O1 | 日志中几乎无 novel_id 上下文 | 全局日志 | 65+ logger 模块，仅 1 处记录 novel_id | 4h |
| O2 | 无请求日志中间件 | `main.py` | 零 access log、无审计轨迹 | 2h |
| O3 | 无外部指标系统 | 项目根 | 零 Sentry/Prometheus/Datadog | 8h |
| O4 | DomainError 处理器不记录日志 | `main.py:307-318` | 对比 global_exception_handler 有 `logger.exception` | 0.5h |
| O5 | 无备份策略 | `docker-compose.yml` | 无 pg_dump 脚本、无 cron | 2h |

### 运维修复总工作量: ~16.5h

---

## 📋 汇总

| 类别 | 项数 | 总工作量 |
|------|------|---------|
| P0-CRITICAL | 8 | ~22h |
| P1 Top 20 | 8 | ~31h |
| 安全 P1 | 8 | ~14h |
| 测试 P1 | 6 | ~19.5h |
| 部署 P1 | 5 | ~8.5h |
| UX P1 | 7 | ~22h |
| 运维 P1 | 5 | ~16.5h |
| **总计** | **47** | **~133.5h** |

### 按阶段建议

**立即（1-2 天）：** #1，#2，#3，#4，#5，#6，#7 + S4，S6，S8，D2，D4，D5
**短期（1 周）：** #8，#10，#12，#13，#14，#16 + S1，S3，S5，T1，T3，T6，D1，D3，U3，U7，O2，O4
**中期（2-4 周）：** #9，#11，#15 + S2，S7，T2，T4，T5，U1，U2，U4，U5，U6，O1，O3，O5

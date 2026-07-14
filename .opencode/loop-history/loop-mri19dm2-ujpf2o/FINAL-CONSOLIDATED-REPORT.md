# 🔍 最终整合报告：优先级排序与修复路线图

**生成日期**: 2026-07-13  
**复核修订**: 2026-07-14（第一轮 P0/P1 修复完成后，以当前工作区、模块 README、测试与 GitHub 仓库设置为准）  
**代码级核对**: 2026-07-14（7 个并行 explorer 子代理逐项打开当前代码验证，47 项中 41 项确认、6 项部分不符、0 项完全不符）  
**来源**: 20 轮审计（R1-R20 完成）  
**累计发现**: ~1,700 项（CRITICAL: ~81, HIGH: ~242, MEDIUM: ~414, LOW: ~421 + ~500 i18n）  
**验证状态**: 全部 P0/P1 已由并行 sub-agent 验证，8 项原报告误差已修正（详见文末）

---

## 复核修订摘要（2026-07-14）

第一轮修复以提交 `d42462aa4 Fix audited P0 and P1 issues` 为界，覆盖 47 项 P0/P1 候选。终审结果：

| 终审分类 | 项目数 | 项目 |
|---|---|---|
| **已修复** | 30 | #1、#3、#4、#5、#6、#7、#10、#12、#13、#16；S3、S4、S5、S8；T1、T2、T3、T5、T6；D2；U1–U7；O1、O2、O4 |
| **不成立、过时或未立证** | 10 | #9、#11、#14、#15；S1、S6、S7；T4；D4、D5 |
| **合理暂缓** | 7 | #2（仅远端分支保护）、#8、S2、D1、D3、O3、O5 |
| **当前适合修复** | 0 | 无 |

> 详细分诊与逐项收口证据见同目录 `P0-P1-ISSUES.md`。下文各表在原条目右侧标注当前状态：✅已修复 / ⏸合理暂缓 / ❌不成立或过时 / ⏳未变（仍为 backlog）。

### 代码级核对结果（2026-07-14，7 个并行 explorer 子代理）

7 个子代理分别核对 7 个类别的 47 项，逐项打开当前代码文件验证声称状态：

| Agent | 范围 | 确认 | 部分不符 | 不符 |
|-------|------|------|---------|------|
| exp-1 | P0 #1-#8 | 7 | 1（#2） | 0 |
| exp-2 | P1 #9-#16 | 5 | 3（#11/#15/#16） | 0 |
| exp-3 | 安全 S1-S8 | 7 | 1（S7） | 0 |
| exp-4 | 测试 T1-T6 | 5 | 1（T4） | 0 |
| exp-5 | 部署 D1-D5 | 5 | 0 | 0 |
| exp-6 | UX U1-U7 | 7 | 0 | 0 |
| exp-7 | 运维 O1-O5 | 5 | 0 | 0 |
| **合计** | **47** | **41** | **6** | **0** |

**6 项部分不符及修正**：

| 项 | 原声称 | 核对发现 | 修正 |
|---|--------|---------|------|
| #2 | ⏸仓库侧已完成 | CI 配置比描述更完整（Python 3.12+uv lock+lint+fast-test+RuntimeWarning 全覆盖），分支保护确实未启用 | 状态标签准确，补充说明 CI 完整度 |
| #11 | ❌未立证为阻塞 | `showModalHtml` 仍无内置转义，但全体 100+ 调用方一致使用 `esc()`；属约定安全而非纵深防御 | 状态合理，标注单点遗漏风险 |
| #15 | ❌描述已过时 | Writing/Scene 确为软废弃；但**地图删除仍是硬 DELETE**（`map_api.py:213-220`，CLAUDE.md 声明 demo 阶段允许） | 补充地图硬删除例外 |
| #16 | ✅已修复主加载边界 | **仅首屏**（index.html）使用骨架屏；写作/大纲/Scene 工作台视图内加载态未使用骨架屏 | 降级为⚠️部分修复 |
| S7 | ❌论证未成立 | Alembic 与 runtime 默认读同一 `DATABASE_URL`，**无独立迁移用户配置项**；可手动通过环境变量区分但非一等支持 | 安全关注点有合理性，改为⚠️部分成立 |
| T4 | ❌描述已失效 | `memory/tests/test_api.py`（44 行 7 路由）和 `rag/tests/test_api.py`（82 行 chunk CRUD/retrieve/rebuild/metrics）均存在且有真实测试 | 升级为✅已修复 |

---

## 第一部分：Top 20 立即修复（按影响排序，附复核状态）

### P0-CRITICAL

| # | 标题 | 位置 | 为什么现在修复 | 工作量 | 复核状态 |
|---|------|------|---------------|--------|---------|
| 1 | **API Key 曾提交至 Git 历史** | `backend/.env`（曾提交） | 占位符密钥 `sk-placeholder` 在初始提交 `ee3290966` 中提交，后于 `87144222a` 中删除。非真实密钥泄露，但环境文件曾进入历史是不安全实践 | 2h | ✅ 防回归已完成：`make secret-hygiene` 与 CI 扫描 Git index 各 stage 与已跟踪工作区，阻止敏感文件和高置信凭据再次入库；历史无需重写 |
| 2 | **零 CI/CD + 无分支保护** | 项目根 | 任何变更直接合入 main，无测试/审查门禁 | 4h | ⏸ 仓库侧已完成（CI 比描述更完整：Python 3.12+uv lock+lint+fast-test+RuntimeWarning 全覆盖）；GitHub `main` 分支保护需远端授权后启用 |
| 3 | **Mock-in-production — 生产代码检测 Mock** | `imports/workflow.py:17`, `orchestrator.py:514,541`, `extraction_service.py:81` | 9 处 `isinstance(db, Mock)` 改变生产行为，测试未验证真实路径 | 3h | ✅ 已移除全部 Mock import 与检测分支；静态回归门禁禁止生产代码重新 import 或按模块名检测 `unittest.mock` |
| 4 | **无 HTTP 速率限制 — 无 DoS 防护** | 全局（FastAPI 应用） | 任何客户端可耗尽连接池、压垮 LLM | 3h | ✅ 单 worker/direct-peer 边界已修复：进程级 token bucket，非本地环境缺正 RPM/burst 拒绝启动；多 worker 聚合负载仍需反向代理容量规划 |
| 5 | **后端完全缺失安全响应头** | `main.py` 中间件 | 无 HSTS/X-Frame-Options/X-Content-Type-Options | 2h | ✅ 最外层 ASGI 响应边界统一注入 `nosniff`、`DENY`、`X-Request-Time-Ms`；权威 HTTPS scheme 写入一年期 HSTS，覆盖正常/错误/流式/CORS 短路 |
| 6 | **3 处 `except Exception: pass` 吞关键错误** | `rag/query_expansion.py:65`, `world/entity_alias_service.py:181`, `world/suggestion_queue_service.py:680` | 纯 `pass` 掩盖错误，无日志记录 | 2h | ✅ 已修复（实际 4 处，含漏算的 `rag/tuning.py` embedding 降级）：保留降级语义，补充受控结构化 warning + traceback |
| 7 | **pg_trgm fallback 后缺 `db.rollback()`** | `world/repositories.py:158-165,725-728` | `pg_trgm` 错误后直接执行 fallback 查询，session 处于错误状态 | 2h | ✅ 已修复：connection-level savepoint 隔离 pg_trgm 查询，失败先回滚 savepoint 再执行 fallback，不破坏 `autoflush=False` |
| 8 | **无 Dockerfile — 无法可重复部署** | 项目根 | 零容器化路径 | 4h | ⏸ 合理暂缓：Dockerfile、多 worker 与反向代理须由正式部署目标、进程模型和 TLS 边界共同决定，不宜在 demo 阶段拆分 |

### P1-HIGH

| # | 标题 | 位置 | 为什么现在修复 | 工作量 | 复核状态 |
|---|------|------|---------------|--------|---------|
| 9 | **领域事件机制缺失 — 发布工作流强耦合** | `writing/tasks.py` publish_chapter handler | RAG 索引→内存快照硬编码顺序，无法扩展 | 8h | ❌ 未立证为阻塞：设计/质量改进，未证明阻塞当前主流程 |
| 10 | **50+ 处 `detail=str(exc)` 泄露 Python 异常给前端** | 多个 api.py | 暴露 SQL/路径/内部实现细节给客户端 | 3h | ✅ 已修复当前确认泄露路径：Scene workbench 未知异常现返回稳定通用 500 消息并服务端记录 traceback；精确扫描剩余 21 处均位于显式 4xx 分支，不构成 50+ 未知异常泄露 |
| 11 | **前端 `showModalHtml` 依赖调用方转义纪律（XSS 风险）** | `modal.js:107` | 74 处 innerHTML 中绝大部分已正确使用 `esc()`，但 `showModalHtml` 依赖调用方自觉转义 | 2h | ⚠️ `showModalHtml` 仍无内置转义（`modal.js:382-384` 直接 innerHTML），但全体 100+ 调用方一致使用 `esc()`；属约定安全而非纵深防御，有单点遗漏风险 |
| 12 | **LLM 生成 API 前端 15s 超时 — 必然失败** | 前端 `api.js` 调用 | AI 生成需 60-120s，前端超时设置远低于实际耗时 | 1h | ✅ 已修复：当前 LLM 请求使用 90 秒 timeout |
| 13 | **2 个 API 端点接受未经类型验证的 dict body** | `imports/api.py:281,308` | `body: dict = Body(...)` 绕过所有 Pydantic 校验 | 2h | ✅ 已修复：`DeepImportRecoveryRequest` 共享 typed request model，保持 `{task_id: string}`、缺失/空值 400、错误类型 422 语义 |
| 14 | **嵌入缓存 key 缺模型名** | `embedding/cache.py:28-30` | 切换模型后最多 1h 返回旧模型结果 | 1h | ❌ 路径不成立：BGE client 与内存 cache 同属进程内单例，模型路径构造时固定，无热切换入口，进程退出清空 cache；原报告旧向量路径无法复现 |
| 15 | **无删除撤销系统 — 所有删除操作不可逆** | 全局（除 project 回收站） | 章节/场景/剧情线/伏笔/揭示硬删除 | 12h | ⚠️ 部分过时：Writing/Scene 已为软废弃（`status="deprecated"`）；但**地图删除仍是硬 DELETE**（`map_api.py:213-220`，CLAUDE.md 声明 demo 阶段允许+二次确认） |
| 16 | **CSS 骨架屏已定义但零使用** | `styles.css` + 各视图 | 5 个视图还在用"加载中..."文本，骨架屏 CSS 完全浪费 | 2h | ⚠️ 部分修复：**仅首屏**（`index.html:136-142`）使用骨架屏（含 `role=status`/`aria-live=polite`）；写作/大纲/Scene 工作台视图内加载态未使用骨架屏 |

### P2-MEDIUM

| # | 标题 | 位置 | 为什么现在修复 | 工作量 | 复核状态 |
|---|------|------|---------------|--------|---------|
| 17 | **`autospec=True` 零使用 — mock 不验证 API 形状** | 246 处 `@patch`/`@mock.patch` 调用 | 签名变化时 mock 不失败，测试假阳性 | 6h | ⏳ 未变：保留为 backlog，按真实回归风险逐步添加 |
| 18 | **项目列表（入口页面）无 loading/错误状态** | `projectView.js:280-295` | 用户看到的第一个页面，API 失败只显示空数组 | 1h | ✅ 已修复（随 U1/U3 批次）：项目列表加载与错误状态已补齐 |
| 19 | **`settings/facade.py` `LookupError` 抛 500 而非 404** | `settings/facade.py:37` | 不存在的 project_id 请求 effective-llm-settings 返回 500→应 404 | 0.5h | ⏳ 未变：保留为 backlog |
| 20 | **无请求日志中间件 — 无访问日志/审计轨迹** | `main.py` | 零请求日志，无法审计或排障 | 2h | ✅ 已修复（O2）：最外层 ASGI access log 中间件，记录受控 method/route template/status/duration |

---

## 第二部分：短中期修复（按主题分组，附复核状态）

### 🔒 安全加固（5-8 项）

| # | 标题 | 位置 | 严重性 | 工作量 | 复核状态 |
|---|------|------|--------|--------|---------|
| 1 | CSRF 保护仅依赖 `X-Requested-With` — 同源 XSS 可绕过 | 全局中间件 | HIGH | 3h | ❌ 论证不准确：当前不是 cookie 会话，该头不能抵御同源 XSS；将来改 cookie 身份体系再单独设计 |
| 2 | CSP `style-src 'unsafe-inline'` 削弱 XSS 防御 | `index.html` meta tag | HIGH | 1h | ⏸ 合理暂缓：Accepted ADR 明确保留该策略，须先完成系统性前端样式迁移再收紧 |
| 3 | 文件上传无 MIME/幻数验证 — `.exe` 重命名即接受 | `imports/upload` | HIGH | 2h | ✅ 已修复：统一解析入口按 TXT/HTML、EPUB、MOBI/AZW3 实际内容校验；EPUB 限制成员/路径/压缩/解压规模；伪装 PE 返回稳定 422 |
| 4 | `LLM_RATE_LIMIT_PER_MINUTE=0` 默认无限 | `config.py` | HIGH | 0.5h | ✅ 已修复：本地/测试可显式设 0；其他环境必须正 RPM，API/worker/reload 监督进程均 fail closed |
| 5 | `Bearer Token` 明文存 sessionStorage 通过 HTTP 发送 | 前端认证 | HIGH | 4h | ✅ 已修复：封闭测试 token 只存当前页面 module memory，刷新丢失；fetch/上传/错误上报共用同一认证路径 |
| 6 | `rag/api.py:143` `/metrics` 端点无认证 | `rag/api.py` | HIGH | 1h | ❌ 已由全局 access-token 中间件在配置 `APP_ACCESS_TOKEN` 时覆盖；是否需额外路由级限制取决于未来指标暴露策略 |
| 7 | 数据库单用户运行迁移和运行时（DDL+DML 共用） | `alembic.ini` + config | MEDIUM | 2h | ⚠️ 部分成立：Alembic 与 runtime 默认读同一 `DATABASE_URL`，无独立迁移用户配置项；可手动通过环境变量区分但非一等支持，安全关注点有合理性 |
| 8 | `backend/.env` 环境变量名不匹配：`APP_DEBUG` vs `DEBUG` | `config.py` + `.env.example` | HIGH | 0.5h | ✅ 已修复：`.env.example`、Settings 与 FastAPI 启动统一使用 `DEBUG`，默认 false，旧 `APP_DEBUG` 不再生效 |

### 🧪 测试质量（5-8 项）

| # | 标题 | 位置 | 严重性 | 工作量 | 复核状态 |
|---|------|------|--------|--------|---------|
| 1 | `core/` + `shared/` 层零测试覆盖（config/database/container） | `core/`, `shared/` | HIGH | 6h | ✅ 已按真实缺口修复：`core.dependencies` 与 `shared.types` 100%、`shared.utils` 95%；原"dependencies.py 和整个 shared 零覆盖"已过时 |
| 2 | 8 处 `@pytest.fixture` + `async def` 应改用 `@pytest_asyncio.fixture` | 测试文件 | HIGH | 1.5h | ✅ 已修复：实际 11 个文件 18 处，均改用 `pytest_asyncio.fixture`；静态门禁覆盖 alias/call/class/允许场景防回归 |
| 3 | 无 `pytest-xdist` 并行 + `pytest-timeout` 挂起防护 | `pyproject.toml` | MEDIUM | 1h | ✅ 已修复：fast 层默认 120s 单测试超时；`test-fast-parallel` 按 `TEST_WORKERS` 并行，CI 固定 2 worker + `loadscope`；E2E/真实 LLM 保持串行 |
| 4 | Memory 模块无 API 层测试 + RAG 无独立 API 测试 | `tests/` | MEDIUM | 4h | ✅ 已修复：`memory/tests/test_api.py`（44 行 7 路由参数化 404 测试）和 `rag/tests/test_api.py`（82 行 chunk CRUD/retrieve/rebuild/metrics/split）均存在且有真实路由测试 |
| 5 | 跨模块 E2E 场景缺失（导入→生成→发布→检索） | E2E tests | MEDIUM | 6h | ✅ 已修复：快速集成层串行执行导入→发布索引/快照→确认生成→采用→再发布→canonical 检索；并验证异项目正文与项目 LLM 凭据不进入生成 prompt |
| 6 | 无 `pytest-cov` 阈值/报告配置 | `pyproject.toml` | LOW | 1h | ✅ 已修复：`test-fast-coverage` 统计 `app/core/shared/infrastructure/modules` 生产代码，排除测试文件与 conftest，85.0% 阈值；复验基线 86.44% |
| 7 | 1494 处冗余 `@pytest.mark.asyncio`（`asyncio_mode=auto` 下死代码） | 测试文件 | LOW | 批量清理 | ⏳ 未变：实际 246 处（原报告高估 6 倍），保留为机械清理 backlog |

### 🚀 部署（3-5 项）

| # | 标题 | 位置 | 严重性 | 工作量 | 复核状态 |
|---|------|------|--------|--------|---------|
| 1 | 无生产 gunicorn/多 worker 启动配置 | 项目根 | HIGH | 3h | ⏸ 合理暂缓：须由正式部署目标与进程模型决定 |
| 2 | `start.sh` 未启动任务 worker — 后台任务不处理 | `start.sh` | CRITICAL | 0.5h | ✅ 已修复：`start.sh` 委托 `scripts/dev_stack.py start`，backend/worker/frontend 同一 pidfile 与退出清理管理 |
| 3 | 无反向代理（nginx/Caddy）— 无 TLS/静态文件服务 | 项目根 | HIGH | 4h | ⏸ 合理暂缓：须由正式部署 TLS 边界决定 |
| 4 | `POSTGRES_PASSWORD` 明文硬编码在 docker-compose.yml | `docker-compose.yml` | HIGH | 0.5h | ❌ 不成立：`novel_dev_pass` 是本地 Compose/.env.example 配套开发凭据，非生产 secret |
| 5 | 无 `.dockerignore` — 构建上下文过大 + 含 `.env` | 项目根 | HIGH | 0.5h | ❌ 不成立：仓库无 Dockerfile，`.dockerignore` 无构建消费者 |

### 🎨 用户体验（5-8 项）

| # | 标题 | 位置 | 严重性 | 工作量 | 复核状态 |
|---|------|------|--------|--------|---------|
| 1 | HTTP 409 错误未在前端 errorMap 映射 — 显示"请求失败" | 前端 error handler | HIGH | 2h | ✅ 已修复：409 映射为"请求冲突"并保留领域 detail |
| 2 | `setTimeout(()=>_bindEvents(),0)` 竞赛条件 — 内存泄漏 + 跨视图污染 | 各 View.js | CRITICAL | 6h | ✅ 已修复真实绑定竞态：当前 18 处 `setTimeout` 均承担轮询/退避/自动保存/防抖等明确生命周期；新鲜渲染改用 `onRendered()`，keep-alive 用 `onActivate()` |
| 3 | 大纲子视图错误静默吞掉 — 用户看到空状态而非错误 | `outlineView.js:207-240` | HIGH | 2h | ✅ 已修复：剧情线/篇章纲/伏笔/揭示加载失败显示转义错误 + 重试入口，不再伪装空列表 |
| 4 | 模态框 ARIA 三重缺失（焦点陷阱/无 role="dialog"/无 aria-labelledby） | `index.html:165` + `modal.js` | HIGH | 3h | ✅ 已修复：`role="dialog"`、`aria-modal="true"`、`aria-labelledby`；Tab/Shift+Tab 约束在对话框内，关闭恢复触发控件 |
| 5 | 编辑器中无脏状态保护（关闭/取消时丢失输入） | 各 View.js | MEDIUM | 4h | ✅ 已修复共享模态路径：打开时记录控件基线，关闭/取消/遮罩/Escape 对真实可编辑差异确认放弃；成功 action 免确认 |
| 6 | `router.js:276-306` A→B→A 快速导航时慢请求覆盖为新项目 | `router.js` | CRITICAL | 3h | ✅ 已修复：AbortSignal + 请求代次 + 应用内 no-store；过期导航不提交 metadata/view/hash/渲染 |
| 7 | `generateView:1093-1150` 聊天历史写 localStorage 无大小限制 | `generateView.js` | CRITICAL | 2h | ✅ 已修复：单项目 512 KiB 上限、最多 5 项目 LRU、超限先丢弃预览再收敛为最近 40 条；项目隔离 + 损坏去重警告 |
| 8 | EbookLib AGPLv3+ 许可证需评估替代方案 | 依赖管理 | HIGH | 4h | ⏳ 未变：保留为 backlog |

### ⚙️ 运维（3-5 项）

| # | 标题 | 位置 | 严重性 | 工作量 | 复核状态 |
|---|------|------|--------|--------|---------|
| 1 | 日志中几乎无 `novel_id` 上下文 — 无法按项目过滤日志 | 全局日志 | CRITICAL | 4h | ✅ 已修复当前 HTTP/worker 关联边界：HTTP scope 与 worker attempt 用独立 ContextVar，project facade 验证成功后绑定规范化 UUID；未验证只记安全占位符 |
| 2 | 无请求日志中间件 — 无访问日志/审计轨迹 | `main.py` | HIGH | 2h | ✅ 已修复：最外层 ASGI access log，记录受控 method/route template/status/duration + `X-Request-Time-Ms` |
| 3 | 无外部指标系统（Prometheus/Datadog/Sentry） | 项目根 | HIGH | 8h | ⏸ 合理暂缓：须由正式运维方案决定 |
| 4 | `DomainError` 处理器不记录日志 | `main.py:307-318` | HIGH | 0.5h | ✅ 已修复：4xx 记 INFO、5xx 记 ERROR；只记白名单 method/route template/status/code，不记领域 message/动态路径/请求体/Key/traceback |
| 5 | 无备份策略 | `docker-compose.yml` | HIGH | 2h | ⏸ 合理暂缓：须由正式运维方案决定 |

---

## 第三部分：统计摘要

### 各轮发现数统计

| 轮次 | 主题 | 总数 | CRITICAL | HIGH | MEDIUM | LOW |
|------|------|------|----------|------|--------|-----|
| R01 | 后端模块全面扫描 | 251 | 24 | 60 | 95 | 72 |
| R02 | 跨模块交互/安全/数据流/文档 | 59 | 5 | 11 | 21 | 22 |
| R03 | 深层模式（异常/竞态/事务/配置） | 80 | 9 | 18 | 29 | 24 |
| R04 | 架构一致性/性能 | 93 | 3 | 13 | 49 | 38 |
| R05 | 基础设施/质量 | 62 | 4 | 22 | 25 | 11 |
| R06 | 依赖/数据流/债务/异步 | ~60 | 0 | 17 | 16 | 27 |
| R07 | 数据层/构建系统 | ~90 | 7 | 21 | 38 | 24 |
| R08 | 深层架构/一致性 | 55 | 0 | 8 | 24 | 23 |
| R09 | 中间件/前端状态/迁移/WebSocket | 65 | 9 | 16 | 24 | 16 |
| R10 | 文件上传/限流/CORS/密钥 | 71 | 5 | 9 | 18 | 39 |
| R11 | 缓存/后台作业/事件模式 | ~77 | 1 | 6 | 12 | 58 |
| R12 | i18n/a11y/响应式/跨浏览器 | ~542 | 2 | 10 | 16 | ~514 |
| R13 | API 版本化/HTTP 方法/状态码 | ~27 | 0 | 2 | 6 | 19 |
| R14 | 测试基础设施/Fixture/Mock | ~21 | 1 | 3 | 8 | 9 |
| R15 | 错误消息/UX 流程 | ~40 | 8 | 11 | 12 | 9 |
| R16 | Python 兼容/Docker/CI-CD/许可 | ~28 | 3 | 8 | 9 | 8 |
| R17 | Git 卫生/Review/README/贡献指南 | ~27 | 0 | 7 | 12 | 8 |
| R18 | 性能分析/内存泄漏/打包体积* | — | — | — | — | — |
| R19 | Web 安全/认证/API Key/数据隐私* | — | — | — | — | — |
| **合计** | | **~1,700** | **~81** | **~242** | **~414** | **~963** |

*\* R18/R19 审计进行中，发现数据暂未计入统计。*

### P0/P1 复核收口分布（47 项，含代码级核对修正）

| 分类 | 已修复 | 合理暂缓 | 不成立/过时/未立证 | 部分不符/部分修复 | 待修 |
|------|--------|---------|-------------------|------------------|------|
| P0-CRITICAL（8） | #1、#3、#4、#5、#6、#7（6） | #2、#8（2） | 0 | 0 | 0 |
| P1 Top 20（8） | #10、#12、#13（3） | 0 | #9、#14（2） | #11⚠️、#15⚠️、#16⚠️（3） | 0 |
| 安全 P1（8） | S3、S4、S5、S8（4） | S2（1） | S1、S6（2） | S7⚠️（1） | 0 |
| 测试 P1（6） | T1、T2、T3、T4、T5、T6（6） | 0 | 0 | 0 | 0 |
| 部署 P1（5） | D2（1） | D1、D3（2） | D4、D5（2） | 0 | 0 |
| UX P1（7） | U1–U7（7） | 0 | 0 | 0 | 0 |
| 运维 P1（5） | O1、O2、O4（3） | O3、O5（2） | 0 | 0 | 0 |
| **合计** | **30** | **7** | **6** | **4** | **0** |

> 代码级核对将 T4 从"不成立"升级为"已修复"（test_api.py 确实存在）；#11、#15、#16、S7 标记为⚠️部分不符，状态标签需细化但不改变"当前无阻塞待修项"的结论。

### 按模块的严重程度分布（原始审计口径）

| 模块 | 估计发现数 | 关键问题 | 核心风险 |
|------|-----------|---------|---------|
| **world** | ~60 | 4 CRIT | 部分提交、封装破坏、多 worker 锁失效、递归栈溢出 |
| **writing** | ~50 | 6 CRIT | 版本历史不一致、并发切分、TOCTOU 删除 |
| **outline** | ~50 | 4 CRIT | enqueue_task 未导入、竞态合并/拆分、索引增长 |
| **frontend** | ~100+ | 13 CRIT | XSS、DOM 缓存泄漏、跨视图状态污染、竞态导航 |
| **imports** | ~35 | 3 CRIT | 回滚后 session 崩溃、区间无效、Phase 3 资产永久丢失 |
| **rag** | ~25 | 3 CRIT | 任务状态无限卡死、novel_id 隔离绕过、SQLite 兼容性 |
| **settings** | ~15 | 1 CRIT | LookupError 500 而非 404 |
| **memory** | ~15 | 1 CRIT | relation_id 缺失时清空所有 relations |
| **context** | ~20 | 1 CRIT | datetime.utcnow() 时区不一致 |
| **project** | ~20 | 0 CRIT | 软删除绕过、TOCTOU 竞态 |
| **infrastructure** | ~30 | 0 CRIT | 任务 lease 延迟加载、worker CancelledError 处理 |
| **test** | ~30 | 3 CRIT | 假阳性断言、共享 fixture 无隔离、Mock-in-production |
| **core/shared** | ~15 | 0 CRIT | 测试覆盖空白、配置安全默认值 |
| **部署/CI/CD** | ~30 | 6 CRIT | 无 Dockerfile、无 CI/CD、无分支保护、密钥泄露 |
| **安全** | ~40 | 8 CRIT | API Key 泄露、无限流、无安全头、XSS、CSRF |

> 注：上表为原始审计估计口径，部分"关键问题"已在第一轮修复中收口（如 Mock-in-production、pg_trgm rollback、安全头、速率限制、骨架屏、router 竞态、setTimeout 绑定竞态、模态 ARIA、脏状态保护、localStorage 限制、access log、novel_id 上下文、DomainError 日志等）。剩余 CRITICAL 多属合理暂缓的部署/运维项或已立证不成立项。

### 按主题分类（原始口径）

| 主题类别 | 发现数 | CRITICAL | 修复优先级 |
|----------|-------|---------|-----------|
| 🔒 安全 | ~100 | ~15 | **P0 - 立即** |
| 📊 数据完整性 | ~80 | ~12 | **P0 - 立即** |
| 🚀 可部署性 | ~50 | ~8 | **P0-P1** |
| 🐞 代码质量 | ~300 | ~10 | P1-P2 |
| 🎨 用户体验 | ~80 | ~13 | P1-P2 |
| ⚙️ 运维 | ~50 | ~5 | P1-P2 |
| 🧪 测试 | ~60 | ~3 | P1-P2 |
| 📝 文档/治理 | ~70 | 0 | P2-P3 |
| 🌐 国际化 | ~500 | 0 | P3（架构级） |
| 📦 性能/打包 | ~40 | 0 | P2-P3 |

### 整体评分（1-10）

| 维度 | 原始评分 | 复核评分 | 变化说明 |
|------|---------|---------|---------|
| **安全** | 3/10 | 5.5/10 | 已修复：安全响应头、速率限制（单 worker 边界）、上传内容验证、LLM RPM fail closed、token 不再入 Web Storage、DEBUG 配置统一、凭据防回归门禁；暂缓：CSP 收紧；部分成立：S7 DB 单用户无独立迁移配置；不成立：CSRF/metrics 认证 |
| **数据完整性** | 5/10 | 6.5/10 | 已修复：pg_trgm savepoint 恢复、dict body typed 化、静默降级补日志；不成立：删除撤销（已为软废弃） |
| **可部署性** | 1/10 | 3/10 | 已修复：CI workflow、start.sh 含 worker；暂缓：Dockerfile/多 worker/反向代理须由正式部署目标决定 |
| **代码质量** | 6/10 | 7/10 | 已修复：Mock-in-production 移除、Scene workbench 异常泄露收口、dict body typed；不成立：领域事件/showModalHtml 未立证为阻塞 |
| **用户体验** | 4/10 | 6.5/10 | U1–U7 全部修复：409 映射、setTimeout 绑定竞态、大纲错误状态、模态 ARIA、脏状态保护、router 竞态、localStorage 限制；#16 骨架屏仅首屏覆盖，视图级未用（⚠️部分修复） |
| **测试质量** | 7/10 | 8/10 | 已修复：core/shared 覆盖、async fixture、xdist/timeout、跨模块串行场景、coverage 85% 门禁、Memory/RAG API 测试（T4 经代码核对确认已存在） |
| **运维** | 2/10 | 5/10 | 已修复：access log、novel_id 上下文、DomainError 日志；暂缓：外部指标系统、备份策略 |
| **文档** | 5/10 | 5/10 | 未变 |
| **API 设计** | 6/10 | 6.5/10 | 已修复：dict body typed、Scene workbench 异常泄露；剩余 21 处 `detail=str(...)` 均在显式 4xx 分支 |
| **性能** | 5/10 | 5/10 | 未变（进程内同步嵌入、O(n²) 回退、N+1 仍为 backlog） |
| **治理** | 2/10 | 4/10 | 已修复：CI workflow、凭据防回归门禁；待授权：main 分支保护；`make format` 因 27 个存量未格式化文件暂未入 CI |
| **综合** | 4.5/10 | **5.5/10** | 第一轮修复收口 30/47 P0/P1 项；代码级核对确认 41/47 项声称属实，6 项部分不符已细化；架构设计优秀，工程化短板已部分补齐；剩余短板集中在正式部署方案、视图级骨架屏覆盖与外部运维 |

---

## 路线图总结建议（复核修订版）

### 已完成（第一轮修复，提交 `d42462aa4`）
- ✅ #1 凭据防回归门禁 + #3 Mock-in-production 移除 + #5 安全响应头 + #6 静默降级补日志 + #7 pg_trgm savepoint 恢复
- ✅ #4 速率限制（单 worker/direct-peer 边界）+ S3 上传内容验证 + S4 LLM RPM fail closed + S5 token 不入 Web Storage + S8 DEBUG 配置统一
- ✅ #10 Scene workbench 异常泄露收口 + #12 前端 LLM 超时 90s + #13 dict body typed
- ✅ T1 core/shared 覆盖 + T2 async fixture + T3 xdist/timeout + T4 Memory/RAG API 测试（代码核对确认） + T5 跨模块串行场景 + T6 coverage 85% 门禁
- ✅ D2 start.sh 含 worker + U1–U7 全部 UX 修复 + O1 novel_id 上下文 + O2 access log + O4 DomainError 日志
- ✅ #2 仓库侧 CI workflow（GitHub main 分支保护待远端授权）

### 待外部授权或正式部署目标触发（合理暂缓，7 项）
1. #2 GitHub `main` 分支保护 — 需远端设置授权后把 CI job 设为必需检查
2. #8 Dockerfile + D1 多 worker + D3 反向代理 — 须由正式部署目标、进程模型和 TLS 边界共同决定
3. S2 CSP 收紧 — 须先完成系统性前端样式迁移并更新 ADR
4. O3 外部指标系统（Sentry/Prometheus）+ O5 备份策略 — 须由正式运维方案决定

### 已立证不成立或过时（6 项，不再作为既定缺陷）
- #9 领域事件 — 设计/质量改进，未证明阻塞主流程（代码确认：`writing/tasks.py` 硬编码顺序但功能正常）
- #14 embedding cache key — 进程内单例无热切换入口，原路径无法复现（代码确认：`cache.py:28-30` key 不含模型名，但 `client.py:70-71` 单例构造时固定路径）
- S1 CSRF — Bearer token 认证下 CSRF 检查无实际防御意义（代码确认：`main.py:394-413` Bearer token 认证）
- S6 metrics 认证 — 已由全局 access-token 中间件覆盖（代码确认：`/api/rag/metrics` 不在豁免列表）
- D4 Compose 密码 — 本地开发凭据 `novel_dev_pass`（代码确认：`docker-compose.yml:11`）
- D5 .dockerignore — 无 Dockerfile，无构建消费者（代码确认：全局搜索零结果）

### 部分不符/部分修复（4 项，需细化状态但不阻塞）
- #11 showModalHtml — 仍无内置转义，但全体 100+ 调用方一致使用 `esc()`；属约定安全，有单点遗漏风险
- #15 删除撤销 — Writing/Scene 已软废弃；地图删除仍是硬 DELETE（demo 阶段允许+二次确认）
- #16 骨架屏 — 仅首屏使用，写作/大纲/Scene 工作台视图内加载态未覆盖
- S7 DB 单用户 — 无独立迁移用户配置项，安全关注点有合理性，可手动通过环境变量区分

### 剩余 backlog（不标为 P0，按真实故障/反馈/部署目标触发）
1. #16 骨架屏视图级覆盖（首屏已用，写作/大纲/Scene 工作台视图内加载态未覆盖）
2. #19 settings LookupError 500→404、#17 autospec 逐步添加、246 处冗余 asyncio mark 清理
2. 结构化日志深化、领域事件机制、模块拆分（2000+ 行文件）
3. API 版本化、i18n 国际化、WebSocket 替代轮询、AGPLv3 依赖评估
4. `make format` 干净基线建立后启用 CI 格式门禁

---

## 附录：验证修正记录

以下修正基于并行 sub-agent 对全部 P0/P1 发现的实际代码审查，修正前文不准确项。

### 误报（NOT FOUND — 原报告错误）

| 原报告断言 | 验证结果 | 修正说明 |
|-----------|---------|---------|
| `enqueue_task` 未导入（P0） | 已正确导入 `outline/api.py:8` | 审计误读代码 |
| 真实 API Key 泄露（P0） | 仅占位符 `sk-placeholder` 曾提交 | 无真实密钥泄露 |
| 20+ 处 `except Exception: pass`（P0） | 3 处纯 pass + 若干静默降级 | 其余有日志/返回值 |
| 1494 处冗余 `@pytest.mark.asyncio` | 实际 246 处 | 计数高估 6 倍 |
| 无 Python lock 文件（P2） | 已有 `uv.lock` + `requirements.txt` | 审计遗漏文件 |
| 3 个 dict body 端点 | 实际 2 处 | 多报了 1 处 |

### 需修正措辞（PARTIALLY — 原报告夸大了严重性或低估了数量）

| 原报告断言 | 验证修正 |
|-----------|---------|
| core/shared 零测试覆盖 | core 的 config/database/container 在 `tests/unit/` 下有测试；dependencies.py + 整个 shared 为零（第一轮已补齐） |
| 8 处 async fixture 误用 | 实际 11 个文件 18 处（多了 `test_base.py` 等） |
| 前端 innerHTML 未转义 | 74 处 innerHTML 中绝大部分正确使用 `esc()`；`showModalHtml` 依赖调用方纪律 |
| 跨模块 E2E 场景缺失 | 各模块有碎片化 E2E 测试，但缺少完整串行流程（第一轮已补齐） |

### 完全确认（CONFIRMED — 与实际代码一致，且第一轮已修复）

| 类别 | 项数 | 关键项 | 修复状态 |
|------|------|--------|---------|
| P0 | 6 | Mock-in-production 9 处、无速率限制、无安全头、except pass 3 处、pg_trgm 缺 rollback | 全部 ✅ 已修复（代码核对确认） |
| P1 Top 20 | 3 | writing.generate 15s 超时、dict body 2 处 | 全部 ✅ 已修复（代码核对确认） |
| 安全 | 4 | 无 MIME 验证、LLM 无限流、sessionStorage token | 3 ✅ + S2 ⏸暂缓 |
| 测试+部署 | 7 | async fixture 18 处、无 xdist/timeout、跨模块 E2E、无 cov 配置、Memory/RAG API 测试、start.sh 无 worker | 全部 ✅ 已修复（T4 经代码核对升级为已修复） |
| UX+Ops | 10 | 409 未映射、setTimeout 竞态、4 处静默 error、ARIA 缺失、无脏状态、router 竞态、localStorage 无限制、日志无 novel_id、无 access log、DomainError 静默 | 全部 ✅ 已修复（代码核对确认） |

### 代码级核对发现的偏差（6 项部分不符）

| 项 | 原声称 | 代码核对结论 |
|---|--------|-------------|
| #2 | ⏸仓库侧已完成 | CI 比描述更完整，状态标签准确 |
| #11 | ❌未立证为阻塞 | ⚠️ 约定安全有单点遗漏风险，状态合理但需标注 |
| #15 | ❌描述已过时 | ⚠️ 地图删除仍是硬 DELETE（demo 允许） |
| #16 | ✅已修复主加载边界 | ⚠️ 仅首屏覆盖，视图级未用骨架屏 |
| S7 | ❌论证未成立 | ⚠️ 无独立迁移用户配置，关注点有合理性 |
| T4 | ❌描述已失效 | ✅ 升级为已修复，test_api.py 确实存在 |

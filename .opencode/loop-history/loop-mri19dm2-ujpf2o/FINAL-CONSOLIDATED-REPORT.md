# 🔍 最终整合报告：优先级排序与修复路线图

**生成日期**: 2026-07-13  
**来源**: 20 轮审计（R1-R19 完成，R18-R19 进行中）  
**累计发现**: ~1,700 项（CRITICAL: ~81, HIGH: ~242, MEDIUM: ~414, LOW: ~421 + ~500 i18n）

---

## 第一部分：Top 20 立即修复（按影响排序）

### P0-CRITICAL

| # | 标题 | 位置 | 为什么现在修复 | 工作量 |
|---|------|------|---------------|--------|
| 1 | **API Key 已提交至 Git 历史** | `backend/.env`（曾提交） | 真实 `sk-5MQh...` 和 `AqPK...` 密钥已泄露。需立即轮换 + Git 历史清理 | 2h 轮换密钥 + 4h BFG 清理 |
| 2 | **CRIT-1: 零 CI/CD + 无分支保护** | 项目根 | 任何变更直接合入 main，无测试/审查门禁。Block 所有其他修复 | 4h 搭建 GitHub Actions + main 保护 |
| 3 | **Mock-in-production — 生产代码检测 Mock** | `imports/workflow.py:17`, `orchestrator.py:514,541`, `extraction_service.py:81` | 7 处 `isinstance(db, Mock)` 改变生产行为，测试未验证真实路径 | 3h 移除 Mock 检测，重构测试 |
| 4 | **无 HTTP 速率限制 — 无 DoS 防护** | 全局（FastAPI 应用） | 任何客户端可耗尽连接池、压垮 LLM。缺 `slowapi`/令牌桶 | 3h 集成速率限制中间件 |
| 5 | **后端完全缺失安全响应头** | `main.py` 中间件 | 无 HSTS/X-Frame-Options/X-Content-Type-Options → 点击劫持/MIME 嗅探/降级攻击 | 2h 添加安全头中间件 |
| 6 | **enqueue_task 未导入 — 3 个端点运行时必挂** | `outline/api.py:105` | `analyze`/`generate`/`extract` 端点调用未导入函数 | 0.5h 添加 import |
| 7 | **~20+ 处 `except Exception: pass` 吞关键错误** | 多个模块（embedding/worker.py, world/services, rag/source_collection.py 等） | 掩盖 DB 连接失败、LLM 超时、竞态条件，导致无声数据丢失 | 4h 逐处修复：记录日志 + 最小恢复 |
| 8 | **DTO 对象因 `PendingRollbackError` 回滚后瘫痪** | `world/repositories.py:158-165,725-728` | `pg_trgm` 错误后 fallback 查询前未 `rollback()` → 后续所有查询失败 | 2h 添加 `rollback()` 守卫 |

### P1-HIGH

| # | 标题 | 位置 | 为什么现在修复 | 工作量 |
|---|------|------|---------------|--------|
| 9 | **无 Dockerfile — 无法可重复部署** | 项目根 | 零容器化路径，每次部署手工操作不可重现 | 4h 编写 Dockerfile + .dockerignore |
| 10 | **无领域事件机制 — 模块间耦合严重的发布工作流** | `writing/tasks.py` publish_chapter handler | RAG 索引→内存快照硬编码顺序，无法扩展 | 8h 设计轻量领域事件总线 |
| 11 | **前端 `innerHTML` 未转义（XSS 风险）** | 多处前端文件 | API 返回内容直接 `innerHTML` 赋值，用户/AI 内容可能含恶意脚本 | 4h 全面审计并加 `esc()` |
| 12 | **LLM 生成 API 前端 15s 超时 — 必然失败** | 前端 `api.js` 调用 | AI 生成需 60-120s，前端超时设置远低于实际耗时 | 1h 调整超时配置 |
| 13 | **3 个 API 端点接受未经类型验证的 dict body** | `imports/api.py:281,308` + 多处 | `body: dict = Body(...)` 绕过所有 Pydantic 校验 | 2h 定义 Pydantic schema |
| 14 | **嵌入缓存 key 缺模型名** | `embedding/cache.py:28-30` | 切换模型后最多 1h 返回旧模型结果 | 1h key 中加入 model_name |
| 15 | **无删除撤销系统 — 所有删除操作不可逆** | 全局（除 project 回收站） | 章节/场景/剧情线/伏笔/揭示硬删除，无用户错误恢复路径 | 12h 设计软删除/回收站方案 |
| 16 | **CSS 骨架屏已定义但零使用** | `styles.css` + 各视图 | 5 个视图还在用"加载中..."文本，骨架屏 CSS 完全浪费 | 2h 替换 5 处 loading 状态 |

### P2-MEDIUM

| # | 标题 | 位置 | 为什么现在修复 | 工作量 |
|---|------|------|---------------|--------|
| 17 | **无 Python lock 文件 — 依赖图不可复现** | 项目根 | 不同 install 解析不同依赖图，团队/CI 行为不一致 | 1h 生成 `requirements.lock` |
| 18 | **50+ 处 `detail=str(exc)` 泄露 Python 异常给前端** | 多个 api.py | 暴露 SQL/路径/内部实现细节给客户端 | 3h 替换为安全错误消息 |
| 19 | **`autospec=True` 零使用 — mock 不验证 API 形状** | 150+ `@patch` 调用 | 签名变化时 mock 不失败，测试假阳性 | 6h 逐步添加 autospec |
| 20 | **项目列表（入口页面）无 loading/错误状态** | `projectView.js:280-295` | 用户看到的第一个页面，API 失败只显示空数组 | 1h 添加 loading + error UI |

---

## 第二部分：短中期修复（按主题分组）

### 🔒 安全加固（5-8 项）

| # | 标题 | 位置 | 严重性 | 工作量 |
|---|------|------|--------|--------|
| 1 | CSRF 保护仅依赖 `X-Requested-With` — 同源 XSS 可绕过 | 全局中间件 | HIGH | 3h 加固 CSRF 策略 |
| 2 | CSP `style-src 'unsafe-inline'` 削弱 XSS 防御 | `index.html` meta tag | HIGH | 1h 收紧 CSP |
| 3 | 文件上传无 MIME/幻数验证 — `.exe` 重命名即接受 | `imports/upload` | HIGH | 2h 添加 `python-magic` 验证 |
| 4 | `LLM_RATE_LIMIT_PER_MINUTE=0` 默认无限 | `config.py` | HIGH | 0.5h 设置合理默认值 |
| 5 | `Bearer Token` 明文存 sessionStorage 通过 HTTP 发送 | 前端认证 | HIGH | 4h 添加 HTTPS 强制 + Secure flag |
| 6 | `rag/api.py:143` `/metrics` 端点无认证 | `rag/api.py` | HIGH | 1h 添加认证守卫 |
| 7 | 数据库单用户运行迁移和运行时（DDL+DML 共用） | `alembic.ini` + config | MEDIUM | 2h 分离迁移/运行时用户 |
| 8 | `backend/.env` 环境变量名不匹配：`APP_DEBUG` vs `DEBUG` | `config.py` + `.env.example` | HIGH | 0.5h 规范化命名 |

### 🧪 测试质量（5-8 项）

| # | 标题 | 位置 | 严重性 | 工作量 |
|---|------|------|--------|--------|
| 1 | `core/` + `shared/` 层零测试覆盖（config/database/container） | `core/`, `shared/` | HIGH | 6h 为核心基础设施加测试 |
| 2 | 8 处 `@pytest.fixture` + `async def` 应改用 `@pytest_asyncio.fixture` | 测试文件 | HIGH | 1.5h 统一 fixture 装饰器 |
| 3 | 无 `pytest-xdist` 并行 + `pytest-timeout` 挂起防护 | `pyproject.toml` | MEDIUM | 1h 配置插件 |
| 4 | Memory 模块无 API 层测试 + RAG 无独立 API 测试 | `tests/` | MEDIUM | 4h 补 API 层测试 |
| 5 | 跨模块 E2E 场景缺失（导入→生成→发布→检索） | E2E tests | MEDIUM | 6h 编写端到端串行测试 |
| 6 | 无 `pytest-cov` 阈值/报告配置 | `pyproject.toml` | LOW | 1h 配置覆盖率门禁 |
| 7 | 1494 处冗余 `@pytest.mark.asyncio`（`asyncio_mode=auto` 下死代码） | 测试文件 | LOW | 批量清理（脚本化） |

### 🚀 部署（3-5 项）

| # | 标题 | 位置 | 严重性 | 工作量 |
|---|------|------|--------|--------|
| 1 | 无生产 gunicorn/多 worker 启动配置 | 项目根 | HIGH | 3h 编写 `gunicorn.conf.py` + 生产 entrypoint |
| 2 | `start.sh` 未启动任务 worker — 后台任务不处理 | `start.sh` | CRITICAL | 0.5h 修复脚本 |
| 3 | 无反向代理（nginx/Caddy）— 无 TLS/静态文件服务 | 项目根 | HIGH | 4h 配置 nginx |
| 4 | `POSTGRES_PASSWORD` 明文硬编码在 docker-compose.yml | `docker-compose.yml` | HIGH | 0.5h 替换为环境变量 |
| 5 | 无 `.dockerignore` — 构建上下文过大 + 含 `.env` | 项目根 | HIGH | 0.5h 创建 `.dockerignore` |

### 🎨 用户体验（5-8 项）

| # | 标题 | 位置 | 严重性 | 工作量 |
|---|------|------|--------|--------|
| 1 | HTTP 409 错误未在前端 errorMap 映射 — 显示"请求失败" | 前端 error handler | HIGH | 2h 添加 409 映射 |
| 2 | `setTimeout(()=>_bindEvents(),0)` 竞赛条件 — 内存泄漏 + 跨视图污染 | 各 View.js | CRITICAL | 6h 用 MutationObserver 替换 |
| 3 | 大纲子视图错误静默吞掉 — 用户看到空状态而非错误 | `outlineView.js:207-240` | HIGH | 2h 添加 toast 错误提示 |
| 4 | 模态框 ARIA 三重缺失（焦点陷阱/无 role="dialog"/无 aria-labelledby） | `index.html:165` + `modal.js` | HIGH | 3h 添加 a11y 属性 |
| 5 | 编辑器中无脏状态保护（关闭/取消时丢失输入） | 各 View.js | MEDIUM | 4h 添加 dirty flag + 确认对话框 |
| 6 | `router.js:276-306` A→B→A 快速导航时慢请求覆盖为新项目 | `router.js` | CRITICAL | 3h 添加 AbortController + 响应时间校验 |
| 7 | `generateView:1093-1150` 聊天历史写 localStorage 无大小限制 | `generateView.js` | CRITICAL | 2h 添加 LRU + 大小限制 |
| 8 | EbookLib AGPLv3+ 许可证需评估替代方案 | 依赖管理 | HIGH | 4h 评估 `pypub`/`python-docx` 替代 |

### ⚙️ 运维（3-5 项）

| # | 标题 | 位置 | 严重性 | 工作量 |
|---|------|------|--------|--------|
| 1 | 日志中几乎无 `novel_id` 上下文 — 无法按项目过滤日志 | 全局日志 | CRITICAL | 4h 添加结构化日志 + novel_id 上下文 |
| 2 | 无请求日志中间件 — 无访问日志/审计轨迹 | `main.py` | HIGH | 2h 添加 access log 中间件 |
| 3 | 无外部指标系统（Prometheus/Datadog/Sentry） | 项目根 | HIGH | 8h 集成 Sentry + Prometheus |
| 4 | `DomainError` 处理器不记录日志 | `main.py:307-318` | HIGH | 0.5h 添加 `logger.exception()` |
| 5 | 无备份策略 | `docker-compose.yml` | HIGH | 2h 编写 pg_dump 脚本 |

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

### 按模块的严重程度分布

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

### 按主题分类

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

| 维度 | 评分 | 说明 |
|------|------|------|
| **安全** | 3/10 | 严重漏洞存在（Key 泄露、无速率限制、XSS 未完全防护） |
| **数据完整性** | 5/10 | novel_id 隔离设计好但实现有洞，竞态条件多 |
| **可部署性** | 1/10 | 零 CI/CD、零容器化、零生产配置 |
| **代码质量** | 6/10 | 架构分层好，但模块过大（2,189 行文件）、Mock-in-production 严重 |
| **用户体验** | 4/10 | 无撤销、无引导、错误处理原始、a11y 差 |
| **测试质量** | 7/10 | 数量充足（5,170 用例），但有假阳性、核心基础设施零覆盖 |
| **运维** | 2/10 | 无可观测性、无结构化日志、无指标、无备份 |
| **文档** | 5/10 | 模块 README 优秀，但缺 LICENSE/CONTRIBUTING/CHANGELOG |
| **API 设计** | 6/10 | 一致性较好但缺版本化、错误文档、示例 |
| **性能** | 5/10 | 进程内同步嵌入推理阻塞、O(n²) 回退、N+1 查询普遍 |
| **治理** | 2/10 | 无分支保护、无 PR 模板、30% 非规范提交、51MB 二进制文件在 Git |
| **综合** | **4.5/10** | 架构设计优秀但工程化严重不足；安全+部署+运维是最薄弱环节 |

---

## 路线图总结建议

### 立即处理（1-2 天）— 安全 + 部署底线
1. 轮换泄露的 API Key + 清理 Git 历史
2. 搭建 CI/CD 流水线 + main 分支保护
3. 修复 `except Exception: pass` 吞错误（20+ 处）
4. 添加 HTTP 速率限制 + 安全响应头
5. 修复 `enqueue_task` 未导入
6. 移除 Mock-in-production 检测

### 短期（1 周）— 数据完整 + 用户体验
1. 修复竞态条件（writing/outline 模块 10+ 处）
2. 添加删除撤销系统
3. 修复 50+ 处 `detail=str(exc)` 异常泄露
4. Dockerfile + 生产启动配置
5. 骨架屏替换 loading 文本
6. 修复 router 导航竞态

### 中期（2-4 周）— 质量 + 运维
1. 结构化日志 + novel_id 上下文
2. 领域事件机制
3. 核心基础设施测试覆盖
4. Sentry/Prometheus 监控
5. Python lock 文件 + 依赖同步
6. 模块拆分（2000+ 行文件 → 可维护大小）

### 长期（1-3 月）— 架构演进
1. API 版本化策略
2. i18n 国际化基础设施
3. WebSocket 替代 REST 轮询
4. 前端虚拟 DOM 迁移评估
5. AGPLv3 许可证依赖替换评估

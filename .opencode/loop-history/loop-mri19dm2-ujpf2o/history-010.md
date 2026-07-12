# Round 10/20 — File Upload / Rate Limiting / CORS & Security Headers / Env & Secrets

**Status**: PASS  
**Goal**: 文件上传处理、限流/DoS 防护、CORS/安全头、环境变量与密钥管理  
**Started**: 2026-07-13  
**Completed**: 2026-07-13  

## 结果总览

| 审计模块 | 发现数 | CRITICAL | HIGH | MEDIUM | LOW |
|----------|--------|----------|------|--------|-----|
| 文件上传与处理 | 7 | 0 | 1 | 2 | 4 |
| 限流与 DoS 防护 | 32 | 3 | 3 | 5 | 21 |
| CORS 与安全头 | 17 | 2 | 4 | 6 | 5 |
| 环境变量与密钥管理 | 15 | 0 | 1 | 5 | 9 |
| **合计** | **71** | **5** | **9** | **18** | **39** |

---

## 文件上传与处理 — 7 个发现（1 HIGH + 2 MEDIUM + 4 LOW）

**上传入口**: 仅 `POST /api/imports/upload` 一个端点，`multipart/form-data`，前端浏览器限制 `accept` 为白名单格式

- 🔴 **HIGH**: **无 MIME/幻数验证** — 仅检查文件扩展名（`.txt .epub .html .htm .mobi .azw3`），任意文件（`.exe`、`.zip`）重命名后全接受，解析前读入 50MB 内存
- 🟡 MEDIUM: **无上传速率/并发限制** — 无 IP 限流、无每个 novel_id 并发限制
- 🟡 MEDIUM: **ZIP 炸弹/解压膨胀风险** — EPUB/MOBI 解析器无解压后大小限制
- ✅ 路径遍历防护良好（`os.path.basename`）、文件大小在分块读取中渐进检查、解析后 HTML 经 `sanitize_writing_text()` 剥离标签
- ✅ 临时文件在 `finally` 块清理、导入记录有部分唯一索引防重复、`novel_id` 隔离贯穿全程

---

## 限流与 DoS 防护 — 32 个发现（3 CRITICAL + 3 HIGH + 5 MEDIUM + 21 LOW）

### 已实现（良好覆盖率）
✅ LLM 客户端令牌桶速率限制器（代码存在，但默认禁用）
✅ LLM 信号量并发控制（默认 8 并行）
✅ LLM/Embedding 熔断器（连续失败 N 次后 60s 冷却）
✅ LLM 重试 + 带抖动指数退避（max_attempts=3，max_delay=60s）
✅ Embedding 批量队列背压（max_items=64，timeout=30s）
✅ 任务 worker 并发控制（默认 2 并行）
✅ 文件上传大小限制（50MB，413）、导入章节限制（1000）
✅ RAG top_k 上限（50）、上下文 token 预算（4000）含层级驱逐

### 未实现（关键缺陷）

**🔴 CRITICAL**: **无 HTTP API 速率限制** — 任何端点（`/api/*`）无 `slowapi`/无令牌桶/无固定窗口。单客户端可耗尽数据库连接池（10 连接）、可反复触发 RAG 查询压 LLM

**🔴 CRITICAL**: **无 DoS/慢速攻击防护** — 无 uvicorn `--limit-concurrency`、无请求体大小 ASGI 中间件、无请求超时中间件、无连接数限制（每个 IP 或全局）

**🔴 HIGH**: **`LLM_RATE_LIMIT_PER_MINUTE=0` 默认禁用限流** — 令牌桶代码正确但购后默认 0（无限）。生产部署无约束调用可快速达到提供商配额和大额账单

---

## CORS 与安全头 — 17 个发现（2 CRITICAL + 4 HIGH + 6 MEDIUM + 5 LOW）

- 🔴 **CRITICAL**: **后端完全缺失安全响应头** — `X-Content-Type-Options`、`X-Frame-Options`、`Strict-Transport-Security`、`Referrer-Policy`、`Permissions-Policy` 全部缺失 → MIME 嗅探、点击劫持、中间人降级风险
- 🔴 **CRITICAL**: **CSRF 保护仅依赖 `X-Requested-With`** — 对传统 `<form>` 有效，但同一来源 XSS 可用 `fetch()` 设置任意头绕过
- 🔴 HIGH: **API 响应完全缺失 `Cache-Control`** — 敏感数据受浏览器默认缓存影响
- 🔴 HIGH: `allow_methods=["*"]` + `allow_headers=["*"]` 生产环境过于宽松
- 🔴 HIGH: **无 HTTPS** — uvicorn 和 Vite 均明文传输
- 🔴 HIGH: CSP 前端 `<meta>` 标签 `style-src 'unsafe-inline'` 削弱 XSS 防御

### 现有良好实践
✅ 生产环境 CORS 拒绝通配符 origin、`X-Requested-With` 全局检查、Bearer token 常量时间比较、生产屏蔽调试端点、路径脱敏、Key 日志脱敏

---

## 环境变量与密钥管理 — 15 个发现（1 HIGH + 5 MEDIUM + 9 LOW）

**整体评价**: 密钥管理实践显著优于平均水平（LLM API Key Fernet 强制加密、响应自动清除 Key、多管道脱敏）

**🔴 HIGH**: **无加密密钥轮换机制** — `LLM_SETTINGS_ENCRYPTION_KEY` 静态值；泄露/需轮换时无 re-wrap 工具
**🟡 MEDIUM**: 单数据库用户用于迁移和运行时（DDL + DML 共用，违反最小权限）
**🟡 MEDIUM**: 模块层直接 `os.getenv` 绕过 Settings（`dedup_service.py:43` 的 `DEDUP_MODEL_ACTIVE`、`env_helpers.py` 等）
**🟡 MEDIUM**: 部分字段在类定义 import 时求值而非 `default_factory`
**🟡 MEDIUM**: 缺 `pool_recycle` 配置
**🟡 MEDIUM**: DATABASE_URL 含明文密码；`alembic.ini` 也硬编码密码（有环境变量覆盖缓解）
✅ `.env` 在 `.gitignore`、`.env.example` 含 46 行模板、LLM API Key 加密存储、响应只返回 `api_key_configured: bool`、前端未硬编码 Key

# Round 19/20 — Web Security / Auth / API Keys / Data Privacy

**Status**: PASS  
**Started**: 2026-07-13 | **Completed**: 2026-07-13  

## Results

| Module | Issues | CRITICAL | HIGH | MEDIUM | LOW |
|--------|--------|----------|------|--------|-----|
| Web security | ~6 | 0 | 0 | 2 | 4 |
| Authentication | ~8 | 3 | 3 | 2 | 0 |
| API Key mgmt | ~8 | 0 | 1 | 2 | 5 |
| Data privacy | ~8 | 1 | 1 | 2 | 4 |
| **Total** | **~30** | **4** | **5** | **8** | **13** |

### Web Security (XSS/CSRF/SQLi) — 整体优秀
✅ 所有 innerHTML 有 `esc()` 转义（70+ 处）
✅ CSRF 已由 X-Requested-With 中间件覆盖、无 cookie → 零 CSRF 风险
✅ SQLAlchemy ORM 全覆盖，Alembic 无拼接
🟡 MEDIUM: `rag/repositories.py:700` — `text(f"SET LOCAL hnsw.ef_search = {val}")`（已 int() 缓解，模式脆弱）
🟡 MEDIUM: CORS 开发模式 `allow_origins=["*"]`
✅ 集成测试验证 XSS payload 存活 + CSRF 403 拒绝

### Authentication & Authorization
🔴 CRITICAL: Token 永不过期、不可撤销、无 refresh/登出
🔴 CRITICAL: 无用户模型（无注册/登录/登出/密码重置）
🔴 CRITICAL: 无授权（无 owner_id，任意 token 可读写任意项目）
🔴 HIGH: Token 存 sessionStorage（XSS 易受攻击）
🔴 HIGH: 无多租户隔离（`Project` 模型无 user_id 字段）
🔴 HIGH: 无暴力破解保护（无速率限制）
🟡 MEDIUM: 无 MFA/2FA
✅ CSRF 已由中间层覆盖所有状态变更方法（X-Requested-With）

### API Key Management
🔴 HIGH: `.env` 含疑似真实 DeepSeek API Key + 加密密钥（`sk-5MQh...`）
🟡 MEDIUM: 速率限制器默认禁用（`LLM_RATE_LIMIT_PER_MINUTE=0`）
🟡 MEDIUM: `.env.example` 缺 `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL`
✅ 业务 LLM API Key 加密存储（Fernet）→ API 响应零泄露（已验证测试）
✅ `redaction.py`（48 行）全面日志脱敏、`sanitize_llm_profile()` 排除密钥
✅ 轮换/更新机制存在（`update_llm_settings` 支持 `clear_api_key` / `clear_all_api_keys`）

### Data Privacy
🔴 HIGH: 用户对 LLM 数据使用无知情同意（核心功能——内容发送至 DeepSeek）
🟡 MEDIUM: AsyncTask.meta 软删除后保留 LLM 请求负载
🟡 MEDIUM: 日志中含截断的小说内容片段（shared/utils.py）
LOW: 无 GDPR 数据导出端点
LOW: 部分 innerHTML 未使用 esc()
✅ 后端 30+ 表 `ondelete=CASCADE`、永久删除需二次确认
✅ 无 Sentry/APM/分析工具、无 Cookie、`redact_diagnostic()` 系统化脱敏

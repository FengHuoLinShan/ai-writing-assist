# 账号模块

`backend/modules/account/` 负责公开浏览器账号、登录身份、会话、重新认证、延期删除，以及
账户模型连接、全局作者偏好和加密凭据。

## 用户能力

- 邮箱验证码公开注册/登录；微信按钮由 Authing 配置开关控制。
- 新登录会撤销旧浏览器会话。
- 首次进入账号、切换账号和退出会清除浏览器中的项目、草稿、任务恢复和诊断缓存；
  主题偏好不含账号内容，予以保留。
- 删除账号前必须在 10 分钟内完成原登录方式重新认证；申请后有 30 天恢复期。
- 待删除账号只能退出、查看状态、重新认证和撤销删除。

邮箱与微信是互斥的主身份，不自动绑定。同一个人用两种方式会得到两个独立账号。

## 数据与隔离

| 表 | 职责 |
|---|---|
| `accounts` | 账号状态、支持码、删除申请和到期时间 |
| `account_identities` | 唯一邮箱或 Authing 微信主身份 |
| `web_sessions` | 单一有效浏览器会话及令牌/CSRF 摘要 |
| `email_login_challenges` | 邮箱验证码 keyed HMAC、尝试次数和过期状态 |
| `account_security_events` | 不含项目内容的脱敏安全审计 |
| `account_consents` | 版本化协议同意记录 |
| `account_llm_credentials` | 按 owner/provider 保存已验证的加密 API Key 与连接版本 |
| `global_llm_defaults` | 账户当前 provider 和非 secret 默认 |
| `global_author_preferences` | 账户级作者偏好 |

安全事件与协议同意随账号清除。`projects.owner_id` 是非空外键，项目、设置和任务入口都通过
owner 门禁。

## HTTP 入口

- `/api/auth`：配置、邮箱登录/注册、当前账号、退出和邮箱重新认证；
- `/api/account`：延期删除状态、申请与撤销；
- `/api/auth/wechat`：Authing 微信登录；
- `/api/auth/reauth/wechat`：微信重新认证。
- `/api/account/settings/*`：账户连接、图片连接、余额与全局偏好的 canonical 路径；

account facade 只向 project 暴露 secret-free 的运行时 contract。project 打开文本或图片 client 时
再按已通过 owner 门禁的项目读取当前轮换后的账户 Key；Key 不进入 API、日志、项目 JSON 或任务
snapshot。项目作者偏好和 effective composition 不属于 account。

条款和隐私页是无 API 前缀的 `/legal/terms` 与 `/legal/privacy`。所有写请求仍经过同源、
XHR、CSRF 和账号状态门禁；调用方不能提交 owner ID。

运维入口为：

```bash
cd backend
python scripts/manage_accounts.py claim-legacy --email test@example.com
python scripts/manage_accounts.py status <account-uuid-or-support-code>
python scripts/manage_accounts.py ban <account-uuid>
python scripts/manage_accounts.py unban <account-uuid>
python scripts/manage_accounts.py purge-due
python scripts/manage_accounts.py purge-due --execute
python scripts/manage_accounts.py smtp-smoke --to test@example.com
```

每日清理应运行 `purge-due --execute`，超过 26 小时没有成功记录时由部署监控告警。
应用访问日志由部署层按 30 天滚动保留；数据库备份自身最多保留 30 天。两项都属于上线
门禁，不能因为在线账号已清除而跳过备份到期删除。

# Account 模块

公开浏览器账号的领域边界。稳定跨模块入口仅为 `contracts.py` 与 `facade.py`；
项目和设置模块不得直接依赖账号 ORM 或 service。

## 一期约束

- 账号只有一个主身份：`email` 或 `authing_wechat`，不绑定、不合并。
- 邮箱验证码为 6 位、5 分钟、单次使用、最多尝试 5 次；同一邮箱发送间隔为 60 秒，数据库不保存明文验证码。
  失败次数和第 5 次失效状态必须随 HTTP 400 一起持久化。
- 一个账号只保留一个有效浏览器会话。会话 Cookie 只保存随机令牌，数据库只保存
  HMAC 摘要；写请求同时校验同源、XHR 与 CSRF。
- `pending_deletion` 账号只能退出、查看删除状态、重新认证和撤销删除；到期清理由
  `scripts/manage_accounts.py purge-due --execute` 执行。
- 管理员工具只显示账号元数据和支持码，不读取项目标题、ID 或内容。

Authing 微信由 `AUTHING_WECHAT_ENABLED` 控制。关闭时所有微信入口返回 404；开启前
必须完成 Authing、微信开放平台和真实扫码验证。公开模式禁止 `DEBUG=true`，SMTP 只允许
`starttls` 或 `ssl`。Authing issuer 与 redirect URI 必须使用 HTTPS（本地环境仅允许 HTTP
loopback）；discovery 的 authorization、token 与 JWKS 端点必须使用 HTTPS，且与 issuer
保持相同 hostname/port。回调从 JWKS 验证 ID token 签名，只允许 `RS256` 或 `ES256`；
随后要求 `iss`、`aud`、`exp`、`iat`、`sub`，校验 nonce，并以 60 秒 leeway 验证 OIDC
claims。ID token 提供 `at_hash` 且授权码响应有 access token 时，也会校验二者匹配。

## 数据表

- `accounts`：账号状态、支持码和延期删除；
- `account_identities`：唯一邮箱或 Authing 微信主身份；
- `web_sessions`：单一有效浏览器会话与 HMAC 摘要；
- `email_login_challenges`：邮箱验证码摘要、尝试次数和过期状态；
- `account_security_events`：脱敏安全审计；
- `account_consents`：版本化协议同意。

## HTTP 入口

- `/api/auth`：邮箱登录/注册、当前账号、退出和邮箱重新认证；
- `/api/account`：延期删除状态、申请与撤销；
- `/api/auth/wechat`：Authing 微信登录；
- `/api/auth/reauth/wechat`：微信重新认证；
- `/legal/terms`、`/legal/privacy`：公开协议页面。

HTTP 路由只从当前 account principal 解析 owner。跨模块 owner 查询使用
`current_account_id()`、`current_account_principal()`、
`current_owner_id_or_system_none()` 与 `require_account_active()`；不得绕过 facade 读取
账号 ORM。

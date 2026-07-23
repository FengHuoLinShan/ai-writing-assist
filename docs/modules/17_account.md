# 账号模块

`backend/modules/account/` 负责公开浏览器账号、登录身份、会话、重新认证和延期删除。

## 用户能力

- 邮箱验证码公开注册/登录；微信按钮由 Authing 配置开关控制。
- 新登录会撤销旧浏览器会话。
- 首次进入账号、切换账号和退出会清除浏览器中的项目、草稿、任务恢复和诊断缓存；
  主题偏好不含账号内容，予以保留。
- 删除账号前必须在 10 分钟内完成原登录方式重新认证；申请后有 30 天恢复期。
- 待删除账号只能退出、查看状态、重新认证和撤销删除。

邮箱与微信是互斥的主身份，不自动绑定。同一个人用两种方式会得到两个独立账号。

## 数据与隔离

`accounts` 保存状态、支持码和删除到期时间；`account_identities` 保存唯一身份；
`web_sessions`、`email_login_challenges` 只保存 keyed HMAC 摘要；安全事件与协议同意
随账号清除。`projects.owner_id` 是非空外键，项目、设置和任务入口都通过 owner 门禁。

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

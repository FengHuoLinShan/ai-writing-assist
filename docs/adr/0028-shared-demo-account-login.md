# ADR-0028：演示共享账号的口令登录边界

- 状态：Accepted / Implemented
- 日期：2026-09-21
- 影响模块：account、部署维护

## 背景

面试演示需要让未注册访客以真实账号的全部能力体验产品（含写操作与账户连接驱动的生成功能），
而账号体系没有口令存储，唯一通用登录方式是邮箱验证码。匿名 RP（ADR-0024）与 `?demo=1` 只读
principal 都无法覆盖作者侧工作流；直接共用真实账号又会把演示流量、模型额度与个人身份耦合在
一起。

## 决策

1. 新增 `POST /api/auth/demo-login`，仅 public 模式且 `PUBLIC_DEMO_LOGIN_ENABLED`、
   `PUBLIC_DEMO_LOGIN_ACCOUNT_ID`（合法 UUID）与 `PUBLIC_DEMO_LOGIN_SECRET`（≥8 字符）
   全部有效时开放（`modules/account/demo_login.py` fail-closed，配置无效即整体 404）。
2. 口令经 `hmac.compare_digest` 常时比较，绝不进入 `/api/auth/config`、响应或日志；同一
   peer 15 分钟内 5 次失败即节流拒绝，成败均写 `account_security_events`（含 peer 摘要）。
   端点沿用既有同源 Origin、XHR 与全局 IP 限流门禁。
3. 会话签发给配置指向的唯一既有账号，`identity_type="demo_shared"`，与邮箱登录完全等价
   （无路径白名单限制）；复用单一有效会话语义，新登录撤销旧会话。首次登录幂等补记当前版本
   条款同意。
4. 演示账号由运维预先创建并持有演示数据与（复制的）账户连接；该账号不存在、封禁或配置失效
   时入口 fail-closed。口令轮换仅改部署 env 并重建容器。
5. 前端登录门在 `demo_login_enabled` 时展示次级「演示账号登录」块，仍要求勾选条款。

## 结果与非目标

- 不引入通用口令存储或任意账号口令登录；本端点只为单个配置账号服务，不改变邮箱/微信登录、
  匿名 RP 与只读 demo principal 的任何语义。
- 残留风险由部署方承担：系统没有按账号的模型消费上限，持口令者可消耗该账号名下项目的
  LLM 额度，演示数据也可被写坏。缓解：口令仅定向分发、可随时轮换或关闭入口，演示数据可从
  备份重建。

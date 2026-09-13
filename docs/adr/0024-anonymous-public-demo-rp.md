# ADR-0024：匿名公开演示 RP 的临时身份与前台执行

- 状态：Accepted / Implemented
- 日期：2026-09-14
- 影响模块：account、interaction、evidence、project、部署维护

## 背景

公开演示需要让读者先体验固定作品版本的 RP，而不要求注册、配置账户连接或取得作者项目的
访问权。复用普通 RP 的 worker 会把浏览器临时提交的 Key 变成可恢复任务的隐式依赖；复用普通
同 owner source 规则又会让匿名旅程无法读取经批准公开的作者资料。两者都不能通过放宽全局
owner/`novel_id` 隔离解决。

## 决策

1. `POST /api/auth/anonymous-rp` 只在 `PUBLIC_DEMO_ENABLED`、`PUBLIC_DEMO_RP_ENABLED` 及
   `PUBLIC_DEMO_RP_SOURCE_REVISION_ID` 均有效时创建独立 `anonymous_rp` 账号。它记录当时的
   条款/隐私版本，session 的 idle 与 absolute 期限均为 24 小时；session Cookie 为 HttpOnly，
   CSRF 仍按现有同源/XHR/header 门禁工作。匿名账号由每小时 maintenance 级联清理。
2. 公开来源只能是配置精确指向的 `ready` source revision。读取、建旅程和 Evidence 编译都重验
   revision ID、ready 状态、整体 fingerprint 与 manifest；Evidence 仅在这个 contract 成立时放宽
   source/consumer 的同 owner 比较。任意其它 author source 继续适用 ADR-0018。
3. 匿名旅程仍是匿名 owner 自己的隐藏 interaction project。分支、选中路径、手动回顾、停止和
   重试复用既有持久化语义；两个匿名 session 没有任何读取或写入共享。
4. `POST /api/interactions/journeys/{journey_id}/attempts/{attempt_id}/stream` 先原子 claim 一个
   taskless attempt，再在该 SSE 请求内从 `X-DeepSeek-API-Key` 临时创建固定
   `https://api.deepseek.com` / `deepseek-v4-flash` client。Key 不进入 Cookie、Pydantic wire body、
   attempt snapshot、AsyncTask、数据库、响应或日志。长上下文回顾在同一请求以同一临时 Key 完成，
   不转 worker；断开或取消关闭 provider stream 并把本次 attempt 收敛为可重试终态。
5. 匿名体验禁止看海、主动连续性/后台续写、web search、导入与作者 source 管理。它可读取和手工
   修正自己的分支与回顾，但不会创建后台 summary/proactive task。
6. `scripts/freeze_public_demo_rp_source.py --project-id ...` 默认 dry-run，只有显式 `--execute`
   才会从该项目既有的 published drafts、Scene/span、entities 和 RAG coverage 物化或幂等复用一个
   ready revision；任一 fingerprint/coverage/歧义门禁失败则零写入。`--source-revision-id` 是纯验证
   模式。两条路径均不调用模型、不导入、不索引或修改作者数据。

## 结果与非目标

- 临时 Key 只承担当前请求的 provider 授权，不成为产品账户连接或长期凭据；真实模型调用仍由
  演示者明确提供 Key，自动化测试不发付费请求。
- 公开资料不是通用作品库、分享功能或跨作者读取授权；source 变更、归档、指纹不符或 coverage
  缺失一律 fail closed。
- 生产部署仍须单独设置公开开关和经只读 gate 验证后的 revision ID；本 ADR 不授权创建、迁移或
  覆盖真实作品来源。

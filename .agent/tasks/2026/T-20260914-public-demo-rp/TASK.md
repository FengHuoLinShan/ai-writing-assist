---
id: T-20260914-public-demo-rp
title: 免登录演示、匿名 RP 与账户副本
status: active
created: 2026-09-14T00:03:45+08:00
updated: 2026-09-14T00:03:45+08:00
---

# 免登录演示、匿名 RP 与账户副本

## 恢复快照

- 实际完成：确认工作树干净并从 `origin/main` 的 `b8f7a6832` 建立 `codex/public-demo-rp`；前置 `make docs-check` 通过。
- 当前里程碑：实现公开只读演示、匿名 RP 临时 Key 和登录后演示项目副本。
- 下一步：按前端、公开鉴权/副本、匿名 RP 三条互不重叠路径并行实现，主会话收口 migration、共享接口和验收。
- 阻塞：无。
- 工作区：`/Users/tywww/Desktop/项目/ai-writing-assist`，分支 `codex/public-demo-rp`；当前未提交改动仅为本任务笔记。
- 最后核实：2026-09-14T00:03:45+08:00。

## 目标与验收

- 目标与交付物：登录页可免登录查看演示项目和进入演示 RP；演示工作台只读且严格限定配置项目；匿名 RP 固定 DeepSeek `deepseek-v4-flash`，Key 仅保存在浏览器会话并只随当前生成请求发送；登录用户可幂等复制演示项目到本人账户。
- 完成条件：关键鉴权、隔离、Key 零持久化、24 小时匿名会话、流式 RP、复制幂等与前端路径有自动化验证；权威文档和 migration 同步；主会话审查并修复并行产物。
- 非目标：提交、推送、PR、部署；匿名旅程迁移到账户；后台主动 RP、看海、Web 搜索；任意 provider/model/base URL。

## 上下文与边界

- 关键路径与来源：`frontend-console/vue/auth/AuthGate.vue`、`frontend-console/vue/views/interaction/`、`backend/modules/account/`、`backend/modules/project/`、`backend/modules/interaction/`、Alembic 与对应测试。
- 硬约束与授权范围：保护真实演示数据；不记录或持久化 API Key；匿名访问只能读取配置的演示项目/冻结 RP source；项目副本由当前登录 owner 持有；不直接提交 main。
- 依赖：现有 FastAPI、Vue 3、PostgreSQL、对象存储与 DeepSeek OpenAI-compatible client；不新增依赖或基础设施。
- 已确认事实：演示项目 ID 为 `937c86f1-a2c3-4db5-963d-f3181095f339`；当前异步 RP worker 需要持久账户凭据，因此匿名 Key 路径采用请求内 SSE 生成并复用现有生成核心。
- 假设与待决问题：公开 RP source revision 由部署配置指定；真实 DeepSeek 烟测需要另行提供临时 Key 和成本授权，本次使用替身验证。

## 里程碑与进度

- [ ] 公开只读演示鉴权与入口。
- [ ] 登录用户幂等复制演示项目。
- [ ] 匿名 RP 临时账户、冻结 source 与请求内 SSE。
- [ ] 前端会话级 Key、匿名 RP 与复制体验。
- [ ] migration、文档、测试、浏览器验收与主会话复核。

## 决策、发现与失败

- 2026-09-14；Key 只用 `sessionStorage`，不进入 cookie、localStorage、IndexedDB、数据库、任务快照或日志；满足刷新保留、关闭浏览器通常清除的产品要求。
- 2026-09-14；匿名 RP 仅支持前台交互能力，禁后台续写和外部搜索；连接关闭即取消供应商请求，避免浏览器关闭后继续花费。
- 2026-09-14；每账户、演示源、演示版本只创建一份副本，重复请求返回已有或恢复软删除副本。

## 验证证据

- `make docs-check`；通过；2026-09-14T00:03:45+08:00；基线 `b8f7a6832`。

## 交付结果

- 已交付：执行中。
- 未交付：实现、测试、浏览器验收、文档收口。
- 交付边界：仅本地分支；未提交、未推送、未部署。
- 正式知识与后续任务：执行中。

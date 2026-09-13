---
id: T-20260914-public-demo-rp
title: 免登录演示、匿名 RP 与账户副本
status: completed
created: 2026-09-14T00:03:45+08:00
updated: 2026-09-14T01:41:33+08:00
---

# 免登录演示、匿名 RP 与账户副本

## 恢复快照

- 实际完成：登录页公开演示/RP 入口、严格项目范围的只读浏览、登录后幂等副本、匿名 24 小时会话和请求内 DeepSeek 流式 RP 已完成。
- 当前里程碑：主会话已修复 migration 多头、公开搜索/地图读取、RP source 公开边界、只读 UI 误锁和刷新后消息/失败状态恢复。
- 下一步：如需上线，另行授权 push/PR/部署，并在生产配置固定演示项目、版本与已冻结 RP source revision。
- 阻塞：无。
- 工作区：`/Users/tywww/Desktop/项目/ai-writing-assist`，分支 `codex/public-demo-rp`；实现与主会话验收修复均已收口。
- 最后核实：2026-09-14T01:41:33+08:00。

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

- [x] 公开只读演示鉴权与入口。
- [x] 登录用户幂等复制演示项目。
- [x] 匿名 RP 临时账户、冻结 source 与请求内 SSE。
- [x] 前端会话级 Key、匿名 RP 与复制体验。
- [x] migration、文档、测试、浏览器验收与主会话复核。

## 决策、发现与失败

- 2026-09-14；Key 只用 `sessionStorage`，不进入 cookie、localStorage、IndexedDB、数据库、任务快照或日志；满足刷新保留、关闭浏览器通常清除的产品要求。
- 2026-09-14；匿名 RP 仅支持前台交互能力，禁后台续写和外部搜索；连接关闭即取消供应商请求，避免浏览器关闭后继续花费。
- 2026-09-14；每账户、演示源、演示版本只创建一份副本，重复请求返回已有或恢复软删除副本。

## 验证证据

- `make docs-check`；通过；2026-09-14T00:03:45+08:00；基线 `b8f7a6832`。
- 前端 Vitest；190 files / 2467 tests 通过；ESLint 与生产构建通过。
- 后端受影响 account/project/interaction；88 tests 通过；公开证据搜索的配置项目可读且跨项目失败关闭。
- PostgreSQL 专用库；migration 单一 head `20260914_anonymous_rp_accounts`；副本并发幂等测试通过。
- 真实浏览器；公开项目、搜索、地图与匿名 RP 可用；伪 Key 失败后可换 Key 重试，刷新保留开场、失败状态和旅程。
- 临时 Key 全库表扫描无匹配；`make secret-hygiene` 与 `make docs-check BASE_REF=origin/main` 通过。

## 交付结果

- 已交付：实现、migration、自动化验证、真实浏览器验收、部署配置文档。
- 未交付：未使用真实 DeepSeek Key 付费生成；未冻结生产 source revision。
- 交付边界：仅本地 `codex/public-demo-rp` 分支；未 push、未 PR、未部署。
- 正式知识与后续任务：ADR-0024 和项目/交互模块文档已同步；上线时使用冻结脚本产生并配置 source revision。

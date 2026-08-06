# ADR — LLM、Worker、Embedding 背压与前端 CSP baseline

- **状态**: Accepted
- **日期**: 2026-07-07
- **关联**: ADR-0003 Leaflet for map viewport

## 背景

深度导入和生成链路会同时触发 LLM 调用、异步任务执行和 embedding 写入。没有明确背压边界时，开发环境容易出现请求堆积、worker 抢占、embedding 批处理放大和前端安全策略缺口。

本批变更拆成四个子任务并行处理：LLM limiter、TaskWorker 并发、BGE batch queue、CSP baseline。本文记录共同决策，具体代码分别落在各自拥有的模块中。

## 决策

### 1. LLM limiter

LLM 调用必须通过明确 limiter 控制并发和排队。默认目标是保护本地开发、真实 provider 配额和深度导入稳定性，而不是追求最大吞吐。

Limiter 的行为应保持可观测：队列等待、并发占用和超时/失败要能在日志或测试中被验证。不同 provider 的速率差异后续可通过配置扩展，但不得绕过统一入口直接放飞并发。

### 2. TaskWorker 并发

PostgreSQL async task queue 继续作为当前 worker 基础设施，不引入 Redis/Celery 等新运行时。TaskWorker 并发应由显式配置控制，避免多个任务同时放大同一类下游资源消耗。

并发控制属于 worker 基础设施边界；业务模块不应自行创建后台执行池来绕过队列语义。

### 3. BGE batch queue

BGE embedding 写入采用 batch queue 做背压。批大小和 flush 时机需要在吞吐和响应延迟之间折中，避免单个导入流程把 embedding provider 或数据库写入拖成无界队列。

Batch queue 的失败处理必须保持可重试或可恢复语义，不应因为单批失败丢失 novel_id 隔离、schema 校验或任务状态。

### 4. CSP baseline

前端入口添加 `Content-Security-Policy` meta baseline：

```text
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' http://localhost:* http://127.0.0.1:*; object-src 'none'; base-uri 'self'
```

`script-src` 不允许 `'unsafe-inline'` 且仅允许本源。`style-src` 不再允许外部 origin，暂时保留
`'unsafe-inline'`，兼容 `index.html` 现有静态 inline style 和现有视图模板中的内联样式。

Leaflet 1.9.4 根据 ADR-0003 的 2026-08-06 交付修订改为锁定 npm 依赖和 Vite 按需 chunk，
浏览器不再访问 unpkg；这是对原 CSP baseline 的收紧，不改变 Leaflet/Canvas 使用边界。

## 影响

- LLM、worker、embedding 的并发上限成为显式系统边界，后续调优应优先改配置和测试，而不是在业务调用点散落并发控制。
- 前端 CSP baseline 会阻止未授权脚本来源和 inline script，同时继续允许现有 inline style。
- Leaflet JS/CSS 与 BSD-2-Clause 许可均由应用本源交付；生产构建验证外部 CDN 引用不会回归。

## 后续

- 下一批可逐步迁移静态 inline style 到 `styles.css` 或组件样式约定，再收紧 `style-src` 去掉 `'unsafe-inline'`。
- 若后续新增图片、字体、worker、frame 或第三方 API 来源，必须同步更新 CSP 测试和前端文档。

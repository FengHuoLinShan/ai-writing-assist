# ADR Index — LLM 并发、限流与熔断细化

- **状态**: Accepted / Index
- **日期**: 2026-07-07
- **上游权威 ADR**: `docs/adr/llm-worker-embedding-backpressure-and-csp.md`

## 定位

本文是既有 ADR 的细化索引，不制造第二个权威来源。权威决策仍是 `docs/adr/llm-worker-embedding-backpressure-and-csp.md` 中的 LLM limiter、TaskWorker 并发、BGE batch queue 和 CSP baseline。

## 细化记录

LLM 调用的目标是有界并发和可观测失败，而不是修改业务默认吞吐参数。Limiter / circuit breaker 应在 LLM 基础设施入口生效，覆盖普通 generate、stream、structured direct provider path 和远程 embedding provider path。

细化原则：

- 进程级并发使用 semaphore，避免业务模块各自创建无界执行池。
- 速率限制使用 token bucket 或等价机制，provider 差异通过配置调优。
- 熔断器记录连续失败并短时拒绝新请求，防止故障 provider 被持续打满。
- 日志和测试应能观察排队、超时、熔断和恢复。

## 不变项

不得把本文解读为要求调整 `PHASE1B_ENRICH_CONCURRENCY` 默认值；该默认值当前保持 200，风险由 LLM limiter、TaskWorker 并发上限和 embedding batch queue 背压共同缓解。

业务模块不得绕过统一 LLM 客户端或 limiter 直接调用 provider。

## 后续

如未来为不同 provider 增加独立 limiter profile，应更新本索引和既有 ADR 的配置说明，并补充 provider 级测试。

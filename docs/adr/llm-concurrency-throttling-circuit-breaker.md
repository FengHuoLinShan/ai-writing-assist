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
- 并发 semaphore 与 RPM token bucket 继续由同一进程内全部项目共享，作为服务器和
  provider 总吞吐保护；不得按项目拆分后放大总请求量。
- availability 熔断状态按“项目或 system + chat/embedding + 规范化 endpoint”分桶。
  endpoint identity 不包含 userinfo、query、fragment、API Key 或 model。
- 熔断门禁先于全局 RPM/semaphore；已打开的桶不消耗其他项目的 admission capacity。
- cooldown 到期后进入单探针 half-open；成功或明确的认证、内容、schema 响应只关闭当前
  桶，availability 失败只重新打开当前桶。
- breaker registry 仅保留失败状态，使用 256 项进程内 LRU 上限；它不跨 API/worker
  进程协调。
- 日志和测试应能观察排队、超时、熔断和恢复。

## 不变项

不得把本文解读为要求调整 `PHASE1B_ENRICH_CONCURRENCY` 默认值；该默认值当前保持 200，风险由 LLM limiter、TaskWorker 并发上限和 embedding batch queue 背压共同缓解。

业务模块不得绕过统一 LLM 客户端或 limiter 直接调用 provider。

## 实施状态

2026-07-24 已按上述规则实施。普通 generate、stream、structured direct provider、
structured format repair 与远程 embedding 均通过同一个深层 limiter module；只向其传递
secret-free availability scope。远程 embedding 使用实际 `EMBEDDING_BASE_URL` identity，
项目配置仅提供 breaker owner，不覆盖 system embedding 凭据。项目 A 的 timeout、
connection failure 或 429 不再打开项目 B 的桶，同一进程的并发和 RPM 仍保持统一。

未来若要把 RPM、并发或 breaker 扩展为跨进程/分布式配额，属于新的运行时架构决定，必须
另行评审；不得把当前 process-local registry 误当作全部署共享状态。

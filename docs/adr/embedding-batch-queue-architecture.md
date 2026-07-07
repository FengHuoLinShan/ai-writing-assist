# ADR Index — Embedding batch queue 与背压细化

- **状态**: Accepted / Index
- **日期**: 2026-07-07
- **上游权威 ADR**: `docs/adr/llm-worker-embedding-backpressure-and-csp.md`

## 定位

本文是既有 `docs/adr/llm-worker-embedding-backpressure-and-csp.md` 的 embedding 细化索引，不替代该 ADR。权威决策仍是：embedding 写入通过 batch queue 做背压，并与 LLM limiter、TaskWorker 并发共同构成资源边界。

## 细化记录

Embedding batch queue 的职责是把高频 embedding 请求收敛为有限队列和批量 flush：

- query/document 可使用分离队列或分离批处理策略，避免一种调用形态阻塞另一种。
- 队列 maxsize、batch size、flush interval 和超时应来自显式配置。
- 未启动 worker 或测试场景可保留 direct encode fallback，但 fallback 仍不得绕过 novel_id 和 schema 约束。
- 批量失败应降级为可恢复路径，不能因为单批失败丢失任务状态、错误诊断或重试能力。

## 边界

本文不引入 Redis/Celery/外部队列，不改变当前 PostgreSQL task queue 基础设施。

本文不要求调整 `PHASE1B_ENRICH_CONCURRENCY` 默认值；该默认值保持 200，embedding 背压在基础设施层吸收峰值。

## 后续

后续如增加 provider-specific batch profile，应补充队列饱和、批失败降级和重试统计测试，并同步 `development-guide.md` 的配置说明。

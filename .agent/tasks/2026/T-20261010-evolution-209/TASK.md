---
id: T-20261010-evolution-209
title: Issue 209 世界演化账本缓存与发现容量专项优化
status: active
created: 2026-10-10T23:18:06+09:00
updated: 2026-10-11T00:37:04+09:00
external_ref: https://github.com/FengHuoLinShan/ai-writing-assist/issues/209
---

# Issue 209 专项优化

## 恢复快照

- 分支：`codex/issue-209-evolution-capacity`，base main `aafcc86b`；独立草稿 PR，不合并或部署。
- 实现完成：同事务 project/来源 scope UUID 令牌、有界跨调用前缀证明；确定性索引/历史/正文分片；new 通过全部索引片身份复核；精确覆盖、失败重放与幂等。
- 验证完成：最终 Evolution 模块 378 passed、1 real_llm deselected；最后的 retained-ORM 与首个超大索引修复后定向 45 passed。迁移降级重升与 ORM parity 在 WASM 下通过；Ruff 与模块依赖门禁通过。
- PostgreSQL WASM：迁移成功；实际查询计数及 EXPLAIN ANALYZE 完成；13 个独立顺序断言通过。报告与原生验证命令见 [VALIDATION.md](VALIDATION.md)。
- 原生 CI：PostgreSQL 17.11 critical 78 passed，包含 #209 全部 14 项（asyncpg、并发写入、迁移/ORM parity）。PR #211；随后 native 规模基准/EXPLAIN CI 共 81 passed；3 份 native JSON 证据已保存。最后 >8192 scope / 每查询 <=4097 参数回归及守卫修复待 CI；追加本地定向 24 passed。
- 环境：原生 PG 缺失，用户命名空间不能切换非 root；PGlite/PostgreSQL WASM socket 的 asyncpg 不完成，使用同步 psycopg2 顺序适配。WASM 耗时不是原生性能结果。

## 目标与边界

- 仅 #209：账本 freshness、持续发现批次容量；未改 #208 Scene Projection 消费登记查询。
- 合成数据、确定性回归、实际 SQL 计数/形态、EXPLAIN；来源换版、Scene 变更、历史恢复、rollback 与项目隔离。
- 用户授权实现、运行测试、提交独立 PR；未调用付费模型。

## 决策与发现

- PR206 list_ledger 单页已有 cache；独立调用与不同前缀重复遍历历史。旧 cache 参数缺失 epoch/项目边界，不能安全跨调用复用。
- 来源行 INSERT/UPDATE/DELETE 在同事务改写随机 UUID epoch，rollback 不造成 token ABA；engine/project/run/attempt/manifest 隔离、有界 LRU。无令牌与 SQLite 均走完整验证。完整验证前后 epoch 一致才发布 owned 前缀；继承 run 不误认证为自身完整前缀。
- 项目发生无关追加时，核对原 proof 的 run/attempt/scene/chapter scopes，避免重验未变历史；相关修改仍完整重验。完整验证期间 SELECT 强制 populate_existing，不能用 Session 保留的旧 ORM 值认证新 token。
- 1/10/100 Scene 五次独立读取旧查询为 60/420/4020，warm 为 5，完整验证为 0；100 Scene/120 theme 两页旧 40808 查询变为 128。小历史的 per-claim 守卫有额外查询开销，冷验证仍线性；触发器同项目写竞争未测。
- 未选相关性删除方案，避免丢失潜在别名/未解析历史候选；全部索引确定性分片保留。每项 new 对所有片复核，耗费原根预算；超限/失败/未知不能采用或虚报已覆盖。已执行 journal 恢复不重复采样，操作键防止重复采用。
- 正文窗口使用权威源偏移，保留全部字符和观察；不可分超大条目只隔离对应批次。首个超大索引/上下文不会污染全部其它批次，新提议只在首个可发送上下文提出。
- 文档检查对 Makefile 仅新增既有 critical 清单条目触发的 governance 文档采用已逐项核对说明：testing-guide、数据库、Evolution 与 Prompt 文档更新；开发指南/架构 README/文档维护的治理流程及依赖方向不变。

## 交付状态

实现与可复现验证材料完成，本分支供独立草稿 PR 审查；原生规模基准完成，最后来源 scope 参数上限回归待 CI；同项目写争用未测。

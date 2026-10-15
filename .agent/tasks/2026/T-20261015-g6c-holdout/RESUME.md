# G6c 单次运行恢复边界

主记录见 [TASK.md](TASK.md)，冻结配置、实际结论和验收标准见 [ACCEPTANCE.md](ACCEPTANCE.md)。
G6 已按用户要求结束：全部冻结门槛满足，修复版综合 31/32，保留 1 条确定性门禁失败，不调参或重跑。
用户明确授权本次完成后结束 G6，不继续调参或重跑；通过、失败或不完整都如实保存。

- 私有根：`/Users/tywww/.codex/private/g6c-holdout-20261015`。
- `FREEZE_CONFIG.json` 已固定源码、Prompt、rubric、资料、schema 和父校准证据；不编辑这些文件追认结果。
- `run.started.json` 已存在，整体及逐题材料锁已占用。不要再次执行 run 或删除任何锁。
- run、judge-0、judge-1 均有 complete 标记；66 笔原生调用退出 0，无 unknown，禁止重放。
- judge-0 与 judge-1 已各完成一次，禁止再次执行。
- 离线报告已保存 result.json 与 artifacts/holdout-ledger-v1.json；可只读核对原材料，不能改参考标签或冒充作者验收。
- 原版从封存源码加载；当前修复版产品 Prompt 不改变。调用经同一独立开发库的 verified owner/Project Luna/max；教师限定 Sol/xhigh。
- 原生捕获器仍只在旧 private/live 下新增 UUID 目录；全部旧文件由冻结哈希保护，不能覆盖旧账本或首轮失败。
- 任务已关闭；原始教师/确定性 3 条分歧及剩余失败单列审计，不改原统计。其他 evaluator 不解禁，G7、合并或部署未启动。

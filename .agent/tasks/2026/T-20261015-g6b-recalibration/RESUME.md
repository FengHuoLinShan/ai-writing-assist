# G6b 结果复核与后续恢复

本轮 30 条教师自测及 34 条 debug 生成/评分已经完成，详见 [TASK.md](TASK.md) 与
[ACCEPTANCE.md](ACCEPTANCE.md)。保留全部阶段标记，不重复执行旧阶段。

- 原运行依据为私有 live/run-freeze.json 及 frozen-sources；收尾代码仅增加取消回收/环境白名单和格式整理，
  两个版本分别有哈希。原始请求、结果、源码和失败回执均在仓库外，旧预检和历史账本未覆盖。
- 最终连接以 live/setup-result-final.json 为准；早期 setup-result.json 属于校准时已验证的旧捕获器指纹，不能直接作为未来运行快照。
- 本树 backend/.env（忽略文件）指向独占容器 g6b-calibration-pg-20261015、端口 65195 和专用库
  agent_e2e_g6b_calibration。CLI 经捕获入口固定真实 0.160.0。不要改用共享数据库或复制真实作品。
- 连接/CLI/捕获器或 wrapper 改动后，必须走账户正常验证，再从 Project facade/snapshot 核验 Luna/max。
  不通过时停止模型；不得伪造 verified credential 或修补旧 snapshot。
- 后续若获准整改唯一过度拒答，应先审查该 case 的现有完整原文和两条来源，保留本轮 33/34 基线。
  新输入、Prompt、执行版本或回执使用明确关联的新记录，保留旧 pending/unknown，不能覆盖或隐藏失败。
- 其他 reviewer/scene-gold 仍暂停；新 holdout 属 G6c，须新 family/冻结配置/独占启动标记。
  本轮 debug、旧教师人类收据或绿色工程测试都不能替代独立留出/作者验收。

离线复验（仓库根，不调用模型）：

```bash
make eval-fast
make eval-ask-world OUTPUT=/tmp/g6b-offline-check.json
make docs-check BASE_REF=origin/main
git diff --check
```

## 已完成的最小拒答修复续接

见 [REFUSAL-COMPARISON.md](REFUSAL-COMPARISON.md) 和新账本 artifacts/refusal-comparison-v1.json。
已冻结 8 个新资料族正反题后，用同配置比较原版/唯一候选，各两次重复。新族过拒答 5→0，
语义通过 27/32→32/32，未观察到幻觉增加；原失败题新复验 0/2→2/2。首轮记录不替换。
私有 refusal-v1 的 baseline/candidate/judge-0/judge-1 全部 complete，禁止重放这些阶段。
当前最小 Prompt 与权威文档已更新，只有本地改动；无剩余已授权阶段。独立 G6c 留出和作者验收仍未做。

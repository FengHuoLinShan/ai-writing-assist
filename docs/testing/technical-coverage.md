# 技术覆盖主线：工程与离线证据

规划基线 `a7173869ca832537cf476e0a05e97f1f5275012a`。本轮仅合成资料、离线执行与
专用 PostgreSQL/浏览器验收。任何确定性结果都不代表模型质量、线上分布、十万 DAU 或生产准入。
实施状态与最终证据见 [任务记录](../../.agent/tasks/2026/T-20260920-technical-coverage/TASK.md)。

## 逐题覆盖

表中“已有”指可定位代码，不代表本轮已重新验收；本轮状态由任务记录的验证证据给出。

| 面试问题 | 业务场景与当前实现 | 本轮证据/边界 |
|---|---|---|
| PagedAttention 原理、KV 内存碎片 | 当前使用项目模型网关，未自托管推理 | P6 独立 GPU 实验，未测 |
| PagedAttention 与 FlashAttention | 内存分配与注意力计算的不同层 | P6 研究与实测，未宣称项目使用 |
| 低并发、长 prefill、框架选型数值 | 推理性能对照 | P6 未测 |
| RAG 为何缓解幻觉、局限 | Evidence 原文回读、版本和引用 | P1 证据组召回及来源拒绝 |
| RAG 拉低效果的场景 | 同名、否定、过期、未来、无答案 | P1 负例及五臂配置 |
| 长上下文是否替代 RAG | 相同授权来源的上下文选择 | P1 配置就绪，真实生成待评测 |
| RAG 与微调如何取舍 | 事实更新与行为训练分开 | 已有 Evidence；训练在 P7 |
| 10 万 DAU、日均五问、p95 两秒 | PG 队列与模型调用分层 | P5 只测应用/队列，不外推推理容量 |
| 企业物理隔离 | 当前 owner/novel_id 逻辑隔离 | 物理隔离为 P7，未实现 |
| 三倍突发与防雪崩 | 有界预算、租约、队列恢复 | P5 稳态/三倍突发及拒绝率 |
| 千页 PDF、长文档召回 | 当前小说文稿导入不含 PDF | P7 独立资料管线，未实现 |
| 成本占比与降低 30% | 运行信封累计用量 | P0/P3 导出实际与未知消费；无降本声明 |
| 何时拆 Agent、收益递减 | deep_review 按查证目标分工 | P3 三臂对照，质量待评测 |
| 调度、路由、循环与踢皮球 | 单宿主三成员、注册蓝图和根预算 | P3 重复/失败/恢复回归 |
| 多 Agent 结论冲突 | 原领域复核与分歧保留 | P3 不以投票认定事实 |
| 自动效果回归、迭代不劣化 | 现有 evals 与领域测试 | P0 版本化指标；P1–P5 对应场景 |
| 测试集分布与自评偏差 | 合成故事族及现有 fixtures | P0 按故事族隔离；不称线上分布 |
| LLM judge 准确度与人工评审 | 现有校准与盲评导出 | P3 材料准备；人工评审未完成 |
| 项目整体架构/项目怎么做 | Vue → API → facade → 领域 → PG/LLM | 三条演示与现有模块 README |
| Workflow、Agent、Skill 区别 | 合法流程、自主选工具、审稿方法 | P2 模板与工具；P3 固定蓝图 |
| 如何提升 function calling | 参数契约与工具身份回放 | P2 必须/可省/禁止三类用例 |
| 工具调用方式与按需调用 | 服务端注册的只读与提案工具 | P2 多余/漏调用/参数错误 |
| Function calling、MCP、Skill | 模型消息、传输协议、方法模板 | P2 独立 stdio 实验；无生产 MCP |
| Skills 与 rules | 方法不能授予权限 | P2 注入与权限负例 |
| MCP 使用场景 | 合成证据搜索与精确读取 | P2 本地只读实验 |
| Agent 长短期记忆 | checkpoint、选中历史、回顾、长期约定 | P4 生产物化与序列回归 |
| Prompt 如何设计 | 来源分隔、输出 schema、任务特定方法 | P2 三种方法模板及契约版本 |
| 记忆覆盖如何解决 | 人工纠正、分支 lineage、来源 hash | P4 再摘要/切支/恢复 |
| Agentic RAG 与传统 RAG | 有界补查与确定性检索 | P1 五臂配置；保留停止原因 |
| RAG 分片逻辑 | 现有中文字符切块和原文 offset | P1 保留基线，不把字符叫 token |
| 召回分片不完整 | Scene/段落父级补全 | P1 完整区间、否定条件及截止点 |
| 块大小、重叠如何选择 | 证据区间 gold 不绑定 chunk ID | P1 可比消融；不预设最佳值 |
| 如何提升检索质量、其他索引 | 别名/向量/关系/词法已有 | P1 离线 BM25 与融合对照 |
| SSE 边生成边推送 | attempt 持久正文、offset/事件 ID | P5 Unicode、去重、重连与终态 |
| Redis hash 大 key | 生产不依赖 Redis | P7 独立实验，未实现 |
| 快排、旋转数组搜索 | 与业务实现无必要耦合 | 独立练习，不计产品覆盖 |
| LangGraph Memory | 当前使用 PydanticAI/PG | P7 对照实验，未迁移 |
| 多 Agent 易错情形 | 来源不一致、权限、重复消费、局部失败 | P3 故障与预算证据 |
| Skill 与多 Agent 执行 | 模板不持有成员状态或独立预算 | P2/P3 方法与执行分离 |
| Agent 结构化输出 | Pydantic schema、工具回包与领域回执 | P2 参数/回包及身份链路 |
| Skill 和 memory 沉淀 | 版本化方法与用户维护的长期约定 | P2/P4 不从结果自动写正史 |
| 动态 workflow | 注册蓝图内的有界工具选择 | P3 不开放任意自治流程 |
| Agent 开发环节 | 范围/契约/实现/离线/盲评/准入 | P0–P5；盲评和启用后置 |
| 编排偏确定还是自由 | 外层确定、内部有界 | P3 三臂对照 |
| ReAct 与 Plan-and-Execute | 调查内部与协调外层 | P3 同权限/来源/预算比较 |
| Agent 怎么选择工具 | 描述、schema、注册可用集合 | P2 选择负例 |
| 不同文档分块策略 | 本轮仅小说原文与 Scene | 表格/PDF 为后续资料扩展 |
| 生成如何控制幻觉 | 引用回读、反证、领域复核 | P1/P3 不能把创意候选当事实 |
| 提示词攻击防护 | 不可信资料与服务端权限分离 | P2 注入不得新增工具或写入 |
| Agent 沙箱 | 注册工具、资源预算、禁止任意代码执行 | P2 本地只读边界；不声称 OS 沙箱 |
| zset 限流瓶颈 | 当前不是 Redis 限流 | P7 独立实验，未实现 |
| MVCC | 真实 PG 事务、租约 fence、采用 CAS | P5 并发/旧执行者/重复确认 |
| SSE 与 WebSocket | 当前服务端单向生成进度 | P5 恢复；未增加 WebSocket |
| 单 Agent、多 Agent、Workflow 优势 | 同一深度审稿任务 | P3 对照配置及实际消费 |

## 指标与数据约定

- `p_at_5` 保持历史 v1：分母为实际返回数。`p_at_fixed_5_v2` 固定分母 5，暂不改变历史门槛。
- `evidence_group_recall` 以不可变来源与 Unicode 字符区间为 gold；一组必需区间全部覆盖才命中。
  区间重叠取并集，旧版本、其他作品、来源同名都不能替代。无答案样本单独记录误取/拒答。
- `technical-evidence-v1` 保存基线 SHA、工作区差异 hash、实现文件 hash、数据 hash、来源指纹、
  有效配置与逐请求观测。已知用量仅作小计；存在未知消费时总量为 null。
- 依故事族与来源划分 dev/test。旧长期记忆留出集仅保留历史诊断身份；新候选需新冻结验收资料。
- 离线替身、已录制响应、真实模型必须标明 observation mode；默认 `quality_claim_allowed=false`。

## 交付边界

生产默认开关保持原值。BM25、MCP 和五臂实验不自动切换业务策略。
真实模型评测须先冻结模型、累计费用上限、阈值和人工评审安排，再单独执行。

## 重跑与三条演示脚本

从仓库根目录运行 `make eval-technical-coverage`。命令只处理合成资料，输出至忽略目录
`backend/evals/artifacts/technical-coverage/`，含检索、工具、协作、长记忆及人工评审模板。
离线协议检查可以用于回归；第三检索臂使用脚本重排输出、协作使用脚本 provider，均不可当作模型效果。

### 演示一：跨章查证与完整证据（约三分钟）

1. 在合成测试项目搜索“铜铃”，打开原文，再展开“查看本次可读的前后文”。说明每段有独立章节与版本。
2. 把阅读截止设为第一章，展示跨章 Scene 的第二章不会返回；将范围收紧到句中，展示裁剪与遗漏。
3. 打开 `retrieval.json`，比较三个检索臂的 range/parent group recall，并展示原文区间 gold。
   更改切块只重跑 `python -m evals.retrieval_comparison --chunk-target 8 --output <output.json>`，不改 gold。
4. 验证入口：`backend/modules/evidence/compilation/tests/test_parent_evidence.py`；浏览器 `rag.spec.js` 的 58 条证据流程。

### 演示二：按需工具与有界协作（约三分钟）

1. 打开 `tools.json`，依次展示必须读取、纯文风无须读取、跨范围/未注册工具被拒绝，以及资料中的恶意指令。
2. 用 `uv run --python 3.13 --locked --extra experiments -- python -m evals.mcp_reference_lab`
   启动 stdio 资料实验；实际客户端往返由 `evals/tests/test_mcp_reference_lab.py` 验证。
3. 打开 `collaboration.json`，说明三臂来源、权限和根预算相同，但实际替身请求数不同；恢复不重做成功项。
4. 打开 `blind-review.html`，只给评审者候选与来源；映射 key 单独保存。当前文件是脚本样本，供检查评审流程，尚无人工质量结论。
5. 在深度审稿浏览器场景离开再返回，展示部分覆盖和领域报告；普通讨论不会沿用上次团队授权。

### 演示三：人工纠正与故障恢复（约三分钟）

1. 展示 RP 连续三次摘要测试：用户将“不能用火”纠正为“能用火”，模型试图修改长期约定也不能覆盖；清空后继续上下文不恢复旧约定。
2. 切换分支再返回，展示各自回顾；作品资料 epoch 改变后，旧结果不能晋升为选中正文。
3. 播放浏览器 Unicode 恢复用例：重复片段不重复显示，缺口读取同一 attempt 快照，刷新保留正文和未发送输入。
4. 展示 PG worker-loss 证据：已提交的过期心跳模拟执行者丢失，扫描回收后新租约接管；旧心跳、旧提交和重复终态提交均拒绝。
5. 打开容量报告，说明 30/90 RPS、固定 25ms 替身、三 worker 的实验边界；首个有效回答耗时为空，不用任务进度代替。

### 专用 PostgreSQL 与浏览器验收

PG 用例只接受显式 `E2E_DATABASE_URL` 与 `RUN_E2E_TESTS=1`，并须带
`-m 'not real_llm and not external_data'`，否则默认快测配置会排除 E2E。
容量工具额外只允许 loopback 上的 `novelcraft_technical_coverage_test` 数据库，且只清理自己创建的随机项目。

```sh
# backend/，DB_URL 必须由操作者指定为本任务可丢弃测试库。
RUN_E2E_TESTS=1 E2E_DATABASE_URL="$DB_URL" uv run --locked --extra ci -- pytest \
  tests/e2e/test_technical_recovery.py tests/e2e/test_agent_teams_runtime.py \
  tests/e2e/test_task_run_envelope_postgres.py tests/e2e/test_task_coalescing_concurrency.py \
  tests/e2e/test_interaction_generation_concurrency.py tests/e2e/test_rp_source_versions.py \
  tests/e2e/test_writing_version_concurrency.py -m 'not real_llm and not external_data'
uv run --locked --extra ci -- python -m evals.task_capacity \
  --database-url "$DB_URL" --output evals/artifacts/technical-coverage/capacity.json
```

浏览器使用显式测试 `DATABASE_URL`、`PW_REUSE_EXISTING_SERVER=0` 和空闲端口；
运行 `interaction.spec.js`、`rag.spec.js`、`agent-teams.spec.js` 中的“流式重复与缺口”、
“58 条证据”、“首次回顾”、“深度审稿”。其中模型与流式故障响应采用替身，真实数据库行为由上面的 PG 层另验。

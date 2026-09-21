# 附件 85 项验收映射

测试层级严格区分：单测/真实域、真实 PostgreSQL、真实浏览器、真实模型盲评。
本表中的部分验证不等于附件用例通过；未运行的质量项保持关闭。实现代码和必要保护均在独立工作树中。

| 用例 | 附件层级 | 当前证据 | 范围与限制 |
|---|---|---|---|
| AT001 | integration | [已验证记录内的工程行为](../../../../backend/modules/assistant/forecast/tests/test_access.py) | 跨 owner 的 feed/evaluate/详情/运行/能力目录均 404，任务数不变。 |
| AT002 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | API 查询均 novel_id 过滤；有跨项目 FK 和 owner 回归，未单独重演该 candidate 组合。 |
| AT003 | integration | [已验证记录内的工程行为](../../../../backend/modules/interaction/tests/test_forecast.py) | 作者路由拒绝 hidden 项目；旅程路由按本人选中路径回读。 |
| AT004 | integration | [已验证记录内的工程行为](../../../../backend/modules/assistant/forecast/tests/test_access.py) | demo principal 的新增作者路由拒绝，未读取标题或创建任务。 |
| AT005 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_access.py) | 作者匿名入口已测；RP require_personal 同时拒绝匿名/demo，具体旅程 cookie 场景未另跑。 |
| AT006 | integration | [已验证记录内的工程行为](../../../../backend/modules/assistant/forecast/tests/test_access.py) | 真实 pending_deletion 账户行被拒绝，未入队。 |
| AT007 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_access.py) | 新增 POST 缺 XHR 为 403；完整 Origin/CSRF 各组合沿既有账户中间件门禁。 |
| AT008 | integration | [部分验证](../../../../backend/modules/collaboration/tests/test_workspaces.py) | 原 confirmation 重新物化且严格资源覆盖；未逐一重演附件指定 Scene 的组合。 |
| AT009 | integration | [部分验证](../../../../backend/modules/collaboration/tests/test_workspaces.py) | 原 Evidence 排除/截止门禁仍在；新代码关闭已确认范围之外的领域扩展，专项组合未另跑。 |
| AT010 | integration | [部分验证](../../../../backend/tests/e2e/test_creative_worker.py) | 真实 worker 测试 Case shutdown；Forecast 有同样末段授权重验，未重复各阶段注入。 |
| AT011 | integration | [部分验证](../../../../backend/modules/collaboration/tests/test_workspaces.py) | 全输入和授权集合指纹决定旧结论有效性；高低权限摘要专项未单独运行。 |
| AT012 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_access.py) | 跨 owner/受限账户入口不返回标题；撤销后的每个历史导出组合未单独运行。 |
| AT013 | model_blind_eval | [真实质量验收未完成](REAL_MODEL_REVIEW.md) | 已有真实模型小样本与 Codex 评阅；120 前缀成对对照和两名独立人工评分未完成。 |
| AT014 | model_blind_eval | [真实质量验收未完成](REAL_MODEL_REVIEW.md) | 已有真实模型小样本与 Codex 评阅；120 前缀成对对照和两名独立人工评分未完成。 |
| AT015 | model_blind_eval | [真实质量验收未完成](REAL_MODEL_REVIEW.md) | 已有真实模型小样本与 Codex 评阅；120 前缀成对对照和两名独立人工评分未完成。 |
| AT016 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 宿主仅计一个已核对锚点，不以输入摘要数抬高评分；摘要语义独立性需要真实内容评审。 |
| AT017 | model_blind_eval | [真实质量验收未完成](REAL_MODEL_REVIEW.md) | 已有真实模型小样本与 Codex 评阅；120 前缀成对对照和两名独立人工评分未完成。 |
| AT018 | model_blind_eval | [真实质量验收未完成](REAL_MODEL_REVIEW.md) | 已有真实模型小样本与 Codex 评阅；120 前缀成对对照和两名独立人工评分未完成。 |
| AT019 | model_blind_eval | [真实质量验收未完成](REAL_MODEL_REVIEW.md) | 已有真实模型小样本与 Codex 评阅；120 前缀成对对照和两名独立人工评分未完成。 |
| AT020 | model_blind_eval | [真实质量验收未完成](REAL_MODEL_REVIEW.md) | 已有真实模型小样本与 Codex 评阅；120 前缀成对对照和两名独立人工评分未完成。 |
| AT021 | model_blind_eval | [真实质量验收未完成](REAL_MODEL_REVIEW.md) | 已有真实模型小样本与 Codex 评阅；120 前缀成对对照和两名独立人工评分未完成。 |
| AT022 | model_blind_eval | [真实质量验收未完成](REAL_MODEL_REVIEW.md) | 已有真实模型小样本与 Codex 评阅；120 前缀成对对照和两名独立人工评分未完成。 |
| AT023 | model_blind_eval | [真实质量验收未完成](REAL_MODEL_REVIEW.md) | 已有真实模型小样本与 Codex 评阅；120 前缀成对对照和两名独立人工评分未完成。 |
| AT024 | integration | [部分验证](../../../../backend/modules/collaboration/tests/test_workspaces.py) | 采用 receipt 绑定 run/revision/source 与授权，评测工具保留 intervention；真实文学对照未运行。 |
| AT025 | integration | [已验证记录内的工程行为](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 旧稿/期望 hash 失配的入口保护，具体处置绑定 assessment。 |
| AT026 | integration | [部分验证](../../../../backend/modules/collaboration/tests/test_workspaces.py) | 新增集合成员使旧负向结论失效有实际域测试；原附件回答疑问的语义效果未评测。 |
| AT027 | postgres | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | SQLite 验证旧 A 有效/新 B 失效不复活 A；尚未单独以 PG 重演此排序样本。 |
| AT028 | integration | [部分验证](../../../../backend/modules/collaboration/tests/test_workspaces.py) | 实际源重验与新集合失效已测，不依赖事件投递；特定丢事件流程未独立重演。 |
| AT029 | integration | [已验证记录内的工程行为](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 处置进入下一次输入与 compute_key；重算仍继承明确拒绝。 |
| AT030 | postgres | [部分验证](../../../../backend/tests/e2e/test_forecast_creative_concurrency.py) | PG 不可变约束与不同版本写入已验；前瞻 published 切换专项未单独重演。 |
| AT031 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 发布前 256 完整依赖和 64 KiB 上限，超限拒绝；未做极限规模单独用例。 |
| AT032 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 原 protocol 非 forecast_v1 拒绝读取/续跑，保存冻结 snapshot；无未来协议迁移声明。 |
| AT033 | postgres | [已验证记录内的工程行为](../../../../backend/tests/e2e/test_forecast_creative_concurrency.py) | 真实 PostgreSQL 独立 session 同 operation 并发仅一个 run；原确认同样幂等。 |
| AT034 | postgres | [部分验证](../../../../backend/tests/e2e/test_forecast_creative_concurrency.py) | 请求内容 hash 比对与原 operation 复读；同 ID 异内容 HTTP 专项未独立重演。 |
| AT035 | postgres | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | prepare 独立子 run，重复只一 batch 已验；多 candidate 并发子 run 专项未独立重演。 |
| AT036 | postgres | [部分验证](../../../../backend/tests/e2e/test_creative_worker.py) | 真实 task 信封/lease 门禁与取消晚到已测；逐节点换 lease 的新工作项矩阵未全部重演。 |
| AT037 | postgres | [部分验证](../../../../backend/tests/e2e/test_creative_worker.py) | 实际 worker/provider 延迟 + PG 会话，Provider I/O 无领域事务；覆盖创作主链。 |
| AT038 | postgres | [部分验证](../../../../backend/tests/e2e/test_creative_worker.py) | 取消/超时/未知用量/partial 原 task 恢复已测，所有崩溃点未逐一注入。 |
| AT039 | postgres | [部分验证](../../../../backend/tests/e2e/test_forecast_creative_concurrency.py) | 新表项目级联删除和共用项目锁序已测；删除与发布的精确同时发生专项未重演。 |
| AT040 | postgres | [已验证记录内的工程行为](../../../../backend/tests/e2e/test_forecast_creative_concurrency.py) | 同时处置同 notice 一次成功、一次 ConflictError。 |
| AT041 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 复用原 AssistantActionBatch 的部分成功回执/重试门禁；新单操作预览已验。 |
| AT042 | postgres | [部分验证](../../../../backend/tests/e2e/test_forecast_creative_concurrency.py) | Case 占用原 Watch 与只读投影、既有 Assistant 并发门禁；review/forecast 到期精确竞态未另跑。 |
| AT043 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_lifecycle.py) | policy 分区合并保留 forecast，generation 参与指纹；沿原 policy 回归。 |
| AT044 | integration | [已验证记录内的工程行为](../../../../backend/modules/assistant/forecast/tests/test_lifecycle.py) | 旧 review 消耗计入共享额度；时区和滚动 24 小时同时约束。 |
| AT045 | integration | [已验证记录内的工程行为](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 客户端 saved_change 不能获得手动运行身份，dirty 不可分析。 |
| AT046 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_lifecycle.py) | 共享 overflow 和 dirty 分区边界保留，枚举遗漏可见；200+ 列表单独负载未重演。 |
| AT047 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_lifecycle.py) | 活跃 Imports 保留 dirty 且延后扫描，原导入幂等门禁保留；长导入噪声观察未跑。 |
| AT048 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_lifecycle.py) | due 轮转/冷却持久化，忙项目推迟 30 秒；长期负载下调度公平性未做持续测试。 |
| AT049 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 处置只更新 notice；原域写入仅在独立 prepare/confirm，伏笔专门样本未重演。 |
| AT050 | integration | [已验证记录内的工程行为](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 物理引用跨保存稿保持 issue；换标题无影响，不相关替换不继承拒绝。 |
| AT051 | integration | [已验证记录内的工程行为](../../../../backend/modules/assistant/forecast/tests/test_lifecycle.py) | 相同已观察章节不唤醒；后续 indexed 章节的新出现才触发。 |
| AT052 | integration | [已验证记录内的工程行为](../../../../backend/modules/assistant/forecast/tests/test_lifecycle.py) | 归档 Scene 保持 snoozed 并给 unavailable，不猜测到期。 |
| AT053 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 身份包含类型与物理引用，标题不参与；跨不同领域同标题的专项未重演。 |
| AT054 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 同源反向依赖只读汇总，领域意见/遗漏保留；三域冲突语义样本未评测。 |
| AT055 | integration | [已验证记录内的工程行为](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 明确 reopen 走原 CAS；只改变 notice，不改正文或结构。 |
| AT056 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 完整已枚举项目按互斥去向计数；性能负载验证 500 项，附件 8 项精确样本未独立重演。 |
| AT057 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 真实域 freshness 与 not_checked/partial 回执，不承诺语义穷尽；所有检索超时组合未重演。 |
| AT058 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_access.py) | 读取先按 owner/novel/原确认过滤；不可读计数专项未重演。 |
| AT059 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 语义经原知识审查；前瞻 Proposal 不提供 domain_verified，领域采用沿原专门门禁。 |
| AT060 | browser | [已验证记录内的工程行为](../../../../frontend-console/e2e/creative-forecast.spec.js) | 真实浏览器 composition/dirty 禁止分析，焦点保留；保存后恢复。 |
| AT061 | browser | [部分验证](../../../../frontend-console/tests/vue/assistant/Forecast.test.js) | Vue 单测 A 晚到不能覆盖 B，浏览器闭环另验；跨页迟到时序未在浏览器重复。 |
| AT062 | browser | [部分验证](../../../../frontend-console/tests/vue/assistant/Forecast.test.js) | client_context_id 每个实例生成，操作 CAS 在 PG 已验；双标签页端到端未另跑。 |
| AT063 | browser | [已验证记录内的工程行为](../../../../frontend-console/e2e/creative-forecast.spec.js) | 编辑、保存、原动作确认、试改采用和刷新；脏稿处理有真实保存反馈。 |
| AT064 | browser | [部分验证](../../../../frontend-console/tests/vue/assistant/Forecast.test.js) | 展开卡片保持旧 feed，明确点击后更新；键盘焦点新提醒专项未在浏览器重演。 |
| AT065 | browser | [部分验证](../../../../frontend-console/tests/vue/assistant/Forecast.test.js) | 桥接按 Unicode codepoint→UTF-16 转换且重验 range_hash；组合字符浏览器专项未另跑。 |
| AT066 | browser | [已验证记录内的工程行为](../../../../frontend-console/e2e/creative-forecast.spec.js) | 390 px 截图与页面 scrollWidth 断言通过。 |
| AT067 | browser | [部分验证](../../../../frontend-console/e2e/creative-forecast.spec.js) | 默认关闭且普通写作原流程保持；缺模型下的静态能力有单测，独立关闭浏览器回退未另跑。 |
| AT068 | integration | [已验证记录内的工程行为](../../../../backend/modules/interaction/tests/test_forecast.py) | Prompt 和 feed 均排除未选 sibling，原选中消息才作来源。 |
| AT069 | integration | [部分验证](../../../../backend/modules/interaction/tests/test_forecast.py) | 只输入选中正式历史和有效回顾，不直接读取原作后章；带未来原作的专门旅程未另跑。 |
| AT070 | integration | [部分验证](../../../../backend/modules/interaction/tests/test_forecast.py) | 固定 source_revision 和 source epoch 由原旅程回读；作者新稿变化专项未另跑。 |
| AT071 | integration | [已验证记录内的工程行为](../../../../backend/modules/interaction/tests/test_forecast.py) | prefill 仅返回输入文字，消息表数量不变。 |
| AT072 | integration | [部分验证](../../../../backend/modules/interaction/tests/test_forecast.py) | 沿既有有效明确修正链和 overview epoch；新前瞻修正冲突专项未另跑。 |
| AT073 | integration | [部分验证](../../../../backend/modules/interaction/tests/test_forecast.py) | 活动/未完成 attempt fail closed，不建 step/sibling；逐种 length 恢复状态未另跑。 |
| AT074 | integration | [已验证记录内的工程行为](../../../../backend/modules/interaction/tests/test_forecast.py) | source_context_epoch 改变后旧 prefill 拒绝。 |
| AT075 | integration | [部分验证](../../../../backend/tests/e2e/test_creative_worker.py) | 真实 worker timeout/缺 usage 保留未知消费、不重置；Forecast 单独超时未重复。 |
| AT076 | integration | [部分验证](../../../../backend/modules/collaboration/tests/test_maintenance.py) | 到期/关开关取消执行并保留 workspace/预算；已采用正文不回滚，前瞻 prepare 同时重验。 |
| AT077 | integration | [部分验证](../../../../backend/tests/e2e/test_forecast_creative_concurrency.py) | 新表级联不跨项目；expiry 只标失效并保留 receipt，到期清理专项未独立重演。 |
| AT078 | integration | [部分验证](../../../../backend/tests/e2e/test_creative_worker.py) | 注册新 task 类型及部署共用开关，默认关闭；未部署旧 worker/新 API 混部演练。 |
| AT079 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | 宿主封闭能力目录/范围，Prompt 明确数据不授予权力；真实模型注入样本未跑。 |
| AT080 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | Pydantic forbid extras/有限动作注册表，无动态 SQL/provider/URL 执行口；恶意输出专项未另跑。 |
| AT081 | integration | [部分验证](../../../../backend/modules/assistant/forecast/tests/test_forecasts.py) | anchor 和各 evidence_id 均从本轮输入复核，未知来源拒绝；真实模型伪造样本未跑。 |
| AT082 | model_blind_eval | [真实质量验收未完成](REAL_MODEL_REVIEW.md) | 已有真实模型小样本与 Codex 评阅；120 前缀成对对照和两名独立人工评分未完成。 |
| AT083 | model_blind_eval | [真实质量验收未完成](REAL_MODEL_REVIEW.md) | 已有真实模型小样本与 Codex 评阅；120 前缀成对对照和两名独立人工评分未完成。 |
| AT084 | model_blind_eval | [真实质量验收未完成](REAL_MODEL_REVIEW.md) | 已有真实模型小样本与 Codex 评阅；120 前缀成对对照和两名独立人工评分未完成。 |
| AT085 | performance | [部分验证](../../../../backend/tests/e2e/test_forecast_performance.py) | PG 20,000 条评估/500 个事项，30 样本：feed P95 254.82 ms、入队 43.69 ms；不含 HTTP、高并发与保存链计时。 |

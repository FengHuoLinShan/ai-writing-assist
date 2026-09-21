# 两份规划的本地实现与验收

代码已覆盖前瞻 B0–B4 与协作 V2 P0–P5 的工程范围，保存在独立工作树中。
2026-09-21 已运行 [真实 DeepSeek 小样本并由 Codex 评阅](REAL_MODEL_REVIEW.md)，质量准入未通过；
完整成对对照、独立人工盲评和生产灰度尚未验收。全部新增运行开关默认关闭。

- 工作树：`/Users/tywww/.codex/worktrees/forecast-creative-engine/ai-writing-assist`
- 分支：`codex/forecast-creative-engine`
- 当前基线：`6e901693a5d79826d292324e9787f3df7e5230cc`。
  起始基线为 `0f028ff269de249224366319baf110f982cc0f84`；工作期间主干合入的侧栏/RP 工具面板
  已同步，唯一合并冲突保留了新 RP 工具面板和本次前瞻入口。
- 状态：本地未提交；未推送、未建 PR、未合并、未部署。原目录的其他 WIP 未操作。
- 输入仅作为设计依据；两份附件没有授予付费模型、外部发送、生产写入或开发子代理权限。

## 实现范围

| 范围 | 交付的工程能力 | 主要实现 |
|---|---|---|
| B0 / WP01–03 | 核对当前实现；33 项能力、协议、权限和完整依赖；独立派生表、notice CAS、不可变评估 | [前瞻模块](../../../../backend/modules/assistant/README.md) |
| B1 / WP04–10 | 纯读取 feed；有限语义分析；稳定事项/排序/明确处置；暂缓和重开；独立 prepare 与原批次确认；写作面板/保存/IME/恢复 | [作者助手设计](../../../../docs/modules/20_assistant.md) |
| B2 / WP11–13 | World/Story/Writing、地图、Evidence、Imports 与讨论适配；确定性原资料回执、明确遗漏、原组指纹和来源重验；原入口预览 | [领域接口](../../../../backend/modules/assistant/forecast/context.py) |
| B3 / WP14–15 | 项目恢复位置、成果/待办/覆盖复查；私人旅程专用前瞻、选中路径与 epoch 绑定、预填但不发送 | [RP 设计](../../../../docs/modules/18_interaction.md) |
| B4 / WP16 | 共用日额度及滚动额度、冷却与队列轮转；明确反馈偏好；能力/项目灰度、关闭、保留/清理、未知用量和队列诊断 | [维护与诊断](../../../../backend/modules/assistant/forecast/maintenance.py) |
| P0 | V1 依赖失败传播修复；有限 V2 DAG；明确玩家刺激；Grant/Manifest/Artifact 与领域 ports；原协议兼容 | [运行协议](../../../../backend/infrastructure/llm/collaboration_v2.py) |
| P1 | Case 目标与授权分离；有界追加调查/反证；不可变成果；来源失效、预算、停止、原任务恢复 | [协作模块](../../../../backend/modules/collaboration/README.md) |
| P2 | 正文/Story 安排/世界书工作稿覆盖层；两方案及精确检查；跨域原子采用、幂等回执/outbox；三方 rebase 与反向试改 | [协作设计](../../../../docs/modules/21_collaboration.md) |
| P3 | 事件/观察/有限裁决/资源与认知状态；玩家可为观察者；逐段冻结盲读；World 同一情境前后重测 | [共用观察协议](../../../../backend/modules/story/observations.py) |
| P4 | RP attempt/正式正文同事务提交状态；选中分支恢复；私语/在场名单/输入类型；明确授权后的 Case 自动跟进共用 Watch | [RP 输入解释](../../../../backend/modules/interaction/ensemble_input.py) |
| P5 | 研究/精确导入会诊配方；自定义配方只能缩权；已验证连接分配；single/adaptive 同预算与工作区；离线质量工具和灰度保护 | [质量工具](../../../../backend/evals/creative_forecast.py) |

设计包正文实际从 B1 开始；本报告将用户指定的 B0 对应到共同基线和协议准备。
WP10、WP16、P5 的代码与评测工具已提供，真实质量及发布准入仍未通过。

## 已执行验证

| 验证 | 实际结果 | 证据 |
|---|---|---|
| 最终本地 `make test-ci TEST_WORKERS=2` | 部署契约 270 通过；后端 5,952 通过、13 跳过，覆盖率 85.57%；前端 2,532 通过 | [完整日志](artifacts/test-ci-final.log) |
| PostgreSQL 并发/原子采用/真实 worker | 21 通过；包括取消、来源变化、shutdown、超时、未知用量、同 task 续算 | [日志](artifacts/postgres-final.log) |
| 真实浏览器闭环 | 1 通过：编辑/IME→保存→前瞻→原待办确认→两试改→检查→采用→编辑器刷新；390 px 无页面横向溢出 | [日志](artifacts/browser-run.log) |
| frontend ESLint 与生产构建 | 通过；基于更新后的主干 | [lint](artifacts/frontend-lint.log)、[build](artifacts/frontend-build.log) |
| 迁移 | 四条 additive migration；两个专用库均成功，浏览器库从空库迁移 | [迁移实现](../../../../backend/alembic/versions/20260920_creative_engine.py) |
| schema 差异 | 当前 39 项诊断在原基线均能复现；没有本次新增漂移。不是全库 schema 零差异 | [对比](artifacts/schema-comparison.json) |
| 固定负载 | 服务层 feed P95 254.82 ms；入队 43.69 ms；0 Provider 调用 | [原始日志](artifacts/performance.log) |

浏览器没有 mock HTTP 路由；只替换 Provider 传输。真实 SQL、Project gateway、预算、任务、
知识审查、领域写入均实际执行。该证据不能代表真实模型理解或人工文学评价。

性能环境：Apple M1 Pro / 10 核 / 16 GiB，macOS 26.5.1；本机 Docker PostgreSQL 17.10，
Docker 内存上限约 7.65 GiB。负载为 300 章、1,500 Scene、5,000 对象、20,000 条仍保留的
评估，500 个当前事项；3 次预热、30 次样本。包含 PostgreSQL，不含 HTTP、并发用户、
模型耗时及正文保存计时；不外推到 20,000 个同时活跃事项。测试数据随事务回滚。

测试仅使用新建的 `ai_novel_test_forecast_01a0be6b` 和
`ai_novel_agent_e2e_forecast_01a0be6b`，未使用 Guimi、默认开发库或用户正文。
浏览器环境未配置对象存储和本地 BGE，因此清理/embedding 日志有环境告警；本次主链不依赖
它们，不能据此宣称地图存储或 embedding 已做集成验收。

## 尚未满足的完整验收

- [85 项逐条映射](ACCEPTANCE.md) 与 [机器记录](artifacts/acceptance-mapping.json)：
  20 项具有记录层级内的验证，52 项为部分验证或沿用已有门禁，13 项完整真实模型盲评仍未完成；机器记录是本轮真实调用前的历史快照。
  没有把全部 85 项标为通过；尤其双标签页、全组合故障注入、真实混部回退与高并发未全量重演。
- 离线工具提供 12 个不同机制的原创故事族、120 个冻结前缀、48 个安静反例；8 个开发族、
  4 个留出族。已实现独立盲评包、实际消费/未知用量、B/C 公平条件、C−B/C−D 与族聚类区间。
  [语料](artifacts/eval-prefixes.jsonl) 尚无人工作品级审阅；已有 9 次真实运行与单人 Codex 评阅，
  但没有四臂成对对照或两名独立人工评分，详见 [实测报告](REAL_MODEL_REVIEW.md)。
- 未执行真实公开网络研究、付费多模型对照或生产灰度。所有 provider 测试均为传输替身；
  真实两连接配置/共享预算已验证，但不能推断两种模型的现实效果。
- 范围有明确上限：完整试改上下文 24,000 字符，盲读最多 8 停点，段落对齐最多 32,000 字符；
  对象再出现暂缓依据后续已同步章节，不承诺同章 Scene 内的语义识别。超限/缺资料会给遗漏或拒绝。

源附件和当前权威文档均保留。本轮已获 DeepSeek 与 $20 上限授权，但实测发现的内容和评测问题
须先修正再运行完整对照；满足工程和内容门槛后才决定灰度。关闭功能不撤销已经明确采用的正文。

# 全代码库优化审查总报告

日期：2026-09-11。执行：主 Agent + 24 个只读审查子代理（W1 六槽、W2 十五槽、W3 四槽，另有 W0 由主 Agent 直接完成）。授权链：用户"开始计划"启动 W0/W1，"/goal 执行全部计划"授权全部剩余波次。本报告是计划 §1 定义的第一个独立验收结果；**优化实施未开始、未授权**。

## 1. 基线与范围

- 分支 `main`，HEAD `e7d0b8d5b`，`origin/main` = `2c462f2c7`（本地领先 1 未推送提交）。审查以工作树为准。
- 他人 WIP 全程未动：imports api.py/test_import_api.py（D5b 标注审查）、styles.css（D8c 标注审查）、`.agent` 两文档。审查零代码改动，产物全部为 `.agent/tasks/` 下新增/本地文件，无提交/推送/部署。
- 计划 §10.1 规模事实在执行中全部复核有效；一处修正：历史"16 份 stable_hash"实为更多（census 见 §4）。

## 2. 覆盖账本（§1 完成标准第 1、2 条）

- `coverage-ledger.csv`：**2453/2453 个 Git 跟踪文件全部标记已审**，与 `git ls-files -z` 程序化比对零缺漏、零重复、零未归属。无目录抽样宣称（F6 的 docs/历史目录按计划授权用"前缀+计数+抽样"方式，逐路径可追溯）。
- 生产源码逐文件语义阅读：后端 9 模块 + infrastructure + core/shared/app 全部逐文件（含 4018 行 world 生成中心、3871 行 world/api.py、3871 行级巨文件全文通读）；前端 shell/bridge/composables/shared 与 176 个 vue/views 全部逐文件；54 个 alembic 版本逐个读。个别超大测试文件采用"结构清单+关键段精读"并在各报告方法声明中如实标注（D2a 26/48、D3a 抽读、E 组按系统性方法）。
- 槽位完成度：F1–F6、D1、D2a–c、D3a/b、D4、D5a/b、D6a/b、D7、D8a–c、E1–E3、X1–X4 共 25 个槽位报告齐备于 `units/`。

## 3. 依赖与所有权图（指针）

- 114 表→模块→模型类所有权图、迁移链现状（head=`20260913_schema_parity_repair`，线性无分叉）、repositories 语义差异三档：units/F4.md 共享事实。
- 19 路由注册面、47 任务 handler 清单、LLM 客户端获取路径现状、状态枚举地图：units/F2.md；组合根/DI/生命周期：units/F1.md。
- 前端契约地图（手写:契约≈254:153）、island↔路由↔装载图、bridge seams：units/F3.md；发布契约/镜像清单/CI 步骤图：units/F5.md；文档权威源地图：units/F6.md。

## 4. 已裁定发现

- **241 条**（P0=0，P1=4，P2=58，P3=179），全部有 file:line 级证据、兼容面影响、最小方案、验证命令、回滚与裁定；索引见 `findings-ledger.md`，全字段见各槽位报告。主 Agent 对 8 条头部发现做了独立抽查实锤（F4-1、F3-1、F6-1、D5a-1、D5b-1、D3b-1、D8b-1、D8c-3、X1-1），全部属实；一处引用路径段缺失（D5a-1 漏 entity_extraction/ 目录）已修正记录。
- **安全结论**：novel_id 隔离与 owner 校验、图片上传门禁链、confirmation 三段重验与指纹、RP 无作者资产写回、地图三层 CAS、固定 SHA 发布合同——九条链交叉复核全部成立，**未发现 P0 级安全/数据丢失/隔离问题**；历史警示（deepseek probe 真实 key 轮换）维持开放。
- **P1 四条**：F4-1 测试扫描 .venv（基线失败根因，已独立复跑实锤）、D5a-1 prompt 硬编码第三方小说内容、D5b-1 导入恢复死循环、E1-1 52 个测试脱离门禁。前三者性质为已有功能错误/测试缺陷，按 §2 单列修复（批次表 R 组），未混入优化。

## 5. 旧候选复核结果（约 70 项）

- 仍成立（多数形态修正）：A1-1 部分、A1-2、A1-5、A1-6、A1-7、A2-1、A2-2 残余、A2-4 缩小、A3-1、A3-2、A3-5（24→64 处）、A5-1 扩大、A5-2、A5-4、A5-5、A5-8、A5-10、A6-1（4→5）、A6-3/4/7、A7-1 缩小、A7-3、A7-4 形态更新、A8-2、A8-3、A8-4 部分、A8-5/X1-9、X1-3、X1-6 不立项但证据完备、Wave0 四目录跟踪现状。
- 已解决：X1-7、A4-1、A4-5、A8-6 大部分、迁移压缩（20260703 已 squash）、镜像 test 文件、根 .test-logs、A3-5 story 面、A4-3 符号。
- 误报/不成立：A1-3、A1-4、`deep_import_phase01` 删除（真实验收工具链）、`tools/deepseek_scene_probe` 删除（DECISIONS 依据）、`frontend-console/docs` 未跟踪说、A1-1"恒 403"、A4-8 字面、A3-4 不存在、mock autospec 合规担忧（AST 守卫零违规）、"evals 全部 CI 活跃"（仅 eval-ask-world）。
- 功能变更/待查：X1-8（运行时 session 标记）、A5-6/A5-11/A5-14、A1-8（底稿缺失按现状关闭）、A3-6/A9-12（前提未满足）。

## 6. 架构裁定（P3）

按 §5 P3 条件（外部兼容可证明、事实源明确、依赖方向更清楚、可回滚）裁定：

- **实施候选（进 B3/B4）**：snapshot/checkpoint helper 收敛（归 llm_runtime 与 tasks facade，现有 owner）；story 入队流合并；conflict/generate 同步双轨退役；手写 manager 工厂化（保留语义清单前置）；smartDedup composable 化（1238 行本体保留）；views/ 迁移。
- **保留现状（不为完整报告虚构重构）**：状态词表三套（实为不等价状态机，收敛=破坏表达）；interaction/assistant 状态枚举；world 资产双词汇（收敛点已建，残余渐进）；InteractionView 2620 行拆分；X1-8 flag；A1-3 组织读点；UUID 类型统一。
- **补证据（不进可执行队列）**：D3b-2 memory 双投影、D2a-8 O(n²)、D6a-2/D6b-4 N+1、D8b-9 大列表、D7-7 selected 全量加载——全部"收益待测"，需专门授权的隔离性能会话（probe 修复+数据集）后再裁。
- **超范围/需确认**：alembic squash（部署窗口取证）；D3b-1/D4-1 补实现 vs 删 seam（产品裁定）；X3-3 world 任务用户取消（产品裁定）；D6b-5 搬家语料特判（产品裁定）；E1-9 语料样本（法务）。

## 7. 批次依赖与回滚

见 `batch-plan.md`：R1–R6 功能修复单列，B1a–d 清理（无前置可并行）→ B2a–e 同语义复用（契约对比前置）→ B3a–e 模块内编排 → B4a–f 跨模块收敛 → B5 数据结构默认不实施。每批独立提交独立回滚；共享 hash/状态批须字节兼容证明；B5 与全部"收益待测"项无基线不实施。

## 8. 实际验证结果

- W0 门禁基线：docs-check、ruff、前端 eslint/build 全过；vitest 183 文件 2480 测试全过；后端 fast 层 5288 过/2 失败，均已根因定位（见 §4 P1）并在 `baseline.md` 记录。
- 全程子代理只读，未运行任何测试/构建/数据库命令；主 Agent 仅运行门禁、两个单测定性复跑（test_identity 27 分钟通过实锤）与只读抽查。
- 文档门禁：本报告落盘后运行 `make docs-check` 与 `git diff --check`（结果见 TASK.md 验证节）。

## 9. 未验收项（如实列出）

- 未运行：`make test-postgresql-critical`、`make test-e2e`、浏览器功能/视觉 e2e、`make test-deploy`/镜像测试、动态性能基准（probe 本机必败且需隔离数据集）、真实模型/付费验收。均按计划 §8 属实施期或专门授权会话；审查结论中涉及运行时行为的部分以代码证据+静态推演为限，已逐条标注。
- 优化实施、合并、发布：未执行，待用户按批次表逐批授权。

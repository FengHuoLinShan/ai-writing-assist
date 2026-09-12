---
id: T-20260911-full-codebase-optimization-implementation
title: 全代码库优化实施
status: completed
created: 2026-09-11T23:00:00+08:00
updated: 2026-09-12T12:00:00+08:00
---

# 全代码库优化实施

## 恢复快照

- 目标：执行全代码库审查产出的全部可执行实施计划；明确延期、收益待测、真实数据清理、付费模型、合并、推送和部署不擅自执行。
- 工作区：`/Users/tywww/Desktop/项目/ai-writing-assist-full-optimization`，分支 `codex/full-optimization-implementation`，从本地 `main@44728ec22` 建立；`origin/main@2c462f2c7` 落后 5 个本地提交。
- 选择本地 main 的原因：它包含审查产物和已完成的前端修订；主工作区的 imports 未提交 WIP 未带入本分支。
- 已完成：R0a/R0b、R1–R4、R6b/R6c/R6d/R6e；B1a/B1b/B1d 与 B1c 无争议 leaf；B2a–c、B2e；B2d 全部代码项（F5-7 转运维拓扑门禁）；B3a/b/d/e；B4a/b/c/d/f。
- 当前验证：fast 全量 5410 passed/13 skipped、覆盖率 85.72%；PostgreSQL critical 33 passed；前端 185 files/2441 tests、lint/build/生产资源校验；部署 270 passed，生产镜像与真实恢复演练通过；docs-check 及 `BASE_REF=origin/main` 显式复核通过。
- 最新原子提交：`de9846689`–`bf74bc654`。完成六维 continuity、显式导入回收站、B1c 分类清理/合成夹具、B3c 任务轨真实模型验收与同步 AI 轨退役。
- 当前里程碑：剩余问题复核完成。修复 Vitest 漏洞和 eval Python 兼容；RAG “旧 chunk 残留”经完整回归证明是测试误判，已恢复历史 source revision 并纠正验收。
- 下一步：将已通过合并门禁的 `codex/full-optimization-implementation` 快进到本地 `main`；不推送、不部署。
- 未完成：无可安全实施的已授权项；Ragas 上游归档依赖与 F5-7 仍受外部依赖/生产拓扑证据阻塞。本任务未推送、未合并、未部署。

## 合并复核（2026-09-12）

- 已将本地 `main` 合入候选分支并解决 4 个内容冲突；审查文档保留 `main` 的独立复核版本，imports 同时保留越权隐藏测试与字面量路由优先级回归测试。
- `GET /api/imports/{record_id}` 已移到全部字面量 GET 路由之后，`test_import_api.py` 57 passed。
- 完整 `make test-ci TEST_WORKERS=2` 通过：部署 270 passed、后端 5411 passed/13 skipped（覆盖率 85.75%）、前端 185 files/2441 tests；docs、secret、依赖、ruff、lint/build 门禁通过。
- 专用 PostgreSQL 库的 merge-gate critical 33 passed；`git diff --check` 通过。`langchain-community` 仍是 eval extra 的已归档上游依赖，不是本次合并新增漏洞。

## 边界与决定

- 用户已授权执行全部实施计划；每个原子结果仍独立提交、独立回滚。
- 不合并、不推送、不部署；不删除真实数据、已采用资产、审查证据或他人 WIP。
- B1/B2/B3 owner 容器先按发现证据拆成 leaf；B4 先补等价与回滚卡再决定是否仍需代码；无性能基线候选不实施。
- 所有 owner/`novel_id`、Evidence confirmation、snapshot/hash、地图 CAS 与发布合同保持原样。
- 2026-09-12 owner 决定：R5 保留并完整设计空间、时间、逻辑连续性检查与消费体系；X2-3 取消与删除分离，由深度导入面板“回收站”显式触发软清理；B1c 审计归类后删除无明显价值项；B3c 允许有界付费真模型调用；F5-7 暂缓。
- 用户已授权在隔离分支持续实施上述计划；仍不合并、不推送、不部署。

## 完成审计（2026-09-12 03:21）

| 要求 | 当前权威证据 | 判定/解锁条件 |
|---|---|---|
| R5 continuity 位置证据 | 生产树仅剩 Story facade/service 定义与导出，Writing 无消费者；Writing README 仍声明该能力，real-LLM 测试仍有 3 个永不可满足的 kind 断言。前端 kind 标签作历史持久记录兼容面保留 | 方案已定：保留并扩展为版本化六维 Scene 状态及空间/时间/逻辑检查、确认、生成/修订消费闭环 |
| R6/X2-3 取消后产物 | cancelled run 只停止 owner；`abandon_recovery` 仍只接受 failed+recovery_required，`cleanup_workflow_assets` 无 cancelled 入口 | 方案已定：取消不清理；新增预览 fingerprint、显式 cleanup 与深度导入“回收站”Tab，持续软废弃 |
| B1c 证据/工具历史/样本 | `backend/backend` 有 11 个唯一验收日志（100 KiB）；工具历史 58 路径（372 KiB）；两个被 seed 消费的《诡秘之主》原文样本合计 40 KiB | 方案已定：先建分类账，无明显价值则删除；唯一证据最小保留/摘要；原文换原创合成样本，不重写历史 |
| B3c 同步生成/冲突双轨 | 生产前端仅消费任务轨；旧同步路由/service 仅供旧测试 | 已完成：测试迁入任务轨，4 次有界真实模型调用通过后删除旧同步正文生成、冲突复核/建议及前端死契约 |
| F5-7 forwarded 代理信任 | Dockerfile 仍信任 `*`；当前主机没有生产 `ai-writing-assist-egress` 网络，无法确定 OpenResty 经 loopback/DNAT 到 API 时的真实 peer IP | 用户明确暂缓；发布窗口取得 production network inspect/实际 peer 后另立运维安全批 |
| B5/收益待测 | 没有新性能基线或生产 revision 证据 | 按实施计划的“默认不实施”已满足，不是完成阻塞 |

## 验证证据

- R0a：`test_identity.py` 8 passed，pytest 本体 1.82s；完整 fast 5289 passed/12 skipped/7 deselected。
- R0b：定向 53 passed；默认收集从 5301 增到 5354；完整 fast 5342 passed/12 skipped/7 deselected。
- R1：prompt 定向 4 passed；imports 722 passed；生产 bulk prompt 无第三方作品专名或内部评测名。
- R2：workflow orchestration/runs 52 passed；imports 722 passed；专用 PostgreSQL 库迁移到 head 后 critical 32 passed。
- R3：project 125 passed；imports API/review-resolution 73 passed；assistant 52 passed；前端 assistant 13 passed 并通过 lint/build；story/writing 716 passed。
- R4：eval 140 passed/1 skipped；默认 fast 层收集 5507（选中 5500）并通过 5487/13 skipped/7 deselected。
- R6；assistant PostgreSQL 并发 2 passed；world 924 passed；generate-e2e 真正进入 21 个浏览器测试（17 通过，4 个既有失败已记录）。
- B1a：continuity 91 passed；writing+real index 228 passed/3 deselected；imports 701 passed；Evidence indexing 318 passed/2 deselected；Evidence compilation 275 passed。
- B1b/B1c：前端完整 182 files / 2456 tests、lint/build 通过；Playwright 53MB 导入夹具 1 passed；coverage 快照已停止跟踪且本地文件保留。
- B2/B3/B4 leaf：snapshot 285、checkpoint 338、stable-hash/full fast 2358、writing 222、story 489/12 skipped、worker 66、DI 82、World owner/key 203、World 状态映射 12，相关 lint/build 均通过。
- B2d 后续：interaction 134/2 deselected；imports 699；World 924；27 个 UUID coercion 模型的 JSON Schema 前后逐项零差异；无差异 `NovelMixin` 类完成分模块迁移。Evidence compilation `GUID()`、comment/unique/主键/无索引等差异列保留。
- ORM 说明：专用库 `alembic check` 仍报告一组既有 metadata/revision 漂移（Story 索引/时间列、World library 约束等）；本轮未据此生成 migration，后续须单独对基线取证。
- 前端异步：失败轮询统一阶梯退避；Scene auto/runtime manager 迁入共享工厂，Story Outline 因身份拒绝与终态重放保持专用实现。前端全量 183 files / 2448 tests、lint/build 再次通过。
- E1-4：新增 Story HTTP 项目范围、8 个 GET 的 422、任务 202 action/type 与 scene path/body 400 合同；Story 模块 30 passed。
- B2d 环境收尾：wheel 中 test/eval 条目 301→0；`eval-fast` 140 passed/1 skipped；部署测试 269 passed，后端/前端生产镜像与真实恢复演练通过。
- B4a/B4b/B4f：三预览页定向 16 passed；smartDedup 单元关联 87 passed 且浏览器 4 passed；API 错误守卫 15 passed。
- B1d：前端全量 184 files / 2437 tests、lint/build 通过；设置双页+世界审查桌面/390px 4 条功能链通过。视觉套件 3/8 通过、5 失败；在 CSS 批前 `cc16daa85` 对照中 settings-global-light 与 world-objects-light 失败像素数完全相同（8483/16425），确认为基线快照漂移，未擅自更新快照。
- 累计变更：完成记录提交后 123 个原子提交、388 文件、`+7007/-15863`，净删 8856 行。未合并、未推送、未部署。
- 2026-09-12 计划轮：新增 `authorized-remaining-plan.md`，并同步 `batch-plan.md` 与本恢复快照；仅文档变更，业务门禁尚未运行。
- R5a：旧四维 fingerprint 固定样本仍为 `9b0c68160db434ae0f0854d55e5d2de1b92320e1afcc90df34ec4357a6b8a92d`；Story continuity + Evidence compilation 366 passed；相关 ruff 与 diff check 通过。
- R5b：Imports + Story continuity 793 passed；Prompt contracts 22 passed；PostgreSQL critical 32 passed；相关 ruff/diff check 通过。首次未带 E2E_DATABASE_URL 的 critical 调用按门禁拒绝，随后使用既有专用库 `ai_writing_assist_e2e_full_optimization` 通过。
- R5c-core：Writing + Story continuity 317 passed/1 deselected；新增规则覆盖空间同点互斥、时间环/锚冲突、事实互斥、明确前提缺失与逾期承诺；缺维度反例不产出冲突。
- R5c-map：World + Writing 1151 passed/1 deselected；地图 seam 仅返回 adopted node 当前 saved revision、两端地点绑定且来源仍可重验的关系；来源修改反例返回空证据。
- R5d：Evidence compilation + Writing 506 passed/1 deselected；相关 ruff 通过。author/character Scene 写作与两条 conflict AI action 复用同一 scene_world_state，reader 不消费；语义审查记录 V2 三面覆盖。
- R5e-backend：Writing + continuity 320 passed/1 deselected；PostgreSQL critical 33 passed（新增同 item 并发确认只产生一个事件）；API 覆盖重复回执、正文漂移、非 continuity kind 与跨项目 404。
- R5f：前端 184 files / 2439 tests、lint/build 通过；Writing 冲突浏览器链 1 passed，流程内切换 390x844 验证作者确认输入与二次确认。首次仅因 `expectWithinViewport` 调用参数错误失败，修正后复跑通过。
- X2-3a：Imports 703 passed；PostgreSQL critical 33 passed；新增 preview/execute API、recent 清理投影、stale fingerprint、跨项目 404、完整回执重放与 `hard_deleted_assets=0` 断言。
- X2-3b/c：前端 185 files / 2441 tests、lint/build/生产资源校验通过；深度整理回收站浏览器链 1 passed，流程内切换 390x844 验证预览、明确确认、历史保留与隐藏内部标识。
- B1c：分类账见 `b1c-classification.md`；工具会话/占位工件删除 36 文件，错误目录与派生 latest 指针删除 12 文件；保留 239 份付费模型证据及 22 份实质设计探索。第三方原文改为原创三章合成夹具，导入/RAG/Outline 消费链 14 passed，部署门禁 270 passed。曾记录的 RAG 重索引失败经完整回归确认为测试误判：旧 source chunk 用于 ADR-0018 历史 revision 冻结检索，已纠正测试而未改生产语义。
- B3c：Writing 226 passed；前端契约/冲突组件 19 passed、lint/build；冲突浏览器链 1 passed。真实验收改为 PostgreSQL 上的 review-task + suggestion-task，全程经项目 snapshot LLM seam，删除同步轨前后各 1 次通过，共 4 次 DeepSeek 调用；每次均产出 2 条可用 AI 项并完成建议、发布快照及无正文/World/Memory 写回断言。专用库只临时复制加密连接，验收后已清空。E2E 外层事务使独立 retrieval trace 写入看不到未提交项目，产生已记录的 RAG 降级 warning，但 Scene/正文/确认上下文与任务轨验收断言均通过。
- 首轮完成时分支相对 `44728ec22` 为 123 个原子提交、388 文件、`+7007/-15863`（净删 8856 行）；剩余问题复核的最终统计见本节末。
- 最终门禁：docs-check、secret hygiene、后端/前端依赖高危门禁、ruff 均通过；部署 270 passed；后端 fast 5410 passed/13 skipped，覆盖率 85.72%；前端 185 files/2441 tests、lint/build；PostgreSQL critical 33 passed；生产后端/前端镜像、非 root/read-only smoke 与真实恢复演练通过。`langchain-community` 已归档及 Vitest/@vitest-mocker 2 项中危为依赖审计现状，高危门禁未失败，未在本批擅自升级依赖。

## 剩余问题复核（2026-09-12 重新开启）

- 用户授权：审查并修复剩余问题；继续当前隔离分支，不合并、不推送、不部署。
- RAG：初始 E2E 把原始 chunk 表多版本共存误判为残留。完整回归证明旧 source chunk 是 ADR-0018 历史 revision 冻结检索的必要数据；删除尝试已原子 revert。测试现断言默认检索只返回最新 draft、显式 source manifest 可精确回读旧版；PostgreSQL 1 passed，Interaction 历史上下文 8 passed。
- Vitest：GitHub GHSA-82fw-gwwq-j7x9 明确 4.1.11 修复；已从 4.1.10 升级到 4.1.11，`npm audit` 归零。
- `langchain-community`：Ragas 0.4.3 当前仍把它列为 core dependency；项目只在 `eval` extra 间接使用 Ragas，生产不安装。0.4.2 会触发 Ragas 已知导入断裂，故不能靠升级/删除提示来伪装修复；待 Ragas 移除该依赖或评测层获准替换。
- F5-7：本机仍无 production compose network，无法确定宿主 OpenResty 到 api 容器的真实 peer；贸然收窄会让公网请求退化为共享限流桶，继续保持取证门禁。
- eval runtime：锁定 `scikit-network==0.33.5` 在本机 Python 3.14/macOS 构建失败；Make 的 eval 运行器现默认使用已验证的 Python 3.13，可用 `BACKEND_EVAL_PYTHON` 覆盖。`eval-fast` 140 passed/1 skipped，真实 eval-extra fixture manifest 成功。
- 真实模型 warning：仅发生在 PostgreSQL E2E 外层回滚事务中；retrieval trace 按生产防锁设计走独立 session，因看不到未提交的测试 Project 而安全降级。生产项目在任务提交前已持久化，现有专门 trace-lock/失败降级测试覆盖；未把测试夹具差异改成生产逻辑。
- 复核门禁：后端 fast 5410 passed/13 skipped、覆盖率 85.72%；前端 185 files/2441 tests、lint/build、`npm audit` 0 漏洞；eval 140 passed/1 skipped及 fixture manifest；PostgreSQL RAG 1 passed、Interaction 历史上下文 8 passed；生产镜像、非 root/read-only smoke 与真实恢复演练通过。
- 最终分支相对 `44728ec22` 为 129 个原子提交、391 文件、`+7094/-15924`（净删 8830 行，含本条完成记录提交）。

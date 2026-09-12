---
id: T-20260911-full-codebase-optimization-implementation
title: 全代码库优化实施
status: in_progress
created: 2026-09-11T23:00:00+08:00
updated: 2026-09-12T09:00:00+08:00
---

# 全代码库优化实施

## 恢复快照

- 目标：执行全代码库审查产出的全部可执行实施计划；明确延期、收益待测、真实数据清理、付费模型、合并、推送和部署不擅自执行。
- 工作区：`/Users/tywww/Desktop/项目/ai-writing-assist-full-optimization`，分支 `codex/full-optimization-implementation`，从本地 `main@44728ec22` 建立；`origin/main@2c462f2c7` 落后 5 个本地提交。
- 选择本地 main 的原因：它包含审查产物和已完成的前端修订；主工作区的 imports 未提交 WIP 未带入本分支。
- 已完成：R0a/R0b、R1–R4、R6b/R6c/R6d/R6e；B1a/B1b/B1d 与 B1c 无争议 leaf；B2a–c、B2e；B2d 全部代码项（F5-7 转运维拓扑门禁）；B3a/b/d/e；B4a/b/c/d/f。
- 当前验证：fast 全量 5397 passed/13 skipped/7 deselected；PostgreSQL critical 32 passed；前端 184 files / 2437 tests、lint/build/生产资源校验通过；smartDedup 浏览器 4/4，设置+世界审查功能链 4/4；docs-check 及 `BASE_REF=origin/main` 显式复核通过。
- 最新原子提交：`47ca84ba0`–`702fd8cd8`。新增完成 imports start 编排、wheel/锁定运行器、服务镜像 digest、nginx 头继承、Outline 草稿生命周期、API 异常守卫、smartDedup Vue 迁移与重复样式清理。
- 当前里程碑：R5 完成；空间、时间、逻辑六维状态从导入/事件、投影、Evidence、确定性/AI 检查到作者确认、生成/修订和 Scene Lens 已闭环。
- 下一步：实施 X2-3a，增加 cancelled deep-import cleanup preview、显式清理、幂等回执与 run 状态投影。
- 未完成：R5 空间/时间/逻辑连续性闭环；R6a/X2-3 显式回收站清理；B1c 剩余分类清理与合成样本；B3c 任务轨付费验收及同步轨删除。F5-7、B5/收益待测项按决定延期。

## 边界与决定

- 用户已授权执行全部实施计划；每个原子结果仍独立提交、独立回滚。
- 不合并、不推送、不部署；不删除真实数据、已采用资产、审查证据或他人 WIP。
- B1/B2/B3 owner 容器先按发现证据拆成 leaf；B4 先补等价与回滚卡再决定是否仍需代码；无性能基线候选不实施。
- 所有 owner/`novel_id`、Evidence confirmation、snapshot/hash、地图 CAS 与发布合同保持原样。
- 2026-09-12 owner 决定：R5 保留并完整设计空间、时间、逻辑连续性检查与消费体系；X2-3 取消与删除分离，由深度导入面板“回收站”显式触发软清理；B1c 审计归类后删除无明显价值项；B3c 允许有界付费真模型调用；F5-7 暂缓。
- 当前用户请求仅为写计划；上述决定确定方案与未来实施边界，不把本轮扩大为立即修改业务代码。

## 完成审计（2026-09-12 03:21）

| 要求 | 当前权威证据 | 判定/解锁条件 |
|---|---|---|
| R5 continuity 位置证据 | 生产树仅剩 Story facade/service 定义与导出，Writing 无消费者；Writing README 仍声明该能力，real-LLM 测试仍有 3 个永不可满足的 kind 断言。前端 kind 标签作历史持久记录兼容面保留 | 方案已定：保留并扩展为版本化六维 Scene 状态及空间/时间/逻辑检查、确认、生成/修订消费闭环 |
| R6/X2-3 取消后产物 | cancelled run 只停止 owner；`abandon_recovery` 仍只接受 failed+recovery_required，`cleanup_workflow_assets` 无 cancelled 入口 | 方案已定：取消不清理；新增预览 fingerprint、显式 cleanup 与深度导入“回收站”Tab，持续软废弃 |
| B1c 证据/工具历史/样本 | `backend/backend` 有 11 个唯一验收日志（100 KiB）；工具历史 58 路径（372 KiB）；两个被 seed 消费的《诡秘之主》原文样本合计 40 KiB | 方案已定：先建分类账，无明显价值则删除；唯一证据最小保留/摘要；原文换原创合成样本，不重写历史 |
| B3c 同步生成/冲突双轨 | 弃用同步路由与 service 仍在，仅 real-LLM 验收消费；任务轨是生产前端唯一路径 | 付费调用已获允许；待 R5 任务轨稳定后按最多 4 次原创小语料验收，通过才删除同步轨 |
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
- 累计变更：本次记录提交后 103 个原子提交、283 文件、`+2938/-11664`，净删 8726 行。未合并、未推送、未部署。
- 2026-09-12 计划轮：新增 `authorized-remaining-plan.md`，并同步 `batch-plan.md` 与本恢复快照；仅文档变更，业务门禁尚未运行。
- R5a：旧四维 fingerprint 固定样本仍为 `9b0c68160db434ae0f0854d55e5d2de1b92320e1afcc90df34ec4357a6b8a92d`；Story continuity + Evidence compilation 366 passed；相关 ruff 与 diff check 通过。
- R5b：Imports + Story continuity 793 passed；Prompt contracts 22 passed；PostgreSQL critical 32 passed；相关 ruff/diff check 通过。首次未带 E2E_DATABASE_URL 的 critical 调用按门禁拒绝，随后使用既有专用库 `ai_writing_assist_e2e_full_optimization` 通过。
- R5c-core：Writing + Story continuity 317 passed/1 deselected；新增规则覆盖空间同点互斥、时间环/锚冲突、事实互斥、明确前提缺失与逾期承诺；缺维度反例不产出冲突。
- R5c-map：World + Writing 1151 passed/1 deselected；地图 seam 仅返回 adopted node 当前 saved revision、两端地点绑定且来源仍可重验的关系；来源修改反例返回空证据。
- R5d：Evidence compilation + Writing 506 passed/1 deselected；相关 ruff 通过。author/character Scene 写作与两条 conflict AI action 复用同一 scene_world_state，reader 不消费；语义审查记录 V2 三面覆盖。
- R5e-backend：Writing + continuity 320 passed/1 deselected；PostgreSQL critical 33 passed（新增同 item 并发确认只产生一个事件）；API 覆盖重复回执、正文漂移、非 continuity kind 与跨项目 404。
- R5f：前端 184 files / 2439 tests、lint/build 通过；Writing 冲突浏览器链 1 passed，流程内切换 390x844 验证作者确认输入与二次确认。首次仅因 `expectWithinViewport` 调用参数错误失败，修正后复跑通过。

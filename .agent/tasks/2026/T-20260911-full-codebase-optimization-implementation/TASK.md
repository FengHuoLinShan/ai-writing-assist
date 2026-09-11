---
id: T-20260911-full-codebase-optimization-implementation
title: 全代码库优化实施
status: in_progress
created: 2026-09-11T23:00:00+08:00
updated: 2026-09-12T01:38:00+08:00
---

# 全代码库优化实施

## 恢复快照

- 目标：执行全代码库审查产出的全部可执行实施计划；明确延期、收益待测、真实数据清理、付费模型、合并、推送和部署不擅自执行。
- 工作区：`/Users/tywww/Desktop/项目/ai-writing-assist-full-optimization`，分支 `codex/full-optimization-implementation`，从本地 `main@44728ec22` 建立；`origin/main@2c462f2c7` 落后 5 个本地提交。
- 选择本地 main 的原因：它包含审查产物和已完成的前端修订；主工作区的 imports 未提交 WIP 未带入本分支。
- 已完成：R0a/R0b、R1–R4、R6b/R6c/R6d/R6e；B1a/B1b 的可证明清理 leaf；B1c 无争议的 coverage/夹具/旧脚本/文档索引 leaf；B2a/B2b/B2c；B2d 的 timeout、writing 指纹、版本状态、World payload/owner/key、DI 小项；B2e 的 Vue 守卫扩面；B3a story 侧、B3b、B3e 业务逻辑归位；B4d。
- 当前验证：最新 fast 全量在修复前为 5381 passed/13 skipped/7 deselected，4 个静态/存量测试随后定向 230 passed；PostgreSQL critical 32 passed；imports 701 passed；前端完整 2456 passed，后续 World 相关 215 passed，lint/build 通过。
- 最新原子提交：`16e4b8889`–`aee94ec2b`。其中 snapshot/checkpoint/stable-hash 均先做字节/行为兼容收敛；World owner/key/状态标签保持旧导出入口。
- 下一步：继续 B2d 可独立验证的 schema/interaction/前端 leaf，再评估 B3/B4 仍有必要的最小实现；到里程碑重跑后端 fast、前端全量、PostgreSQL critical 与 docs-check。
- 未完成：R5/R6a 产品语义决策；B1c 历史证据/法务去留、B1d 受保护 styles WIP；B2d 大批量 schema/model 收敛及部署环境项；B2e Story HTTP 覆盖；B3c 付费验收门禁、B3d；B4a/b/c/f；B5/收益待测项按计划保持延期。

## 边界与决定

- 用户已授权执行全部实施计划；每个原子结果仍独立提交、独立回滚。
- 不合并、不推送、不部署；不删除真实数据、已采用资产、审查证据或他人 WIP。
- B1/B2/B3 owner 容器先按发现证据拆成 leaf；B4 先补等价与回滚卡再决定是否仍需代码；无性能基线候选不实施。
- 所有 owner/`novel_id`、Evidence confirmation、snapshot/hash、地图 CAS 与发布合同保持原样。

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

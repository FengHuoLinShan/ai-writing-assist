---
id: T-20261016-editorial-diagnosis-v1
title: 编辑审读诊断 A/B 试跑与盲评交接
status: blocked
created: 2026-10-16T18:02:35+08:00
updated: 2026-10-16T19:55:00+08:00
---

# 编辑审读诊断 A/B 试跑与盲评交接

## 恢复快照

- 目标：实施对照试跑工程补缺，用 Codex gpt-6-luna/max 完成旧/新提示词冒烟及全量运行；交付盲评包与 HANDOFF，等待作者另开 Claude Sonnet 5.5 任务评分。本轮不做评分。
- 工作树：/Users/tywww/项目/ai-writing-assist/.worktrees/editorial-diagnosis-v1；分支 codex/editorial-diagnosis-v1。
- 已有提交：第一阶段 04424535a2a164f0274aee2f65dd8d300b3f236f（提示词、桥接、v2）。
- 候选组固定提交：c0a32c7778ab4faaaa9f949ef8ba8a7de0606318；基线提示词来自 00d861283e34bdc0ef3f34ee5605c71e1f89c553。
- 真实模型请求：0。S01 冒烟在 `DATABASE_URL` gate 前停止；没有调用其他模型。
- 另有未跟踪 TEST-COVERAGE.md（本任务目录）记录并行测试补充；作为既有 WIP 保留，不纳入本轮文件写入或提交。
- 下一步：为该 worktree 配置指向本机专用 `codex_luna_runtime_test` 的 `DATABASE_URL`；随后重新运行冒烟。连接配置仍须经 owner Project facade 核验。
- 阻塞：当前进程没有 `DATABASE_URL` / `E2E_DATABASE_URL`；localhost:5432 PostgreSQL 无可用认证。只读发现的主工作树数据库配置属于其他用途，未连接；不以它代替专用库。

## 范围与边界

- 新增 editorial_cases_v3.json，保留 v1/v2；29 例标注 report、no_report 或 unchecked，增加与主要约束对应的原创正例。评分按正例召回、对照误报和 unchecked 正确率分开报告；零意见基线为 0/11 命中、11/11 漏报、0/17 误报、0/1 unchecked 正确。
- 新增仅在 backend/evals 使用的运行器：冻结基线 _SYSTEM 与候选固定提交 _SYSTEM；同一 Assistant worker、validator、来源和范围，仅切换系统提示词；两臂顺序随机。
- 只用本机专用 codex_luna_runtime_test PostgreSQL 与已验证的 owner Codex 连接。每请求经 modules.project.facade.open_project_llm_client() 核验 codex/gpt-6-luna/max；不符即停、不回退。
- 总请求硬上限：29 × 2 × 7 = 406，冒烟计入。case 启动与请求预留先持久化；出错、未知用量、进程中断均不重放；同一外部依赖连续 3 次失败暂停全局。
- 原始结果与 blind 映射仅存仓库外私有目录；本轮不评分，不 push、不开 PR、不合并、不部署。

## 决策与实现

- 已定：不新增 mismatch_type，不加风格偏好/伦理入口，不新增结构改写路径；只切换提示词；审美偏好默认不报。
- v3 替换重复 v1 情节的 S01 为伤势连续性冲突；新增客观记录、明示谜题、复仇、连载承诺、主动主角目标等正例，另有制度性被动人物对照。新文均为原创合成文本。
- editorial.py 有内部执行 seam，允许 runner 注入系统提示词、假/真客户端及请求钩子；tasks.py 只从 db.info 读取该内部选项，不暴露 API 或设置。
- 同步提示词行为措辞、Prompt README 权威位置、盲评导入模型与测试。worker synthesis checkpoint 同步保留累计请求预算，避免合并写回时覆盖预算记录。
- 盲评包每份只用随机 blind ID；映射放在 blind/ 外。HANDOFF 禁止给出分组、候选 SHA、分支或映射路径。

## 进度与验证

- [x] v3 数据、分母标签、零意见基线及哈希测试。
- [x] Luna 对照运行器离线实现：database gate、owner/Project facade profile 核验、wrapper manifest、全局请求账本、失败/未知/中断停止、不重放、随机化、原始输出与 blind 文件权限。
- [x] review.py 15 项盲评导入 schema 与契约测试；Assistant fake-client 注入测试。
- [x] 定向 Assistant 与评测测试：186 passed（2026-10-16）；make lint 通过；make prompt-contracts 26 contracts 通过。
- [x] git diff --check 通过。make docs-check BASE_REF=origin/main 因 module-tasks 规则列出 3 份未变文档；按维护流程以无当前架构影响说明复跑 scripts/check_architecture_docs.py 并通过。理由：只增加 Assistant 评测专用 db.info 钩子；任务注册、队列/租约/生命周期、API、跨模块契约及恢复语义未变，Assistant 与 Prompt README 已同步。
- [x] 工程与数据本地提交：c0f4fd2b28237ff6ce1ed35c45d2644cf2a95a4c；Project profile mismatch fail-closed 修正：c0a32c7778ab4faaaa9f949ef8ba8a7de0606318。候选提示词固定于后者。
- [x] 尝试 S01 两臂 smoke；runner 在 `DATABASE_URL` gate 停止。请求数 0，29 个 case 全部 `not_started`，无中断或已停止 case。
- [ ] 配好专用库连接后重跑 S01 两臂 smoke；确认每臂 7 次、共 14 次、输出完整、来源验证有效后再跑余下 28 例。
- [ ] 生成私有盲评包和 HANDOFF；不运行评分。

## 试跑产物路径

- 私有运行根目录：/private/tmp/novelcraft-editorial-diagnosis-v1-run-20261016/
- 原始输出：/private/tmp/novelcraft-editorial-diagnosis-v1-run-20261016/raw/
- 盲评包：/private/tmp/novelcraft-editorial-diagnosis-v1-run-20261016/blind/
- 盲号映射：/private/tmp/novelcraft-editorial-diagnosis-v1-run-20261016/mapping/blind-map.json
- 盲评交接：本目录的 HANDOFF-blind-review.md；此文件不得包含映射路径。
- 私有根目录及 raw/blind/mapping 子目录已按 0700 创建且均为空；没有 manifest/state 文件、原始结果、盲评包或映射。真实模型请求仍为 0。

## 最终交付状态与下一步

数据库连接解除后，先记录 owner/profile 核验，再完成 smoke 和全量运行。记录实际/不确定请求数、每个 case 状态、候选 SHA、输出路径及门禁结果。交付止于盲评包和 HANDOFF；之后等待 Sonnet 盲评结果，再解盲汇总正例、对照例与零意见基线。

---
id: T-20261001-anw-review-remediation
title: anw-improvements 批次审查整改（12 项 + 测试缺口）
status: active
created: 2026-10-01T21:30:00+08:00
updated: 2026-10-01T22:25:00+08:00
---

# anw-improvements 批次审查整改（12 项 + 测试缺口）

## 恢复快照

- 实际完成：12 项修复 + 三个测试缺口全部落地；后端 1317 通过、前端 2647 通过；docs-check（带 no-change-reason）通过；待提交。
- 当前里程碑：全部实现完成，进入提交。
- 下一步：`git add` 全部改动并提交到 codex/anw-improvements-batch-a；合并 main 另取授权。
- 阻塞：无。
- 工作区：主仓库分支 codex/anw-improvements-batch-a（基线 f98a70c3d + 本次未提交改动）。
- 最后核实：2026-10-01T22:25:00+08:00。

## 目标与验收

- 目标与交付物：修复审查报告的必须修 4（B2 身份碰撞、A2 门禁不对称、A2 前端死路、B3 视角门控）、应修 4（B5 能力名映射、B1 冲突标签、A3 资料性质、B3 首开状态）、小问题 5（A4 复核失效、B1 基稿跳过提示、B2 迁移继承、B3 来源标签、EditorialDesk 竞态）+ 补三测试缺口（A2 链路、B2 碰撞、B5 真实 id）。
- 完成条件：受影响模块测试 + lint 通过；docs-check BASE_REF=origin/main 通过；提交在任务分支。
- 非目标：B4、C1–C4（按方案不实施）；不合并 main。

## 上下文与边界

- 关键改动：
  - backend/modules/assistant/editorial.py：`_fingerprint` 无对象时追加首条引文锚点（去空白归一）；`_save_findings` legacy 别名命中要求对象集合一致才迁移/继承。
  - backend/modules/writing/semantic_review.py：unmet 无 excerpt 归一 unknown；contract_omission severity minor→major（阻断）。
  - frontend-console WritingEditor.vue：新增 `targetedRevisionReady`，incomplete 无可选条目时主按钮退回「重新独立审查」。
  - backend EditorialBriefLoader：门控 consumer_action=="writing.generate" 且 reveal_mode∈{author_safe,author_full}，否则 warning+不注入。
  - backend/modules/project/ai_usage.py：真实 id 映射 + 点分前缀回退（`_capability_label`）。
  - ConflictDetailDialog.vue：补 cross_chapter_repetition=「跨章复读风险」+ degraded 来源标签「跨章复读检查」。
  - markdown_renderer.py：新增 candidate/mixed 两级；补 world_entities、world_bible_activation/synopsis/working_pages、reader_visible_world/manuscript、historical_role_context、scene_world_state、author_pinned_material、focused_pins/evidence 标注。
  - project editorial_brief.py：PUT for-writing 返回 effective（`_brief_substantive` 提取共用）。
  - writing repositories/services：`list_chapter_summaries(populate_existing=)`；导出复核用它；`_repetition_items` 返回 (items, omissions)，基稿不可用/被改过时 degraded+omission 记录。
  - context_compiler.py：editorial_brief 来源 id=`editorial_brief:v{N}`、label=`编辑约定 v{N}`。
  - EditorialDesk.vue：toggle 用返回的 effective；toggle/load 均加 projectId 守卫，开关状态写入移到一致性检查后。
- 硬约束与授权范围：用户拍板"全部修复"+"unmet 一律不可直接采用"。
- 决策：定向返修/批注改写复用冻结 confirmation 不重新编译（grep 核实 writing 模块仅 assistant_generation_tool.py 传 writing.generate），B3 门控无返修回归；A3 混排 section（作者添加/专项查阅）标 mixed 而非猜测单一性质；B1 静默跳过走既有 degraded+omissions 通道而非新 schema。

## 里程碑与进度

- [x] 必须修1 B2 身份碰撞 + 迁移继承（测试：碰撞回归、迁移一致/不一致两分支）
- [x] 必须修2 A2 门禁对称（链路测试：unmet major 阻断→门禁拒绝、unmet 无位置→incomplete、全 met→pass 放行；prepare_targeted_revision 过滤测试）
- [x] 必须修3 A2 前端死路（测试：无可选条目退回重审、有可选条目双按钮可达）
- [x] 必须修4 B3 加载器门控（测试：character/reader/其他动作跳过+warning）
- [x] 应修5 B5 映射（测试：注册表∪绑定表全覆盖非回退标签；test_lifecycle 改真实 id）
- [x] 应修6 B1 冲突标签（测试：中文标签不暴露枚举）
- [x] 应修7 A3 资料性质（测试：核心 fact/candidate/mixed 标注）
- [x] 应修8+竞态12 PUT effective + EditorialDesk（前端 3 用例 + 后端契约用例）
- [x] 小问题9 A4 populate_existing（repo 级 identity map 回归测试）
- [x] 小问题10 B1 基稿跳过提示（degraded+base_draft_modified 测试）
- [x] 小问题11 B3 来源标签（section sources 断言）
- [x] 验证 + 文档同步（01_project/08_evidence/11_writing/Prompt体系设计）

## 决策、发现与失败

- 2026-10-01；`test_retrieve_with_custom_top_k`（evidence/indexing）在本目录失败但在 /tmp 干净 worktree 通过；stash 全部改动后仍失败 → 本机环境基线问题（重排序降级路径不裁剪 top_k），非本次改动引入；疑为降级路径真 bug，超出本任务范围，未修。
- 2026-10-01；docs-check BASE_REF=origin/main 要求 review indexing README/01_数据库设计/05_memory；分支无 schema/模型/迁移变更（indexing 仅测试改动），用 --no-change-reason 通道确认通过。

## 验证证据

- 后端：`python -m pytest modules/assistant modules/writing modules/project modules/evidence infrastructure/tasks -q` → 1317 passed, 1 failed（上述环境基线例）；ruff check + format 全过。
- 前端：`npx vitest run` → 209 files / 2647 tests 全过；改动文件 eslint 全过。
- docs-check：`check_architecture_docs.py --base-ref origin/main --no-change-reason "…"` → passed（2026-10-01T22:20+08:00）。
- `git diff --check` 干净。

## 交付结果

- 已交付：见"关键改动"；本地未提交。
- 未交付：B4、C1–C4（按方案不实施）；indexing 降级 top_k 基线问题（另行处理）。
- 交付边界：本地工作树，待提交到 codex/anw-improvements-batch-a；未推送、未合并、未部署。
- 正式知识与后续任务：docs/modules/01_project.md、08_evidence.md、11_writing.md、docs/prompts/Prompt体系设计.md 已同步。

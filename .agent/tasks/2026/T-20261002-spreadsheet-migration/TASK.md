---
id: T-20261002-spreadsheet-migration
title: 表格（xlsx/csv）迁移作者在途项目资产
status: in-review
created: 2026-10-02T21:32:00+09:00
updated: 2026-10-03T22:30:00+09:00
---

# 表格迁移

## 恢复快照

- 实际完成：实现、集成、独立 review 整改、复审修复轮与全部门禁均已在集成分支完成。
  提交链（`codex/spreadsheet-migration`，基于 `origin/main@0d555c463`）：
  79ae8e04a(计划) → 7ed082b47(L0) → 625d34541(任务记录) → 七车道 merge
  (c368a6d6d/fb1f61b38/f04deee5e/8b555a4ed/ec5425c6d/38d08bf0f/8e3c3f322)
  → 07dd57f0b(L8 集成) → 5b7d35346(清单门禁) → eacd5e6e3(L7b+ADR Accepted+fixtures)
  → bc752a4ab(review 修复) → 98885f2e2(autospec 注释位置修复)
  → b4c2389db(任务记录收尾)
  → 复审修复轮：efea9297f(服务层) → 045efc77d(前端) → 8594e0ffc(e2e 实测)
  → 3d07eb3db(defusedxml 移除) → 文档同步（本提交）。
- 当前里程碑：复审修复轮完成，等待用户 review / 授权推送与合入。
- 下一步：用户授权后 push 分支并走 PR；真实模型验收与真实来源文件支持宣称另行授权。
- 阻塞：无。
- 工作区：`/Users/tywww/Desktop/项目/ai-writing-assist-spreadsheet`，工作树干净。
- 最后核实：2026-10-03（复审修复轮定向验证 + 浏览器 e2e 实测）。

## 目标与验收

- **目标与交付物**：作者上传 `.xlsx`/`.csv`，系统识别人物卡、世界对象、关系、卷纲、主线支线、伏笔、
  细纲和总纲，作者在预览中调整后确认，落为已采用资产。资产带“表格迁移”来源，整次可撤销。
  大纲类表可选 AI 整理，结果只进预览。
- **完成条件**：计划 §4 L8 的全部门禁通过；ADR-0030 改为 Accepted；权威文档已同步。
  只对跑过真实文件验收的来源宣称支持。
- **非目标**：
  - 不支持 `.xls`、`.et`、`.ods` 和 Notion zip；
  - 不扩展正文导入白名单；
  - 不修复 planned Scene 与深度导入可能重复的问题（与 P20 现状一致）。

## 上下文与边界

- **关键路径与来源**：计划文档 §2–§4（冻结契约、车道文件归属、合并顺序）。
- **用户已确认的决策（2026-10-02）**：
  - 范围：世界对象与人物卡、人物关系、大纲和细纲（LLM 转化）；
  - 格式：只做 xlsx 和 csv；
  - 映射：规则识别，加上可选的 AI 整理；
  - 落库：确认即采用；同名只补空字段，绝不覆盖；冲突不落库，只展示给作者。
- **硬约束**：`novel_id` 与 owner 隔离；匿名 demo 不可用；LLM 只能经项目快照获取；
  会话和回执不长期保存正文；`@patch` 必须 `autospec=True`。
- **依赖**：新增 `openpyxl`（`defusedxml` 曾列入后经复审确认无引用，已移除）。
  storyforge-v6 仍在另一分支未合入，无 rebase 冲突。

## 里程碑与进度

- [x] 需求确认与架构计划（计划文档）。
- [x] Wave 0：L0 契约冻结并提交（7ed082b47）。
- [x] Wave 1：L1–L6 与 L7a 并行完成（L2/L4/L5 子代理因模型配额中断，由主会话续完），交接报告已审查。
- [x] Wave 2：L8 集成——SQLite 真实链路 e2e、PG 关键路径（`tests/e2e/test_import_migrations_pg.py`
  6 用例入 Makefile `BACKEND_POSTGRESQL_CRITICAL_TESTS`）、1000 行 apply 计时、仓库内三真实夹具验收、
  浏览器 e2e 骨架（`e2e/spreadsheet-migration.spec.js`，随专用 PG 配方跑）。
- [x] 独立 review + 修复（bc752a4ab：组件 scoped 样式与窄屏回退、决策/关系文案、apply 原子性用例；
  98885f2e2：autospec-exempt 注释位置）。
- [x] L7b 文档全量同步，ADR-0030 改为 Accepted，全量门禁通过。
- [x] 复审修复轮（2026-10-03）：default_entity_type 保留三层防护（后端回填+响应暴露+前端携带）、
  AI 成本预估接入 ai_authorization（默认范围 + submit 带 operation_id）、回执 10 个内部码文案、
  解析并发 Semaphore(2)、预览 decision_scope + 前端决策/列目标选项按类型过滤、
  defusedxml 移除、浏览器 e2e 换真实夹具并以 `make spreadsheet-e2e` 实测通过。
- [ ] 真实模型验收、真实来源（Excel/WPS/飞书/腾讯/Google/Notion 实际导出）文件验收——需用户另行授权。
- [ ] push、PR、合入 main——需用户授权。

## 决策、发现与失败

- **2026-10-02**：world 落库改用新的窄 seam，不复用 adoption package。原因：单包上限 32 项、没有人物字段、
  `force_create=False`，且回滚只覆盖 focused 包。
- **2026-10-02**：未识别列写入 `hidden_truth` 作为作者备注。该字段只在作者视图进入上下文，读者和 RP 侧已剔除。
- **2026-10-02**：origin/main 上没有 `project/model_routing.py`，Alembic head 为 `20260929_world_object_image_candidates`。
  因此 AI 任务暂不接入成本分档。
- **2026-10-03**：七车道零合并冲突（文件独占策略有效）。集成期修掉的关键 bug：
  路由挂载顺序（`/api/imports/migrations` 必须先于 `/api/imports/{record_id}` 挂载，否则被吃掉）；
  `applied_change_reversal.py` 对 Character 误用 `model.id`（主键实为 `entity_id`）致回滚 500；
  PG 锁用例改测「持锁挂起、放锁后串行完成」（facade 默认阻塞语义）。
- **2026-10-03（复审修复轮）**：复审发现#1「STORY_COLUMN_TARGETS 缺 core_conflict」为误读——
  修复前运行级复核确认 constants.py:128 已含该键且分类测试通过，未改动（教训：修复前逐项 grep+pytest 复核）。
  e2e 实测陷阱：项目页导入区展开状态（session.importSectionOpen）跨路由保留，从世界库返回后
  再点 toggle-import 会收起抽屉，测试改为仅在收起时点开。
- **2026-10-03**：已知待决（非阻断）：L6 `use_existing` 决策缺目标选择 UI（当前仅 `different_object` 可选）；
  L2 本地关系关键词表与 L1 `synonyms.guess_relation_kind` 双份（避免反向依赖，语义一致，可后续收敛）；
  前端窄屏/冲突/恢复人工走查未完整执行（组件测试与浏览器 e2e 已覆盖主要流）。
- **2026-10-03**：基线失败（非本次引入，已在干净 L1 基线 worktree 复现）：
  `test_project_task_gate_concurrency::test_delete_rejects_later_handler_commit…` 与
  `test_task_coalescing_concurrency::test_running_owner_allows_only_one_pending_follower`（PG，UUID 断言不匹配）；
  前端 smoke `project.spec.js`「空项目状态显示新建按钮」标题找不到。

## 验证证据

- 2026-10-03（复审修复轮，定向验证）：
  - 后端：`pytest modules/imports -q` 910 passed；`ruff check modules/imports` 通过；
    autospec 门禁 `tests/unit/test_test_harness.py` 16 passed（无新增豁免）。
  - 前端：`vitest run tests/vue/project/spreadsheetMigration*.test.js` 20 passed；改动文件 eslint 通过。
  - 浏览器 e2e：`make spreadsheet-e2e`（专用库 ai_novel_e2e_spreadsheet@PG5207，全新后端/前端，
    PW_REUSE_EXISTING_SERVER=0）1/1 passed——上传真实夹具→映射→跳过 AI→采用→
    世界库「表格迁移」徽标→撤销全链路实测。
- 2026-10-03（终态，提交 98885f2e2）：
  - `make test`：6677 passed / 15 skipped / 7 deselected（唯一失败为 autospec 门禁指出
    `test_spreadsheet_migration_ai.py` 的 exempt 注释位置，修复后门禁+该文件 30 passed 定点复验；此前全量其余全绿）。
  - `make -C … test-pg`（BACKEND_POSTGRESQL_CRITICAL_TESTS）：42 passed，另有 2 例基线失败（见上，非本次引入）。
  - `make lint`、`make docs-check`、`make prompt-contracts`（26 契约）、`git diff --check origin/main`、
    `git diff --check`（工作树）：全部通过。
  - 前端：2664 passed；smoke 57 passed + 1 基线失败（见上）。
  - 1000 行 xlsx apply 在 PG 实测通过（套件含 <300s 计时断言，实际套件总计 46s）。
  - 仓库内三真实夹具（backend/tests/fixtures/spreadsheets/）非 mock 解析验收通过；
    Notion 夹具因属 zip 白名单外合理 skip（放宽断言只验证后缀清理）。
- 2026-10-02：L0 门禁（make lint、schema-check、公共面测试、SQLite 隔离与 PG 全链迁移 up/down/up）全过。

## 交付结果

- **已交付**：完整实现（后端 11 端点 + world/story 迁移 seam + AI 整理任务 + 前端迁移面板与导入抽屉双页签 +
  浏览器 e2e 实测通道 `make spreadsheet-e2e`）、ADR-0030（Accepted）与全部权威文档同步、真实文件夹具。
  分支 `codex/spreadsheet-migration`，工作树干净。
- **未交付**：push / PR / 合入 main（待授权）；真实模型验收（消耗额度，待授权）；真实来源文件支持宣称
  （Excel/WPS/飞书/腾讯/Google 实际导出待脱敏样本；Notion zip 属白名单外，不宣称支持）。
- **交付边界**：仅本地集成分支；无远端、CI、部署状态变化。
- **正式知识**：以 ADR-0030 与 `docs/modules/13_imports.md` 为准。

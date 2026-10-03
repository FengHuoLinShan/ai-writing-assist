# ADR-0030 — 表格迁移（xlsx/csv）：独立入口、确认即采用、窄 facade 落库

- 状态：Accepted（浏览器 e2e 与 PG 关键路径已过；真实来源文件与真实模型验收见下）
- 日期：2026-10-02
- 授权：用户于 2026-10-02 确认范围（世界对象/人物卡/关系/大纲细纲）、格式（仅
  `.xlsx`/`.csv`）、映射（规则识别 + 可选 AI 整理）与落库语义（确认即采用、同名只补
  空、冲突不落库、整次可撤销）。

## 背景

作者普遍用 Excel、WPS、飞书、腾讯文档、Google 表格和 Notion 数据库管理人物卡、设定
词条、关系与大纲。系统此前只能导入正文，在途项目只能逐条手抄。深度导入（ADR-0016
链路）以正文为源，无法直接消费表格。

## 决策

1. **独立入口，正文白名单不变**。表格迁移归 imports 子包
   `modules/imports/spreadsheet_migration/`，路由 `/api/imports/migrations`。
   不扩展 `parsers.ALLOWED_EXTENSIONS`、不复用 `/imports/upload`；签名校验与分派
   接入 `parsers.py`（`SPREADSHEET_EXTENSIONS`、`audit_zip_container` 与 EPUB 共用）。
   匿名 demo 不放行（`/api/imports/` 不在 demo 只读白名单，有测试钉住）。
2. **xlsx 按有界固定部件 OOXML 处理**：不落盘、不执行公式或宏、拒绝 OLE/宏包/不安全
   成员/解压炸弹；单元格统一转字符串（日期 ISO、整数浮点去尾、布尔「是/否」），公式
   只取上次保存的缓存值。csv 走编码探测（BOM/GBK）与分隔符嗅探。全部限额（表数/行数/
   列数/单元格/会话字符量）明确拒绝，不静默截断。
3. **确认即采用**。作者核对预览后 apply：新资产直接 `status="canonical"`、
   `created_by="spreadsheet_migration"`、`approved_by=<owner>`（授权人对齐
   ADR-0017 §4）；项目启用 world validation policy 时失败关闭、零写入。
   与已有对象同名时绝不覆盖，只补空字段；冲突项不落库，只展示；未识别列以
   「作者备注」追加 `hidden_truth`（该字段只在作者视图进入上下文）。
4. **落库只经 world/story 窄 facade**：`plan/apply/rollback_author_migration_world`
   与 `plan/apply/rollback_author_migration_structures`。不复用 adoption package
   （单包 32 项、无人物字段、`force_create=False`、回滚只覆盖 focused 包），不走
   CreationSuggestion。apply 在同一事务内重算 preview 比对 `preview_hash` → 项目
   排他锁 → world → story（用 world 回执的 `entity_ids`）→ 会话标记。
5. **AI 只产出预览**。capability `imports.spreadsheet_migration`
   （`CONFIRMATION_NONE`，输入只有作者自上传行），step `outline`/`cleanup`，治理按
   ADR-0025（`govern_group_output`，最多返修一次）加确定性校验（行引用、逐字
   evidence、章号、字段白名单、forbidden keys）。大纲类表默认预选 AI；模型未配置、
   作者跳过或单行失败时回落规则映射，原文逐字保留。模型仅经项目 LLM 执行快照。
6. **会话表 imports 自有**：`import_migration_sessions` 草稿期暂存有界单元格，采用或
   删除后清空 `rows_json`；回执只存 id、hash、被改字段原值与标签，不存正文。
   mapping/decisions 以 revision CAS。
7. **回滚语义**：按回执逆序（story 先 world 后）；当前状态哈希与 `after_hash` 一致才
   废弃/恢复，否则保留（`modified_after_migration`）；被外部关系或世界书引用保留
   （`referenced`）；总纲 head 仍是本次修订时回基线或清 head 指针。删除迁移记录后
   不可再撤销。

## 被拒方案

- 复用 adoption package / CreationSuggestion（理由见决策 4）。
- 只落 candidate 再人工走采用流：作者明确要求「确认即采用」，多一步审阅无对应价值。
- AI 唯一路径：无模型项目不可用，规则回落是产品要求。
- `.xls`/`.et`/`.ods` 与 Notion zip：旧格式/宏风险/打包结构，首版不做；`.xls` 给出
  「另存为 .xlsx」指引。
- 直接扩展 `/imports/upload` 与文稿白名单：正文与结构化资产的生命周期完全不同。

## 后果

- world/story 各新增一个窄 seam 与对应回执模型（`modules/world/contracts.py`、
  `modules/story/outline_state/contracts.py`），story 复用 world 的
  `FieldConflict`/`MigrationAppliedChange`/`MigrationRollbackResult`（允许的窄依赖）。
- 新表 `import_migration_sessions`（迁移 `20261003`）；任务类型
  `spreadsheet_migration_ai`；capability 注册与 prompt 契约见
  `tools/prompt_contracts/`。
- 批量采用会触发逐条 synopsis 失效与 reannotation（已知性能点，1000 行实测后再决定
  是否加批量通道）；planned Scene 与深度导入可能对同一章出现两个 Scene（与 P20 现状
  一致，只记录不修复）；作者自定义类型不会自动与深度导入对齐（预览提示）。
- 对外只对跑过真实文件验收的来源宣称支持。

## 验收记录（2026-10-03）

- 代码门禁：后端默认层 6671 通过；`make lint`、`make docs-check`、
  `make prompt-contracts`（26 契约）通过；前端 211 文件 2664 用例通过。
- 真实链路（SQLite，无替身）：`modules/imports/tests/test_spreadsheet_migration_e2e.py`
  （上传→映射→预览→采用→可见性→撤销）。
- PG 关键路径：`tests/e2e/test_import_migrations_pg.py` 六用例（并发 apply 单胜者、
  排他锁串行、预览过期 409、回滚竞争保留、mapping CAS、1000 行 apply 约 40s 内）。
- 浏览器 e2e：`make spreadsheet-e2e`（专用 PG 库 + 真实 xlsx 夹具：上传→映射→跳过 AI→
  采用→世界库「表格迁移」徽标→撤销）1/1 通过（2026-10-03 本地实测）；smoke 57/58 通过，
  1 例失败（project 空项目态标题）经基线复现为既有问题，与本特性无关。
- 真实文件：本仓库夹具（xlsx/GBK csv/Notion 形状）非 mock 验收通过；Excel/WPS/飞书/
  腾讯文档/Google 表格的真实导出文件待取得脱敏样本后补测，未实测前不宣称支持。
- 真实模型验收（自由文本大纲 + 人物小传拆字段）消耗用户额度，待用户单独授权。

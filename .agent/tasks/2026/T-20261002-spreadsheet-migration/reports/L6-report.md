# L6 交接报告（前端）

车道：L6　分支：`codex/spreadsheet-migration-l6`　提交：见分支 log

> 执行说明：车道代理因模型配额中断未开工；本车道由集成者在主会话完成。

## 已完成

- `api.js`：`imports.migrations.{create,list,get,rows,saveMapping,startAi,
  saveDecisions,rollbackPreview,apply,rollback,remove}`；create 用 uploadMultipart；
  apply/rollback/startAi 走契约通道（长超时）。
- `apiContracts.js`：`imports.migrations.apply/rollback/startAi` 三个契约
  （AI_PREVIEW_APPLY_TIMEOUT / AI_TASK_SUBMIT_TIMEOUT），requiredBody 与后端
  Literal[True] 对齐。
- `SpreadsheetMigrationPanel.vue`：向导编排（上传→核对→AI→预览→完成），
  409 revision/预览过期自动刷新重取、AI 轮询 4s、撤销/删除、完成页跳世界库。
- `spreadsheetMigration/`：`MigrationUploadStep`（多文件+校验+建议先表格后正文
  文案）、`MigrationSheetMappingStep`（逐表类型/表头行/列映射/样例、窄屏卡片）、
  `MigrationAiStep`（大纲类默认预选、确认授权、状态/复核拦截数）、
  `MigrationPreviewStep`（五分页签、逐条决策、conflict 摘录、validation policy
  警示、confirmed+preview_hash 采用）、`MigrationRecordList`（状态/摘要/继续/
  撤销/删除二次确认）。
- `logic/spreadsheetMigration.js`：全部文案与数据形状（类型/列目标/动作/状态
  标签、目标选项四组、mapping/decisions payload、409 判定、分页签）。
- `ImportDrawer.vue`：「导入正文」「导入设定表格」双页签；正文页签 accept 与
  行为不变。
- `useImportUpload.js`：`SPREADSHEET_FILE_ACCEPT`、`validateSpreadsheetFiles`
  （数量 ≤5、扩展名、单文件 ≤10MB）；`IMPORT_FILE_ACCEPT` 不变。
- `shared/workflowProgress.js`：`spreadsheet_migration_ai: "整理表格大纲"`。
- 来源徽标 `spreadsheet_migration: "表格迁移"`：WorldEntityCollection.vue、
  WorldAliasesTab.vue、useWorldReview.js、outlineStructure.js、sceneModel.js。
- `WorldEntityDetail.vue`：profileFields 补 weakness/current_goal/stance/
  relationship_summary。
- 空态入口：世界库资料空态（WorldLibraryHome）与大纲篇章空态（OutlineArcsTab）
  各加「从 Excel/表格导入」按钮（navigate("project")）。
- 测试：`tests/vue/project/spreadsheetMigration.test.js`（7）+
  `spreadsheetMigrationComponents.test.js`（8：ImportDrawer 页签/accept 不变、
  映射改投、预览空态/冲突/确认门、上传校验）；`tests/api-contract.test.js` 的
  definedApiMethods 递归支持嵌套命名空间（imports.migrations.*）。
- `e2e/spreadsheet-migration.spec.js`：流程骨架（上传→映射→采用→徽标→撤销），
  L8 用专用 PG 与真实夹具运行。

## 改动文件

全部在本车道独占清单内；`tests/api-contract.test.js` 为共享文件的最小扩展
（递归收集嵌套 api 方法，属测试工具适配，无断言削弱）。

## 契约偏离

无。一点说明：契约键名与实际方法路径一致（`imports.migrations.apply`），
契约测试据此校验注册完整性。

## 测试

- `npx vitest run`（npm run test）→ 211 files / 2664 tests 全过。
- `npm run lint` → 通过。
- e2e 与窄屏人工走查 → L8。

## 文档要点（供 L7b）

- 导入抽屉双页签与「先表格后正文」提示；表格迁移向导五步。
- AI 整理需要显式勾选授权（模型额度）；大纲类表默认预选。
- 「表格迁移」徽标覆盖世界对象/别名/大纲结构/Scene 五处来源标签。

## 风险与待决

- MigrationPreviewStep 决策选项按 item 通用渲染（different_object/use_existing
  的 target 选择 UI 未做——use_existing 需要作者从相似列表选 id，L8 联调时视
  预览数据补一个选择器）。
- AI 轮询 4s 常量未做配置；离开面板时停止。
- e2e 夹具与真实文件验收共用 backend/tests/fixtures/spreadsheets/。

# P08 结果：导入准备与章节检查

日期：2026-09-12。执行范围按主代理任务卡限定，仅新增 frontend-console/prototypes/redesign/ImportPreview.vue 与 frontend-console/tests/prototypes/importPreview.test.js；未修改根组件、WorkspacePreview、其他域或正式导入代码。

## 已完成

- 三步准备流程：选择文稿→检查章节→准备资料。
- 选择《潮汐来信.txt》虚构示例；明确支持 txt/epub/html/htm、单文件 50MB 边界，不读取本地文件、不上传。
- 章节检查支持长标题、四章多选、清空/全选、选择数量和提纲片段标识；范围确认后进入资料准备。
- state=error 且 initialSection=chapters 可展示解析失败、保留原示例、重试解析。
- 准备资料页明确“尚未写入作品 · 演示”，展示人物地点/关系规则/剧情线范围选择，并将整理任务留给后续 E04。
- 支持重新选择、上一步、取消并返回作品档案；准备整理资料入口通过 open 事件交给主代理。
- 样式采用普通 style，所有选择器限定在 #redesign-root .rd-import-preview 下，适配窄屏单列。

## 接口

- props：state、initialSection。
- emits：navigate('projects')、open('准备整理资料', 'import', true)。
- 组件只有本地演示状态，不接 useImportUpload、API、Storage 或真实文件。

## 验证

- npm test -- --run tests/prototypes/importPreview.test.js：1 个文件，3 个测试通过。
- npx eslint prototypes/redesign/ImportPreview.vue tests/prototypes/importPreview.test.js：通过。
- git diff --check -- prototypes/redesign/ImportPreview.vue tests/prototypes/importPreview.test.js：通过。

## 主代理待验

- 浏览器检查三步流程、长标题、多选、解析失败重试、浅深色和窄屏布局。
- 主代理将组件接入导入导航并联验返回作品档案及 E04 整理入口。
- 真实文件选择、上传、解析、任务恢复、候选审阅和处理记录不在本包范围。

# E04b 结果：导入整理工作流与待决定

日期：2026-09-12。执行范围仅修改 ImportPreview.vue 与其测试，接续已验证的 E04a。

- 在准备资料页加入手动整理工作流：未开始、进行中、已停止、失败、待决定。
- 进行中可停止、手动完成或演示失败；停止可恢复；失败可重试未完成部分。
- 已完成项单独列出，失败重试不会重置“人物 2 项”等成功结果；完成演示追加地点项并进入待决定。
- 待决定状态提供“审阅导入世界资料”并以 open('审阅导入世界资料', 'compare', true) 交给共享候选审阅；另有查漏与处理记录入口。
- 明确候选资料未写入正式设定；未实现完整业务状态机、定时器、API、Storage 或真实模型。
- state=error 的失败状态可由 props 变化观测；initialSection=chapters/prepare 直接带已选示例。
- P08 外壳修正为 rd-page-scroll > rd-page-inner > rd-import-preview，避免嵌套 main。

验证：importPreview.test.js 6 项通过；定向 ESLint 与 diff-check 通过。浏览器由主代理验收。

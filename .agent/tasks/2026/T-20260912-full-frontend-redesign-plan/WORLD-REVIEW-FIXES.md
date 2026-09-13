# 世界域修复结果

日期：2026-09-12。范围按主代理授权，修改 WorldPreview.vue、WorldDetail.vue、WorldImport.vue 及对应世界测试；未改共享或其他域，未进行浏览器操作。

- 关系页新增“关系图谱 / 关系审阅”切换；关系审阅复用 WorldReview(kind=关系)，保留过期阻断、拒绝和比较路径。
- 世界审阅子视图放入 KeepAlive 并按 kind 使用 key，切换分类/跨页后保留同一会话内的决定和选择。
- WorldDetail 保存时向父级发出 update；WorldPreview 按 entry.id 保存本地详情草稿，关闭并重新打开同一对象仍显示本次预览编辑。
- WorldImport 增加本地重试边界；目录错误重扫后收起错误并显示成功反馈，避免失败与“已准备好”同时出现。
- 处理历史按状态区分：已完成查看范围，失败恢复失败步骤，避免所有记录都显示恢复。
- 保留跨入口 initialSection 时的 selected 对象，不再因入口 section 更新无条件清空已选对象。
- 修复 KeepAlive 接入造成的 Vue 模板条件错误：结果区改为独立 v-if/v-else-if，恢复全站编译。

验证：
- npm test -- --run tests/prototypes/worldPreview.test.js tests/prototypes/worldDetail.test.js tests/prototypes/worldReview.test.js tests/prototypes/worldImport.test.js tests/prototypes/worldConnections.test.js：5 个文件，20 个测试通过。
- 定向 ESLint：通过。
- git diff --check：通过。

未验证：浏览器视觉、焦点、窄屏和真实世界业务/API/Storage；由主代理负责浏览器复核。

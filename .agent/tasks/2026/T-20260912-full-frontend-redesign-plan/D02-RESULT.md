# D02 结果：世界资料详情

日期：2026-09-12。执行范围按任务卡限定，修改 `WorldPreview.vue`、`world-preview.css`，新增 `WorldDetail.vue` 与 `tests/prototypes/worldDetail.test.js`；共享壳、`data.js`、正式 WorldView 及其他页面保持只读。

## 已完成

- 列表选中对象后由本域 `WorldDetail` 承接资料阅读，取消列表原先调用主壳静态 `person` 对话框的路径；同一对象的名称、类型、角色、说明和来源保持关联。
- 增加本地编辑模式：角色与说明可编辑，取消恢复原值，保存只更新本次详情预览并显示明确反馈，不写入作品。
- 增加图片状态演示：无图片、加载中、加载失败、可用，以及添加/重新加载/替换示例图片；失败时文字资料仍可读。
- 增加来源与历史区：显示当前来源、两条示例历史记录，并通过 `navigate('search', '正文')` 回看原文。
- 增加回到本章写作入口；危险的归档操作先调用确认，再显示确认/取消结果，示例数据不被删除或归档。
- 详情使用现有 `rd-detail-surface`、按钮、图标、状态令牌和本域 `#redesign-root` 样式，窄屏将详情上下排列；没有文件上传、API、Storage 或新增依赖。

## 接口

- `WorldPreview` 保留 props `state/initialSection` 与 emits `open/navigate`。
- `WorldDetail` props：`entry`；emits：`close`、`navigate(page, section)`。

## 验证

- `npm test -- --run tests/prototypes/worldPreview.test.js tests/prototypes/worldDetail.test.js`：2 个文件，8 个测试通过。
- `npx eslint prototypes/redesign/WorldPreview.vue prototypes/redesign/WorldDetail.vue tests/prototypes/worldPreview.test.js tests/prototypes/worldDetail.test.js`：通过。
- `git diff --check -- frontend-console/prototypes/redesign/WorldPreview.vue frontend-console/prototypes/redesign/WorldDetail.vue frontend-console/prototypes/redesign/world-preview.css frontend-console/tests/prototypes/worldPreview.test.js frontend-console/tests/prototypes/worldDetail.test.js`：通过。

## 主代理待验

- 主壳已接入；需由主代理在浏览器检查桌面/窄屏、浅深色、长中文、键盘焦点、详情关闭/返回链以及全站 CSS 冲突修复后的实际呈现。
- 本包未执行浏览器检查，不能标记浏览器验收通过；未接真实资料保存、图片服务、文件上传或正式归档业务。
- D03 后续承接待决定、关系/别名批量审阅，不在此组件内复制候选审查机制。

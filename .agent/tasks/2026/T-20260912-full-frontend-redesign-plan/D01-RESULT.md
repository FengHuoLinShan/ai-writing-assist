# D01 结果：世界资料浏览

日期：2026-09-12。执行范围按任务卡限定，新增 `WorldPreview.vue`、`world-preview.css` 与 `tests/prototypes/worldPreview.test.js`；未修改共享壳、`data.js`、正式 WorldView 或其他页面。

## 已完成

- 新增世界资料主视图：沿用 `people` 示例数据，提供人物、地点、物品、规则、组织和待决定/关系/别名入口。
- 默认采用紧凑列表，提供列表/卡片密度切换；卡片视图保留相同对象、来源和选择语义，没有复制首页大卡片布局。
- 搜索按名称、类型、角色和说明过滤；输入不触发列表动效，分类切换复用现有 `vReveal`。
- 选择条目后在同页展示轻量详情，保持对象、来源、角色和跨域入口一致；完整资料经 `open(title, kind, drawer)` 交给主壳，地点/写作入口经 `navigate(page, section)` 交给主壳。
- 提供加载、空资料、搜索无匹配、失败保留旧示例、明确重试及重试成功反馈；所有状态均为本地预览，不读取 API、Storage 或真实作品。
- 局部样式限定在 `#redesign-root .rd-world-preview`，复用现有色彩令牌、按钮、图标、动效和响应式规则；长中文使用 `overflow-wrap` 保持可读。

## 接口

- props：`state`（默认 `normal`）、`initialSection`（默认 `全部`）。
- emits：`open(title, kind, drawer)`、`navigate(page, section)`。

## 验证

- `make docs-check`：通过。
- `npm test -- --run tests/prototypes/worldPreview.test.js`：1 个文件，5 个测试通过。
- `npx eslint prototypes/redesign/WorldPreview.vue tests/prototypes/worldPreview.test.js`：通过。
- `git diff --check -- frontend-console/prototypes/redesign/WorldPreview.vue frontend-console/prototypes/redesign/world-preview.css frontend-console/tests/prototypes/worldPreview.test.js`：通过。

## 主代理待验

- 主壳接入 `WorldPreview` 并提供现有 `state/initialSection`；浏览器检查桌面/窄屏、浅深色、真实长中文、键盘焦点和详情返回链。
- 本包没有执行浏览器检查，不能标记浏览器验收通过。
- D02 后续承接完整资料阅读/编辑、图片状态和更深对象详情；D03 承接待决定、关系/别名批量审阅。

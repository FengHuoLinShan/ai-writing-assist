# D04 结果：关系与知识图谱

日期：2026-09-12。执行范围按任务卡限定，修改 `WorldPreview.vue`、`world-preview.css`，新增 `WorldConnections.vue` 与 `tests/prototypes/worldConnections.test.js`；共享壳、`data.js`、正式 WorldView 及其他页面保持只读。

## 已完成

- “关系”页签改为同一虚构作品的关系浏览：林舟、沈雁、白沙港、北境海图及三条可读关系。
- 使用原生 SVG 作为关系图辅助，并提供完整的原生按钮对象列表，支持键盘/触摸选择，不依赖拖动、缩放或图形交互才能完成任务。
- 选中对象后显示同一对象的类型、角色、说明、关联对象、关系语义和来源；地点可回地图，人物可回本章写作，也可回看正文来源。
- 关系展示不输出实体/关系原始 ID；关系图和列表使用作品中的对象名称。
- 样式复用现有令牌、图标和详情/按钮模式，窄屏将图与对象列表纵向排列；所有数据和选择均为本地示例。

## 接口

- `WorldConnections` emits：`navigate(page, section)`。
- `WorldPreview` 将“关系”页签路由到 `WorldConnections`，并继续向主壳转发导航事件。

## 验证

- `npm test -- --run tests/prototypes/worldPreview.test.js tests/prototypes/worldConnections.test.js`：2 个文件，8 个测试通过。
- `npx eslint prototypes/redesign/WorldPreview.vue prototypes/redesign/WorldConnections.vue tests/prototypes/worldPreview.test.js tests/prototypes/worldConnections.test.js`：通过。
- `git diff --check -- ...`（本包文件）：通过。
- 首轮测试发现并修复 SVG 关系标签缺少 `v-for` 的渲染错误，修复后无警告失败。

## 主代理待验

- 浏览器检查 SVG 辅助图、节点列表键盘路径、对象详情一致性、浅深色和窄屏排版。
- 本包未执行浏览器检查，不能标记浏览器验收通过；未接真实关系查询、编辑或持久化业务。

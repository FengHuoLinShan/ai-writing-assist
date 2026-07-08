# Scene 树折叠展开点击交互优化

## 背景

写作页左侧 Scene 树（`frontend-console/views/writing/chapterTree.js`）当前将「展开/折叠」与「选中 Scene」两个职责混在一起：

- 三角按钮（`.scene-tree-toggle`）仅负责展开/折叠。
- Scene 标题按钮（`.scene-tree-label`）负责选中 Scene 并**强制展开**该分组。

这导致用户无法通过 Scene 标题折叠已展开的分组，折叠控制入口单一且不符合直觉。

## 目标

统一 Scene 标题与三角按钮的折叠能力，同时保留 Scene 标题的跳转功能。

## 设计决策

### 1. Scene 标题点击行为

点击 Scene 标题（`.scene-tree-label`）时：

1. 触发 `select-scene` 回调：跳转到该 Scene 关联的首章，并通知 orchestrator。
2. 切换该 Scene 分组的展开/折叠状态：展开变折叠，折叠变展开。

实现上，`_selectScene` 不再无条件将分组状态设为 `true`，而是读取当前状态取反：

```js
const groupId = this._sceneGroupKey(scene)
const currentlyExpanded = this._isSceneGroupExpanded(groupId, false)
this._sceneGroupExpansion[groupId] = !currentlyExpanded
```

### 2. 三角按钮点击行为

点击三角按钮（`.scene-tree-toggle`）时：

- 仅切换展开/折叠状态。
- 不触发 `select-scene` 回调，不跳转。
- 阻止事件冒泡，避免触发父级 Scene 标题的点击事件。

### 3. 未归类分组

「未归类」分组没有对应 Scene，因此：

- 点击「未归类」文字仅切换该分组的展开/折叠状态。
- 三角按钮同样仅切换折叠状态。

### 4. 默认展开策略

首次加载、选中章节/Scene 时的默认展开策略保持不变，避免本次改动引入额外副作用。

### 5. 状态持久化

本次为最小改动，`_sceneGroupExpansion` 仍保存在内存中，刷新页面后重置。如需持久化可在后续迭代中补充。

## 受影响文件

- `frontend-console/views/writing/chapterTree.js`
- `frontend-console/tests/writing/chapterTree.test.js`

## 测试计划

1. 更新现有测试「Scene 分组三角按钮可折叠并在重渲染后保持状态」：
   - 验证点击 Scene 标题会切换该分组折叠状态。
   - 验证点击 Scene 标题会触发 `onSelect` 与 `onSceneSelect` 回调。

2. 新增测试「三角按钮只折叠不跳转」：
   - 验证点击三角按钮会切换折叠状态。
   - 验证点击三角按钮不会触发 `onSceneSelect`。

3. 新增测试「未归类标题只折叠不跳转」：
   - 验证点击「未归类」文字会切换折叠状态。
   - 验证不会触发 Scene 相关回调。

## 验收标准

- [ ] 点击 Scene 标题可展开已折叠分组。
- [ ] 点击 Scene 标题可折叠已展开分组。
- [ ] 点击 Scene 标题仍跳转到该 Scene 首章。
- [ ] 点击三角按钮只切换折叠状态，不跳转。
- [ ] 未归类分组标题只切换折叠状态，不跳转。
- [ ] 相关单元测试通过。

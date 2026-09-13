# P01a 结果：标题/正文输入与稿件身份

日期：2026-09-12。执行范围按主代理任务卡限定，仅修改 `frontend-console/prototypes/redesign/WritingPreview.vue` 与新增 `frontend-console/tests/prototypes/writingInput.test.js`。

## 已完成

- 将样板正文从只读段落改为原生 `contenteditable` 多行正文区域，保持纸面排版、中文长文本和现有正文内容；输入通过 `input` 更新当前章节本地草稿，不在每次输入时重建编辑器节点。
- 标题改为原位可编辑 `h1[role=textbox]`，保留原有纸面标题视觉和现有回归测试定位。
- 以章节索引保存独立标题/正文草稿。切换章节后再返回，当前章节本次输入保留；暴露 `locateChapter(index)`，供主壳从来源定位回写章节，不引入跨页状态引擎。
- 增加稿件身份选择：工作稿可编辑；正式正文、历史版本、AI 建议均明确显示只读身份和解释文字。候选状态仍只展示演示身份，不覆盖工作稿。
- 空态增加“开始写作”入口；选择后进入同一正文纸面。保留 props `state/focus/externalPanel` 及 KeepAlive 兼容。
- 新增最小输入回归：章节草稿隔离、标题/正文输入、只读身份阻断、`locateChapter` 合法性。

## 验证

- `npm test -- --run tests/prototypes/writingInput.test.js tests/prototypes/redesign.test.js`：2 个文件，9 个测试通过。
- `npx eslint prototypes/redesign/WritingPreview.vue tests/prototypes/writingInput.test.js`：通过。
- `git diff --check -- prototypes/redesign/WritingPreview.vue tests/prototypes/writingInput.test.js`：通过。

## 待主代理浏览器检查

- 中文输入法合成、撤销、选区、长文滚动和焦点在真实浏览器中检查。
- contenteditable 在浅色/深色、移动窄屏和减少动态效果下的纸面表现。
- 从来源/查找调用 `locateChapter` 的跨页返回连续性。
- 正式保存、备份失败、冲突、恢复、正式确认和真实业务接回属于 P01b/后续阶段，本包没有假保存或 API 接线。

## 复核修正

- 移除了标题/正文可编辑节点的 Vue 插值绑定；节点只在初始、换章或切换身份时显式同步，输入事件使用 `innerText` 更新本地草稿，避免 Vue 在每次输入时回写节点打断光标、IME 和原生撤销。
- 空态改用独立空稿对象；“开始写作”进入空白正文，不复用或清空其他章节草稿。
- 新增节点身份与空稿测试；定向结果更新为 2 个文件、10 个测试通过，ESLint 和 diff-check 仍通过。

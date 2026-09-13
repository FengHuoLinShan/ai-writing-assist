# P03b 结果：独立审查与定向返修演示

日期：2026-09-12。执行范围按主代理任务卡限定，仅修改 `frontend-console/prototypes/redesign/CandidateReview.vue` 与 `frontend-console/tests/prototypes/candidateReview.test.js`；未修改 WritingPreview、共享文件或正式产品。

## 接口

- props：复用 `candidate`，支持 `status/source/review/stale`，以及可选 `title/original/suggestion/diffSummary/revision`。
- emits：保留 P03a 的 `update:status`、`update:stale`、`open`、`navigate`、`close`；新增 `update:review`、`update:revision`。
- 组件不直接修改 candidate prop。主壳负责把事件写回同一内存候选对象；本组件不建立状态机或真实业务调用。

## 已完成

- 独立审查结果区分待审查、审查通过、有阻断项；待审查/阻断项不会显示可采用。
- 采用条件收紧为候选待采用、来源未过期且独立审查通过；来源过期始终阻断采用，可重新确认来源或拒绝。
- 阻断项展示人物知识边界示例，入口提供状态演示以复核待审查/阻断/通过/来源过期。
- 定向返修支持要求输入、进行中、失败、完成和失败后重新返修；状态推进全部由按钮手动触发，无计时器伪造成功。
- 支持重新生成候选入口；返修说明保留原候选、原稿和来源记录。
- 候选标题、原稿、建议和差异统计优先使用 candidate 可选字段，默认保留《潮汐来信》样板；差异默认写为“局部段落改写 · 示例”，不硬编码数字。
- 比较容器内边距收窄，适合嵌入宽 PreviewDialog；新增样式全部限定在 `#redesign-root .rd-candidate-review` 下。

## 验证

- `npm test -- --run tests/prototypes/candidateReview.test.js`：1 个文件，4 个测试通过。
- `npx eslint prototypes/redesign/CandidateReview.vue tests/prototypes/candidateReview.test.js`：通过。
- `git diff --check -- prototypes/redesign/CandidateReview.vue tests/prototypes/candidateReview.test.js`：通过。

## 主代理待验

- 浏览器检查宽比较、浅深色、长中文、窄屏单列及 PreviewDialog 嵌入边距。
- 接入主壳后联验 update 事件驱动同一 candidate 在待决定入口和正文入口一致。
- 独立审查/返修真实服务、来源复验、候选确认和正式正文确认不在本包范围。

## 浏览器复核修正

- 将组件样式改为普通 `<style>`，每条选择器完整以 `#redesign-root .rd-candidate-review` 开头，避免 Vue scoped/global 混合导致根节点污染；比较摘要布局恢复为组件内作用域。
- 将拒绝条件独立为“候选待采用且未在返修中”；待审查、来源过期和阻断项仍可拒绝，但不能采用。
- 将原工作稿/候选比较提前到独立审查和返修区之前；返修改为 `details` 渐进展开，避免首次打开宽比较面板时先滚过大段辅助内容。
- 修正后定向测试 4 项通过，ESLint 与 diff-check 通过。

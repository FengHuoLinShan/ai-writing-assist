# P03a 结果：候选来源与比较审阅

日期：2026-09-12。执行范围按主代理任务卡限定，仅新增 `frontend-console/prototypes/redesign/CandidateReview.vue` 与 `frontend-console/tests/prototypes/candidateReview.test.js`；未修改 WritingPreview、共享文件或正式产品。

## 接口

- props：`candidate`，默认结构为 `{ status: "pending", source: "第三章 · 潮汐之间", review: "待审查", stale: false }`。
- emits：`update:status`（`adopted` 或 `rejected`）、`update:stale`（重新确认来源）、`open`、`navigate`、`close`。
- 组件不直接修改 candidate prop；采用到工作稿只发出演示更新事件，不替换正文、不表示正式正文已确认。

## 已完成

- 精细宽比较面板：来源范围、审查状态、3 处改写/28 字变化、原工作稿与候选建议并排长中文比较。
- 待采用、已采用到工作稿、已拒绝、来源已过期四种身份均有文字与语义色；已采用明确说明尚未成为正式正文。
- stale 时显示红色阻断提示，禁用采用/拒绝，提供重新确认来源事件。
- 关闭审阅、返回正文、采用到工作稿、拒绝建议入口明确；移动端比较列收为单列。
- 样式使用 `rd-comparison`、`rd-inline-notice`、`rd-button`、`PreviewIcon`；新增 scoped 规则以 `#redesign-root` 为范围。
- 没有新增审查/返修状态机；P03b 承接独立审查、定向返修与更复杂状态。

## 验证

- `npm test -- --run tests/prototypes/candidateReview.test.js`：1 个文件，3 个测试通过。
- `npx eslint prototypes/redesign/CandidateReview.vue tests/prototypes/candidateReview.test.js`：通过。
- `git diff --check -- prototypes/redesign/CandidateReview.vue tests/prototypes/candidateReview.test.js`：通过。

## 主代理待验

- 实际浏览器检查宽比较、浅深色、长中文和窄屏收纳。
- 接入主壳时由主代理提供同一内存 candidate，并联验 `open/navigate/close` 返回链。
- P03b 再补独立审查、定向返修、来源重查和更完整的审查结果状态。

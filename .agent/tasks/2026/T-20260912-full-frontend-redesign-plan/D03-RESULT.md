# D03 结果：世界资料待决定、关系与别名

日期：2026-09-12。执行范围按任务卡限定，修改 `WorldPreview.vue`、`world-preview.css`，新增 `WorldReview.vue` 与 `tests/prototypes/worldReview.test.js`；共享壳、`data.js`、正式 WorldView 及其他页面保持只读。

## 已完成

- 将“需要决定”“关系”“别名”从通用占位说明替换为同一虚构作品中的本地审阅页签，并保留列表筛选与本次选择。
- 待决定对象按“等待你决定”和“已处理”分组，提供当前筛选范围、全选、批量确认/拒绝和逐项确认/拒绝；已确认与未决定不混在同一组。
- 来源过期的对象、关系和别名均禁用确认/采用，但仍可逐项或批量拒绝；选区包含过期项时批量确认明确阻断。
- “查看差异”统一发出 `open('审阅世界资料', 'compare', true)`，复用主壳已有 `CandidateReview`，没有新增第二套比较面板。
- 关系展示“林舟 与 沈雁”“白沙港 通向 旧灯塔”等可读名称和来源，不显示实体/关系原始 ID。
- 别名明确展示“归属对象 / 已有对象”，例如“守塔人 → 沈雁”，确认语义为附着已有对象，不建立新实体。
- 保留本地筛选、状态反馈和演示边界；所有动作不写业务、不调用 API/Storage，不新增依赖。

## 接口

- `WorldPreview` 继续提供 `state/initialSection` props 与 `open/navigate` emits。
- `WorldReview` props：`kind`（`需要决定`、`关系`、`别名`）；emits：`open(title, kind, drawer)`、`navigate(page, section)`。

## 验证

- `npm test -- --run tests/prototypes/worldPreview.test.js tests/prototypes/worldDetail.test.js tests/prototypes/worldReview.test.js`：3 个文件，12 个测试通过。
- `npx eslint prototypes/redesign/WorldPreview.vue prototypes/redesign/WorldDetail.vue prototypes/redesign/WorldReview.vue tests/prototypes/worldPreview.test.js tests/prototypes/worldDetail.test.js tests/prototypes/worldReview.test.js`：通过。
- `git diff --check -- ...`（本包文件）：通过。
- 额外运行旧 `tests/prototypes/redesign.test.js`：8 个测试中 6 个通过，2 个失败均命中旧 `.rd-world-card` 与主壳静态 person 对话框选择器；这是 D01/D02 新行为后的待迁移主壳回归，未在本包越界修改。

## 主代理待验

- 浏览器检查三个页签的桌面/窄屏、浅深色、键盘焦点、筛选与批量操作、过期阻断和比较面板返回链。
- 更新主壳旧世界卡片/静态 person 回归选择器，使其反映列表选中与 `WorldDetail` 本域详情。
- 本包未接真实候选、关系、别名 API 或持久化；D03 仅交付可评阅设计状态。

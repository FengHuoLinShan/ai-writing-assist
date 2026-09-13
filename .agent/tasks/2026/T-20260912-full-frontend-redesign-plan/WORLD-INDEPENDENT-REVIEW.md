# 世界域 D01–D05 独立源码评审

日期：2026-09-12。审查对象：WorldPreview、WorldDetail、WorldReview、WorldConnections、WorldImport、world-preview.css 及其正式 WorldView/WorldbookImportPanel 调用边界。只读源码审查，未进行浏览器操作；不把真实业务未接回本身判为缺陷。

| 优先级 | 位置 | 触发 | 影响 | 最小建议 |
|---|---|---|---|---|
| P1 | WorldPreview.vue:17,113-115；WorldReview.vue:5,9-12,45-46 | 进入“关系”页签并尝试审阅关系候选或处理过期关系 | WorldReview 明确实现了 kind=关系（含过期项、确认/拒绝、批量阻断、来源），但 WorldPreview 对“关系”始终渲染 WorldConnections，WorldReview 只接“需要决定/别名”。关系页因此只剩图谱和详情，关系候选的待决定/过期审阅路径不可达，D03 的关系审阅被 D04 图谱覆盖。 | 在关系域保留图谱浏览并增加明确的“关系审阅”入口，或在同页组合 WorldReview(kind=关系)；确保过期关系仍可拒绝、不可确认。 |
| P1 | WorldImport.vue:37,56-63 | state=error 进入世界书“导入目录”，点击“重新扫描示例” | scan() 只设 scanned/feedback，props.state 仍是 error，错误条持续显示；同时页面会显示“示例目录已准备好”，形成扫描失败与成功准备并存。 | 使用本地 retry 状态收起错误并显示重试成功，或将按钮文案改为“查看上次示例”，不要在 error 仍存时宣称扫描完成。 |
| P1 | WorldReview.vue:56-64,95-115 | 在待决定页确认一项后切换筛选/返回，再重新打开同一候选 | items、选中集和决定只保存在 WorldReview 实例；WorldPreview 在切换分类时保持组件条件切换，重新进入会重新 buildItems，确认/拒绝决定丢失。设计阶段可不接持久化，但“已处理”分组会在同一会话中消失，无法验证离开后重开同一待决定项。 | 将当前 review decisions 放入 WorldPreview 持有的最小本地对象并按 kind 传入，或明确组件不承诺离开重开；连续路径验收前至少保留同一 WorldReview 实例状态。 |
| P2 | WorldDetail.vue:8-25,43-47 | 编辑对象 A 后保存，再关闭并打开对象 B，或切换后回到 A | 编辑保存只更新 WorldDetail 的 savedNote/savedRole，未回写 entry；关闭详情后新实例恢复原 entry。预览边界允许不写作品，但“已保存在本次预览”只在当前实例成立，跨对象/返回无法保持本次编辑结果。 | 文案改为“已在当前详情中预览”，或由 WorldPreview 持有按 entry.id 的本地草稿；不要声称对象级保存已保留。 |
| P2 | WorldConnections.vue:19-20,45-49 | 选择“北境海图”或关系节点，再尝试定位其全部关联关系 | selected 详情依赖 people，关系列表只从 links 推导；节点图本身 aria-hidden，交互完全依赖列表。可用名称选择路径存在，但没有关系审阅/来源过期/处理状态，且“关系”标题容易让人以为可以编辑/决定。 | 在图谱详情明确“仅浏览”，并提供关系审阅入口/状态；图谱与审阅共享同一关系对象清单，避免两个视图各自维护关系事实。 |
| P2 | WorldImport.vue:31-34,85-88 | 处理历史选择“可恢复”或点击已完成/失败记录下一步 | continueHistory 对所有记录都只写同一类“已恢复本地示例，等待下一步”反馈；已完成的“查看范围”也被描述成恢复，失败记录没有具体回到目录/健康/审阅的上下文。 | 按记录状态分别回到范围、冲突检查或候选审阅，并显示对应记录标识；至少让“已完成”不使用“恢复”文案。 |
| P2 | WorldPreview.vue:45-56,84-93 | state 从 error 改回 normal，或点击重试后继续使用筛选/选择 | error 重试只由 props state 决定，retried 仅用于本次提示；state 变化会 reset retried，但 query/view/selected 的保留规则不统一。选择在 error 前已存在时会保留，initialSection 变化却清空 selected，跨入口返回的对象上下文可能消失。 | 统一记录“重试是否成功”和对象/筛选返回规则；按 PLAN 要求从跨域返回时至少保留 section 与当前对象。 |

## 可复用点

- WorldPreview 已集中分类、搜索、列表/卡片密度、状态入口和本域子视图分派；主壳接入只需消费 navigate/open，不需要新增路由。
- WorldDetail 已有编辑取消回滚、图片失败仍可读、来源历史和危险确认；这些可作为作者对象详情的状态样板。
- WorldReview 已有待决定/已处理分组、过期阻断、批量确认/拒绝和候选比较复用点；关系审阅缺口是接线路由问题，不必重做审阅机制。
- WorldConnections 已提供键盘/触摸对象列表作为图谱非拖动替代；WorldImport 已区分候选、工作稿、正式资料、健康提醒和处理历史，方向与 PLAN 一致。

## 限制

未进行浏览器操作，未确认 CSS 实际编译、焦点回还、窄屏布局或动画效果；未运行全量测试。报告只指出源码可证明的入口、状态和连续性风险，不要求 D01–D05 在设计阶段接真实文件、API、世界资料保存或健康任务服务。

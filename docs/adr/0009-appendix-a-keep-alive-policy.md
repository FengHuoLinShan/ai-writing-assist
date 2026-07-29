# ADR-0009 附录 A — 活 DOM 缓存裁定（所有视图移出 keep-alive）

- **状态**: Accepted
- **日期**: 2026-07-19
- **兑现**: ADR-0009 原路线图延后的 writing/outline 缓存设计与最终 Vue shell 收口

> 本附录的 DocumentFragment、renderer 单例和 keep-alive 均是已删除机制或被拒绝方案；
> “最终裁定”是当前生效契约。

## 触发问题

旧 router 把 `#workspace-content` 子树搬进 DocumentFragment，并按
`view + subView + projectId` 缓存。Vue app 实例、命令式 renderer 单例、轮询器和编辑状态却有
不同所有权：一个 island 重挂载可能卸载缓存 fragment 中的 app；跨项目切换也可能把仍存活的
renderer 内存与另一个项目的 DOM 重新组合。缓存的是“活 DOM”，却无法同时证明 app、异步
请求、项目 owner 和业务会话仍属于当前路由。

## 最终裁定

1. router 不再维护 `_keepAliveViews`、DocumentFragment 或 `onActivate/onDeactivate`。
   离开任何视图都调用 `onLeave`；重新进入执行 `onEnter → render → onRendered`。
2. `mountIsland` 只持有当前挂载的一个 Vue app。`onLeave` 递增 load generation 并卸载；
   同视图 force refresh 在重新挂载前卸载残留实例。
3. 写作台不以存活 DOM 保存草稿。`writingSession` 按项目与章节保存显式 snapshot，重进时
   重新加载服务端事实并恢复允许保留的本地编辑态；未保存离开仍由同步 `canLeave` 守卫确认。
4. Outline/Scene 的 workflow、筛选、当前选择和滚动位置通过所属 manager/session 明确恢复；
   离开时停止轮询。地图离开时销毁 viewport controller，草稿/未提交编辑由 `canLeave` 和
   `beforeunload` 阻止静默丢失。
5. 所有异步提交继续使用 project owner + lifecycle generation。卸载、项目切换或新请求后，
   旧响应不得写回新页面。

## 项目边界事务（WORLD-009）

作者工作台的项目页共享同一条 route-host 生命周期。项目边界不是“先加载目标、成功后替换
旧页”，而是一次有明确提交点的事务：

| 阶段 | 顺序与提交规则 |
|------|----------------|
| 退出预检 | 先规范化目标路由，再依次执行当前 renderer 的同步 `canLeave` 与 `closeModal({ reason: "project-navigation" })`。任一拒绝时不改 state、不卸载、不请求目标项目；`popstate` 还原来源 hash。项目列表等不依赖项目的 route host 不拥有当前项目，不能因列表中有选中项目而触发该弹窗门禁。 |
| 提交边界 | router 原子取走 `_mountedRoute`，在旧项目 state 与 DOM 仍有效时恰好调用一次 `onLeave`，随后清空宿主、显示无项目业务操作的中性骨架、清理全局选择，再切换 `currentProjectId`。从这一刻起，失败或重试都不能恢复旧项目的活 DOM。 |
| 同步目标 | 取消上一项目请求，并用 route transition generation 获取目标元数据。晚到、已取消或被更新导航取代的结果不得修改 state、URL、DOM、history 或失败态。程序化导航只在当前目标仍有效时写 history；pending/stale 阶段不触发 `onNavigate`。 |
| 目标提交 | 目标 renderer 必须完整完成 `onEnter → render → onRendered` 后才能成为新的 `_mountedRoute`。任一步失败都调用该 renderer 的 `onLeave` 清理半启动资源，再进入不含业务操作的失败页；骨架与失败页都不是 mounted route。 |
| 恢复与重入 | 跨项目临时失败只允许重试同一目标或返回项目列表；不可访问项目清除无效选择。同项目 refresh 遇网络、408、429 或 5xx 时保留当前编辑页，遇 403、404、422 等不可重试 4xx 时立即退出。A→B 尚未完成又转向 C 时取消 B 并复用中性态，A 的 `onLeave` 仍只执行一次，B 不得短暂挂载。 |

Router 分开保存 mounted route、pending target 与 failure route，不得再根据历史 view 字段或全局
失败标记互相推断。项目所有权只来自已经挂载且 `requiresProject` 的路由；项目 ID 变化时即使
view 名相同，也必须清除跨页全局选择。401 继续由账户安全刷新边界接管。

## 显式重建表

| 能力 | 重建方式 |
|------|----------|
| Outline/Scene 任务恢复 | project/task/workflow 持久键 + manager `recover()`；`onLeave` 停止轮询 |
| Outline 子导航滚动 | `state.viewStates.outline.scrollTop` |
| Writing 当前章节与未保存快照 | 项目隔离的 `writingSession`；服务端版本仍是事实源 |
| Writing 字数仪表盘 | 挂载时派发 `writing:dashboard-update`，卸载时清空 |
| Map Leaflet/Canvas 状态 | `MapViewportAdapter` 依据规范 route context 重建；编辑脏态阻止离开 |
| query-only 导航 | `mountIsland` 比较 query signature，在 `onRendered` 前补载 |
| route 全局动作 | router `onNavigate` 返回 unsubscribe；Shell/bootstrap dispose 时清理 |

## 接受的取舍

- 返回视图需要重新创建组件和必要的数据请求，不承诺缓存 DOM 的瞬时返回。
- 只有具有明确业务价值的状态才进入 session；偶然的 details 展开态或组件局部 hover 状态不
  作为跨路由契约。若性能证据表明需要缓存，应缓存可失效的数据快照，不恢复活 DOM。

## 拒绝方案

- **按 cache key 保存 Vue app Map**：会把 `mountIsland` 与 router 内部缓存键、项目切换和
  force refresh 强耦合，仍无法证明命令式子系统与异步 owner 一致。
- **仅 Writing 保留单视图 keep-alive**：会保留两套生命周期语义，并继续依赖 renderer 单例
  的隐式项目状态；显式 session 已覆盖真正需要恢复的作者编辑态。

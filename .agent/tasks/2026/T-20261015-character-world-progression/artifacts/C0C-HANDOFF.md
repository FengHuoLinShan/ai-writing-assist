# C0c 实现检查点交接

核实时间：2026-10-16。C0c 自有实现分两次提交：`89b34c1ee9d7e78b41ffab0f837f3425f793676f`（对象有效期、别名区间、自定义 Story 状态与作者界面）和 `371ab21d4a8096cd9249a734f06e6e267ca612c1`（地图声明 Story 契约与作者入口）。本记录不代表三份计划整体完成；Sol 独立审修、共享组合根接线和最终验证仍未完成。

## 已实现切片

- 项目设置 `world_object_dossier_v1` 默认关闭，使用版本 CAS；设置只改变截止点读取，不重写 World/Story 历史。
- 档案条目可选绑定同对象已登记 Story 字段；只有精确对象、字段、可信确认来源与 cutoff Scene 之前的观察才可参与覆盖。关系按稳定 `EntityRelation.id` / `relation_status` 绑定，不以端点、类型或旧 RelationAttitude 模型推断身份。冲突与缺口进入只读 `world.object_validity` NoticeSource。
- 别名 Scene/章节有效期贯穿新增、编辑、移动、批量复核、类型转换和历史恢复；旧无区间别名保留来源/状态/复核语义。别名存在本身不授予角色身份知识。
- World 模板可声明自定义文字状态字段；状态值写入 Story author-confirmation 事件，按项目、类型、字段键和模板版本重验，沿用逐字段来源与现有三视角过滤。自由字段保留；模型输出不会升级为作者确认。
- 地图声明使用 `map_declaration.effective_status`。World helper 只接受当前作品 adopted node 的 current saved revision 与精确声明 kind/FeatureKey、有效期和 canonical 端点；锁定 node 行直到同一事务的 Story 事件写入，防止并发保存替换已校验版本。Story 保存原项目、node、revision、kind、FeatureKey 的 typed identity。
- Story 投影键是 project-scoped UUID5，输入为规范化 UUID namespace 加无歧义 canonical JSON，包含 node、kind、FeatureKey 和 contract 版本；它只是 Story 投影键，不是 World `CoreEntity`。读端要求 exact project/node/current revision/kind/ID/field、author-confirmed、Scene view 身份及 cutoff 一致，Scene 观察严格早于 cutoff。历史无 identity、删改或 revision 替换、未来观察、来源无效、降级投影均 fail closed 并留 gap；不根据位置、相似文本或同值对齐。
- 地图作者入口只为有有效期且 `event_observed` 的选中声明开放，并要求已采用节点的当前 saved revision。提交只写 Story；显式调用既有 Scene checkpoint ensure。409/保存失败保留按 project/node/revision/kind/声明/Scene 隔离的状态草稿与幂等键；Story 已写而 projection 失败时重试只更新投影。reader、character 与 `author_safe` 不读取或暴露地图状态，character/reader 继续遵循既有知识/揭示边界。
- 势力阶段账本尚未上线，仍披露 unavailable/gap，绝不从旧字段回退。无数据库列或 migration 变更。

## 共享接线清单

Sol 需将真实 World facade callable 注册为 DI 键 `world.require_map_declaration_state`，签名为 `require_map_declaration_state(db, novel_id, *, node_id, revision_id, declaration_kind, declaration_id)`，并注册 `story.map_declaration_state.confirm`（`POST /api/novels/{novel_id}/memories/map-declaration-state`，R2、`confirmed=true`、v1 请求字段已写入 `OPERATIONS-SPEC-C0C.md`）。另需把已实现的 `world.object_validity` 注册为 NoticeSource，复核/保留/静默复用 `assistant.notice.set_disposition`。既有 typed DI `world.read_map_spatial_brief` 不增新键；`author_full` 增加状态冲突/缺口，其他视角沿作者有效期读取。

操作目录、服务键常量、bootstrap/assistant operation registry、真实路由棘轮和目录冻结由 Sol 集中组合；本分支没有手改共享槽或弱化注册门禁。所有精确 op/DI/HTTP/版本与冻结要求见 `.agent/tasks/2026/T-20261015-character-world-progression/artifacts/OPERATIONS-SPEC-C0C.md`。

迁移祖先建议：首检查点的两条迁移保持 `20261015_operation_trace_v2 → 20261016_relation_validity → 20261016_dossier_story_field_key` 链；第二地图提交无 DDL。组合时保留该祖先关系，不为 map 状态另开或压平迁移；当前单 head 是 `20261016_dossier_story_field_key`。

## 验证与未覆盖

- 第一提交离线回归：后端 93 passed；前端 121 passed（7 files）；Vite production build、目标 Ruff、Alembic 单 head 和 docs-check 通过。
- 第二提交：地图作者组件 Vitest 10 passed；改动文件 ESLint 通过；Vite production build 与 production-reference 验证通过；后端目标 Ruff check、format check、compileall、`git diff --check` 通过；`make docs-check` 通过。基于 `origin/main` 的文档影响检查需 review `CLAUDE.md`；该文件仅导入 `AGENTS.md`，使用脚本支持的 `--no-change-reason` 后检查通过。
- 第二提交 backend pytest 尚未收集：新增 route 的 `x-novelcraft-operation-id=story.map_declaration_state.confirm` 触发全局 `app.main` 硬门禁，报 `HTTP route references unknown assistant operation`。没有绕过注册、改 app/bootstrap 或抬高冻结基线；Sol 接线后需重跑真实测试。
- 尚未获得 PG 65202 新专库授权；未运行 PostgreSQL/API集成、真实数据库升级、app lifespan/drain、真实模型或真实稿件。没有 390/1280 实浏览器验收或作者接受；组件响应式与键盘行为需要在共享组合后的浏览器路径补验。

## 可执行下一步

Sol 对 `371ab21d4` 做独立审修并直接修复发现的问题，然后按 SPEC 完成共享接线；由 root 组合两检查点、分配专库并运行被硬门禁挡住的后端回归/API验证，随后补 390/1280 与键盘/重读浏览器验收。不得因本记录或离线组件测试通过而宣称整个 C0c 或三份计划完成。

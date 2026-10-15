# C0c 实现检查点交接

核实时间：2026-10-16。状态：第一检查点已实现并通过离线验证，等待本地提交与 Sol 独立审修；地图 typed Story 声明观察按 root 明确要求在下一独立提交继续完成。本记录不代表整项 C0c 或三份计划已完成。

## 已实现切片

- 项目设置 `world_object_dossier_v1` 默认关闭，版本 CAS 更新；仅影响截止点读取，不重写 World/Story 历史。
- 档案条目可选绑定同对象已登记 Story 字段；覆盖只认精确对象/字段、可信确认来源及 cutoff Scene 之前观察。作者区间内的冲突统一进入只读 `world.object_validity` NoticeSource；GET 只走 Story state view，不 ensure / rebuild checkpoint。
- 关系保存作者有效期；Story 状态按稳定 `EntityRelation.id` 和 `relation_status` 来源精确核对，端点/类型不充当身份。原 RelationAttitude 模型未重做；真实关系建立/结束事件进入字段来源投影，结束事实保留在只读观察面。
- 别名稳定 Scene/章节区间贯穿新增、编辑、移动、批量复核、类型转换和历史恢复；旧无区间别名维持来源/状态语义。历史对比现在显示区间变化。别名不会授权角色知道真实身份。
- World 模板可声明自定义文字状态字段，值仅写入 Story author-confirmation 事件；项目、类型、字段键与版本重验，继续复用三视角过滤与逐字段来源。自定义自由字段继续保留；模型输出不被标为作者确认。
- 项目设置、World 档案/关系/别名、Story 状态已有作者界面和草稿/并发/异步上下文保护。具体操作注册、NoticeSource 组合根和共享 DI 由 Sol 按 `OPERATIONS-SPEC-C0C.md` 接线。
- 地图当前保持 fail-closed：缺同一结构声明 Story 身份契约时只返回 gap；不从位置、相似值或偶然 ID 推断。Root 已授权在下一提交实现最小 typed map-declaration observation 接口；历史无契约记录仍是 gap。
- 势力阶段账本仍不可用，不从旧字段回退。

## 关键边界与下一步

地图结构项 ID 是任意稳定 `FeatureKey` 字符串；Story 事件 `entity_id` 是 UUID。下一提交将由 World helper 校验本项目 adopted node、当前 saved revision、声明 kind/ID 与 Scene，再返回由无歧义规范序列化确定的 project-scoped synthetic UUID 作为 Story 投影键。元数据同时留原 FeatureKey、node、kind、revision。该 UUID 仅是 Story 投影键，不是或不冒充 CoreEntity。读写均验证同一 novel 和当前声明版本；删除、替换、旧 revision、未来 cutoff、跨项目及角色/读者泄露必须失败关闭。GET 不写事件。

第一检查点后，可执行下一步：提交当前对象/关系/别名/自定义文字状态与界面代码；然后开始地图 observation 的第二提交，更新操作纯 SPEC 和 typed tests。

## 已验证

- 后端定向离线回归：93 passed，包括设置 CAS、别名、对象档案、精确有效期观察、地图 gap、Story typed registry/reducer、Evidence dossier viewpoint。
- 前端定向组件回归：121 passed（7 files），覆盖项目设置、别名/关系、档案编辑器、写作档案视图与别名历史。
- Vue 生产构建通过（Vite bundle 与 production references 验证）；Ruff 目标文件检查及格式检查通过；Alembic 为单 head `20261016_dossier_story_field_key`。
- `make docs-check` 通过。基于 `origin/main` 的影响检查通过：Project README 与模块文档已更新；CLAUDE.md 只是 AGENTS.md 导入器，使用脚本支持的 `--no-change-reason` 明确说明不另维护重复架构规则。
- 不连 PostgreSQL、真实稿件或真实模型；PG 65202 尚未分配。没有做生产/作者验收、390/1280 浏览器截图、数据库升级执行或 app lifespan/lifecycle drain 验证。
- 操作注册仍未完成：请按 `OPERATIONS-SPEC-C0C.md` 由 Sol 处理服务键、应用组合根、assistant operation registry、真实路由棘轮和目录冻结。

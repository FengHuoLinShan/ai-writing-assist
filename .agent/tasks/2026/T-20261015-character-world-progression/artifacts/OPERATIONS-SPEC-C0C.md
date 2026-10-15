# C0c 操作目录组合规格

本文只记录 Luna 分支已经实现或本批准备交 Sol 组合的真实 API / facade 操作；不替代
`assistant_operation_registry`、路由棘轮、冻结清单或组合根。Sol 组合前应逐项核对实际
路径、schema 与本地固定提交，不得据此注册尚不存在的服务。

## 已实现操作

| op_id | HTTP / 路径 | 风险与确认 | 版本 / 冻结 |
| --- | --- | --- | --- |
| `project.object_validity_settings.read` | `GET /api/projects/{project_id}/object-dossier-settings` | R0，只读；项目 owner 与 `novel_id` 仍由项目门禁校验 | v1；无历史冻结变更 |
| `project.object_validity_settings.edit` | `PUT /api/projects/{project_id}/object-dossier-settings` | R2，作者明确切换；`expected_version` CAS，旧值冲突返回 409 | v1；新增 op，冻结请求字段 `expected_version, allow_story_override` |
| `story.custom_text_state.confirm` | `POST /api/novels/{novel_id}/memories/custom-text-state` | R2，显式作者确认；`expected_template_version_number`、项目/Scene/实体/模板字段重验，幂等键；事件只写 Story | v1；新增 op，冻结请求字段 `scene_id, entity_id, field_key, value, expected_template_version_number, idempotency_key, confirmed` |
| `story.map_declaration_state.confirm` | `POST /api/novels/{novel_id}/memories/map-declaration-state` | R2，`confirmed=true`；World 重验 adopted node/current saved revision/声明 kind+FeatureKey/有效期/canonical 端点，Story 重验本项目 Scene；幂等事件只写 Story | v1；新增 op，冻结请求字段 `scene_id, node_id, revision_id, declaration_kind, declaration_id, status, idempotency_key, confirmed`，固定字段 `effective_status` |
| `world.dossier.read` | `GET /api/world/entities/{entity_id}/dossier` | R0，只读；不物化 continuity，不写档案 | 响应新增有效期政策与逐项状态/gap，建议 op schema v2；保留 v1 冻结 |
| `world.dossier.entry.create` | `POST /api/world/entities/{entity_id}/dossier/entries` | R2，作者保存档案；检验 Story 对齐字段和稳定 Scene 锚 | 请求新增可选 `story_field_key`，op v2；保留 v1 冻结 |
| `world.dossier.entry.edit` | `PATCH /api/world/entities/{entity_id}/dossier/entries/{revision_id}` | R2，作者保存档案修订；expected revision CAS | 请求新增可选 `story_field_key`，op v2；保留 v1 冻结 |
| `world.dossier.template.read` | `GET /api/world/dossier-templates/{profile_type}` | R0，只读 World 模板 | 响应增加自定义状态字段定义，建议 op schema v2；保留 v1 冻结 |
| `world.dossier.template.edit` | `PUT /api/world/dossier-templates/{profile_type}` | R2，作者确认并保存模板修订；CAS revision | 请求增加 `state_fields`，op v3；保留 v1、v2 冻结 |
| `world.relations.read` | `GET /api/world/relations?as_of_scene_id=...` | R0，只读 World 作者关系 + Story read projection；不物化或写入 | 新 op v1；冻结 query 字段与结果 `validity_status, story_status, validity_gap` |
| `assistant.notice.set_disposition` | `PATCH /api/assistant/notices/{notice_id}/disposition` | R2，作者复核 / 保留 / 静默；由现有统一提醒实现 | v1 不改参数；仅将 `world.object_validity` source 注册到 NoticeSource 组合根 |

## 组合根接线与依赖

- Story 自定义文字状态通过 DI port `world.require_custom_text_state_field` 重验 World 模板、
  项目、类型、字段键和模板版本。Story 只追加 author-confirmation 事件；其后续 checkpoint
  仍只由已有显式 `story.scene.checkpoints.ensure` POST 构建，GET 不调用 ensure。
- Story 地图状态通过 DI port `world.require_map_declaration_state` 重验项目、节点、当前
  revision 和原始声明身份；Story 保存 typed `map_declaration.effective_status`，来源元数据
  同时保留项目、node、revision、kind 和原始 FeatureKey。World 读取还要求 exact identity_ref
  与截止 Scene；地图 revision 更新后需要作者对新 revision 再确认。
  Port 签名为 `require_map_declaration_state(db, novel_id, *, node_id, revision_id,
  declaration_kind, declaration_id) -> {novel_id, node_id, revision_id, declaration_kind,
  declaration_id, field_key, subject_id, label}`；World facade 已暴露该 helper，但应用组合根需将
  精确服务键 `world.require_map_declaration_state` 注册到该 facade callable。World 写 helper 对 node
  行加锁，和地图保存共享同一锁，避免验证 current revision 后并发替换。
- `world.object_validity` 是只读 `NoticeSource`，由应用组合根注册；来源包括档案条目、关系、
  地图结构化有效期的 conflict/gap。复核复用 `assistant.notice.set_disposition`，没有新增
  notice 写操作。
- Scene-state view 为既有纯读入口；World/Dossier/Relation/Map GET 只读该入口，不调用
  Story checkpoint ensure/rebuild。
- 势力阶段账本尚未在本批注册，因此势力时间态返回明确 unavailable/gap；不得从旧字段回退。

## 既有读取端口的行为变化

- 既有 typed DI `world.read_map_spatial_brief` 保持原请求/响应 schema 与 R0 风险等级；`author_full` 新增基于
  当前 saved revision 的地图有效期冲突/缺口回执，并只在项目开关显式开启时允许可信 Story 状态覆盖。
  `reader`、`character` 和 `author_safe` 继续按作者地图区间过滤，不读取或暴露 map-declaration Story 状态。
  端口仅调用既有纯读 Scene state view，不 ensure/rebuild checkpoint、不写事件或地图。
- Project 设置由已有对象设置 UI 管理；Story 地图状态使用新 HTTP op `story.map_declaration_state.confirm`，
  完成后客户端单独调用既有 `story.scene.checkpoints.ensure`。没有新的数据库迁移。

## 明确未包含

`world.object_validity` 的 DI/NoticeSource 实际组合、助手工具/核心操作注册、路由棘轮基线和
目录冻结由 Sol 在共享组合分支处理。此文件不是合并授权。旧地图状态事件没有 typed
map-declaration identity、与当前 revision 不一致或不早于 cutoff 时继续披露 gap；不会回写或推断历史观察。

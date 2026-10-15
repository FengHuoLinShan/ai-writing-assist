# C0c 操作目录组合规格

本文只记录 Luna 分支已经实现或本批准备交 Sol 组合的真实 API / facade 操作；不替代
`assistant_operation_registry`、路由棘轮、冻结清单或组合根。Sol 组合前应逐项核对实际
路径、schema 与本地固定提交，不得据此注册尚不存在的服务。

## 已实现操作

| op_id | HTTP / 路径 | 风险与确认 | 版本 / 冻结 |
| --- | --- | --- | --- |
| `project.object_validity_settings.read` | `GET /api/projects/{project_id}/object-dossier-settings` | R0，只读；项目 owner 与 `novel_id` 仍由项目门禁校验 | v1；无历史冻结变更 |
| `project.object_validity_settings.edit` | `PUT /api/projects/{project_id}/object-dossier-settings` | R2，作者明确切换；`expected_version` CAS，旧值冲突返回 409 | v1；新增 op，冻结请求字段 `expected_version, allow_story_override` |
| `story.custom_text_state.confirm` | `POST /api/novels/{novel_id}/memories/custom-text-state` | R2，显式作者确认；`expected_template_version_number`、项目/Scene/实体/模板字段重验，幂等键；事件只写 Story | v1；新增 op，冻结请求字段 `scene_id, entity_id, field_key, value, expected_template_version_number, idempotency_key` |
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
- `world.object_validity` 是只读 `NoticeSource`，由应用组合根注册；来源包括档案条目、关系、
  地图结构化有效期的 conflict/gap。复核复用 `assistant.notice.set_disposition`，没有新增
  notice 写操作。
- Scene-state view 为既有纯读入口；World/Dossier/Relation/Map GET 只读该入口，不调用
  Story checkpoint ensure/rebuild。
- 势力阶段账本尚未在本批注册，因此势力时间态返回明确 unavailable/gap；不得从旧字段回退。

## 明确未包含

`world.object_validity` 的 DI/NoticeSource 实际组合、助手工具/核心操作注册、路由棘轮基线和
目录冻结由 Sol 在共享组合分支处理。此文件不是合并授权。地图当前仅披露缺少同身份 Story
观察的 gap；后续 typed map-declaration contract 若被实现，必须单独更新本规格和版本冻结，不得
回写或推断历史观察。

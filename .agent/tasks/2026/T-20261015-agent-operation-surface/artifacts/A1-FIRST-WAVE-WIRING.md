# A1 首批领域插件与路由接线

本文记录 A1 第一波插件及 Sol 组合接线。15 项已进入 Assistant v8 新运行目录，旧 v1–v7
冻结清单不自动扩权；对应 HTTP 操作标签和窄入口已接通。产品范围仍以操作入口计划、ADR-0038
与 `A1-A2-HANDOFF.md` 为准，后续 A1/A2/A3/A4 未因此完成。

## 本地插件

本批新增 15 条 v2 `OPERATIONS_SPEC`，每条都显式声明 `op_version`、风险、费用、可撤销性、前置条件、产出、目标类型、事务形态和 schema-safe 留痕字段：

| 模块 | 新目录项 | 事务与范围 |
|---|---|---|
| World | `world.entity.transition_type` | 通过 `WorldEntityService.update` 与 `EntityTypeTransitionService`；单事务、CAS。 |
| World | `world.entity.fuse` | 仅融合作者明确选择的一组不重叠对象；调用 caller-transactional `WorldEntityFusionService.apply`；R3，返回实际受影响对象 ID 和汇总，不伪造回执 ID，也不把建议生成任务的内部提交误算到此路径。 |
| World | `world.history.set_note` | 复用 `load_revision_notes` / `set_revision_note`；不删除或改写修订。 |
| World | `world.entity.restore_revision` | 复用 `WorldEntityService.rollback_to_revision`；执行前重验最新对象基线。 |
| Story | `story.scene.reorder` | 完整 Scene 集合校验、锁定并调用 `SceneWorkbenchService.reorder_scenes`；内容/顺序指纹阻止 stale apply。 |
| Story | `story.scene.merge` | 复用 Scene workbench 预览和确认合并；R3。 |
| Story | `story.scene.split` | 复用 Scene workbench 预览和确认拆分；预览规范化仅移除服务每次重算都重新生成、非作者可见的 `adopted_at` 时间戳，保留其余影响字段做 CAS；R3。 |
| Writing | `writing.chapter.rename` | 对当前最新工作稿调用 checkpoint 服务，仅改标题并保留正文版本。 |
| Writing | `writing.chapter.mark_editorial_ready` | 复用正式服务并绑定正文 hash；不等于发布或知识边界签署。 |
| Writing | `writing.comment.set_status` | 锁批注并确认其仍锚定当前正文版本，再调用原状态服务。 |
| Writing | `writing.conflict_check.create` | 只基于当前最新草稿/hash 创建确定性报告，不接收任意正文，不启动模型任务。 |
| Evidence | `evidence.project.search` | R0；作者当前可见范围检索。已有原 confirmation 时只回传那份确认资料，不扩大检索。 |
| Evidence | `evidence.source.read` | R0；精确回读来源，复核 owner、novel、当前 cutoff；有原 confirmation 时来源必须在 selected 范围且不在 excluded/omitted 中。 |
| Evidence | `evidence.knowledge.preview_scope` | R0；经 Evidence inspection、owner、novel、排除与可见截止校验，仅预览。 |
| Evolution | `evolution.prepare_reading` | 复用 `workflow.preview_reading` 覆盖 bootstrap/append/continue/revise/scoped_recompute；apply 只返回其授权预览，不启动任务或模型调用。 |

仍复用而不重复注册：`story.edit_information_plan` 已能修改伏笔的 seed/reinforce/payoff 章节以及揭示阶段 `chapter_index`，覆盖伏笔/揭示**计划时间线**；`evolution.prepare_spatial_reading` 与 `evolution.prepare_spatial_rescan` 保持原入口。本批没有新增 Alembic 表或 service key；旧 v1–v7 快照与黄金指纹保留，新作者运行改为 v8。

## 已完成组合接线

- `app/assistant_operation_registry.py` 与 `app/bootstrap.py` 物化全部 15 项，总目录从 74 增至 89。
  `modules/assistant/service.py` 新运行使用 v8 全 schema/metadata 快照；teams、恢复与读工具按 v8
  传播，旧版本从各自冻结清单解析，新增项不进入旧运行。
- 同语义的现有 World 融合/历史备注/恢复、Story 排序/合并、Writing 编辑准备/批注、Evolution
  阅读预览路由标注操作 ID 与逐字段留痕映射。Evolution 路由只记 `previewed`，不会产生作者
  已授权启动的假事件；融合/合并的 `confirmed=false` 不记成作者已确认。
- `modules/assistant/operation_api.py` 增加类型迁移、Scene 窄拆分、章节改名、当前草稿冲突检查的
  作者预览与相同指纹确认入口，并加 Evidence 的三个 R0 窄读入口。宽体对象编辑、正文
  checkpoint、任意正文冲突检查和 Evidence 原宽路由不冒充窄操作。R0 不走 apply。
- `app/main.py` 的 HTTP 留痕从明确映射的 Pydantic 字段提取摘要；不会将 body 中的正文、
  owner、visibility、原始 Request 或未声明字段原值写入 trace。新入口受当前 owner/未回收
  项目预门禁，最终 commit 成功才留下同事务 `executed`。新路由逐项登记，没有扩大旧未绑定
  路由 baseline。
- 原 confirmation 仅选定对象/草稿的部分字段或来源范围时，`evidence.knowledge.preview_scope`
  拒绝整目标投影，防止 selected 资产 ID 被当作所有内容的授权；精确 `evidence.source.read`
  仍按所选范围、excluded 和 omitted 逐项核对。无原确认的作者只读范围保持原样。

Sol 接线时的代码组合点：

1. 在 `backend/app/assistant_operation_registry.py` 导入并 `_materialize` 四个新模块的 specs（World/Story/Writing/Evidence）；Evolution 的 `assistant_tools.OPERATIONS_SPEC` 已被 `_EVOLUTION` 导入，新增项随现有 `evolution_operations` 一起物化。Story information plan 已由 `_STORY_INFORMATION` 物化，不重复合并。
2. 在 `backend/app/bootstrap.py` 的 `ASSISTANT_OPERATIONS` 字典并入上述物化结果，键保持 operation ID 唯一；无须新增 service key。
3. 路由实际绑定使用各 API handler 上的 `openapi_extra`：`x-novelcraft-operation-id` 与需要时的参数映射。回归检查是 `backend/tests/unit/test_assistant_operation_route_ratchet.py`；只允许减少 `backend/tests/fixtures/assistant_operation_unbound_write_routes.json` 里的旧缺口，新路由不得扩 baseline。
4. 当前 `/api/evidence/compilation/evidence/*` handler 的 body 参数名为 `request`，`backend/app/main.py::_trace_route_arguments` 会跳过 `request`，route argument map 不能覆盖这条跳过逻辑。Sol 接线时须为这些读取路由添加窄的 body-to-operation trace 提取，且只取目录 schema 的字段，绝不记录原始 request 或正文。
5. v1–v7 冻结内容不能追加本批目录项。下一目录版本由 Sol 决定；需检查 `backend/modules/assistant/operations.py` 的 `runtime_protocol/resolve_operations`、`backend/modules/assistant/service.py` 的新运行快照，以及目标运行 `teams/runner.py` / `teams/plans.py` 的版本分派。旧运行目录变化时继续 fail closed。

## 原始路由建议与实际收口

下表保留插件提交时的原始映射建议。类型转换、Scene 拆分、章节改名、冲突检查和三条 Evidence
读操作现在走上述新窄入口；表内旧宽路由仍保留原作者工作台用途，不作为这些新操作绑定。

| 操作 | 现有路由 | 接线要求 |
|---|---|---|
| `world.entity.transition_type` | `PUT /api/world/entities/{entity_id}` | 此路由还允许普通对象字段编辑，不能把整条宽路由直接认作类型转换。若要覆盖，新增窄类型迁移入口并复用 `WorldEntityService.update`；或仅在确认 body 只含 `entity_type` 时由适配层走窄 schema。 |
| `world.entity.fuse` | `POST /api/world/entities/fusion-suggestions/apply` | 映射 `suggestions`；作品 ID 来自已验证的请求/操作上下文；R3 author confirmation 映射领域服务 `confirmed=True`，不能信任模型自行填写确认位。 |
| `world.history.set_note` | `PUT /api/world/revision-notes` | 仅映射 `target_kind/revision_id/note`，`novel_id` 从路由范围注入。 |
| `world.entity.restore_revision` | `POST /api/world/entities/{entity_id}/rollback-by-revision` | 映射 path `entity_id` 与 `revision_id`；UI 的 `expected_updated_at` 仍须保留 CAS 语义，operation 侧使用预览冻结的基线。 |
| `story.edit_information_plan` | `PATCH /api/outline/foreshadowing/{plan_id}`；`PATCH /api/outline/reveals/{plan_id}` | 两条路由复用同一个 `kind/plan_id/changes` 目录项。时间线范围仅为伏笔计划章节字段与揭示阶段章节字段，不代表可编辑任意事实事件时间线。 |
| `story.scene.reorder` | `POST /api/outline/scenes/reorder` | 同步校验需确保 ID 是本作品完整有效 Scene 集合；目录回调额外做范围与锁定基线校验。 |
| `story.scene.merge` | `POST /api/outline/scene-workbench/merge` | R3。映射 `target_scene_id/source_scene_ids`；不要让 API `confirmed` 字段替代目录的作者确认。 |
| `story.scene.split` | `POST /api/outline/scene-workbench/split` | R3。映射窄拆分 schema；拒绝模型提供任意 `draft_scenes`，保留服务自身预览和章节/正文区间检查。 |
| `writing.chapter.rename` | `POST /api/writing/drafts/{draft_id}/checkpoint` | 现有 checkpoint body 允许编辑正文；路由适配必须从当前版本读取正文并只应用标题，保留该路由原有 CAS。直接转发宽 body 会扩大写入能力。 |
| `writing.chapter.mark_editorial_ready` | `POST /api/writing/drafts/{draft_id}/editorial-ready` | 映射 path `draft_id` 和 `expected_content_hash`，作品 ID 从已验证请求上下文注入。 |
| `writing.comment.set_status` | `PATCH /api/writing/comments/{comment_id}` | 映射 path ID 和 `status`，作品 ID 由当前项目上下文提供；两侧都调用 `set_comment_status`。 |
| `writing.conflict_check.create` | `POST /api/writing/conflict-checks` | 现有请求允许任意 `content`。目录路由只能接收 draft ID/hash/可选 Scene，加载当前草稿后调用同一 `WritingConflictCheckService`；不可传入任意正文。 |
| `evidence.project.search` | `POST /api/evidence/compilation/evidence/search` | 现有请求允许 caller 指定 novel/visibility/pending 等宽字段。操作入口应丢弃这些字段并从已验证 owner 与 WorkContext 派生范围，只接受 query/scopes；不要直接绑定整个 `request`。 |
| `evidence.source.read` | `POST /api/evidence/compilation/evidence/read` | 仅接受精确 source_ref；从 owner/WorkContext 推导 visibility，固定 `before=after=0`、关闭 parent expansion；原 confirmation 时再查 selected/excluded/omitted。 |
| `evidence.knowledge.preview_scope` | `POST /api/evidence/compilation/evidence/inspect` | 仅映射 target ref；从 owner/WorkContext 派生 visibility，不接受调用方扩大范围。 |
| `evolution.prepare_reading` | `POST /api/evolution/reading/preview` | 请求 schema 是 `workflow.ReadingRequest` 子类；必须只调用 preview。现有 spatial 专项仍映射 `POST /api/evolution/reading/preview` 和 `POST /api/evolution/reading/{run_key}/spatial-rescan-preview`。 |

Evidence API handler 参数名为 `request`，而当前 HTTP trace 通用提取会忽略 `request` 对象；route adapter 需从已验证 operation schema 明确构造 trace arguments，不能把含正文、任意可见性或调用方 owner 字段的原始 request 写入操作留痕。

## 明确未覆盖

- Writing 章节重排：当前没有能够安全重排章节、同步 Scene/来源索引并维持引用有效性的稳定领域服务。本批不直接改 `chapter_index` 或 ORM；需另一个领域切片，并在其服务、来源/Scene 关联、CAS 和回滚语义明确后接入。
- 一般事实时间线编辑：现有 `GET /api/novels/{novel_id}/memories/events/{entity_id}/timeline` 只读；continuity 的已确认事件 facade 当前是内部入口，没有作者侧公开写路由/操作。本批仅复用伏笔/揭示**计划时间字段**，不把 Scene 排序当作事实时间线。
- 本文记录的是首批 15 项目录与 HTTP 接线，不包含未来 A1 章节重排或一般事实时间线服务。
- A1 后续模块、A2 目标运行、A3 Interaction/Collaboration/地图与势力、A4 留痕报表均未由本提交完成。完整 A1 也不能仅凭本首批闭合项宣称完成。

## 离线行为验证

从 `backend/` 执行：

```bash
DATABASE_URL=postgresql+asyncpg://unit@127.0.0.1:1/operation_trace_unit_test \
  /Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/.venv/bin/python \
  -m pytest tests/unit/test_a1_operation_specs.py tests/unit/test_a1_operation_behaviors.py -q
```

行为测试使用工程 SQLite 单测 fixture，不连接 PostgreSQL、启动 app lifespan、调用模型或启动 worker。

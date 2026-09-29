# 世界对象管理用户路径设计

## 背景
网络小说作者需要在 `worldView` 中维护人物、地点、势力、物品、概念、事件、别名、关系和人物知识边界。自动入库的对象必须可手动编辑、合并、回滚。

## 当前状态
后端 `modules/world` 已具备：
- `CoreEntity` CRUD、`entity_type`/`status` 过滤、`skip`/`limit` 分页。
- 别名内联存储在 `core_entities.content_json.aliases`，支持增删。
- `EntityRelation` CRUD、去重 `upsert`、自环清理、关系迁移。
- `EntityDedupService.merge_candidate_into_entity` 事务合并（别名继承、关系迁移、自环清理、文本字段合并、冲突归档、候选标 `merged`、目标标 `canonical`）。
- `EntityRevisionService.rollback_to_scene_index` 优先从 `text_archive` 恢复，否则回退到 `entity_revisions`，并写入 `rollback` 归档。
- `CharacterKnowledge` 支持 `unknown/rumor/partial/full/false_belief/restricted/misunderstood`，schema 要求 `false_belief`/`misunderstood` 必须提供 `misconception`。

前端 `worldView.js` 已具备：对象库表格、创建/编辑/删除/合并/回滚/知识边界弹窗、关系/别名子标签、自动入库分组+“新”标记。

## 缺口
1. **后端列表搜索**：`GET /api/world/entities` 缺少按名称/别名搜索参数 `q`。
2. **手动创建标记**：手动创建实体时未设置 `created_by=manual`。
3. **关系创建校验**：`POST /api/world/relations` 未显式校验 `source_id != target_id`、双方存在且属同一 `novel_id`、同 `source/target/type` 不重复。
4. **前端分页与过滤**：对象库未传递 `skip/limit`，无分页控件；无 `entity_type`/`status` 过滤 UI；无搜索框。
5. **前端选择器 UX**：关系、别名、知识边界弹窗仍要求用户手动填写对象 ID，应改为下拉选择。
6. **测试覆盖**：需要补充后端对搜索/过滤/别名/关系校验/合并/回滚/知识边界的单测，以及前端 E2E 对空态/创建/编辑/删除/关系/别名/合并/回滚/知识弹窗的覆盖。

## 设计决策
1. **搜索实现**：在 `CoreEntityRepository.get_by_novel` 增加 `q` 参数，使用 `search_text` 生成列的 `ILIKE`（SQLite 回退）或 `pg_trgm similarity`（PostgreSQL）过滤；API 透传 `q`。
2. **手动创建**：在 `WorldEntityService.create` 中，若请求未提供 `created_by`，默认设为 `"manual"`；AI 导入路径使用 `repo.create_raw`，不受影响。
3. **关系校验**：在 `EntityRelationService.create` 中覆盖基类方法，先校验端点有效性与重复，再写入；保持 `upsert` 接口不变。
4. **前端分页**：对象库请求默认 `skip=0&limit=20`，渲染上一页/下一页/页码信息；过滤/搜索变化时重置到第 1 页。
5. **下拉选择**：关系创建弹窗从当前 `_entities` 渲染源/目标 `<select>`；别名创建弹窗渲染实体 `<select>`；知识边界弹窗渲染目标实体 `<select>`。
6. **危险操作确认**：保留现有 `confirmAction` 二次确认，合并/删除/回滚弹窗本身即确认入口。

## 验收标准
- 后端单测覆盖：实体 CRUD、搜索+过滤、别名增删、关系自环/重复/跨 novel 拒绝、合并事务、回滚、人物知识边界。
- 前端 E2E 覆盖：对象库空态、创建/编辑/删除、关系子标签、别名子标签、合并、回滚、知识弹窗。
- `make lint` 通过；后端 `make test` 通过；E2E 在 `make dev` 环境下可运行通过。

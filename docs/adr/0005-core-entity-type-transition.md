# ADR-0005 — CoreEntity 自定义类型与可逆 Profile 迁移

- **状态**: Accepted
- **日期**: 2026-07-14

## 背景

`core_entities.entity_type` 的数据库与 wire 契约一直是字符串，但请求 schema 把作者输入
限制在 AI 系统白名单内。作者因此无法在新建、编辑后采用或已采用对象编辑时表达项目特有
分类。直接放宽校验又会让 AI 创建未定义类型，并使 strong/generic Profile、地图和人物等
专属能力失去唯一真相。

## 决策

### 1. 作者类型与 AI 类型使用不同边界

- AI 抽取和建议创建只接受固定系统目录；深度导入与生成中心在进入作者宽松 schema 前也
  必须完成系统类型校验。
- 作者 create、update、promote 和 suggestion edit-confirm 接受系统别名或安全的 1–64 字符
  自定义值。英文字符小写化，拒绝空值、控制字符和内部 sentinel。
- 自定义名称同时是分类键和显示名；本期不提供重命名、合并、归档或独立 label。
- `GET /api/world/entity-types` 返回固定系统目录和当前项目所有状态对象使用过的自定义类型。

### 2. 类型转换由 world 内部单一服务编排

已有对象的 update、编辑后 promote、建议影子同步和 EntityRevision 回滚全部委托
`EntityTypeTransitionService`。服务在调用方事务内锁定 CoreEntity 与 Profile；门禁、迁移、
实体更新、revision 和失效标记任一步失败都回滚。类型未变化时不迁移。

### 3. migrated row 可共存，但活跃 Profile 只能有一个

strong Profile 与 `GenericEntityProfile` 可以为了历史恢复同时保留；只有一个 row 可处于非
`migrated` 状态。发现两个活跃 Profile 时返回 `profile_state_conflict`，不猜测覆盖顺序。

通用 Profile 的 `extra_json._type_migration_v1` 是版本化内部持久化契约：

```json
{
  "snapshots": {
    "location": {
      "profile_kind": "strong",
      "status": "canonical",
      "source": "manual",
      "confidence": null,
      "evidence_refs_json": [],
      "data": {},
      "extra_json": {}
    }
  },
  "history": [
    {
      "from_type": "location",
      "to_type": "宗教/神祇",
      "changed_at": "2026-07-14T00:00:00+00:00",
      "changed_by": "manual"
    }
  ]
}
```

离开当前类型前保存公共元数据、专属数据和扩展字段；进入旧类型优先恢复 snapshot。首次从
generic 进入 strong 只映射目标 binding 字段，其余保存在 `extra_json.unmapped_generic`。
旧 row 标记 `migrated` 而不删除，因此 strong↔generic、strong↔strong 和 generic↔generic
都可逆且不会重复创建 Profile。

### 4. 硬依赖阻止转换，不自动清理

转换前只检查代码明确要求旧类型的项目内依赖，包括人物/事件扩展、人物知识、事件地点与
因果引用、地图 location/marker/territory 绑定、species worldbuilding 引用，以及指向活跃
Profile 的 World Bible、知识策略、冲突/建议和其他 Profile TargetRef。普通实体关系、别名、
无类型要求的实体 ID 引用和不可变历史 revision 不阻止转换。

阻止时返回 `entity_type_change_blocked` HTTP 409，context 只包含原/目标类型及 blocker 类别和
数量，不返回内部 ID。共享 `DomainError.context` 仅在非空时进入响应，旧错误 wire 保持不变。

## 影响

- 不新增表、Alembic migration、依赖、基础设施或跨模块 facade。
- 成功转换写原有 EntityRevision，并使 context/synopsis 相关派生结果失效。
- 自定义类型使用 Generic Profile，不自动获得地图、人物或事件能力。
- AI 不读取项目自定义类型，Prompt 模板保持不变。

## 备选方案

### A. 只允许新建时自定义

拒绝。采用前后类型语义会不一致，且无法修正已采用对象。

### B. 类型变化时删除或归档专属依赖

拒绝。自动清理会造成作者数据丢失，且无法可靠恢复。

### C. 给自定义类型新增模板表或动态 Prompt

延期。当前需求只需要真实分类和通用 Profile；模板管理会扩大数据模型和 AI 权限边界。

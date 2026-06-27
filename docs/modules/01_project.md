# Module: project / 小说项目模块

## 定位

project 模块是系统的根聚合。所有其他模块通过 novel_id 关联到项目。

## 数据表

- `projects` — id / title / genre / tone / language / target_length / current_stage / default_reveal_policy / settings / deleted_at

### settings 字段

JSONB 配置字段，存储项目级可调参数，如 `temporary_entity_expiry_chapters` 等。

### deleted_at 字段

软删除标记。`DELETE` 接口仅设置 `deleted_at`，数据不动。回收站 API 可列出/恢复/永久删除已软删除的项目。

## 回收站流程

```
用户点击"删除项目" → 标记 deleted_at（软删除）
    ↓
回收站中列出已删除项目
    ↓
恢复 → 清空 deleted_at
永久删除 → 级联 DELETE 所有 novel_id 关联行
```

## 服务

- ProjectService：项目 CRUD + 软删除/恢复/永久删除

## Facade

```python
async def get_project_context(db, novel_id) -> ProjectContext | None
```

## API

```
POST   /api/projects                          # 创建项目
GET    /api/projects                           # 项目列表
GET    /api/projects/{id}                      # 项目详情
PUT    /api/projects/{id}                      # 更新项目
DELETE /api/projects/{id}                      # 软删除（移至回收站）
GET    /api/projects/recycle-bin               # 回收站列表
POST   /api/projects/{id}/restore              # 恢复项目
DELETE /api/projects/{id}/permanent            # 永久删除（级联）
```

# Module: project / 小说项目模块

## 定位

project 模块是系统的根聚合。所有其他模块通过 novel_id 关联到项目。

## 数据表

- `projects` — id / title / genre / tone / language / target_length / current_stage / default_reveal_policy

## 服务

- ProjectService：项目 CRUD + 项目上下文读取

## Facade

```python
async def get_project_context(db, novel_id) -> ProjectContext | None
```

## API

```
POST   /api/projects        # 创建项目
GET    /api/projects         # 项目列表
GET    /api/projects/{id}    # 项目详情
PUT    /api/projects/{id}    # 更新项目
DELETE /api/projects/{id}    # 删除项目
```

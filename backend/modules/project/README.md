# Module: project / 小说项目模块

## 定位

project 模块负责小说项目基础元信息，是其他所有模块的根。
其他模块通过 `novel_id` 引用项目，并通过 `facade.get_project_context()` 获取项目配置。

## 职责

- 创建小说项目
- 管理标题、题材、风格、语言
- 管理目标规模（字数/章节数）和当前创作阶段
- 提供 `novel_id` / `project_id`
- 提供项目级默认策略（如 `default_reveal_policy`）

## 边界

明确不做：

- 世界观管理 → world 模块
- 人物管理 → character 模块
- 大纲管理 → outline 模块
- RAG 检索 → rag 模块
- 正文生成 → writing 模块
- 结构复查 → review 模块

## 数据表

| 表名 | 用途 |
|------|------|
| `projects` | 小说项目基础元信息 |

### projects 表字段

- `id` — UUID 主键
- `title` — 项目标题（必填）
- `genre` — 题材（如：玄幻、科幻、悬疑）
- `tone` — 风格基调（如：严肃、轻松、黑暗）
- `language` — 创作语言（默认 `zh`）
- `target_length` — 目标规模（如：short, medium, novel, epic）
- `current_stage` — 当前创作阶段（如：world_building, outlining, writing, revising）
- `default_reveal_policy` — 默认揭示策略（默认 `author_safe`）
- `created_at` / `updated_at` — 时间戳

## 对外契约（contracts.py）

```python
class ProjectContract:
    """其他模块可依赖的项目契约"""
    novel_id: str
    title: str
    genre: str | None
    tone: str | None
    language: str
    target_length: str | None
    current_stage: str | None
    default_reveal_policy: str
```

## Facade（facade.py）

```python
async def get_project_context(db, novel_id: str) -> ProjectContext: ...
```

供其他模块获取项目上下文信息，包含项目基本元信息和策略配置。

## API 路由

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/projects` | 创建项目 |
| GET | `/api/projects` | 项目列表 |
| GET | `/api/projects/{project_id}` | 项目详情 |
| PUT | `/api/projects/{project_id}` | 更新项目 |
| DELETE | `/api/projects/{project_id}` | 删除项目 |

## 测试方式

```bash
cd backend
python -m pytest modules/project/tests/ -v
```

## 依赖

- `core.database` — 数据库连接
- `core.base` — Base ORM、UUIDMixin、TimestampMixin
- `core.dependencies` — DbSession 依赖注入
- `shared.types` — NovelID 等类型别名
- `shared.enums` — 枚举定义
- `shared.constants` — DEFAULT_PAGE_SIZE 等常量

## MVP

仅实现 CRUD 和项目上下文读取。

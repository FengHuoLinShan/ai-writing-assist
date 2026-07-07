# Module: project / 小说项目模块

## 定位

project 模块是系统的根聚合。所有其他模块通过 novel_id 关联到项目。

## 数据表

- `projects` — id / title / genre / tone / language / target_length / current_stage / default_reveal_policy / settings / deleted_at

### settings 字段

JSONB 配置字段，存储项目级可调参数，如 `temporary_entity_expiry_chapters` 等。
其中 `settings.llm` 是项目级业务 LLM Profile；业务调用只使用项目/全局数据库配置
和代码内置默认，不从旧版 `LLM_*` 环境变量继承供应商、模型、Base URL 或 API Key。
典型字段：

- `provider_id` / `label`：供应商模板标识与显示名
- `base_url` / `model`：OpenAI-compatible API 地址与默认模型
- `timeout` / `max_tokens` / `temperature` / `top_p` / `extra`：业务调用参数
- `api_key`：写入式字段；API 响应只返回 `api_key_configured`

更新 LLM Profile 时，空 `api_key` 表示保留旧密钥；只有 `clear_api_key=true`
才清除已保存密钥。所有项目详情、列表和 LLM 设置响应都不得回显 API Key。

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
GET    /api/projects/llm/provider-templates     # LLM 供应商模板
GET    /api/projects/{id}/llm-settings          # 项目级 LLM 配置（不回显 API Key）
PUT    /api/projects/{id}/llm-settings          # 更新项目级 LLM 配置
POST   /api/projects/{id}/restore              # 恢复项目
DELETE /api/projects/{id}/permanent            # 永久删除（级联）
```

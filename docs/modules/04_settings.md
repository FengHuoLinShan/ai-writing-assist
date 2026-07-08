# Module: settings / 设置模块

## 定位

settings 模块管理全局 LLM 默认值、全局作者偏好，以及项目级作者偏好覆盖。
项目级 LLM Profile 的保存入口仍在 project 模块，settings 负责全局默认和 effective
合并规则。

## 关键约束

- API Key 只允许项目级保存；全局 LLM 默认不存 Key，schema 和 service 双重拒绝
  `api_key` 字段。
- `owner_id` 在 demo 阶段固定为 nil UUID，前端显示为 `local`；未来账户系统接入时由
  路由层 authorizer 补齐。
- 项目作者偏好字段允许 `NULL`，语义为继承全局值；每个项目最多一行覆盖记录。
- 字段级恢复继承只接受白名单字段，不拼接任意列名或 JSON path。
- 全局 `deep_import` 列当前保持 `NULL`，全局设置页不暴露深度导入的细粒度参数。

## 数据表

| 表 | 说明 |
|----|------|
| `global_llm_defaults` | 全局 LLM 默认值，不含 API Key |
| `global_author_preferences` | 全局作者偏好 |
| `project_author_preferences` | 项目级作者偏好覆盖，`NULL` 表示继承 |

## 服务与对外入口

- `SettingsService`：全局默认、作者偏好、项目覆盖和字段级恢复继承。
- `settings.facade.get_effective_llm_settings()`：合并项目设置、全局默认和系统默认。
- `settings.facade.get_effective_author_prefs()`：合并项目作者偏好、全局偏好和系统默认。
- `settings.facade.materialize_effective_project_settings()`：为调用方生成可直接消费的项目设置。
- `settings.facade.list_projects_using_defaults()`：列出仍继承全局默认的项目摘要。

## API

```http
GET    /api/settings/llm-defaults
PUT    /api/settings/llm-defaults
GET    /api/settings/author-preferences
PUT    /api/settings/author-preferences
GET    /api/settings/projects-using-defaults
POST   /api/settings/refresh
GET    /api/settings/projects/{project_id}/author-preferences
PUT    /api/settings/projects/{project_id}/author-preferences
DELETE /api/settings/projects/{project_id}/author-preferences/field/{field_name}
```

项目级 effective LLM 和作者偏好查询仍由 project 模块提供：

```http
GET    /api/projects/{id}/effective-llm-settings
GET    /api/projects/{id}/effective-author-preferences
DELETE /api/projects/{id}/llm-settings/field/{field_name}
```

## Effective 响应

effective 响应中每个字段返回 `{ value, source }`：

| source | 含义 |
|--------|------|
| `project` | 项目字段有值，覆盖全局 |
| `global` | 项目为空，继承全局 |
| `system` | 项目和全局都为空，回退代码内置默认 |
| `unset` | 无项目值、全局值或系统默认 |

`api_key_configured` 只返回布尔值，不返回明文；其来源只可能是 `project` 或 `unset`。

## 跨模块边界

- settings 不直接读取 project 内部 repository/service；跨模块聚合通过 project facade。
- project 调用 settings facade 获取 effective 合并结果，不直接 import settings 内部实现。
- 业务 LLM 调用消费合并后的 project settings，不从全局设置表直接读取 API Key。

## 测试

```bash
cd backend
pytest modules/settings/tests/ -v
```

# Module: settings / 设置模块

## 定位

settings 模块拥有全局 LLM 默认、全局作者偏好和项目级作者偏好覆盖。它不拥有项目本身，
也不保存 API Key；项目级 LLM Profile 与写入式密钥仍属于 `projects.settings.llm`。

## 数据表

| 表 | 范围 | 设计要点 |
|---|---|---|
| `global_llm_defaults` | owner | 每个 `owner_id` 最多一行的 LLM 默认值；所有可继承字段可为 NULL。 |
| `global_author_preferences` | owner | 每个 `owner_id` 最多一行的作者偏好默认。 |
| `project_author_preferences` | project | 每个 `project_id` 最多一行的覆盖值；NULL 表示继承全局。 |

`LOCAL_OWNER_ID` 是 bootstrap account 的 nil UUID 别名，不再是未接入账户系统的占位。
本地和封闭测试会自动解析为该账号；公开浏览器请求必须从当前 account principal 解析 owner，
不得由请求参数指定。worker 通过项目上下文携带 owner，不能回退读取其他账号的全局默认。

## 安全与继承规则

- `global_llm_defaults` 不允许 `api_key` 字段；schema 与 service 双重拒绝，避免把密钥
  提升为全局数据。
- 项目 LLM Profile 的密钥是写入式、加密字段，并按当前项目的供应商模板隔离保存。
  当前模板仍通过 `projects.settings.llm.api_key` 提供给运行时；响应只暴露
  `api_key_configured` 和不含密钥的 `api_key_configured_providers`。空 API Key 表示复用
  当前模板已保存的 Key，只有 `clear_api_key=true` 能清除当前模板 Key。
- effective 设置逐字段合并：项目值优先，其次全局值，最后才是代码内置默认；没有内置值
  的字段保持 unset。API 响应为每个字段携带 `value` 与 `source`，`source` 为
  `project`、`global`、`system` 或 `unset`。
- 项目覆盖的单字段删除只接受白名单字段，用于恢复继承；不得拼接列名或 JSON path。
- `global_llm_defaults.deep_import` 是预留列，当前全局设置流程不写入它。
- 项目 `deep_import.phase1c` 提供自动融合阈值（默认 `0.92`）、边界上下文、并发、token 和超时设置。`decision_max_tokens` 留空时继承有效 LLM `max_tokens`（当前系统默认 `12000`），Phase 1c 默认超时为 360 秒。
- 项目设置页会在没有 `deep_import` 项目覆盖时直接显示当前系统默认值；显式 `null` 的可空字段仍保持留空/继承语义。
- `high_quality` 表示 DeepSeek `max` reasoning 和 Phase 1c，不会自动切换项目手动选择的 model。

## 对外接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET/PUT | `/api/settings/llm-defaults` | 读取或更新全局 LLM 默认 |
| GET/PUT | `/api/settings/author-preferences` | 读取或更新全局作者偏好 |
| GET | `/api/settings/projects-using-defaults` | 列出会继承默认值的项目 |
| POST | `/api/settings/refresh` | 通知客户端刷新设置缓存 |
| GET/PUT | `/api/settings/projects/{project_id}/author-preferences` | 读取或更新项目作者偏好覆盖 |
| DELETE | `/api/settings/projects/{project_id}/author-preferences/field/{field_name}` | 删除单字段覆盖并恢复继承 |
| GET | `/api/projects/{id}/effective-llm-settings` | 获取项目 LLM 的 effective 视图 |
| GET | `/api/projects/{id}/effective-author-preferences` | 获取项目作者偏好的 effective 视图 |
| DELETE | `/api/projects/{id}/llm-settings/field/{field_name}` | 删除项目 LLM 单字段覆盖 |

写接口使用 XHR/CSRF 保护。项目级 effective 与 LLM Profile 路由属于 project 模块，
因为它们以项目资源为入口；合并规则仍属于 settings。

## 模块边界

- `modules.settings.services` 接收项目的原始 settings dict，负责计算 effective 值，不能
  直接读取 project 的内部 models/repositories/services。
- `modules.settings.facade` 向 project 暴露 effective 设置函数；需要项目列表的聚合通过
  `modules.project.facade` 获取项目摘要。
- 其他模块只能消费已经解析的项目设置或 facade 返回值，不应自行实现字段继承或读取
  `global_*` 表。

## 验证

```bash
cd backend
pytest modules/settings/tests/ -v
```

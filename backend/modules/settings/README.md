# Settings Module

管理全局 LLM 默认、全局作者偏好、项目级作者偏好覆盖。

## 关键约束

- **API Key 永远项目级**：`global_llm_defaults` 表不存 Key，`GlobalLLMDefaultsUpdate` schema `extra="forbid"` 硬拒 `api_key` 字段；PUT 接口和 service 层都对此双重防御。
- **`owner_id` demo 阶段用 nil UUID**（`LOCAL_OWNER_ID = 00000000-0000-0000-0000-000000000000`）；UI 显示 `local` 字样。未来账户接入后路由层加 authorizer，DB 无需改 schema。
- **项目级表不带 `owner_id`**：靠 `project → owner` 关系未来追加，避免双写冗余。
- **项目作者偏好所有字段允许 NULL**：NULL = 继承全局（D2）。`UNIQUE(project_id)` 保证每个项目最多一行。
- **字段级 DELETE 硬白名单**：`AUTHOR_PREFS_FIELDS`（作者偏好）、`LLM_INHERITABLE_FIELDS`（LLM 字段，不含 `api_key`）。非白名单返回 400，不拼列名、不拼 JSON path。
- **全局 `deep_import` 本期永不写入**（D9）：`global_llm_defaults.deep_import` 列存在但保持 NULL；全局页不渲染 40+ 深度导入字段，避免臃肿。未来需要全局默认时单独开 issue。
- **通用输出上限默认 `12000`**：项目未覆盖时按项目 → 全局 → 系统顺序解析；深度导入不继承该值，继续使用自己的阶段预算。

## effective 响应结构（契约）

```json
{
  "provider_id": { "value": "deepseek", "source": "global" },
  "base_url":    { "value": "https://api.deepseek.com/v1", "source": "global" },
  "model":       { "value": "deepseek-chat", "source": "project" },
  "api_key_configured": { "value": true, "source": "project" },
  "deep_import": { "value": {...}, "source": "project" },
  "temperature": { "value": 0.3, "source": "system" }
}
```

`source ∈ {project, global, system, unset}`：

| source | 含义 |
|--------|------|
| `project` | 项目字段有值（覆盖） |
| `global` | 项目 NULL，全局有值（继承） |
| `system` | 项目与全局都 NULL，回退代码内置默认（官方 DeepSeek） |
| `unset` | 项目与全局都 NULL，且无内置默认（如 Key、`daily_goal` 空时） |

`api_key_configured` 永远只返回 bool 不返回明文；`source` 永远 `project` 或 `unset`（Key 永远项目独有，不参与继承）。

## 接口

详见 `api.py`。路由前缀 `/api/settings/`：

- `GET/PUT /api/settings/llm-defaults` — 全局 LLM 默认
- `GET/PUT /api/settings/author-preferences` — 全局作者偏好
- `GET /api/settings/projects-using-defaults` — 引用此默认的项目聚合（D18: 任一字段 NULL 即列出）
- `POST /api/settings/refresh` — 调试端点：通知客户端刷新缓存（D16）
- `GET/PUT /api/settings/projects/{project_id}/author-preferences` — 项目覆盖
- `DELETE /api/settings/projects/{project_id}/author-preferences/field/{field_name}` — 单字段恢复继承

三个项目级作者偏好入口都在读写前校验 active project；项目不存在或已进入
回收站时统一返回 404。全局 LLM 默认、全局作者偏好、默认继承聚合和
refresh 不绑定单个项目，不使用该门禁。

项目级 effective 接口仍走 `/api/projects/<id>/...`（位于 `modules/project/`）：

- `GET /api/projects/{id}/effective-llm-settings` — 合并视图
- `GET /api/projects/{id}/effective-author-preferences` — 合并视图
- `DELETE /api/projects/{id}/llm-settings/field/{field_name}` — LLM 字段恢复继承

上述 effective 接口同样以 active project 为边界；项目不存在或已进入回收站时返回
标准 DomainError 404，不回退到系统默认，也不暴露普通 Python 异常。

## 跨模块边界

- `modules.settings.services` 拥有 effective settings 计算规则，接收 raw project settings dict，不直接读取 project 模块。
- `modules.settings.facade` 暴露 `get_effective_llm_settings` / `get_effective_author_prefs` / `materialize_effective_project_settings` 供 `modules.project` 调用。
- 跨模块聚合（如 `/api/settings/projects-using-defaults`）只在 `modules.settings.facade` 薄编排：通过 `modules.project.facade` 读取项目摘要，再委托 settings service 组装 response。
- 不允许直接 import 对方模块的 `services.py` / `repositories.py` / `models.py`。

## D 决策索引

详见 `docs/superpowers/specs/2026-07-07-settings-page-restructure-design.md` §0 关键决策表（D1-D25）。

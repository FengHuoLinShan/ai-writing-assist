# Settings Module

管理账户级文本/图片模型连接、只读余额、全局作者偏好和项目级作者偏好覆盖。

## 数据表

- `account_llm_credentials`：owner/provider 唯一的加密 Key、指纹与验证时间；
- `global_llm_defaults`：owner 唯一的当前模板/provider 与非 secret 兼容默认；
- `global_author_preferences`：owner 唯一的全局作者偏好；
- `project_author_preferences`：project 唯一的可空偏好覆盖。

## 关键约束

- **API Key 永远账户级**：`account_llm_credentials` 按
  `(owner_id, provider_id)` 唯一加密保存。项目设置、任务 meta、execution snapshot、响应和
  日志都不保存或回显 Key；指纹使用部署加密密钥和用途分隔的 HMAC-SHA256，仅用于判断
  同一账户连接是否重复保存，不是认证凭据。遗留的无密钥 SHA-256 指纹在作者下次保存该连接并
  完成真实验证后惰性改写，不新增 migration；遗留项目 Key 由既有 migration 清除。
- **连接编辑只有模板和 Key**：第一版固定 DeepSeek `deepseek-v4-flash` 与 Kimi
  `kimi-k3` 两个代码模板；DeepSeek 默认可用，Kimi 在真实兼容门禁通过并显式启用前不进入
  API 响应，也不能被选择。
- **连接先验证再原子激活**：新 Key 先做真实最小调用，成功后才加密保存并切换当前模板；
  相同已验证 Key 重存不重复验证。没有可用 Key 时业务调用 fail-closed，不暗降级到其他模型。
- **当前模板按 owner 保存**：复用 `global_llm_defaults` 的 owner 唯一行记录模板字段；
  该表不含 Key，也不再构成可任意编辑的运行时 provider/profile 平面。
- **全局默认按账号 owner 隔离**：`owner_id → accounts.id`；worker 由项目上下文显式携带
  owner，不能回退到其他用户的全局设置。
- **本地与封闭测试使用 bootstrap owner**：`LOCAL_OWNER_ID` 仅标识固定 bootstrap
  账号；公开模式必须先认领该账号，不能把 nil UUID 当作绕过 owner 门禁的系统主体。
- **项目级作者偏好沿项目 owner 隔离**：项目自身持有非空 `owner_id`，设置查询先验证项目
  归属；不会在项目设置表重复写 owner。
- **项目作者偏好所有字段允许 NULL**：NULL = 继承全局（D2）。`UNIQUE(project_id)` 保证每个项目最多一行。
- **字段级 DELETE 硬白名单**：`AUTHOR_PREFS_FIELDS`（作者偏好）和兼容
  `LLM_INHERITABLE_FIELDS`（不含 `api_key`）。非白名单返回 400，不拼列名、不拼 JSON path。
- **全局 `deep_import` 本期永不写入**（D9）：`global_llm_defaults.deep_import` 列存在但保持 NULL；全局页不渲染 40+ 深度导入字段，避免臃肿。未来需要全局默认时单独开 issue。
- **余额是非阻塞只读辅助**：只查询已连接且已启用的 provider，原币种返回总可用额；
  失败统一为 unavailable，不影响连接状态或故事生成。前端标注“可能有延迟”，不轮询、
  不拆分余额、不显示充值入口。
- **通用输出上限默认 `12000`**：由固定账户模板提供；深度导入继续使用自己的阶段预算。
- **图片连接独立**：`openai-image` 只复用 `account_llm_credentials` 的加密存储，固定 OpenAI
  base URL 与 `gpt-image-2`；不进入文本模板目录，也不改变 `active_provider_id`。连接检查只
  显示“密钥连接成功”；图片权限、组织验证与额度在首次实际生成时确认。

## effective 响应结构（契约）

```json
{
  "provider_id": { "value": "deepseek", "source": "global" },
  "base_url":    { "value": "https://api.deepseek.com", "source": "global" },
  "model":       { "value": "deepseek-v4-flash", "source": "global" },
  "api_key_configured": { "value": true, "source": "global" },
  "deep_import": { "value": {...}, "source": "project" },
  "temperature": { "value": 0.3, "source": "system" }
}
```

`source ∈ {project, global, system, unset}`：

| source | 含义 |
|--------|------|
| `project` | 项目拥有的非 secret 工作流字段有值，例如 `deep_import` |
| `global` | 当前账户模板或账户凭据提供 |
| `system` | 没有显式值时使用代码默认 |
| `unset` | 没有适用值，例如账户尚未连接 Key |

`api_key_configured` 永远只返回 bool，不返回明文；运行时 provider/model/Key 不接受项目覆盖。

## 接口

详见 `api.py`。路由前缀 `/api/settings/`：

- `GET /api/settings/llm-connections` — 当前账户可用模板、连接状态和当前模板
- `PUT /api/settings/llm-connections/{provider_id}` — 验证、加密保存 Key 并激活模板
- `POST /api/settings/llm-connections/{provider_id}/activate` — 切到已有连接，不重复验证
- `DELETE /api/settings/llm-connections/{provider_id}` — 清除该 provider 的账户 Key
- `GET /api/settings/llm-balances` — 非阻塞查询已连接 provider 的原币种余额
- `GET/PUT/DELETE /api/settings/image-connection` — 查询、验证保存或清除独立图片连接
- `GET/PUT /api/settings/llm-defaults` — 全局 LLM 默认；timeout/max_tokens/
  temperature/top_p/extra 等调优字段叠加进账户运行 profile 真正生效，
  连接身份字段（provider/label/base_url/model）仍只能在账户模型连接入口切换
- `GET/PUT /api/settings/author-preferences` — 全局作者偏好
- `GET /api/settings/projects-using-defaults` — 引用此默认的项目聚合（D18: 任一字段 NULL 即列出）
- `POST /api/settings/refresh` — 调试端点：通知客户端刷新缓存（D16）
- `GET/PUT /api/settings/projects/{project_id}/author-preferences` — 项目覆盖
- `DELETE /api/settings/projects/{project_id}/author-preferences/field/{field_name}` — 单字段恢复继承

三个项目级作者偏好入口都在读写前校验 active project；项目不存在或已进入
回收站时统一返回 404。全局 LLM 默认、全局作者偏好、默认继承聚合和
refresh 不绑定单个项目，不使用该门禁。

项目级兼容/effective 接口仍走 `/api/projects/<id>/...`（位于 `modules/project/`）：

- `GET /api/projects/{id}/effective-llm-settings` — 合并视图
- `GET /api/projects/{id}/effective-author-preferences` — 合并视图
- `DELETE /api/projects/{id}/llm-settings/field/{field_name}` — 清理兼容项目字段

上述 effective 接口同样以 active project 为边界；项目不存在或已进入回收站时返回
标准 DomainError 404，不回退到系统默认，也不暴露普通 Python 异常。

## 跨模块边界

- `modules.settings.services` 拥有账户连接、凭据加密、模板启用门禁、余额和 effective
  settings 规则，不直接读取 project 模块。
- `modules.settings.contracts` 暴露 project API 使用的 effective response 类型和
  非 secret 字段白名单；`modules.settings.facade` 暴露
  `resolve_account_llm_runtime_profile`、`resolve_account_image_runtime_connection`、`get_effective_llm_settings` /
  `get_effective_author_prefs` 供 `modules.project` 调用。业务模块不得绕过
  project 的 client/snapshot seam 直接取得明文凭据。
- 跨模块聚合（如 `/api/settings/projects-using-defaults`）只在
  `modules.settings.facade` 薄编排：settings 提供“完全覆盖作者偏好”的 ID subquery，
  project facade 在自身的 active/author/owner 条件、排序和分页查询中应用排除；不得跨 owner
  扫描或把 project ORM 实现泄漏给 settings。
- 不允许直接 import 对方模块的 `services.py` / `repositories.py` / `models.py`。

## D 决策索引

详见 `docs/superpowers/specs/2026-07-07-settings-page-restructure-design.md` §0 关键决策表（D1-D25）。

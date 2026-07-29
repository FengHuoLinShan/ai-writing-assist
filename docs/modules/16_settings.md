# Module: settings / 设置模块

## 定位

settings 模块拥有账户级模型连接、只读余额、全局作者偏好和项目级作者偏好覆盖。它不拥有
项目本身；业务模块通过 project facade 间接消费当前账户连接，不能直接读取凭据。

## 数据表

| 表 | 范围 | 设计要点 |
|---|---|---|
| `account_llm_credentials` | owner/provider | 已验证 API Key 的加密值、指纹和验证时间；组合唯一。 |
| `global_llm_defaults` | owner | 每个 `owner_id` 最多一行；保存当前模板/provider 与非 secret 兼容默认，不含 Key。 |
| `global_author_preferences` | owner | 每个 `owner_id` 最多一行的作者偏好默认。 |
| `project_author_preferences` | project | 每个 `project_id` 最多一行的覆盖值；NULL 表示继承全局。 |

`LOCAL_OWNER_ID` 是 bootstrap account 的 nil UUID 别名，不再是未接入账户系统的占位。
本地和封闭测试会自动解析为该账号；公开浏览器请求必须从当前 account principal 解析 owner，
不得由请求参数指定。worker 通过项目上下文携带 owner，不能回退读取其他账号的全局默认。

## 安全与运行时规则

- 第一版代码模板为 DeepSeek `deepseek-v4-flash` 和 Kimi `kimi-k3`。DeepSeek 默认启用；
  Kimi 在真实兼容门禁通过并显式设置 `ENABLE_ACCOUNT_KIMI_K3` 前不出现在连接响应。
- 新 Key 必须先完成真实最小验证；成功后才在同一事务保存 credential 并激活模板。相同指纹的
  已验证 Key 可免重复验证。连接失败不覆盖旧连接，运行时不暗降级。
- Key 使用 `LLM_SETTINGS_ENCRYPTION_KEY` 加密；response、日志、task meta、execution
  snapshot 和 producer provenance 只保存脱敏状态/摘要。
- 项目中的遗留 Key 由 migration 不可逆清理；兼容项目 LLM API 仍保留 wire，但任何
  `api_key/clear_api_key/clear_all_api_keys` 写入都会被拒绝。
- effective LLM 响应保留 `{value, source}` wire；账户模板/凭据使用 `global`，项目只拥有
  `deep_import` 等非 secret 工作流字段。provider/model/Key 不接受项目覆盖。
- 项目覆盖的单字段删除只接受白名单字段，用于恢复继承；不得拼接列名或 JSON path。
- `global_llm_defaults.deep_import` 是预留列，当前全局设置流程不写入它。
- 项目 `deep_import.phase1c` 提供自动融合阈值（默认 `0.92`）、边界上下文、并发、token 和超时设置。`decision_max_tokens` 留空时继承有效 LLM `max_tokens`（当前系统默认 `12000`），Phase 1c 默认超时为 360 秒。
- 项目设置页会在没有 `deep_import` 项目覆盖时直接显示当前系统默认值；显式 `null` 的可空字段仍保持留空/继承语义。
- `high_quality` 表示 DeepSeek `max` reasoning 和 Phase 1c；它不切换账户当前模板。
- 余额查询只面向已连接且已启用的 provider，原币种返回总可用额；失败为 unavailable，
  不影响连接或生成。前端不轮询、不换算、不拆分，也不显示充值入口。

## 对外接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/settings/llm-connections` | 当前账户模板、连接和激活状态 |
| PUT | `/api/settings/llm-connections/{provider_id}` | 验证、加密保存 Key 并激活 |
| POST | `/api/settings/llm-connections/{provider_id}/activate` | 切换已有连接 |
| DELETE | `/api/settings/llm-connections/{provider_id}` | 清除该 provider Key |
| GET | `/api/settings/llm-balances` | 查询原币种余额；非阻塞失败 |
| GET/PUT | `/api/settings/llm-defaults` | 读取或更新全局 LLM 默认 |
| GET/PUT | `/api/settings/author-preferences` | 读取或更新全局作者偏好 |
| GET | `/api/settings/projects-using-defaults` | 列出会继承默认值的项目 |
| POST | `/api/settings/refresh` | 通知客户端刷新设置缓存 |
| GET/PUT | `/api/settings/projects/{project_id}/author-preferences` | 读取或更新项目作者偏好覆盖 |
| DELETE | `/api/settings/projects/{project_id}/author-preferences/field/{field_name}` | 删除单字段覆盖并恢复继承 |
| GET | `/api/projects/{id}/effective-llm-settings` | 获取项目 LLM 的 effective 视图 |
| GET | `/api/projects/{id}/effective-author-preferences` | 获取项目作者偏好的 effective 视图 |
| DELETE | `/api/projects/{id}/llm-settings/field/{field_name}` | 清理兼容项目 LLM 字段 |

写接口使用 XHR/CSRF 保护。项目级 effective 与 LLM Profile 路由属于 project 模块，
因为它们以项目资源为入口；合并规则仍属于 settings。

## 模块边界

- `modules.settings.services` 拥有 credential、连接验证、模板门禁、余额与 effective 规则，
  不能直接读取 project 的内部 models/repositories/services。
- `modules.settings.facade` 只向 project 暴露 account runtime profile/effective 设置函数；
  需要项目列表的聚合通过 `modules.project.facade` 获取项目摘要。
- 其他业务模块只能通过 project facade 消费已经解析的 client/snapshot，不得直接读取
  `account_llm_credentials` 或 `global_*` 表。

## 验证

```bash
cd backend
pytest modules/settings/tests/ -v
```

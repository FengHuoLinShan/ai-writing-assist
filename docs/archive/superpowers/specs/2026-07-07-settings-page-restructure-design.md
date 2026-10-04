# 配置页设计

- 日期：2026-07-07
- 范围：全局设置页 + 项目级 LLM/深度导入配置页 重组
- 状态：评审决策已收口
- 评审版本：v2（含 2026-07-07 评审问题清单全部决策）

## 0. 关键决策表（评审收口）

|# |决策点|结论|
|---|------|-----|
|D1|source 分类|四类：`project` / `global` / `system` / `unset`|
|D2|NULL 语义分层|项目字段 NULL = 继承全局；全局字段 NULL = 继承代码内置默认；既无项目也无全局值且无内置默认 = `unset`|
|D3|项目覆盖字段 nullable 范围|项目 LLM 配置沿用 `Project.settings["llm"]` JSON 存储（非独立表）；非 Key 字段缺失或显式 null = 继承全局；Key 永远项目独有，source 永远 `project`/`unset`|
|D4|PUT/PATCH/DELETE 分工|`PUT` = 全量替换（缺失字段置 NULL = 恢复继承）；不引入 PATCH；`DELETE /<resource>/field/<field_name>` = 单字段恢复继承；`field_name` 服务端硬白名单，非白名单返回 400，不拼列名|
|D5|LLM 设置也加字段级 DELETE|是。`DELETE /api/projects/<id>/llm-settings/field/<field_name>`|
|D6|deep_import JSONB 覆盖粒度|整体覆盖，不做字段级合并。项目 NULL = 继承全局；有值 = 整体覆盖；UI「恢复到全局默认」按钮放在整个 Tab 而非每字段；子字段仍走 schema 校验|
|D7|effective 接口稳定响应结构|`{ field: { value, source } }`；`source ∈ {project, global, system, unset}`；`deep_import` 整体作为一个单元返回|
|D8|API Key 绑定安全|Key 永远项目级，source 永远 `project` 或 `unset`，从不 `global` / `system`；effective 接口仅返回 `api_key_configured: bool`，不留明文；继承的 provider/base_url 与项目 Key 在 UI 警告提示；后端 LLM 调用不阻断跨供应商 Key，日志记 `key_provider_mismatch` 审计字段|
|D9|全局深度导入默认进 UI|**不进**。`global_llm_defaults.deep_import` 列保留但本期永不写入；深度导入 source 永远 `project` 或 `system`；项目级才有覆盖；避免全局页 40+ 字段臃肿；未来需要时单独开 issue|
|D10|owner_id 类型|UUID，demo 用 nil UUID `00000000-0000-0000-0000-000000000000`；UI 仅显示 `local` 字样|
|D11|项目级表 owner_id|不带。当前 `projects` 表无 `owner_id` 列，项目级新表仅 `project_id` 隔离；owner 隔离靠 `project → owner` 关系未来追加，避免双写冗余|
|D12|全局作者偏好硬编码默认|`daily_goal = null (unset)`；`editor_font = "system"`；`default_focus_mode = false`|
|D13|项目偏好行不存在返回|`GET` 返回全 NULL 空对象（不是 404）；effective 视图自动等同全继承全局|
|D14|URL project id 权威|`#/projects/<id>/settings` 从 URL 取 project_id，不依赖内存 `currentProjectId`；选中后同步 state；保证深链书签可靠|
|D15|`#/llm` 无项目时|跳到 `#/settings` 全局页 + toast「请先选择项目」|
|D16|全局缓存失效|全局保存后本地缓存失效 + effective 重拉；切 owner 缓存清；多标签页用 `storage` event 通知刷新；新增 `POST /api/settings/refresh` 调试端点|
|D17|未配 Key 时 UI 引导|Key 旁黄色提示「需配置项目 API Key 后才能实际调用 LLM」；保存项目配置 + 全局默认但 Key 空时 toast「Key 未配置，已保存其他字段」|
|D18|`projects-using-defaults` 统计口径|只统计作者偏好默认（不统计 LLM 默认，避免误以为 LLM Key 复用）；任一字段在 `project_author_preferences` 为 NULL 即列出|
|D19|聚合分页|本期不分页；接口预留 `?limit=50&offset=0`；超过 100 时前端展示前 50 + 「更多项目省略」|
|D20|localStorage 旧偏好迁目标|迁为**项目覆盖**（不污染全局默认）；每个项目迁自己的，不存在跨项目冲突|
|D21|首次打开才迁移|接受。文档说明「未再打开的项目其 localStorage 不会自动入库，清浏览器缓存会丢失」；全局设置页底部提供「手动迁移所有项目本地偏好」按钮遍历所有 `novel_author_preferences:*` 批量迁|
|D22|localStorage 与后端冲突|后端有值优先：仅在项目偏好行不存在/全 NULL 时执行迁移；已有项目偏好值时跳过迁移并清旧 key（不覆盖）|
|D23|全局 LLM 默认不存在时 effective|所有字段 source=`system`，回退代码内置默认（`provider_id="openai-compatible"`、`model=""`、`temperature=0.3` 等）；UI 提示「未配置全局默认，使用系统内置默认」|
|D24|owner 隔离测试|pytest 直接构造两个虚拟 owner_id（fixture 注入），断言 owner A 看不到 owner B 的全局行；占位回归断言，账户接入时此测试不需改，仅加 authorizer 单测|
|D25|表重建丢数据|接受（AGENTS.md 已明确 demo 阶段允许）。安全脚本不动；要求测试全部独立 seed|

上述决策为契约性结论，后续章节若与之冲突以本表为准。

## 1. 背景与目标

当前 `frontend-console/views/llmSettingsView.js`（700 行单文件）承载项目级 LLM 主配置、40+ 深度导入参数、作者偏好三大块，缺乏分层。后端 `backend/core/config.py` 提供环境变量级全局配置但不通过 UI 管理。本设计目标：

1. 引入「全局默认 + 项目覆盖」分层，让作者偏好和 LLM 主配置都支持全局默认；切项目时不丢失个人习惯。
2. 把当前单页按 Tab 拆分，30+ 字段的深度导入不再挤在主配置里。
3. 后端表与接口预留 `owner_id`，为未来账户系统接入留出位置；demo 阶段使用 `local` UUID 占位。
4. 不引入后端 env 配置（DATABASE_URL、CORS、池大小等）的在线写入；这些保持由 `.env` / 部署管理。

非目标：

- 引入账户/认证系统
- 后端运行时配置在线修改
- RAG / embedding 维度等基础设施参数在线修改
- 多 owner 隔离的运行时实现（仅在测试中预留断言）

## 2. 架构概览

路由：两个独立 URL，全局与项目作用域在语义上彻底切开。

```
#/settings                         — 全局设置页（无需选项目）
#/projects/<id>/settings           — 项目设置页（依赖 currentProjectId）
```

数据流：

```
前端视图 ─→ /api/settings/*            （owner 隔离的全局默认）
        ─→ /api/projects/<id>/*        （项目覆盖 + effective 合并视图）
        └ localStorage 一次性迁移       （旧 author preferences key → 后端）
```

后端新增三张表，新表带 `owner_id` 预留账户系统：

| 表 | 作用域 | 隔离键 | 存储形式 |
|----|--------|--------|----------|
| `global_llm_defaults` | 全局 LLM 默认（按供应商完整期望，不含 Key） | owner_id | 新 SQL 表 |
| `global_author_preferences` | 全局作者偏好默认 | owner_id | 新 SQL 表 |
| `project_author_preferences` | 项目级作者偏好覆盖（字段 NULL = 用全局） | project_id | 新 SQL 表 |

**项目 LLM 配置不引入新表**：现有实现将项目 LLM 配置存于 `Project.settings["llm"]` JSON 字段（见 `infrastructure/llm/profiles.py:LLM_SETTINGS_KEY`），深度导入存于 `Project.settings["deep_import"]`（`DEEP_IMPORT_SETTINGS_KEY`）。本设计沿用 JSON 存储：缺失/空 JSON key 表示「继承全局默认」（与 NULL 字段等价语义），无需 alembic 改表。

## 3. 路由与信息架构

### 3.1 全局设置页 `#/settings`

无需选项目即可访问，单一页面（无 Tab），垂直分区：

1. **头部状态条**：owner 占位（demo：`local`），提示「主配置、深度导入、作者偏好项目覆盖 需进入项目后访问」+「进入最近项目」跳转按钮（有最近项目时可用）
2. **全局 LLM 默认** section：复用 `shared/llmFormFields.js` 渲染，但去掉 API Key 输入；保存走 `PUT /api/settings/llm-defaults`
3. **全局作者偏好** section：日更目标、编辑器字体、默认专注模式；保存走 `PUT /api/settings/author-preferences`
4. **引用此默认的项目列表**（只读）：从 `project_author_preferences` 聚合 NULL 字段项目；展示全局偏好的辐射范围

### 3.2 项目设置页 `#/projects/<id>/settings`

需要 `currentProjectId`，空时渲染空态 + 「返回全局设置」按钮。三个 Tab：

1. **主配置**：供应商、模型、Key、BaseURL、参数、创作预设（项目覆盖值）；保存走 `PUT /api/projects/<id>/llm-settings`；每字段有「已继承 / 已覆盖」标签
2. **深度导入**：Phase 0/1A/1B/2/3 的 40+ 字段（项目覆盖值）；schema 从 `shared/deepImportFields.js` 抽离
3. **作者偏好**：日更目标、编辑器字体、默认专注模式（项目覆盖值，未覆盖时显示"使用全局默认"标签）；保存走 `PUT /api/projects/<id>/author-preferences`

页面加载时调两个 effective 视图，把每字段的 `source` 元信息（`global` / `project`）传给 Tab 渲染「已继承 / 已覆盖」标签与「恢复到全局默认」按钮。

### 3.3 兼容性

现有 `#/llm` 路由保留为 `#/projects/<id>/settings` 的别名，避免旧书签断链；导航入口跳转 rewrite 到新 URL。

## 4. 数据模型

### 4.1 `global_llm_defaults`

```sql
id              UUID PK
owner_id        UUID NOT NULL UNIQUE  -- 预留账户；demo='00000000-0000-0000-0000-000000000000'
provider_id     VARCHAR NULL
label           VARCHAR NULL
base_url        VARCHAR NULL
model           VARCHAR NULL
timeout         INT NULL
max_tokens      INT NULL
temperature     FLOAT NULL
top_p           FLOAT NULL
extra           JSONB NULL
creative_mode   VARCHAR NULL   -- creative/precise/fast/custom
deep_import     JSONB NULL      -- 列保留但本期永不写入（D9）；永远 NULL，source 永远 system
created_at      TIMESTAMPTZ
updated_at      TIMESTAMPTZ
```

不存 API Key — 全局默认只覆盖「接哪家供应商 + 走什么参数」。所有字段(nullable) 的 NULL 语义 = 继承代码内置默认（D2）。

### 4.2 `global_author_preferences`

```sql
id                  UUID PK
owner_id            UUID NOT NULL UNIQUE
daily_goal          INT NULL
editor_font         VARCHAR     -- system/serif/sans/mono
default_focus_mode  BOOL
created_at          TIMESTAMPTZ
updated_at          TIMESTAMPTZ
```

### 4.3 `project_author_preferences`

```sql
id                  UUID PK
project_id          UUID FK → projects(id) UNIQUE
daily_goal          INT NULL
editor_font         VARCHAR NULL
default_focus_mode  BOOL NULL
created_at          TIMESTAMPTZ
updated_at          TIMESTAMPTZ
```

所有字段允许 NULL，`NULL` 表示「使用全局默认」；覆盖时填值，恢复即 UPDATE 回 NULL。合并不 permit 硬删除（沿用正史保护准则）。

### 4.4 现有项目 LLM 配置（`Project.settings` JSON）

项目 LLM 配置与深度导入参数已存放于 `Project.settings` JSON 字段（`infrastructure/llm/profiles.py:LLM_SETTINGS_KEY="llm"`、`DEEP_IMPORT_SETTINGS_KEY="deep_import"`），**不是独立表**。

本设计沿用 JSON 存储，**不改 alembic / 不 drop 任何项目 LLM 表**。继承语义通过「JSON key 缺失 = 继承全局」表达：

- `settings["llm"]` 缺失或不含某字段 → 该字段继承全局默认
- `settings["llm"]["api_key"]` 字段保留项目独有，Key 永远不参与继承（source 永远 `project` 或 `unset`）
- `settings["llm"]["provider_id"]` 等显式置 `None` 时视为「恢复继承」语义，等价于缺失该 key
- `settings["deep_import"]` 缺失 → 整组继承全局；有值 → 整体覆盖（D6 沿用）

服务层 `update_llm_settings` 在 PUT 时若收到字段值为 `None`，需要主动删除该 JSON key（而非保留 null 字面值），保持存储一致。读取时 `get_llm_profile` 把缺失 key 与显式 null 视同「未覆盖」。

## 5. API 接口

全部 owner 隔离，demo 阶段 `owner_id='local'`。

### 5.1 全局

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/settings/llm-defaults` | 当前 owner 的全局 LLM 默认（可能 null） |
| PUT | `/api/settings/llm-defaults` | upsert |
| GET | `/api/settings/author-preferences` | 全局作者偏好 |
| PUT | `/api/settings/author-preferences` | upsert |
| GET | `/api/settings/projects-using-defaults` | 聚合列出仍引用全局作者偏好为默认的项目（只读） |

### 5.2 项目

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/projects/<id>/author-preferences` | 项目覆盖（可能全 NULL 空对象，不返回 404） |
| PUT | `/api/projects/<id>/author-preferences` | 全量替换；缺失字段置 NULL（=恢复继承） |
| DELETE | `/api/projects/<id>/author-preferences/field/<field_name>` | 单字段恢复继承；`field_name` 服务端硬白名单，非白名单返回 400，不拼列名 |
| GET | `/api/projects/<id>/effective-llm-settings` | 合并视图：`{ field: { value, source } }`；source ∈ {project, global, system, unset} |
| GET | `/api/projects/<id>/effective-author-preferences` | 合并视图：同上结构 |
| PUT | `/api/projects/<id>/llm-settings` | 全量替换；缺失字段置 NULL（=恢复继承） |
| DELETE | `/api/projects/<id>/llm-settings/field/<field_name>` | 单字段恢复继承；服务端硬白名单（不含 `api_key`，Key 永远项目独有） |

**effective 响应结构（契约）**：

```json
{
  "provider_id": { "value": "deepseek", "source": "global" },
  "base_url":    { "value": "https://api.deepseek.com/v1", "source": "global" },
  "model":       { "value": "deepseek-v4-flash", "source": "project" },
  "api_key_configured": { "value": true, "source": "project" },
  "deep_import": { "value": {...}, "source": "project" },
  "temperature": { "value": 0.3, "source": "system" }
}
```

`api_key_configured` 永远只返回 bool 不返回明文；`source` 永远 `project` 或 `unset`（D8）。

## 6. 前端视图与状态组织

### 6.1 文件结构

```
frontend-console/views/settings/
├── globalSettingsView.js        -- #/settings 入口
├── projectSettingsView.js       -- #/projects/<id>/settings 入口
├── tabs/
│   ├── llmMainTab.js            -- 主配置 Tab（项目用）
│   ├── deepImportTab.js         -- 深度导入 Tab（项目用）
│   └── authorPreferencesTab.js  -- 作者偏好 Tab（全局用整页；项目用覆盖版）
└── shared/
    ├── llmFormFields.js         -- 供应商/Key/BaseURL/模型/参数/预设的渲染与读取
    ├── deepImportFields.js      -- 40+ 字段的 schema、渲染、读取（_deepImportGroups 迁来）
    ├── authorPreferencesForm.js -- 日更/字体/专注的渲染与保存
    └── fieldSourceLabel.js      -- 「已继承 / 已覆盖」标记与「恢复到全局默认」按钮
```

每个文件单一职责，互不依赖内部状态；视图通过 props 传数据、通过回传 payload。

### 6.2 视图职责

- **`globalSettingsView`**：渲染顶部状态条 + 全局 LLM 默认 section + 全局作者偏好 section + 引用此默认的项目列表（只读）+ 底部「手动迁移所有项目本地偏好」按钮；保存走全局 PUT。不渲染深度导入（D9）。
- **`projectSettingsView`**：渲染 Tab 切换 + 加载 effective 视图 + 把 source 元信息传给三个 Tab；保存走原项目 PUT，字段重置走单字段 DELETE。
- **三个 Tab**：纯渲染 + 读取，不含路由与数据来源逻辑。
- **`shared/*`**：渲染与读取单元，跨视图复用；`deepImportFields.js` 的 schema 是数据，未来可从后端下发，先抽离常量好接。

### 6.3 路由

`router.js` 新增两个路由：

- `settings` — 全局，无 currentProjectId 依赖
- `project-settings` — 项目，依赖 currentProjectId
- `llm` — 保留为 `project-settings` 的别名（向后兼容）

### 6.4 状态与迁移

`state.js` 新增 `globalSettingsCache`（owner 级缓存）。localStorage 旧 key `novel_author_preferences:<projectId>` 迁移规则（D20-D22）：

- 仅在项目作者偏好后端行为空（行不存在或全字段 NULL）时迁移
- 迁移目标为**项目覆盖**（不污染全局默认）
- 后端已有项目偏好值时跳过迁移并清掉旧 key（不覆盖后端）
- 后端不可达时保留旧 key 不抛，下次再迁
- 全局页「手动迁移所有项目本地偏好」按钮遍历所有 `novel_author_preferences:*` 批量迁
- 文档说明：未再打开的项目其 localStorage 不会自动入库，清浏览器缓存会丢失

`#/projects/<id>/settings` 从 URL path 取 project_id（D14），不依赖内存 `currentProjectId`：保证深链与书签可靠。

## 7. 错误处理与边界

- **URL 权威性**（D14）：`#/projects/<id>/settings` 从 URL path 取 project_id，不依赖内存 `currentProjectId`；选中后同步 state。
- **未选项目访问项目设置**：渲染空态 + 「返回全局设置」按钮，不发起任何 API 调用。
- **`#/llm` 无项目时**（D15）：rewrite 到 `#/settings` 全局页 + toast「请先选择项目」。
- **全局 LLM 默认尚不存在**：`GET /api/settings/llm-defaults` 返回 `null`，前端展示空白带「创建全局默认」按钮；首次保存即 upsert；effective 视图所有字段 source=`system`，UI 提示「未配置全局默认，使用系统内置默认」。
- **项目从未配过 LLM 时 effective 视图**：所有非 Key 字段 `source: "global"` 或 `system`，值回填；Key 状态为「未配置」（source=`unset`），是已知可接受初始态，UI 黄色提示「需配置项目 API Key 后才能实际调用 LLM」。
- **API Key 与继承 provider 的不一致警告**（D8）：项目 provider_id 或 base_url 来自 global/system 时，UI 在 Key 旁提示「当前供应商/BaseURL 来自全局默认，请确认 Key 与该供应商匹配」；后端调用 LLM 时不阻断，但日志记 `key_provider_mismatch: true` 审计字段。
- **保存 Key 空时 toast**（D17）：保存项目配置 + 全局默认但 Key 空时返回成功 + toast「Key 未配置，已保存其他字段」。
- **字段重置**：单字段 DELETE 把该列 UPDATE 为 NULL；前端从 effective 视图重读。批量「恢复全部」作为危险操作走二次确认 modal。`field_name` 服务端硬白名单，非白名单返回 400，不拼列名、不拼 JSON path。
- **deep_import 整体覆盖语义**（D6）：项目 `deep_import` NULL = 继承全局；有值 = 整体覆盖；UI「恢复到全局默认」按钮放在整个 Tab 而非每字段；子字段仍走 schema min/max 校验，失败单字段 toast 整体保存中止。
- **全局默认被改后影响范围**：所有 NULL 字段的项目自动继承新值（设计语义）；页面底部「引用此默认的项目列表」实时反映。
- **`projects-using-defaults` 口径与分页**（D18/D19）：只统计作者偏好默认；任一字段在 `project_author_preferences` 为 NULL 即列出；本期不分页，接口预留 `?limit=50&offset=0`，超过 100 时前端展示前 50 + 「更多项目省略」。
- **localStorage 迁移目标**（D20/D21/D22）：迁为**项目覆盖**；每项目迁自己的；仅在项目偏好行不存在/全 NULL 时执行迁移；后端已有值时跳过迁移并清旧 key（不覆盖）；首次打开迁，未再打开的不迁；全局页底部「手动迁移所有项目本地偏好」按钮遍历所有 `novel_author_preferences:*` 批量迁；清浏览器缓存仍会丢失未打开的项目旧偏好（已记录文档内）。
- **全局缓存失效**（D16）：全局保存后本地缓存失效 + effective 重拉；切 owner 缓存清；多标签页 `storage` event 通知刷新；`POST /api/settings/refresh` 调试端点。
- **novel_id 隔离**：所有 `/api/projects/<id>/...` 继续走现有 currentProjectId 校验中间件；`/api/settings/...` 靠 owner_id 隔离（demo 固定 `local`）。
- **API Key 安全**：全局默认后端实体永远不接收、不存 Key；项目保存沿用现 `api_key_configured` 布尔回显，不留明文，不写日志。
- **demo 阶段放宽项**：直接 drop 表重建；测试同步更新 schema、ORM、API、文档。

## 8. 测试

沿用 vitest 单测 + Playwright E2E 双轨。

### 8.1 后端单测（pytest）

- `test_global_llm_defaults_repo`：upsert、按 owner_id 隔离、Key 字段不存在
- `test_global_author_preferences_repo`：字段 NULL 语义；全局不存在时回退硬编码默认（`editor_font="system"`、`default_focus_mode=false`、`daily_goal=unset`）
- `test_project_author_preferences_field_reset`：单字段 DELETE 后该列 NULL，其他列不变；UNIQUE(project_id) 保证一行
- `test_project_author_preferences_row_not_exist`：`GET` 返回全 NULL 空对象（不是 404）
- `test_effective_llm_settings_merge`：项目 NULL 字段回退全局默认；项目有值优先；Key source 永远 `project` 或 `unset`，从不 `global` / `system`
- `test_effective_llm_settings_system_fallback`：全局默认不存在时所有非 Key 字段 source=`system`，回退代码内置默认
- `test_effective_deep_import_atomic_unit`：项目 deep_import NULL → source=`global` 或 `system`；项目有值 → source=`project` 整体覆盖
- `test_effective_author_preferences_merge`：同上语义
- `test_llm_settings_field_delete`：单字段 DELETE 把该列 NULL；非白名单字段返回 400；`api_key` 不在白名单
- `test_global_llm_defaults_rejects_api_key`：PUT payload 含 `api_key` 字段时后端拒绝/剔除，且不写入日志
- `test_llm_key_provider_mismatch_logging`：调用 LLM 时若 provider 来源层级与 Key 来源层级不一致，日志记 `key_provider_mismatch: true`
- `test_put_full_replace_semantics`：PUT 缺失字段置 NULL（=恢复继承），不做部分更新
- `test_global_settings_owner_isolation`：fixture 注入两个虚拟 owner_id，断言 owner A 看不到 owner B 的全局行（为账户系统接入预留回归断言）
- `test_projects_using_defaults_aggregation`：列出 NULL 字段项目；超过 100 时返回前 100 + 截断标记；断言排序与去重

### 8.2 前端单测（vitest）

- `globalSettingsView`：无 owner 时空态；保存走全局 PUT；调用 `/settings/projects-using-defaults` 渲染列表
- `projectSettingsView`：未选项目空态；Tab 切换；effective 视图 read，source 标签渲染正确
- `llmMainTab` / `deepImportTab`：渲染 + 读取 payload；min/max 校验；创作预设点击；schema 来源 `deepImportFields.js`
- `authorPreferencesTab`（两种形态）：全局版保存全局 PUT，项目版保存项目 PUT，"恢复到全局默认"调用字段 DELETE
- `fieldSourceLabel`：source=global/project 渲染对应标签与按钮
- `state.js` localStorage 迁移：旧 key 存在且后端可达 → 迁移成功清 key；后端不可达 → 保留 key 不抛

### 8.3 Playwright E2E

- 全局 → 项目跳转链路：`#/settings` 点「进入当前项目」跳到 `#/projects/<id>/settings`，Tab 切换渲染
- 作者偏好覆盖流：项目页设字体为 serif → 全局页改默认为 mono → 项目页仍显示 serif（覆盖生效）；项目页「恢复到全局默认」→ 重显 mono（继承生效）
- 字段级 source 标签：新建项目未配 LLM → 主配置 Tab 全字段标「已继承」；改 BaseURL 保存 → 仅该字段切「已覆盖」
- 深度导入校验：超 min/max toast 拒绝
- `#/llm` 兼容别名：旧 URL 仍可达且 rewrite 到 `#/projects/<id>/settings`
- 测试阶段数据库重建：所有 E2E 不依赖历史数据，独立 seed

### 8.4 Review 分级

按 testing-guide：前端 vitest 全模块跑；后端 pytest 受影响模块（settings 子域、projects 子域）全跑；E2E 跑配置相关两条回归路径。lint / typecheck 走项目既有命令。

## 9. 实施顺序提示

后续 `writing-plans` 会按以下顺序拆任务（仅作 brainstorming 阶段提示，正式 plan 以网状依赖为准）：

1. 后端表 + ORM + alembic + repo（三张表）
2. 后端 effective 接口 + 单字段 DELETE 接口 + pytest
3. 前端 `shared/*` 抽离（先无路由纯组件）+ vitest
4. 前端 `globalSettingsView` 路由 + 接口对接
5. 前端 `projectSettingsView` 路由 + 三 Tab + 接口对接
6. router.js 注册 + `#/llm` 兼容别名
7. localStorage 迁移逻辑
8. Playwright E2E 两条回归
9. 文档同步：`development-guide.md` 命令、`CONTEXT.md` 数据模型描述

## 10. 不引入与未来演化

- **不引入账户系统**：`owner_id` 当前用 nil UUID 占位（D10），未来账户接入后路由层加 authorizer，DB 无需改 schema；项目级表不带 owner_id（D11），靠 `project → owner` 关系未来追加。
- **不引入后端 env 在线写**：`DATABASE_URL`、`CORS`、`pool_size`、`EMBEDDING_DIM` 等保持 `.env` 管理。
- **本期全局深度导入默认不进任何 UI**（D9）：`global_llm_defaults.deep_import` 列保留但本期永不写入；未来需要全局默认时单独开 issue 暴露该字段编辑入口。
- **不引入多 owner 隔离运行时**：仅在测试预留断言，运行时 demo 阶段单 owner。
- **`#/llm` 别名将长期保留**，作为稳定书签入口；未来可视为永久别名。
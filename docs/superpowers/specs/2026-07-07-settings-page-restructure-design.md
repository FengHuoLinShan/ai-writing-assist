# 配置页设计

- 日期：2026-07-07
- 范围：全局设置页 + 项目级 LLM/深度导入配置页 重组
- 状态：待评审

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

后端新增三张表，所有表都带 `owner_id` 预留账户系统：

| 表 | 作用域 | 隔离键 |
|----|--------|--------|
| `global_llm_defaults` | 全局 LLM 默认（按供应商完整期望，不含 Key） | owner_id |
| `global_author_preferences` | 全局作者偏好默认 | owner_id |
| `project_author_preferences` | 项目级作者偏好覆盖（字段 NULL = 用全局） | project_id |

现有 `project_llm_settings` 表保留不变，新字段允许 NULL 以表达「继承全局默认」。

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
provider_id     VARCHAR
label           VARCHAR
base_url        VARCHAR
model           VARCHAR
timeout         INT
max_tokens      INT
temperature     FLOAT
top_p           FLOAT
extra           JSONB
creative_mode   VARCHAR   -- creative/precise/fast/custom
deep_import     JSONB     -- 全套深度导入参数当默认值
created_at      TIMESTAMPTZ
updated_at      TIMESTAMPTZ
```

不存 API Key — 全局默认只覆盖「接哪家供应商 + 走什么参数」。

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

### 4.4 现有 `project_llm_settings`

新增字段允许 NULL，含义同上。Key 字段维持现状（项目独有）。

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
| GET | `/api/projects/<id>/author-preferences` | 项目覆盖（可能全 NULL） |
| PUT | `/api/projects/<id>/author-preferences` | upsert |
| DELETE | `/api/projects/<id>/author-preferences/field/<field_name>` | 单字段重置回 NULL（恢复到全局默认） |
| GET | `/api/projects/<id>/effective-llm-settings` | 合并视图：每字段带 source 标签 |
| GET | `/api/projects/<id>/effective-author-preferences` | 合并视图：每字段带 source 标签 |

现有 `GET /api/projects/<id>/llm-settings` 和 `PUT /api/projects/<id>/llm-settings` 保留不变；`PUT` 现在只提交用户改过的字段（其他置 NULL），由后端攒字段语义落地。

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

- **`globalSettingsView`**：渲染顶部状态条 + 全局 LLM 默认 section + 全局作者偏好 section + 引用此默认的项目列表（只读）；保存走全局 PUT。
- **`projectSettingsView`**：渲染 Tab 切换 + 加载 effective 视图 + 把 source 元信息传给三个 Tab；保存走原项目 PUT，字段重置走单字段 DELETE。
- **三个 Tab**：纯渲染 + 读取，不含路由与数据来源逻辑。
- **`shared/*`**：渲染与读取单元，跨视图复用；`deepImportFields.js` 的 schema 是数据，未来可从后端下发，先抽离常量好接。

### 6.3 路由

`router.js` 新增两个路由：

- `settings` — 全局，无 currentProjectId 依赖
- `project-settings` — 项目，依赖 currentProjectId
- `llm` — 保留为 `project-settings` 的别名（向后兼容）

### 6.4 状态与迁移

`state.js` 新增 `globalSettingsCache`（owner 级缓存）。localStorage 旧 key `novel_author_preferences:<projectId>` 在首次加载项目作者偏好覆盖时一次性迁移到后端，迁移后清掉旧 key；后端不可达时保留旧 key 不抛，下次再迁。

## 7. 错误处理与边界

- **未选项目访问项目设置**：渲染空态 + 「返回全局设置」按钮，不发起任何 API 调用。
- **全局 LLM 默认尚不存在**：`GET /api/settings/llm-defaults` 返回 `null`，前端展示空白带「创建全局默认」按钮；首次保存即 upsert。
- **项目从未配过 LLM 时 effective 视图**：所有字段 `source: "global"`，值回填自全局默认；Key 状态为「未配置」是已知可接受初始态。
- **字段重置**：单字段 DELETE 把该列 UPDATE 为 NULL；前端从 effective 视图重读以拿新 source 和值。批量「恢复全部」作为危险操作走二次确认 modal。
- **全局默认被改后影响范围**：所有 NULL 字段的项目自动继承新值（设计语义）；页面底部「引用此默认的项目列表」实时反映，无需对每个项目单独操作。
- **深度导入 40+ 字段校验**：保留现有 `_readOptionalInt/Float` 的 min/max 校验链；失败给单字段 toast，整体保存中止。校验逻辑放 `deepImportFields.js` 全局默认页与项目页共用。
- **迁移失败**：localStorage 旧 key 后端不可达时保留不抛；不阻塞 Tab 渲染（先读后端，读不到再 fallback 解析 localStorage）。
- **novel_id 隔离**：所有 `/api/projects/<id>/...` 继续走现有 currentProjectId 校验中间件；`/api/settings/...` 靠 owner_id 隔离（demo 固定 `local`）。
- **API Key 安全**：全局默认后端实体永远不接收、不存 Key；项目保存沿用现 `api_key_configured` 布尔回显模式，不留明文，不写日志。
- **demo 阶段放宽项**：直接 drop 表重建；测试同步更新 schema、ORM、API、文档。

## 8. 测试

沿用 vitest 单测 + Playwright E2E 双轨。

### 8.1 后端单测（pytest）

- `test_global_llm_defaults_repo`：upsert、按 owner_id 隔离、Key 字段不存在
- `test_global_author_preferences_repo`：字段 NULL 语义
- `test_project_author_preferences_field_reset`：单字段 DELETE 后该列 NULL，其他列不变；UNIQUE(project_id) 保证一行
- `test_effective_llm_settings_merge`：项目 NULL 字段回退全局默认；项目有值优先；Key 不来源全局
- `test_effective_author_preferences_merge`：全局不存在时回退硬编码默认
- `test_global_settings_owner_isolation`：demo owner='local'，断言两虚拟 owner 互不可见（为账户系统接入预留回归断言）
- `test_projects_using_defaults_aggregation`：列出 NULL 字段项目，断言排序与去重

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

- **不引入账户系统**：`owner_id` 当前固定 `local`，未来账户接入后路由层加 authorizer，DB 无需改。
- **不引入后端 env 在线写**：`DATABASE_URL`、`CORS`、`pool_size`、`EMBEDDING_DIM` 等保持 `.env` 管理。
- **不引入全局深度导入默认独立管理页**：`global_llm_defaults.deep_import` 字段存默认值但不单独暴露 UI，由全局 LLM 默认 section 内联查看（避免再开一个 tab）。如果未来发现需要单独调，可后续拆出。
- **不引入多 owner 隔离运行时**：仅在测试预留断言，运行时 demo 阶段单 owner。
- **`#/llm` 别名将长期保留**，作为稳定书签入口；未来可视为永久别名。
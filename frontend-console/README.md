# 小说结构化创作控制台 — 前端

面向中文作者的**小说结构化创作控制台**，采用 Apple 极简 + 杂志留白风格的浅色主题，同时支持暗色模式。

## 快速启动

开发时使用 Vite dev server，支持 CSS 热更新和 JS/HTML 自动刷新。地图视图首次初始化时会按需从固定 CDN 加载 Leaflet，因此离线使用时需要确保浏览器可访问该资源。

```bash
cd frontend-console
npm install
npm run dev
# 打开 http://localhost:8080
```

常用验证脚本：

```bash
npm run test
npm run test:watch
npm run test:e2e
npm run test:e2e:smoke
npm run test:all
```

当前 `package.json` 未定义前端构建脚本，也没有独立 lint/format 依赖；前端验证以 Vitest、Playwright 和仓库级 diff 检查为主。

## 后端连接

前端默认连接 `http://localhost:8000/api`。

如需修改后端地址，可在页面加载前注入全局 `API_HOST`，或调整 `api.js` 中的默认地址。

## E2E 测试

Playwright 默认启动后端 `8000` 和前端 `8080`，可通过环境变量避开端口冲突：

```bash
BACKEND_PORT=8010 FRONTEND_PORT=8090 npm run test:e2e:smoke
```

后端地址可用 `API_HOST` 覆盖，支持 `http://localhost:8000` 或 `http://localhost:8000/api`。
如果 `webServer` 超时，先运行：

```bash
cd ../backend
python scripts/doctor.py --json
```

## 文件结构

```
frontend-console/
├── index.html              # 单页应用入口
├── styles.css              # 完整样式表（浅色主题 + 暗色模式，设计 Token 驱动）
├── state.js                # 全局响应式状态管理
├── stateSlices.js          # 状态副作用、listener 通知、DOM 同步调度 helper
├── api.js                  # API 封装（projects/world/rag/context/writing/imports/tasks）
├── apiContracts.js         # vanilla JS 共享 API 契约注册表（高风险 wrapper 子集）
├── router.js               # Hash 路由系统
├── commands.js             # 命令系统（全中文帮助）
├── app.js                  # 应用主入口（快捷键绑定）
├── shared/                 # 可复用业务组件与工具
│   ├── smartDedup.js       # 智能去重管理器
│   ├── confirmAsync.js     # 异步二次确认封装
│   ├── writingToolsResult.js # 工具结果应用到 orchestrator
│   ├── sceneLocator.js     # 光标/章节定位当前 Scene
│   └── ...                 # 其他共享模块
├── views/                  # 一级路由视图
│   ├── projectView.js      # 项目
│   ├── writingView.js      # 写作台 orchestrator
│   ├── writing/            # 写作台子模块
│   │   ├── chapterTree.js
│   │   ├── editor.js
│   │   ├── versions.js
│   │   ├── publish.js
│   │   ├── deepImportRecovery.js
│   │   ├── autoExtraction.js
│   │   ├── conflictCheck.js
│   │   ├── scenePanel.js
│   │   ├── outlineFloat.js
│   │   ├── focusMode.js
│   │   ├── tools.js
│   │   ├── mobileQuickNote.js
│   │   └── submodules.js   # 子模块工厂
│   ├── worldView.js        # 世界对象 / 关系 / 别名 / 地图子标签
│   ├── mapWorkspaceView.js # 地图一级工作台
│   ├── mapView.js          # 动态地图主视图
│   ├── mapState.js         # 地图前端会话状态
│   ├── mapHexRenderer.js   # 六边形渲染
│   ├── mapEditPanel.js     # 地图编辑面板
│   ├── mapRouteContext.js  # 地图路由上下文
│   ├── outlineView.js      # 剧情结构
│   ├── sceneWorkbenchView.js # Scene 一级工作台
│   ├── ragView.js          # RAG 检索
│   ├── contextView.js      # 旧上下文页代码；当前 hash 入口重定向到生成中心任务页
│   └── generateView.js     # 生成中心
├── tests/                  # 测试目录
│   ├── writing/            # 写作台子模块单元测试
│   └── shared/             # shared 模块测试
└── README.md
```

## 技术栈

- 纯原生 HTML + CSS + JavaScript
- 无前端框架；地图视口按需加载 Leaflet（ADR-0003）
- 所有 UI 文字为中文
- 浅色主题（#F5F5F7）为主，支持暗色模式

## 路由与设置

- 一级路由包含 `project`、`writing`、`world`、`map`、`outline`、`scene`、`rag`、`generate`、`settings`、`project-settings`。
- `settings` 是无项目也可访问的全局设置页；`project-settings` 管理当前项目的 LLM 主配置、深度导入参数和作者偏好。
- 旧 `llm` 入口会按当前项目状态跳转到 `project-settings` 或 `settings`。
- 旧 `context` hash 不再是一级页面，路由层会重定向到 `generate?tab=task`。

## 安全与契约

- `index.html` 配置 CSP meta baseline：脚本仅允许本源和 Leaflet CDN，连接仅允许本源及本地开发后端；`style-src` 暂保留 inline style 兼容。
- 动态内容默认使用 `textContent`；必须拼 HTML 时先走 `esc()`。
- 当前已落地 vanilla JS 共享 API 契约校验第一阶段：`apiContracts.js` 注册高风险 wrapper 的 method/path/query/body/timeout，`api.js` 对应 wrapper 消费该 registry，Vitest 覆盖加载顺序与代表 endpoint 映射。
- TypeScript / OpenAPI codegen 仍是未来设计项；当前契约层不覆盖响应字段级 schema drift，设计记录见 `docs/frontend/typescript-api-contracts.md`。

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `?` | 打开快捷键帮助 |
| `:` | 聚焦命令栏 |
| `/` | 搜索 |
| `Esc` | 返回 / 关闭弹窗 |
| `j` / `k` | 上下移动选择行 |
| `n` | 新建 |
| `e` | 编辑 |
| `s` | 保存 |
| `g` | 生成 |
| `r` | 复查 |
| `c` | 确认 |
| `x` | 删除（二次确认） |

## 管理页批量操作约定

- 列表型管理页支持多选、当前可见列表全选和批量工具条，包括项目、世界对象/候选/关系/别名、剧情结构、Scene 工作台、写作章节树和地图列表。
- “全选”只作用于当前可见列表或当前分页，不跨分页选择全部筛选结果。
- 删除、忽略、永久删除等危险批量动作必须二次确认；执行后会显示成功/失败数量。
- 候选对象和世界对象的“合并”是行内主操作，不放在更多菜单里；没有明确目标对象时需要先搜索并选择目标。
- RAG、Context、Generate 等状态/生成页面不强制提供批量操作，只保留清晰的空状态、错误状态和任务进度。

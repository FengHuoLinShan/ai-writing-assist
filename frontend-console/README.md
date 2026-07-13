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

Playwright 默认复用本机已有的后端 `8000` 和前端 `8080`，没有服务时会自行启动。可通过环境变量避开端口冲突：

```bash
BACKEND_PORT=8010 FRONTEND_PORT=8090 npm run test:e2e:smoke
```

涉及数据库 schema 的 E2E 应使用 fresh server 路径，确保后端启动前执行 `APP_ENV=test alembic upgrade head`：

```bash
PW_REUSE_EXISTING_SERVER=0 npm run test:e2e
BACKEND_PORT=8010 FRONTEND_PORT=8090 PW_REUSE_EXISTING_SERVER=0 npm run test:e2e
```

如果默认端口已有旧服务，先停止旧服务，或像上面一样指定备用端口。`scripts/e2e-servers.sh` 也是 E2E 专用入口，会先迁移 test 数据库再启动 backend；通用 `backend/scripts/dev_server.py` 不自动迁移。

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
│   ├── worldView.js        # 世界对象 / 关系 / 别名 / 世界书 / 地图子标签
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

- 项目回收站支持单个恢复、单个永久删除、批量恢复和批量永久删除；永久删除必须二次确认，批量删除使用后端原子接口，不做部分成功。回收站每页 20 条，桌面端大模态框用双列完整展示当前页，并提供上一页、下一页和总数。
- 一级路由包含 `project`、`writing`、`world`、`map`、`outline`、`rag`、`generate`、`settings`、`project-settings`；Scene 工作台位于 `outline/scenes`，旧 `scene` 路由会自动跳转到该入口。
- Scene 工作台的“场景（scene）自动提取”和“智能去重”与大纲子标签同行，去重只保留一个入口。每行根据当前最高优先级待办切换主按钮；桌面端额外保留“编辑”，移动端收敛为主按钮与更多菜单。健康标签可点击，跨章建议刷新后从后端恢复。
- Scene 融合与拆分使用大尺寸字段对比表，完整展示 AI 建议、原 Scene 引用、叙事标签、POV 和章节映射；默认显示全部字段，可只看服务端初始预览中的差异。融合预览属于同步 LLM 请求，使用 90 秒生成窗口，不受普通 API 的 15 秒超时限制。长来源证据按需展开，AI 建议始终可见。叙事标签统一用 `draft` 表示“未标注”，拆分时显式清空的字段会按空值保存。废弃融合来源需要在预览内再次确认；保存请求期间所有融合操作保持锁定，失败后恢复控件并保留当前编辑内容。
- 深度导入和 Scene 自动提取任务以 `taskId + projectId` 持久化；查询与取消都显式携带 `novel_id`。Scene stage 百分比是基于历史实测的耗时估算，Phase 0 只显示准备状态。Scene 工作台轮询只局部更新进度卡，不重绘正在浏览的列表。运行中的进度卡可在二次确认后取消当前任务；瞬时查询失败保留恢复记录，只有明确 404 或用户关闭时清理失败/已取消任务。
- 共享任务卡只在后端 `available_actions` 包含 `retry` 时显示重试；`restart_origin` 与深度导入 `resume/abandon` 继续走各自领域流程。
- 生成中心自定义模板可查看修订历史并把旧版本载入编辑器；载入不写库，仍需用户明确保存。
- 前端依后端契约分页或拦截超限请求：Scene 建议每次最多忽略 100 条，地图分组每次最多处理 100 条，地形修改每次最多 10000 格，单地点每次最多绑定 5000 格；不会通过多请求静默产生部分成功。
- 生成中心与世界书 AI 每次最多附带 20 章正文，长对话只发送最近 40 条消息；页面历史不因请求上限被删除。
- 写作台自动保存以编辑序号保护请求期间的新输入；版本切换触发局部重绘时不会用旧响应覆盖正文。恢复历史正文时保留选择当时的最新版本快照，发布前若其他会话已更新则提示 409 冲突。
- RAG 索引维护的技术诊断区可按需加载隐私安全的检索追踪摘要，不展示 raw query 或正文。
- 小说检索的智能/字面模式都按章节聚合同章结果：智能模式解释为语义相关性检索，字面模式解释为完全一致文字匹配；结果卡显示该章聚合的相关片段数或出现次数。
- `settings` 是无项目也可访问的全局设置页；`project-settings` 管理当前项目的 LLM 主配置、深度导入参数和作者偏好。主配置中的“默认输出上限”由非深度导入业务调用继承，系统默认 `12000`；深度导入继续显示并使用自己的阶段预算。
- 旧 `llm` 入口会按当前项目状态跳转到 `project-settings` 或 `settings`。
- 旧 `context` hash 不再是一级页面，路由层会重定向到 `generate?tab=task`。

## 内容优先布局

- 写作、Scene、世界书、地图和生成中心采用统一的内容优先分栏；桌面端正文、主列表、编辑区或画布获得约三分之二的可用宽度。
- 辅助栏使用统一的主题化折叠控件，折叠选择按项目和页面保存在当前浏览器会话中；写作专注模式仍优先隐藏两侧栏。
- 中等宽度会重排第三栏，`760px` 及以下改为单栏、抽屉或手风琴；折叠控件完整支持浅色、暗色、键盘焦点和减少动效偏好。
- 任务进度默认显示紧凑摘要、状态和细进度条；失败、恢复或需要用户确认的状态自动展开，用户手动选择在任务重绘时保持。

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

- 列表型管理页支持多选、当前可见列表全选和批量工具条，包括项目、世界对象/待处理项/关系/别名、剧情结构、Scene 工作台、写作章节树和地图列表。
- “全选”只作用于当前可见列表或当前分页，不跨分页选择全部筛选结果。
- 删除、忽略、永久删除等危险批量动作必须二次确认；执行后会显示成功/失败数量。
- 普通待处理对象的“合并”是行内主操作，不放在更多菜单里；没有明确目标对象时需要先搜索并选择目标。由建议队列拥有的兼容影子只通过建议采用/忽略，不直接修改影子对象。
- RAG、Context、Generate 等状态/生成页面不强制提供批量操作，只保留清晰的空状态、错误状态和任务进度。

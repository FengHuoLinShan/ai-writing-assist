# 小说结构化创作控制台 — 前端

面向中文作者的**小说结构化创作控制台**，采用 Apple 极简 + 杂志留白风格的浅色主题，同时支持暗色模式。

## 快速启动

直接打开 `index.html` 即可。地图视图会从 CDN 加载 Leaflet，因此离线使用时建议先启动本地服务器并确保浏览器可访问该资源。

```bash
cd frontend-console
# 方式 1：直接双击 index.html
# 方式 2：使用 Python 启动本地服务器
python -m http.server 8080
# 打开 http://localhost:8080
```

## 后端连接

前端默认连接 `http://localhost:8000/api`。

如需修改后端地址，修改 `api.js` 中的 `API_BASE_URL`。

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
├── api.js                  # API 封装（projects/world/rag/context/writing/imports/tasks）
├── router.js               # Hash 路由系统
├── commands.js             # 命令系统（全中文帮助）
├── app.js                  # 应用主入口（快捷键绑定）
├── views/                  # 8 个一级路由视图 + 地图拆分组件
│   ├── projectView.js      # 项目
│   ├── writingView.js      # 写作台
│   ├── worldView.js        # 世界对象 / 关系 / 别名 / 地图子标签
│   ├── mapWorkspaceView.js # 地图一级工作台
│   ├── mapView.js          # 动态地图主视图
│   ├── mapState.js         # 地图前端会话状态
│   ├── mapHexRenderer.js   # 六边形渲染
│   ├── mapEditPanel.js     # 地图编辑面板
│   ├── mapRouteContext.js  # 地图路由上下文
│   ├── outlineView.js      # 剧情结构
│   ├── ragView.js          # RAG 检索
│   ├── contextView.js      # 上下文编译
│   └── generateView.js     # 生成中心
└── README.md
```

## 技术栈

- 纯原生 HTML + CSS + JavaScript
- 无前端框架；地图视口使用 Leaflet（ADR-0003）
- 所有 UI 文字为中文
- 浅色主题（#F5F5F7）为主，支持暗色模式

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

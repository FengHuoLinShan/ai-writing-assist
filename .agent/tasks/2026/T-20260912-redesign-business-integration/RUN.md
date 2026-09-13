# 本地演示入口

当前运行的真实产品：<http://localhost:8080/>。原型对照：<http://localhost:8097/prototypes/redesign.html>。

采用当前仓库代码，读取已有独立演示环境与账户连接。`run-local.py`只含路径和运行逻辑，不含密钥；显式固定到持久演示库，不自动迁移或清库。运行前确认端口没有已有服务，避免重复启动。

如需重新启动，在仓库根目录使用现有演示Python依次检查，再在各自终端启动后端与worker：

```sh
DEMO_PY='/Users/tywww/Desktop/NovelCraft-诡秘地图演示-20260909/完整项目演示/app/backend/.venv/bin/python'
"$DEMO_PY" .agent/tasks/2026/T-20260912-redesign-business-integration/run-local.py guard
"$DEMO_PY" .agent/tasks/2026/T-20260912-redesign-business-integration/run-local.py backend
```

另一个终端（同一仓库根目录）：

```sh
'/Users/tywww/Desktop/NovelCraft-诡秘地图演示-20260909/完整项目演示/app/backend/.venv/bin/python' .agent/tasks/2026/T-20260912-redesign-business-integration/run-local.py worker
```

前端终端：

```sh
cd frontend-console
npm run build
node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 8080 --strictPort
```

现有Docker数据库/对象存储保持运行；不要通过测试清理fixture管理这个演示库。启动脚本的guard已在本次真实环境运行通过。

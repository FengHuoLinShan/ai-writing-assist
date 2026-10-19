# ADR-0043：完整本地桌面分发

- 状态：Accepted
- 日期：2026-10-18
- 决策范围：用户确认完整本地运行、macOS/Windows 都支持，允许更轻存储，无需旧数据迁移。
  工程实现与各平台验收独立记录，不由 Accepted 状态推断已交付。

## 决策

复用 Vue 正式构建和 Python/FastAPI，以 pywebview 原生窗口与 PyInstaller 分发；
不改写业务前端，也不新增 Rust/Node 常驻业务运行时。共同代码按目标 OS/架构构建。

首版内置 PostgreSQL 17、pgvector/pg_trgm 和离线 ONNX 模型，保留队列、锁、事务和检索契约。
SQLite 是后续候选，当前测试回退不证明产品并发和检索等价。
图片经 World 自有接口写本地私有文件；服务器仍用既有 S3 配置。
本地图片路径仅允许 APP_ENV=local/AUTH_MODE=local。桌面不依赖 Docker、MinIO 或服务器。

监督进程独占数据目录，使用实例凭据与稳定 loopback origin，不继承开发库或环境配置，
不扫描端口终止其他程序。作品、密钥与 WebView 配置位于用户私有目录，
更新/卸载程序不删除作品。GUI 管道断开触发所属服务的有界关闭；
业务写入、来源重验、候选采用、owner 与 novel_id 门禁保持原契约。

项目未上线，不建设旧库迁移兼容、生产配对备份或自动更新服务。
首次初始化使用当前 schema；备份产品方案另定，不自动导入/重建开发库。

## 主要发布路径

2026-10-19 用户收敛方向：本地桌面应用成为后续默认开发和交付形态，放弃独立前后端产品模式。
保留 Vue/FastAPI/PostgreSQL 作为应用内部模块，不重写业务栈。
`make dev` 与 start.sh 运行桌面源码，开发数据独立于安装版作品；旧服务器工具仅供显式诊断/历史运维，
不自动迁移或清理旧数据。PR/main 保留源码、数据库、安全和功能回归，不自动构建安装包或服务器镜像。
`desktop/VERSION` 是桌面产品版本的唯一来源，独立于内部 backend/frontend 包版本。
从已通过 CI 的 `origin/main` 固定 SHA 手动构建，默认仅 macOS ARM64；
macOS x64、Windows x64 或 all 须当次明确选择，只为所选平台执行原生构建与安装验收。
来源、摘要和签名验证不因单平台而降低，缺所选平台或混入其他平台均停止。生成摘要与来源清单，
经 Release 草稿复核再发布。版本不覆盖，稳定版须通过代码签名（Mac 另需公证），
预览版明确限制；版本管理与证书配置见 [桌面发布流程](../../desktop/RELEASE.md)。
这不授权自动合并 main、公开发布、付费证书采购或修改现有服务器部署门禁。

## 验收边界

源码启动、冻结 runtime、系统安装器、原生窗口和签名/公证分别验收。
macOS ARM64 证据不代表 Intel 或 Windows；工程 smoke 不代表真实模型或作者验收。
构建、目录、凭据与限制以 [desktop README](../../desktop/README.md) 为说明源。

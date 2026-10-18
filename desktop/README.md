# NovelCraft 本地桌面版

复用现有 Vue 前端、FastAPI、PostgreSQL 17/pgvector/pg_trgm 和后台任务系统。
Python 原生 WebView 承载正式前端构建；图片写入本机私有文件目录。
安装包包含 Python、数据库与本地检索模型，最终用户不需要安装 Docker、Python、Node
或自行配置服务器。业务 AI 仍需用户在应用内配置并验证模型连接；
原生订阅 CLI 不是本安装包捆绑组件。

桌面安装包是主要交付物；[版本与发布流程](RELEASE.md) 定义发布操作与验收门禁。

共同源码分别生成 macOS Apple Silicon、macOS Intel 和 Windows 10 1903+/11 x64 产物。
构建流程存在不等于所有平台已验收，实际证据与未完成项见
[任务记录](../.agent/tasks/2026/T-20261018-desktop-local-app/TASK.md)。

## 数据与访问

- macOS 数据目录：~/Library/Application Support/NovelCraft/。
- Windows 数据目录：%USERPROFILE%\AppData\Local\NovelCraft\。
- database/ 保存作品、历史、任务和设置；images/ 保存私有图片。
- secrets.json 保存本实例数据库密码与模型凭据加密密钥，必须与数据库一起保留。
- 原生服务只监听 loopback。API 与前端共用稳定本机端口，保留 WebView 的草稿和阅读状态。
  每次启动更换会话令牌，通过一次性入口设置 HttpOnly/SameSite Cookie；
  校验 Host 与写请求 Origin，保留 owner、novel_id 和领域确认门禁。
  启动探针校验实例 HMAC，不向可能抢占端口的程序发送会话令牌。
- 单实例锁阻止并发打开同一数据目录。GUI 断开管道后，监督进程关闭所属
  worker/API/数据库；不按端口扫描终止其他程序。
- 退出需确认，本地任务停止。未知模型请求遵守既有恢复规则，禁止静默重放。
- 启用原生 WebView 下载，文稿与图片导出仍通过保存对话框选择位置。
- 安装目录不保存作品，卸载程序不删除数据。未提供跨设备同步。

项目未上线，本轮不做旧开发库导入、跨版本数据迁移或生产备份兼容。
从新的独立目录初始化当前 schema，不自动读取、认领或删除现有开发数据。
本轮不提供自动备份/恢复产品功能，备份方案另定；不能把“文件存在”显示为“已备份”。

## 开发构建

在独立 worktree/虚拟环境执行，避免替换正在运行的业务环境：

~~~sh
uv sync --project backend --locked --extra desktop --extra ci
uv run --project backend --no-sync python desktop/build.py
uv run --project backend --no-sync python desktop/smoke.py --frozen
~~~

macOS 需 Xcode Command Line Tools；Windows 需 Visual Studio C++ 工具环境、
meson==1.12.1、ninja==1.13.2 与 winflexbison3，设置 CC=cl/CXX=cl。
开发工具不进入最终用户安装流程。
Windows 数据库程序使用进程内 UTF-8 manifest，支持中文安装/数据路径，不修改系统区域设置。
冻结 Python 解释器固定使用 UTF-8；源码构建/测试也以 PYTHONUTF8=1 启动。
Windows 经 pg_ctl 的受限 token 启动数据库，即使父进程有管理员权限也不绕过 PG 安全检查；
监督器保存并验证该数据库的原生进程句柄。
Intel Mac 构建使用 Python 3.13.15（uv sync 加 --python 3.13.15），固定最后提供 Intel
wheel 的 ONNX Runtime 1.23.2；Apple Silicon/Windows 使用锁定的当前版本。
固定 PostgreSQL/pgvector 源码 SHA256、模型 revision 和权重 SHA256；
模型在构建阶段下载，应用检索无需首次联网下载模型。
依赖版本和摘要写入随包分发的 manifest.json，并分发许可证。
PyInstaller 打包窗口程序和独立 console runtime，使子进程可以正常使用标准输入。

macOS 应用位于 desktop/dist/NovelCraft.app，CI 另生成 DMG。
Windows 通过 windows.iss 生成每用户安装器，内含固定摘要的 Microsoft WebView2 bootstrapper；
中文安装文本按固定上游 revision/摘要获取，不依赖构建机另外安装语言包。
系统缺少 WebView2 时首次安装需要联网，不要求用户自行安装运行环境。
安装器检查 Microsoft 公布的注册表版本键，已有 Runtime 时不重复安装。
未配置代码签名/公证时只是开发测试包，不能宣称普通用户的无警告安装已完成。

.github/workflows/desktop.yml 分别构建三平台并运行冻结程序 smoke，再上传产物；
普通构建不发布 Release、不部署、不使用真实稿件或调用业务 LLM。
desktop-release.yml 仅从已通过 CI 的固定 main SHA 调用同一构建，汇总校验后创建 Release 草稿；
公开发布是独立的人工操作。稳定版强制签名（Mac 含公证），预览版明确标注。
smoke 使用专用临时目录，验证本地模型推理、会话保护、创建作品、重复启动、退出和重启。
Windows CI 还实际静默安装、运行安装目录内的程序并卸载。
失败保留隔离证据，成功只删除该次专用测试目录。

SQLite 目前只有测试/检索回退，不构成完整产品支持。换库需要验证任务领取、
CAS/采用、提交冲突和检索规模，不能仅更换数据库连接 URL。

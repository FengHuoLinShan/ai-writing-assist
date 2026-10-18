---
id: T-20261018-desktop-local-app
title: macOS 与 Windows 完整本地桌面应用
status: active
created: 2026-10-18T19:42:17+08:00
updated: 2026-10-18T21:10:26+08:00
---

# 完整本地桌面应用

## 恢复快照

- 工作区：/Users/tywww/.codex/worktrees/desktop-local-app/ai-writing-assist，codex/desktop-local-app，基线 083843474e9880252fe4bfca1b1a7132262dc9b6。其他工作树 WIP 未动；代码已提交推送，草稿 PR #256：https://github.com/FengHuoLinShan/ai-writing-assist/pull/256，未合并/发布。
- 实际完成：desktop 运行/打包/安装器/三平台 workflow、本地图片、OS 安全与锁、文档已实现。源码与首轮冻结 macOS ARM64 smoke 通过，World 全模块 1570 测试通过。
- 当前里程碑：macOS ARM64 冻结搬移 smoke、真实窗口中文工作稿保存/退出/重开、DMG 挂载结构与 ad-hoc codesign 完整性通过；三平台 CI 修复中。
- 下一步：检查 PR #256 最新 Desktop installers run 的三平台日志，修复原生构建/冻结 smoke 的实际故障，再取回安装器。
- 未完成：Windows/Intel 实际构建与验收、签名/公证与正式发布。不能用 ARM64 代表其他平台。

## 目标与验收

- 用户确认完整本地运行，macOS/Windows 都要；允许 SQLite 等更轻存储；项目未上线、无用户，不做旧数据迁移，备份另定。
- 用户无需安装 Docker/Python/Node 或配置数据库/服务器。AI 仍须在程序内配置已验证模型连接；原生订阅 CLI 不捆绑。
- 私有新数据目录、单实例、loopback 鉴权、正常关闭/任务有界排空、持久化重开和浏览器状态保护。
- 不建设旧库导入、跨版本兼容、生产备份、自动更新或远程服务。不读/认领/重建现有开发库。
- 只用合成测试，不调用真实业务模型，不读取作品、账户密钥或 CLI 登录态。

## 上下文与关键决定

- 方案和边界：desktop/README.md、docs/adr/0043-local-desktop-distribution.md。
- pywebview/PyInstaller 复用 Python 与 Vue 正式构建；GUI 与 console runtime 分开打包。
- SQLite 的隔离迁移探针在当前入口报 MissingGreenlet；现有队列/并发依赖 PG 行锁，向量有 Python 回退但不能证明并发/规模等价。首版内置 PostgreSQL 17/pgvector/pg_trgm，SQLite 保留候选。
- 图片用 World 私有 LocalImageClient，不依赖 MinIO/Docker；保留 PNG/owner/novel_id/引用清理边界，原子写入并拒绝穿越/符号链接。
- 固定 PostgreSQL 17.10、pgvector 0.8.6 源码与 SHA256、BGE ONNX revision/权重摘要。ONNX 补齐 token_type_ids 并限制到 BGE 512 token；不更改池化或 embedding 身份。
- os_security.py：POSIX 保留 UID/权限/no-follow/flock，Windows 验证 ACL 并用 msvcrt。POSIX Codex 账户指纹保持不变。
- 稳定 loopback origin 保留 WebView 数据，每次新令牌、一次性入口、HttpOnly/SameSite Cookie、Host/写 Origin 校验。本机探针禁用代理。
- GUI 关闭管道触发所属服务有界退出；os.read 读取 EOF，避免 daemon BufferedReader 解释器关闭死锁。
- 打包需收集业务 JSON/源码等资源，特别是 forecast/capabilities.json 和 companion 源码。
- 运行时复用默认宿主模型准入锁目录，已移除桌面私有目录覆盖，避免分裂账户并发池；单测覆盖。

## 进度

- [x] 调查、隔离 worktree、实现前 docs-check。
- [x] 本地运行、存储与平台适配实现。
- [x] 固定依赖、安装器及 CI 定义。
- [x] 源码与首轮冻结 ARM64 smoke。
- [x] 最终搬移 smoke、原生窗口、DMG。
- [ ] Windows/Intel 实际构建与安装验收。
- [ ] 签名/公证/正式发布，不能以构建配置存在宣称完成。

## 验证证据

- World 全模块：1570 passed，1 deselected，1 warning；日志 desktop/build/world-tests.log（生成文件忽略）。
- 图片/config/worker 针对性：226 passed；embedding/worker/desktop：119 passed。
- Codex 身份/真实跨进程准入/模型池/desktop：80 passed（runtime 单测新增前）。
- desktop/tests 最新 6 passed / 1 Windows-only skipped（Mac）；Windows 6 tests 已通过，包含真实 ACL 反例，含会话、真实锁死亡释放和稳定 origin/不继承凭据。
- 前端正式 build 与 production asset verification 通过，未改前端业务代码。
- backend/desktop Ruff、git diff --check、文档完整性通过。
- 文档 BASE_REF 差异检查通过显式 no-change-reason 复核未变的 CLAUDE 导入层、维护协议与业务模块图；未弱化门禁。
- 首次冻结暴露业务 JSON 漏包与 BufferedReader 关闭故障，修复后完整冻结 smoke 通过。
- 曾并行打包和 smoke 导致库文件正在替换，不算有效产品验收；后续必须串行。
- 本机默认编译 minos 26.0 已纠正到 14.0。最终搬移冻结 smoke 已通过，含中文路径、中文 pg_trgm 与 vector 运算。
- PG17 的 pg_trgm 字符分类仍使用 OS；builtin C.UTF-8 排序之外显式设置 Unicode LC_CTYPE，真实 SQL 断言通过。
- 原生窗口试验发现 WebView 可先创建非私有根目录，现已将私有根目录创建移到 GUI 初始化前并增加单测；修复后原生窗口验证通过，中文正文真实持久化重开。

## 交付边界

本地实施中。无真实模型/作者验收、无生产部署或正式发布；其他平台和签名明确未完成。

## 跨平台构建发现

- 首轮 macOS fresh runner 无 pg_config，不能在未编译前 make clean；现在仅对已有前缀执行清理。
- 新 ONNX Runtime 不再提供 Intel Mac wheel；Intel 使用 Python 3.13 + ONNX Runtime 1.23.2，其他架构保持当前锁定版本。
- Windows elevated process 默认属主可为 Administrators；校验可信 user/SYSTEM/Administrators 属主，同时 DACL 仍禁止其他账户，新增真实 ACL 反例测试。
- 本地 DMG：desktop/dist/NovelCraft-ARM64.dmg，构建源 4c356a5c5；后续修改主要为构建/Windows，正式取最新 CI 包；本地 SHA256 b2208cb62708364dca207fa37fd375ed31fab409b1863a99114052cac11dd9a5。
- GUI 专用合成目录路径保存在 ignored desktop/build/gui-session.json。首次 CUA 自动启动曾创建空默认 NovelCraft/webview；仅将该空根目录收紧到 0700，没有读写其他数据。

- Windows 下一轮构建已到 Meson：runner 的 VS 安装版本发生变化，旧硬编码路径未加载 MSVC，且缺 flex/bison；改为 vswhere + vcvars64 + CC/CXX=cl，并安装 winflexbison3。
- 安全复查补齐启动证明：loopback readiness 只返回实例 HMAC，监督进程校验，不向抢占端口的程序发送会话 Cookie；API/页面仍要求会话。源码 smoke 复验中。
- 关闭失败路径：pg_ctl 不可用仍终止自己启动的进程并释放锁；真实子进程反例单测通过。

- CI run 39128124674（5ca4c54fe）：ARM64 与 Intel Mac 构建、冻结 smoke 和 DMG 上传均通过。Windows 已完成 MSVC 原生编译和冻结，离线模型通过，但 supervisor 首启退出；原 stderr 未打印，下一轮已补脱敏日志。
- 已为 Windows 原生 PG EXE 加入进程 UTF-8 manifest（Windows 10 1903+），避免窄字符入口丢失中文安装路径；这是依据源码/系统 API 的修复假设，等待真实 smoke。
- pywebview 默认禁用下载，已显式开启；Mac 原生保存对话框导出合成中文正文成功，UTF-8 文件内容已核对，保存在项目 output/desktop-20261018/NovelCraft-desktop-export-check.txt。
- worker liveness 原来调用 Windows 不存在的 fchmod、使用 /tmp；现在 Windows 用用户私有 AppData marker + ACL，POSIX/Docker 契约不变，加入跨平台 CI 复用原有 atomic marker 测试。
- 当前最新本机 bundle 在 ignored desktop/build/final-dist，前一版 desktop/dist 的 GUI 被 CUA AX 查询重新拉起为默认数据目录的空白演示实例，可留供用户查看；不要并发覆盖该 bundle。当前 output DMG 尚需更新为开启导出的包。

- CI run 39129339966 的 Windows failure 发生在新复用的 backend/conftest 导入：capabilities.json 被系统默认 CP1252 解码。已将源码构建/测试 PYTHONUTF8=1，冻结两个 EXE 固定 X utf8；仅设置环境不足以影响 PyInstaller 的隔离解释器。
- PostgreSQL 源码 check_root 明确拒绝 Windows elevated token；Windows 改用 pg_ctl 自带的 restricted token 启动，保存 postmaster.pid 对应进程句柄并校验精确 exe 身份。新 Windows-only 测试用真实拥有的 ping 子进程验证身份不符不终止、wait timeout 和精确句柄终止。不能绕过 PG 的安全检查。
- 本机最新包再次搬移 smoke 通过，包含导出开关和 BGE MIT 许可证；当前还需重打含最新平台启动修复的最终包。

- Windows run 39129851048：8 个 desktop 测试通过（含真实句柄身份/超时/终止），复用 liveness 测试失败在 pytest 临时目录 ACL 不符合私有目录契约。测试 fixture 改为专用子目录；smoke 同理在临时 workspace 下显式创建 private_directory 子目录，不放宽 OS 安全检查。这也解释了此前 supervisor 首启可能在 temp ACL 校验即退出。
- 运行初始化命令也使用 CREATE_NO_WINDOW，避免弹出辅助控制台。

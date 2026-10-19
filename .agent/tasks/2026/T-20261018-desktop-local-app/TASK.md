---
id: T-20261018-desktop-local-app
title: macOS 与 Windows 完整本地桌面应用
status: active
created: 2026-10-18T19:42:17+08:00
updated: 2026-10-19T01:42:20+08:00
---

# 完整本地桌面应用

## 恢复快照

- 工作区：/Users/tywww/.codex/worktrees/desktop-local-app/ai-writing-assist；本地分支codex/desktop-local-app，HEAD511e9e1a47285fcb5558e23cecbf23e90561074e。仅本任务笔记未提交，未覆盖原项目工作区。
- 本轮用户明确授权审查、修复并在无阻断后合并main。按code-review双轴+ponytail-review完成完整diff与关联调用链审查；两个只读审查者复核修复后无阻断。
- 修复4c7cccb14+511e9e1a4：真实Mac包因COLLECT继承console runtime而错设LSBackgroundOnly=True，现显式False，Mac两架构smoke从实际冻结包Info.plist验证；源码desktop roles原会补读backend/.env，现共用load_env_file在监督器token存在时跳过，普通模式保持。合成dotenv回归在旧代码失败、新代码通过；未读取真实.env内容/调用业务模型。
- 本地相关226 passed/2 Windows-only skipped，源码完整smoke通过，backend工作目录完整Ruff及desktop Ruff通过。4c最初backend CI仅import分组失败（root运行ruff判断不同），511修复并重验；没有削弱门禁。docs inventory、BASE_REF支持的no-change-reason复核及diff检查通过。
- 最终HEAD全部21项PR检查成功：Backend39149275992为9222 passed/2 skipped、coverage85.3%，deploy323 passed/1 skipped、PostgreSQL通过；Frontend39149275897全单测/构建和两片浏览器通过；native39149275928三平台全通过，Mac实际普通App声明与冻结smoke、Windows真实安装/运行/卸载通过。CodeQL/生产镜像/治理通过。
- PR #256已于2026-10-19T01:41:39+08:00精确squash合并；远端origin/main核验为a991a22dba49045af86c47c1876f3c4b16c2cd02，合并树与已验511完全相同。合并后7类push CI已启动：Backend39150764129、Frontend39150764154、Desktop39150764062、CodeQL39150764127、Architecture39150764142、repo-gates39150764035、ProductionImage39150764054；收尾时仍运行/排队，不能宣称合并后全绿。
- 旧output/desktop-0.1.0-alpha.1/是147c/PR merge00d1测试包，验证记录已明确标记审查前历史包，二进制与摘要保留。-candidate/更早；含修复的最新PR包取native39149275928，正式候选须取main新包。未公开Release、未建tag、未部署服务器。
- 本轮审查修复与合并目标已完成。主任务保留active用于最终三平台原生窗口/覆盖升级、真实签名/公证及后续发行验收；8项签名Secrets未配置，当前仍未签名Alpha。较早M Mac中文保存/重开/系统TXT导出仅证明当时版本。下一步：检查上述main CI结果，按desktop/RELEASE.md记录最终原生窗口与升级结果、配置真实证书；公开Release/付费/服务器部署仍需相应明确授权。

## 用户目标与范围

- 完整本地运行，无需另配服务器；macOS 与 Windows 都做，共同源码、分开安装包可接受。
- 本轮补充：打包版作为后续主要交付方式，补齐可重复的版本、构建、验证、签名与 Release 草稿流程；不自动公开发布。
- 允许 SQLite 等更轻存储；项目未上线、无用户，明确不需要旧数据迁移，备份另定。
- 最终用户无需 Docker、Python、Node 或数据库配置。业务 AI 仍需在应用内配置并验证模型连接；订阅 CLI 非捆绑组件。
- 不导入/认领/删除旧开发库，不做自动备份、同步、自动更新或正式发布；仅合成数据，无真实业务 LLM/稿件/账户 Key/CLI 登录态读取。

## 实现与关键决定

- desktop/README.md 与 ADR-0043 为架构入口。pywebview/PyInstaller 复用 Vue 正式构建、FastAPI 和现有 PG 队列；GUI 与 console runtime 分开。
- 首版内置 PostgreSQL 17.10、pgvector 0.8.6、pg_trgm 与固定 revision/摘要的 BGE ONNX。SQLite 未迁移：现有队列/并发依赖 PG 行锁，隔离迁移探针也报 MissingGreenlet，不能仅换 URL 宣称等价。
- 图片用 World 私有 LocalImageClient，保留 owner/novel_id/PNG 与引用清理门禁，原子写入并拒绝穿越/符号链接；桌面不依赖 MinIO。
- 私有新数据目录、原子凭据、单实例锁、稳定 loopback origin、轮换令牌/一次性入口/HttpOnly SameSite Cookie、Host/写 Origin 校验；启动 HMAC 证明不向抢占端口者发送令牌。
- POSIX UID/权限/no-follow/flock 保持；Windows SID/ACL/msvcrt 锁。接受可信 user/SYSTEM/Administrators 属主，禁止其他账户 ACE。模型准入继续用宿主默认共享目录，不分裂账户并发池。
- Windows PG 经 pg_ctl restricted token 启动；保存精确 PID 的原生句柄并校验 exe，不按端口扫描杀进程。PG 低内存配置 shared_buffers=32MB/max_connections=30，API/worker 各 pool4+overflow4。
- 关闭管道触发所属 worker/API/PG 有界退出；建库 Popen 可取消并 kill/wait 回收。初始化 helper stdin=DEVNULL，API/worker 各用独立 PIPE。
- Windows 原生 PG EXE UTF-8 manifest；冻结 Python X utf8；源码/CI PYTHONUTF8=1；PG builtin C.UTF-8 + OS LC_CTYPE（Windows English_United States.1252/Mac en_US.UTF-8）。
- Windows worker marker 用私有 AppData，固定 LF；POSIX/Docker /tmp 与 PID1 健康契约不变。
- 版本：ARM/Windows Python3.14.8；Intel Python3.13.15 + 最后提供 Intel wheel 的 ONNX Runtime1.23.2。Mac minOS14；Windows10 1903+/11 x64。
- 中文安装语言来自 Inno6.7.1 commit cfdf48923178df4b4f040e038b423aa555a61ffc，SHA256 7d544b9bb1d142cfa11f2e5d3cc8abe2e55f8e066c5124e3772675aa236e1278；许可证同 revision/摘要，并随包包含 NovelCraft、PG、vector、BGE 等许可。

## 已解决的真实故障

- fresh runner 没有 pg_config 时不能先 make clean；Intel ONNX wheel 要固定旧版本/Python；VS 目录改用 vswhere/vcvars64 + flex/bison/Meson；原生 minOS 从本机26纠正14。
- 打包漏 capabilities.json/companion 源码，已收集业务数据/源码。BufferedReader daemon 关闭会崩溃，改 os.read EOF。GUI 必须先建私有根目录再初始化 WebView。
- pywebview 默认禁止下载，已启用并真实 TXT 导出成功。PG17 pg_trgm 仍依赖 OS 字符分类，已真实 SQL 断言中文 trigram 非空。
- Windows elevated mkdtemp 可能只给 Admin 访问；搬移安装 fixture 与真实数据库 staging 均显式 private_directory/current SID ACL，不弱化权限检查。
- Windows checkout 把 frozen SQL 转 CRLF 导致摘要错；.gitattributes 仅将 frozen/*.sql 固定 LF。真实 core.autocrlf=true checkout-index 字节/摘要复核通过，不改快照或预期摘要。
- 最重要：migrate 继承 supervisor 阻塞读取的控制 stdin，冻结 Python 启动卡住。旧 180s 外层超时关闭管道后才短暂出现 SQL，延到600s时无任何 PG 连接。helper 改 DEVNULL 后 Windows 完整冻结 smoke 约1分钟通过。真实嵌套进程回归：保持父管道打开，helper 必须读到 EOF；原实现稳定3秒超时，修复后通过。
- 已撤去排查用 loader debug、faulthandler 和 PG 状态轮询；迁移180s/整体启动检查300s，有界取消保留。
- Inno runner 6.7.1 未安装 unofficial 中文文件；现自行按固定 commit/SHA 获取，不再假定 compiler:Languages 路径存在。

## 验证证据

- World 全模块1570 passed/1 deselected；图片/config/worker226 passed；embedding/worker/desktop119 passed；Codex 身份/真实跨进程准入/模型池80 passed（各次运行有交集，不能相加）。
- 当前 Mac desktop+liveness30 passed/2 Windows-only skipped；Windows访问/ACL/精确进程句柄/锁/取消/控制管道回归11 passed。旧 stdin 反例日志：ignored desktop/build/control-pipe-regression-before.log。
- 源码完整 smoke 在最新 stdin 隔离后通过；日志 ignored desktop/build/source-smoke-devnull.log。前端正式 build/96项资源检查通过。
- 完整 Backend quality/coverage、PostgreSQL critical、CodeQL、治理 gates 多轮通过；生产恢复镜像有一次外站 TLS timeout，重跑通过，未修改恢复逻辑。最终仍核对最新 PR checks，不宣称全部当前 CI 绿。
- 架构 inventory 与 diff/secret/import/dependency 门禁通过。BASE_REF 文档影响用工具支持的 no-change-reason 明确复核未变 CLAUDE 导入层、维护协议与服务器模块图，不改规则/断言过检。

## 交付与剩余

- 三平台 output 包均已更新为 be0a0ac6d；ARM SHA256 227130db0b8faf3ee397a3e49e02b3f5f2936c0f297df3cb077da9676d3662bf；Intel 07bc523a3b4af234af3a358445c113fc74f05b3b84c6fcad7176fbc04cc4e8c2；Windows dd28ffad764e21254bcb3a1107b4250b66966583a5dcdbf5114842e5febdccc3。两个 Mac DMG 挂载、Applications 链接、自有许可证与 ad-hoc codesign 完整性通过。包按原文件摘要核对后 staged/atomic replace，未覆盖用户修改。
- output/desktop-20261018/安装说明.txt 与 SHA256SUMS.txt 已更新，明确版本、系统要求、AI 连接、WebView2 首次联网、数据目录与未验收边界。原生 TXT 合成导出文件也保存在同目录。
- 本机 desktop/dist/NovelCraft.app 可能仍是 CUA 自动重新打开的空白默认演示，不并发覆盖它。最新本机独立包位于 ignored desktop/build/final-dist；正式取最新 CI 包。
- Windows 实际 Inno 安装/运行/卸载步骤通过（job 117709924068；两次 Desktop smoke passed 在 15:19:59Z/15:22:51Z），原始 CI 日志存 ignored desktop/build/windows-ci-be0a0ac6.log。
- 未完成：Windows/Intel 人工窗口验收；正式签名/公证/发布。不能把冻结 runtime 通过写成原生 GUI 或正式用户验收。
- 收尾 make docs-check、受支持的 BASE_REF no-change-reason 检查与 git diff --check 通过；最终笔记保留未提交，产品代码已提交/推送并关联草稿 PR。原主工作区 WIP 未触碰，仅新增/更新本任务 output 产物。

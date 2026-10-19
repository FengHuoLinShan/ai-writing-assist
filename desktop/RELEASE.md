# 桌面版发布流程

桌面应用是默认开发与交付方向。日常 PR/main 不构建安装包；仅手动命令触发，
默认只发布 Mac M 芯片（macOS ARM64）版。Intel Mac、Windows x64 或全平台须当次明确选择。
旧服务器退出产品开发方向；历史环境维护仍遵守 deploy/README.md，本流程不修改线上数据。

## 一次版本发布

1. 在主题分支修改 desktop/VERSION，并添加同名 desktop/changes/<版本>.md，写明用户可见变化、
   系统要求、已验证范围和限制。当前版本是 0.1.0-alpha.1。
   桌面版本格式为 X.Y.Z 或 X.Y.Z-alpha.N / beta.N / rc.N（N 从 1 开始）。
   backend/frontend 包版本有各自用途，无需跟随修改；构建自动写入应用信息、Windows 安装器和来源清单。
2. 完成受影响测试、文档检查与 PR 评审，取得合并授权后合入 main。等待目标 main 提交的
   Backend CI（含 PostgreSQL critical 与轻量桌面源码测试）、Frontend CI、CodeQL、
   Architecture docs、repo-gates 全部成功。服务器镜像已改为手动历史维护流程，不是桌面发布前置。源码、原生运行与人工验收的证据分别记录。
3. 记录完整 40 位 main 提交 SHA，从 main 手动运行 **Desktop release draft**：

   ```sh
   gh workflow run desktop-release.yml --ref main -f source_sha=完整40位提交SHA
   ```

   此命令默认 target=macos-arm64。只有用户明确要求时才加 `-f target=macos-x64`、
   `-f target=windows-x64` 或 `-f target=all`，不自动补齐另外两个版本。
   例如仅 Windows：`gh workflow run desktop-release.yml --ref main -f source_sha=完整40位提交SHA -f target=windows-x64`。

   流程拒绝主题分支、非 main 可达提交、脏工作区、未通过或缺失的目标 SHA CI、缺少版本说明、
   已存在的版本/tag。网络查询失败会停止。失败后修复原因重试；若已有部分草稿，先人工检查并清理，
   不使用 --clobber 覆盖现有版本。
4. 同一套 Desktop installers 工作流只构建本次选定平台，测试冻结程序的本地模型、中文检索、
   会话保护、作品持久化、单实例和重开；Windows 另实际安装、从安装目录运行并检查卸载。
   稳定版在构建中签名，Mac 还须 Apple 公证及 stapler 验证；任一步失败均不进入草稿创建。
5. 汇总选定平台的同版本同 SHA 安装包，重新核对摘要、大小、签名状态，创建 **Release 草稿**。
   缺少选定包、混入未选平台、重复包或校验失败均停止；只发 ARM64 时不要求另外两个包。
   草稿附件包含选定平台安装包、SHA256SUMS.txt、release.json、安装说明.txt、RELEASE-NOTES.md。
   preview 版本勾选 prerelease；此流程没有自动公开发布、自动更新或服务器部署动作。
6. 下载草稿附件，仅对本次发布的系统逐项记录：安装/启动、空态、新建作品、中文正文保存、退出重开、
   系统保存对话框导出、已有安装的覆盖升级及数据保留。记录系统、包摘要、结果与已知问题；
   工程 smoke 不能代替原生窗口或作者验收。核对 release.json 的 commit 和版本，再由负责人
   在 GitHub Release 页面点击 Publish。稳定版须先关闭已知阻断问题；公开发布需当次明确授权。

每个版本的资产只发布一次。修复后提高版本重新发布，不替换已发布安装包，便于定位问题与回退。
测试构建产物仅保留 14 天，正式下载以 Release 附件为准。尚未完成首个公开 Release 时，不宣称下载入口已有版本。

## 签名与公证配置

带 alpha/beta/rc 的预览版不读取签名密钥，明确标注“未正式签名/公证”。
无后缀的稳定版强制走以下签名流程，缺少证书或验证失败即停止，不自动降级为未签名包。

在仓库 Settings → Secrets and variables → Actions 配置以下 secrets；不要写入 .env、提交到 Git 或发到聊天：

| Secret | 内容 |
| --- | --- |
| MACOS_CERTIFICATE_P12 | 包含私钥的 Developer ID Application P12，Base64 编码 |
| MACOS_CERTIFICATE_PASSWORD | P12 导出密码 |
| MACOS_SIGNING_IDENTITY | 完整的 Developer ID Application 签名身份 |
| APPLE_ID | 公证账户 |
| APPLE_TEAM_ID | 对应 Apple Developer Team ID |
| APPLE_APP_PASSWORD | Apple 公证专用 app-specific password |
| WINDOWS_CERTIFICATE_P12 | 系统信任的代码签名 PFX/P12，Base64 编码、一个签名身份 |
| WINDOWS_CERTIFICATE_PASSWORD | 对应导出密码 |

Mac 使用临时 runner keychain，由 PyInstaller 以 Developer ID/hardened runtime 签名，
再对 DMG 签名、公证和附票，结束时清理 keychain。Windows 用 SDK signtool 对主程序、runtime
和安装器做 SHA256 Authenticode + RFC3161 时间戳并验证，结束时移除临时 PFX 和导入私钥。
当前 Windows 接口支持可导入 PFX；若使用硬件/云签名证书，须适配 sign_windows.ps1 后实际验证，
不把 PFX 配置当成所有证书供应商的通用方案。

证书采购、账户申请和签名服务付费未自动执行。配置存在也不等于签名已实测；
每次稳定版必须记录本次所选平台的真实签名、公证（Mac）、下载与系统验证结果。
步骤依据 [PyInstaller 签名文档](https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing)
与 [Apple 公证说明](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)。

## 升级与故障处理

退出旧版后安装新版；稳定的应用身份、安装位置与数据目录保持不变，卸载不删除作品。
当前不提供自动备份/恢复和跨设备同步。升级前可在完全退出后复制整个用户数据目录，
须一起保留数据库、图片和 secrets.json；这是手工保护路径，不能在产品中显示为“已备份”。
包升级会按已有 Alembic 规则处理当前本地 schema，不承诺数据库降级兼容。
发现坏版本时撤下/标记对应 Release，发布修复版本；不要自动安装旧包覆盖新版数据。
在具有可恢复副本并另行确认前，不执行数据库降级、重建或删除数据。

## 开发与验证入口

普通 PR/main 复用 Backend CI 的轻量桌面源码/边界/发布测试，不构建安装包。
需要安装包时，手动运行 `gh workflow run desktop.yml --ref 分支名`，默认仅 ARM64；
另外两个平台或 all 仍须当次明确传 target。它只上传测试产物，不创建或公开 Release。
Release 工作流复用相同构建，不复制另一套打包命令。所有第三方 Actions 固定 commit SHA。
本机 `make desktop-build` 默认 ARM64；Intel/Windows 须显式传 DESKTOP_TARGET 并使用对应宿主。
然后运行 desktop/smoke.py --frozen；生成包位于 desktop/dist/，详见桌面 README。
release.py 的 verify-source/package/assemble 分别负责来源门禁、产物记录和汇总校验，
对应失败路径与手动触发约束测试位于 desktop/tests/test_release.py、test_workflows.py。

每个版本只包含本次明确选择的平台；以后需要增加其他平台时使用新版本重新走流程，
不覆盖已有草稿/公开版本，也不静默补包。未选择平台的原生安装验收不计入本次必需范围。

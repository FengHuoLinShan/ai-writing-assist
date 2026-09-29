# 本机 Agent CLI 适配（当前仅图片生成）

作者在 AI 能力页下载伴随程序并用十分钟配对码绑定作品，在已配对 Mac 上安装并运行
Codex、Claude、Kimi、DSH 或 Pi CLI。**当前唯一用途是图片生成**：World 模块的世界对象
图片与地图册页面在需要 AI 生成图片时调用本模块（`modules.local_agent.facade`）。
项目助手、已登录 RP、前瞻分析、创作协作、连续性检查、场景排演等文本 Agent 路径已经
与本机 CLI 断开，统一改用项目账户模型连接；可恢复任务快照中若仍带着旧的本机文本
执行器引用，会在读回时立即失败关闭（`Local CLI no longer runs project text tasks`），
不会静默回退或重放本机副作用。CLI 的本机登录态不上传服务器，也不成为其他作者的
统一凭据。

## 审查包装（review wrapper）

- **服务器拼提示词**：作者填写的创作简报由服务器拼成完整 CLI 提示词（目标尺寸、
  只读参考文件清单、"不得访问产品数据/调用产品工具"等规则），简报本身作为不可信
  数据追加在末尾，不与规则文本混合。作者在确认阶段仍能看到并编辑这份简报。
- **按任务人工授权**：每个根任务先创建 pending task，作者需确认本轮 CLI 将以 Mac
  当前用户权限使用文件与命令；确认只放开这一个 task，设备离线则继续等待。
- **图片任务不提供产品工具**：不写入 `novelcraft-tool` shim，也不打开产品工具的
  unix socket；CLI 只能使用自身原生工具（文件/shell/图片生成能力）生成
  `output.png`/`output.jpg`。
- **隔离工作目录、用后即删**：每个 invocation 使用独立工作目录；任务结束（完成、
  失败或异常）后伴随进程统一删除整个工作目录。工作目录不是沙箱，CLI 仍可访问当前
  macOS 用户允许的其他文件和命令。
- **服务器侧图片复核**：CLI 产出上传后，服务器重新解码、校验格式/尺寸/单帧、
  去除 EXIF/ICC/文本元数据，再重新编码为 PNG 后才存入 `local_agent_files`；产品
  从不直接存储或转发 CLI 的原始字节。
- **候选态，不自动采用**：复核通过的图片只是候选，World 模块按既有采用/回滚流程
  交给作者确认后才写入正式资产。

## 协议与暂存

运行由原 `async_tasks` 租约负责；本模块记录设备、invocation、工具回执，以及图片
任务的输入/输出二进制暂存（`local_agent_files`，见 `docs/01_数据库设计.md`）。
伴随进程新增两个图片专用端点（复用既有设备 bearer 鉴权与 lease 校验）：

- `GET /api/local-agent/companion/jobs/{invocation_id}/inputs/{ordinal}` 下载一个
  只读参考文件（如 `reference-1.png`、`mask.png`）；仅对图片模式的 invocation 开放。
- `PUT /api/local-agent/companion/jobs/{invocation_id}/output` 上传生成结果
  （PNG/JPEG，硬上限 20 MiB，超限在缓冲前拒绝），经服务器复核后落库。

`local_agent_files` 中的字节只在单次 invocation 运行期间存在：invocation 结束
（无论成功、失败还是超时）后统一删除该 invocation 的全部输入/输出行。原 task 停止、
设备撤销、心跳超时或租约替换后拒绝迟到结果，已见文本/回执可通过项目内接口读取。
本机任务的异步恢复策略统一为 `never_retry`。

离线评测可显式使用 `evals.cli_executor.CLIStructuredExecutor`；既有严格隔离的
`CodexStructuredExecutor` 默认与现有评测命令保持不变。新执行器仅使用合成/明确授权的
输入，不能把旧评测结果直接与项目模型质量比较。

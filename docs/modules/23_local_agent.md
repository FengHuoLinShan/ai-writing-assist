# 本机 Agent CLI 适配（当前业务入口为图片生成）

作者在 AI 能力页下载伴随程序并用十分钟配对码绑定作品，在已配对 Mac 上安装并运行
Codex、Claude、Kimi、DSH 或 Pi CLI。**当前正常新建的业务入口仅用于图片生成**：World 模块的世界对象
图片与地图册页面在需要 AI 生成图片时调用本模块（`modules.local_agent.facade`）。
项目助手、已登录 RP、前瞻分析、创作协作、连续性检查、场景排演等当前新建文本任务使用项目
账户模型连接；可恢复任务快照中若带旧的本机文本执行器字段，Project 恢复会失败关闭。
Story 执行入口额外拒绝旧本机任务标记及排演副快照；`task_snapshot_client` 已删除，
不会因账户主快照可恢复而静默回退或重放本机副作用。

旧文本兼容实现仍留在源码中：`run_local_agent` 仍能创建文本 invocation，`companion._job`
对非图片请求仍走 `_run_text_job`。但服务端入口已缩面：待确认列表与批准只接受
`world_object_image_generate`、`map_atlas_generate` 两类图片任务，companion claim 只下发
`request_json.mode == "image"` 的调用；旧文字或未知模式的 pending task/invocation 在这些
入口直接置为 failed，不发放租约或提示词。因此源码分支的保留只是兼容形状，不构成正常
文字入口，也不表示旧文字 job 可领取。
CLI 的本机登录态不上传服务器，也不成为其他作者的统一凭据。

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
  失败或异常）后伴随进程统一删除整个工作目录。清理工作目录不构成操作系统沙箱；CLI 仍可访问
  当前 macOS 用户允许的其他文件和命令。
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
设备撤销、心跳超时或租约替换后拒绝迟到结果。历史文本和任务回执可通过项目内接口读取；
这是历史结果查询，不代表当前新建文本任务仍走本机执行。回执 `usage` 可能为 `null`，表示用量未知，
不能当作零，也不要与项目账户模型的 AI 用量诊断混为一项。
本机任务的异步恢复策略统一为 `never_retry`。

待确认列表与批准入口只处理 `world_object_image_generate` 和 `map_atlas_generate`；
旧文字 pending task 置为 failed，提示使用当前账户模型重新发起。companion claim
只下发 `request_json.mode == "image"` 的调用；旧文字或未知模式的 pending invocation
置为 failed，不返回提示词或新租约。历史回执继续按 owner + novel_id 读取。

源码保留可选的 `evals.cli_executor.CLIStructuredExecutor`；它不是项目业务文本入口，
其存在不授权新模型调用。既有 `CodexStructuredExecutor` 的新文字调用当前被校准预检拒绝，
旧元数据与 cache-only 回放仍保留；恢复条件见 [测试指南](../../testing-guide.md#离线实验的独立环境)。
合成替身检查不证明实际 CLI 模型质量，也不能把旧评测分数改标为当前模型成绩。

Local Agent 不直引 Project、AssistantRun 或 InteractionAttempt 模型：项目
选择写入由 Project facade 持 owner/novel_id 行锁，批准状态委托各领域 facade，
与任务授权同事务提交；撤销设备使用条件清除避免覆盖另一已选择设备。

# Local Agent — 本机 CLI 图片生成

本模块拥有项目配对设备、一次性授权、伴随进程协议和本机执行回执。HTTP 前缀为
`/api/local-agent`；浏览器入口仍受当前 account principal 与项目 owner 校验，伴随进程
只持有单项目设备令牌。令牌按 SHA-256 摘要存库，配对码十分钟且单次使用；撤销设备后
不能再领取任务或提交结果。

**当前范围仅图片生成。** 本机 CLI（Codex/Claude/Kimi/DSH/Pi）现在只用于生成图片，由
World 模块在需要世界对象图片或地图册页面时调用（见
`backend/modules/world/README.md`）。项目助手、已登录 RP、前瞻分析、创作协作、
连续性检查、场景排演等文本路径已与本机 CLI 断开，改为始终使用项目账户模型连接；旧的
`local_agent` 快照字段一旦出现在可恢复任务里即失败关闭（`Local CLI no longer runs
project text tasks`），不会静默回退到网关模型或重放本机副作用。

## 图片生成审查包装

`images.py` 是纯函数评审层（无 DB/网络）：`review_generated_image()` 校验魔数、格式、
帧数、尺寸（先查尺寸再解压，防炸弹图）、EXIF 方向归一化，再重新编码为不含 EXIF/ICC/
文本 chunk 的干净 PNG，返回 `ReviewedImage(data, width, height, sha256)`；`fit_cover()`
按目标宽高裁切、`limit_edge()` 按最长边等比缩放，供后续地图册拼版和对象图裁剪复用。
服务器只信任经这层重新解码的字节，从不直接存储或转发 CLI 原始输出。

`image_runtime.run_local_image()` 是服务器侧编排：校验原 task 租约、执行器种类、设备
归属与撤销状态（设备不可用时在建 invocation 之前就失败关闭），在服务器侧拼出完整的
CLI 提示词（"wrapper"：中文指令 + 目标尺寸 + 只读参考文件清单 + 作者简报作为不可信数据
追加），把简报和参考图/mask 写入 `local_agent_files` 暂存表，轮询伴随进程直到完成、
失败或超时，最终把复核后的 PNG 返回给调用方；`finally` 中无论成功与否都会清空该
invocation 的全部暂存文件，字节不会跨请求留存。`facade.py` 导出
`ReviewedImage`、`review_generated_image`、`fit_cover`、`limit_edge`、`run_local_image`、
`local_image_task_meta()`；其他模块只通过 facade 调用，不直接 import 本模块实现。

## 每任务人工确认与工作目录隔离

每个根任务先创建 pending task，作者确认本轮 CLI 将以 Mac 当前用户权限使用文件与命令。
确认只放开这个 task；设备离线则继续等待。companion 只以出站 HTTPS（本机开发可 HTTP）
领取，所有事件、心跳、下载参考图、上传产出与完成结果均绑定设备、`novel_id`、owner、
原 task lease 和 invocation lease；越权/迟到请求失败关闭。

图片任务不再写入 `novelcraft-tool` shim、也不打开产品工具 unix socket——服务器拼好的
提示词禁止访问产品数据或调用产品工具，只允许 CLI 使用自己的原生工具（文件、shell、
图片生成能力）生成 `output.png`/`output.jpg`。每个 invocation 使用独立工作目录，
任务结束后（成功、失败、异常）伴随进程统一 `shutil.rmtree` 整个工作目录；文本路径
（历史遗留、已在服务端失败关闭）同样清理工作目录。工作目录**不是沙箱**——CLI 仍可访问
当前 macOS 用户允许的其他文件和命令，界面必须如实告知。

## 伴随进程协议

浏览器设置页可下载单文件 `novelcraft-agent.pyz`，本机安装 Python 3 与所选 CLI 后运行：

```bash
python3 novelcraft-agent.pyz pair https://example.invalid <一次性配对码>
python3 novelcraft-agent.pyz run <返回的设备 ID>
```

图片任务新增的伴随进程端点（复用既有 `/heartbeat`、`/tools`、`/finish` 的设备 bearer
鉴权与 lease 校验）：

- `GET /api/local-agent/companion/jobs/{invocation_id}/inputs/{ordinal}?lease_id=` —
  按 ordinal 下载一个只读参考文件（原始字节，媒体类型取自暂存行）；仅对
  `request_json.mode == "image"` 的 invocation 开放，否则 404。
- `PUT /api/local-agent/companion/jobs/{invocation_id}/output?lease_id=` — 上传 CLI
  产出（PNG 或 JPEG，硬上限 20 MiB，超限在缓冲前拒绝为 413）；服务器在线程池中运行
  `review_generated_image()`，替换该 invocation 之前的 output 行，返回
  `{"sha256", "width", "height"}`；无效图片 400，非图片模式 404/409。

`pending-approvals` 列表新增标签 `world_object_image_generate`（对象图片生成）与
`map_atlas_generate`（地图册生成），供作者在待确认任务列表里识别图片任务。

Codex/Pi 可在启动伴随进程前通过 `NOVELCRAFT_CODEX_MODEL` / `NOVELCRAFT_PI_MODEL`
覆盖本机默认模型；DSH 可通过启动时的 `DSH_HOME` 使用独立配置目录。其他 CLI 采用本机
登录态/配置。端到端验证使用本任务专用 PostgreSQL 数据库，不使用真实作品。

项目执行器配置经 Project context/facade 读取和保存，撤销设备仅在当前配置仍
绑定该设备时清除。根任务批准通过 Assistant/Interaction facade 更新各域
checkpoint，均过滤当前 owner + novel_id + task_id，并与队列授权同事务提交。

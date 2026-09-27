# Local Agent — 项目本机 CLI 运行

本模块拥有项目配对设备、一次性授权、伴随进程协议和本机执行回执。HTTP 前缀为
`/api/local-agent`；浏览器入口仍受当前 account principal 与项目 owner 校验，伴随进程
只持有单项目设备令牌。令牌按 SHA-256 摘要存库，配对码十分钟且单次使用；撤销设备后
不能再领取任务或提交结果。

项目选择保存在 `Project.settings.agent_executor`。旧项目默认 `gateway`。
`facade.py` 提供选取、冻结本机 task meta 和从已验证 project snapshot 创建 task client；
Assistant、已登录 RP、前瞻、协作和 RP 连续性检查复用原领域任务与结果门禁。
匿名 RP 与普通非 Agent 工作流不读取该选择。

每个根任务先创建 pending task，作者确认本轮 CLI 将以 Mac 当前用户权限使用文件与命令。
确认只放开这个 task；设备离线则继续等待。companion 只以出站 HTTPS（本机开发可 HTTP）
领取，所有事件、产品工具调用与完成结果绑定设备、`novel_id`、owner、原 task lease 和
invocation lease；越权/迟到请求失败关闭。工具仅执行本轮注册的领域函数，正式写入仍由
领域确认、来源重验与事务控制。本地文件修改不等于产品保存。

运行回执保存已见文本、工具次数、状态及未知用量；中断或租约失效不自动重放本机 CLI，
作者须显式新建任务。专用工作目录只提供 cwd 与任务文件，**不是沙箱**。CLI 可访问当前
macOS 用户允许的其他文件和命令。浏览器设置页可下载单文件 `novelcraft-agent.pyz`，
本机安装 Python 3 与所选 CLI 后运行：

```bash
python3 novelcraft-agent.pyz pair https://example.invalid <一次性配对码>
python3 novelcraft-agent.pyz run <返回的设备 ID>
```

Codex/Pi 可在启动伴随进程前通过 `NOVELCRAFT_CODEX_MODEL` / `NOVELCRAFT_PI_MODEL`
覆盖本机默认模型；DSH 可通过启动时的 `DSH_HOME` 使用独立配置目录。其他 CLI 采用本机
登录态/配置。端到端验证使用本任务专用
PostgreSQL 数据库，不使用真实作品。

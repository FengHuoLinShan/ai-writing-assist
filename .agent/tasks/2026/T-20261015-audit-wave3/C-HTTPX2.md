# C：OpenAI 3.x HTTP 客户端迁移

- 任务总记录：R1 树 `.worktrees/wave3-r1/.agent/tasks/2026/T-20261015-audit-wave3/TASK.md`。
- 本项树 `.worktrees/wave3-http`、分支 `codex/audit-wave3-httpx2`，基线 main d2ab2dbf3。
- 官方依据：[Python SDK 文档](https://developers.openai.com/api/reference/python#httpx2-migration)，2026-10-15 读取：默认 HTTPX2，自定义客户端/transport/timeout/hooks/mocks 应迁移。已安装 openai 3.28.0 / httpx2 2.12.0 源码确认旧 HTTPX 仅作为兼容分支；官方所读页面未给固定移除版本，不猜测时间。
- 文字、独立 embedding、图片客户端改注入原生 HTTPX2；生产最小依赖 openai>=3.28,<4 与 httpx2>=2.12,<3，lock 未升级其他包。
- egress 同时支持两套 Request/ConnectError，健康/余额探针保留 HTTPX。超时、显式 proxy/trust_env、DNS/白名单私网拒绝与 SDK max_retries=0 不变。
- 验证：748 项 LLM/project/账户/图片相关通过，2 live 用例按默认层排除；283 项 embedding/RAG 引用方通过；新增真实 SDK 客户端身份及私网拦截测试（零网络 IO）、双 HTTP 库 guard 异常类型回归通过。lint、repo-gates 已通过，docs-check 首次要求同步 12_infrastructure，已补后重验。
- 自审：仅迁移 SDK transport 与必要双 HTTP 边界；不改业务模型、API 凭据或真实调用。未运行付费 API/图片/真人验收。待固定提交 CI 和合并授权。

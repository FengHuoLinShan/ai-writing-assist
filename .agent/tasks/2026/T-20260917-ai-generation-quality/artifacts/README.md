# 合成资料真实模型验收

这些脚本复用项目实际 API、service、任务与账户模型入口。Provider 为真实 DeepSeek，数据库使用
`backend/conftest.py` 的独立内存 SQLite；不启动生产 worker，不读取真实小说库。
它们是显式付费的开发验收脚本，不进入默认 CI，不代表盲评或文学质量保证。

`synthetic-cases.json` 保存 11 个世界设计案例；每个案例由公共基础成果与递归覆盖组成，
运行时重新绑定本次独立项目和 confirmation。无需原开发者工作目录或外部小说。

## 运行

在仓库根目录复制到现有忽略目录（脚本在那里才能使用 backend 的 pytest fixtures）：

```sh
mkdir -p backend/.test-artifacts
cp .agent/tasks/2026/T-20260917-ai-generation-quality/artifacts/test_ai_quality_live.py backend/.test-artifacts/
cp .agent/tasks/2026/T-20260917-ai-generation-quality/artifacts/test_rp_quality_live.py backend/.test-artifacts/
cp .agent/tasks/2026/T-20260917-ai-generation-quality/artifacts/test_fresh_chat_quality_live.py backend/.test-artifacts/
cp .agent/tasks/2026/T-20260917-ai-generation-quality/artifacts/test_remaining_text_quality_live.py backend/.test-artifacts/
cd backend
```

进程须已获得获准使用的 `DEEPSEEK_API_KEY`；不要写入命令、报告或 Git。
如连接需要代理，在运行环境设置 `LLM_PROXY_URL`。单个案例示例：

```sh
RUN_AI_QUALITY_LIVE=1 \
AI_QUALITY_CASES=resource-loop \
AI_QUALITY_CAP_YUAN=1.5 \
AI_QUALITY_ARTIFACTS=.test-artifacts/quality-new-run \
uv run --locked --extra ci -- pytest \
  .test-artifacts/test_ai_quality_live.py::test_world_design_real \
  -m real_llm -q --timeout=900
```

完整 World 列表为 `goal-misread,author-boundary,resource-loop,institution-enforcement,information-flow,maintenance-failure,long-feedback,value-tradeoff,insufficient-evidence,reasonable-weirdness,no-issue`。
不指定测试函数而运行 `test_ai_quality_live.py`，还包括七类文本生成和八个知识审查正反控制。
RP 单独运行 `test_rp_quality_live.py`，复用相同环境参数；它走真实流式生成、暂存、审查、释放和持久化。
`test_fresh_chat_quality_live.py` 包含最后追加的三个新领域样本（缺水分配、延迟消息、双人签字），
运行后还须阅读 `reply` 核对任务约束。这两份脚本按单 worker 运行。
`test_remaining_text_quality_live.py` 补验总纲、助手待确认提案和地图文本结构，助手测试须额外设置
`ASSISTANT_ENABLED=1`；仍使用独立SQLite，未调用地图图片模型，也不确认助手的待办写入。

费用上限是**单 worker、单输出目录**的累计估算；并行 worker 的上限须相加，旧目录已有费用也计入。
每次选择新的输出目录以保留旧结果。脚本只接受 DeepSeek Flash 闲时；输入按每百万 token
未命中 ¥1、命中 ¥0.02，输出 ¥4 估算，流式输出保守按未命中算。价格需要按
[官方定价](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)重新核对；这不是账户账单。
账户连接验证的小额请求不在 provider 账本里，预算需留余量。请求缺少用量或中断则标记费用未知，
停止继续请求，核对后再运行。脚本不充值、不切换模型、不自动放宽费用上限。

## 阅读结果

- `requests.jsonl`：真实合成输入、输出、用量和费用估算；无密钥。
- `code-manifest.json`：相关生产代码 SHA256；同目录不得混入不同版本后宣称一次冻结评测。
- `<case>.json`：任务/业务结果以及被阻断时的私有阶段证据。
- `rp-opening.json`：通过审查并实际持久化的 RP 开场。

自动断言只证明调用合同、审查结论及指定负例。还须逐段阅读内容，检查规则、数量、
因果、人物知识与作者要求；模型自评通过不能替代真实作者验收。

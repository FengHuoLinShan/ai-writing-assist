# ADR-0033 — 本机单用户 Codex 普通模型步骤

- 状态：Accepted / 本机实现及受限协议已验证
- 日期：2026-10-13
- 授权：用户要求深度适配 Codex，普通 LLM 默认 gpt-6-luna、max，并大量真实测试。

## 决策

Codex 作为账户文本连接进入既有 project facade、LLMClient、运行信封及恢复快照。
只在 development/test/local 的 AUTH_MODE=local 且 bootstrap owner 下开放；公开账户不共享
服务器本机的 Codex 登录态。已有用户显式选择的 API 连接保留，新本机账户默认显示 Codex。
账户设置用实际的小型结构化生成验证登录和模型可用性，不需要也不保存伪造 API Key。
连接版本绑定 CLI 可执行文件、修改时间、系统用户、Codex home 和当前ChatGPT登录账户的非敏感哈希。身份只从当前作者拥有、他人不可写的常规auth.json解析；API Key登录、缺失/不支持的身份存储、注销或更换账户失败关闭，不打印或存储Token。同账户Token刷新不改变绑定；切换CLI/home或登录账户需重新验证。每次请求在预算预留前，经Project回读当前owner连接，并在CLI启动前重验本机身份。

每个步骤以独立临时目录、read-only sandbox、禁审批、忽略用户配置及 execpolicy .rules，并禁止读取 AGENTS 运行。
关闭 shell、图片、插件、MCP、网页搜索和多 Agent 功能；输出事件仅接受正文/推理类型，
发现工具或未知类型即失败关闭。子进程不继承业务 Key/数据库等环境变量；仍保留登录所需
的 HOME/CODEX_HOME 与代理变量。调用有总时限、输出字节上限和进程组取消，不自动重发
结果未知的进程；临时输入输出结束后清除。这是受限单步骤 adapter，不是任意主机 Agent。

固定 gpt-6-luna / max，无静默回退。封闭 schema 使用原生 output-schema；开放字典保持
字段，通过固定 JSON 包封和现有 Pydantic 验证。业务工具仅生成注册工具的名称与 JSON
参数提案，执行仍由 ADR-0023 的服务端有界 runtime 负责，来源确认、novel_id 隔离、
工具参数校验和领域写入门禁不变。ADR-0029 的旧 local_agent 文本快照继续失败关闭，
图片伴随程序仍按原范围运行。

## 已知边界与验证

CLI 的 temperature/top_p、硬输出 token 上限没有 API 等价保障，max_tokens 只作目标；
字节和超时是实际硬边界。流式在完整结果后交付内容，再交付终态与原生 usage；不能
宣称实时 token 流。模型和 effort 是请求参数，不是独立服务端回执证明。

安装并登录支持上述参数的新版 Codex CLI。多版本环境通过 CODEX_CLI_COMMAND 指向
已验证可执行文件；0.160.0 本机验证通过，0.144.6 不支持 view_image 功能开关，失败关闭。
模型能力预算先维持 unknown-short 保守配置，长文检索测试不自动证明完整语义容量。

离线测试覆盖环境隔离、禁止原生工具、未知结果不重发、开放字段和断开后的恢复门禁。
真实入口 `python -m evals.codex_luna --output <private-directory>` 只允许独立
codex_luna_runtime_test PostgreSQL 库，默认 100 个合成来源案例：十类来源推理、四级长文
位置、业务工具提案。完成/失败/开始标记逐项落盘，恢复不重发未知案例，不额外统计费用
或用量；真实稿件原始输入输出保持仓库外。合成分数不代表文学或作者验收。


旧原生未知结果原因未定，保留且不重发；历史两路/总池策略由下述 2026-10-14 用户授权修订取代。


最终文本模式使用固定 model_instructions_file 替换默认编码指令、project_doc_max_bytes=0
和 skip_host_skill_discovery 隔离 AGENTS/host skills；ignore-rules 仅指 execpolicy .rules。
另外显式关闭 hooks、apps、浏览器、电脑操作、code_mode_host、goals、skill 自动安装与
原生无限重连，避免工具之外的本机环境行为。codex-text-v3 写入账户模板的非敏感 extra，
快照同时显式绑定 native_wrapper 的版本与固定指令SHA256，并由 extra_hash 固定连接；包装缺失/漂移不能静默沿旧快照恢复。历史快照和回执只读保留。

完整原生结果的格式/包封失败仍携带原生usage，既有信封、工作流meter和有界Agent保存为已知失败；只有没有完整回执的结果才未知，不补造或另建用量统计。

2026-10-14收敛证据见 [G2验收报告](../acceptance/2026-10-14-codex-luna-convergence.md)。未来失败仅记录退出码、是否观测到回合开始/完成/失败、是否由adapter停止及固定原因标签；标签不证明模型未执行，不改变unknown防重放。官方 [非交互事件文档](https://learn.chatgpt.com/docs/non-interactive-mode) 说明 JSON 事件与 ephemeral 会话边界，旧ephemeral答案无法据此补造。

## 2026-10-14 已授权修订：模型池、输入与范围

`LLM_MODEL_LIMITS_JSON` 按来源/provider/具体模型配置独立模型池，默认每池并发 8、RPM 0，
不再有跨模型总 semaphore 或全局 LLM RPM。键 `default` → `api/deepseek/*` 等 provider 默认
→ `subscription/codex/gpt-6-luna` 等精确型号依次覆盖；并发/输入预算为正整数，RPM 为非负整数。
普通、流式、修复与远程 embedding 按最终模型和实际 endpoint 归池。同宿主 API/worker 共享 OS 文件锁槽，
订阅池另绑定 ChatGPT 登录账户；配置改变等待本池已接纳请求结束，其他模型继续运行。
生产 API/worker 挂载同一私有 `llm-model-admission` 卷；本地使用系统用户私有目录。
RPM 是每模型的进程内 token bucket，默认关闭；正 RPM 部署仍按 worker 数核算 provider 总吞吐。
取消/进程死亡释放槽，排队受已有 run deadline 约束，provider timeout 不被删除。

新 Codex `gpt-6-luna` 能力配置声明总窗口 1,050,000、完整输入默认 500,000、输出预留 128,000、
额外安全余量 32,000。CLI 显式覆盖 `model_context_window=1050000`、
`model_auto_compact_token_limit=800000`，继续 `--ignore-user-config`，不修改桌面全局 catalog。
完整执行输入计量包括指令、历史/身份/证据、JSON 包封和 schema；为不可观测 CLI 宿主包封另在输入内预留 32,000。
未确认 tokenizer 映射时使用 UTF-8 字节上界，并在能力快照标明估算方法；这不是已实测输入能力。
500k 是输入上限；超过时拆包或明确延期，复核超限保留生成及必要证据为待核对，禁止静默截断。
其他 Luna 型号仍须单独登记。官方规格和配置定义见
[模型规格](https://developers.openai.com/api/docs/models/gpt-6-luna) 与
[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。
能力快照/方法/consumer read-set 固定策略；旧快照、字符规则、请求和原回执不扩大或重新盖章。
订阅 500k 可用性、语义质量和持续高并发未实测。

新 author-confirmed Luna 确定性流水线用 `confirmed_scope`，完成本次确认范围，
不因固定请求数、累计 tokens 或金额暂停。AIRun envelope v2 显式记录模式、可空请求上限及范围指纹；
未声明额度或授权策略不能把空值当放行。范围模式限已验证的冻结 Luna 模型，新队列仍经 owner、来源、
active run 和 lease 检查；其他模型/有界 Agent 仍用有限预算，循环、工具和单次超时不变。
Evolution `budget_total`/`budget_remaining` 允许成对为空；旧有限行原子扣减、旧信封保持原版本。
存在范围数据时迁移拒绝降级。旧未跟踪队列明确保留领域预算 seam，不能冒充已完整跟踪。

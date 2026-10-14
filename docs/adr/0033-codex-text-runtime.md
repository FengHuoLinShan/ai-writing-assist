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


旧大段正文及长合成请求的未知失败缺少原退出码与回合事件，且存在宿主执行环境差异；原因未定，不能归因为高并发。原未知请求保留且不重发。当前原生文本默认两路，CODEX_TEXT_MAX_CONCURRENT_REQUESTS 仅接受整数1—8；同一系统用户、同一ChatGPT登录账户在本机API/worker之间共享OS文件锁槽，配置不一致且有在途时失败关闭，容量改变只在全槽空闲时生效。等候在provider预算预留和请求超时前，并受run deadline约束；取消或进程死亡由OS释放槽。进程内LLM_MAX_CONCURRENT_REQUESTS总上限仍有效。它不跨主机共享，也不代表Luna的供应商并发能力；真实长篇高并发稳定性仍待验收。


最终文本模式使用固定 model_instructions_file 替换默认编码指令、project_doc_max_bytes=0
和 skip_host_skill_discovery 隔离 AGENTS/host skills；ignore-rules 仅指 execpolicy .rules。
另外显式关闭 hooks、apps、浏览器、电脑操作、code_mode_host、goals、skill 自动安装与
原生无限重连，避免工具之外的本机环境行为。codex-text-v3 写入账户模板的非敏感 extra，
快照同时显式绑定 native_wrapper 的版本与固定指令SHA256，并由 extra_hash 固定连接；包装缺失/漂移不能静默沿旧快照恢复。历史快照和回执只读保留。

完整原生结果的格式/包封失败仍携带原生usage，既有信封、工作流meter和有界Agent保存为已知失败；只有没有完整回执的结果才未知，不补造或另建用量统计。

2026-10-14收敛证据见 [G2验收报告](../acceptance/2026-10-14-codex-luna-convergence.md)。未来失败仅记录退出码、是否观测到回合开始/完成/失败、是否由adapter停止及固定原因标签；标签不证明模型未执行，不改变unknown防重放。官方 [非交互事件文档](https://learn.chatgpt.com/docs/non-interactive-mode) 说明 JSON 事件与 ephemeral 会话边界，旧ephemeral答案无法据此补造。

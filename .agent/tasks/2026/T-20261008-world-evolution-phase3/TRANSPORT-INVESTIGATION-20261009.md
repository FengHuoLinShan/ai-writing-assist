# 模型读取失败传输调查

核实日期：2026-10-09。结论为当前证据，不作历史服务端故障认定。

## 已确认结论

v14/v15/v16是三轮完整验收各一次终止读取失败，并非连续三个请求失败。
三轮合计96请求、93完整响应、3错误；多数模型调用成功。之前按整轮粒度暂停并表述
“连续三次服务不可用”不准确，本次按用户详细调查要求恢复受控验证。

三份旧异常链均从httpcore HTTP/1.1 `_receive_response_body` / HTTPX `response.aread`
的ReadError开始，经APIConnectionError映射为LLMConnectionError。没有TimeoutError，
也未到JSON/schema解析阶段。旧日志未保存HTTP状态、响应头/provider request ID、
socket errno及完整底层网络异常，因此无法区分服务端、途中链路或本地网络栈。
三个失败操作的usage_unknown保留；新实验使用独立请求及run，不补写旧用量、不重发旧任务。

| 旧失败 | 实际步骤 | 时长 | 输入字符数 | 输出上限/模式 |
|---|---|---:|---:|---|
| v14 call0030 | Scene4 discovery0 | 0.38秒 | 27985 | 16384 / thinking disabled / JSON |
| v15 call0054 | Scene5 discovery_review0 | 37.83秒 | 28395 | 32768 / thinking enabled high / JSON |
| v16 call0009 | Scene1必需World review | 29.56秒 | 12702 | 65536 / thinking enabled high / JSON |

当前超时900秒。以上时长和异常类型不支持“900秒本地超时”。输入规模不同、三种不同
业务步骤都曾断流，不能仅凭其中一个大请求认定输入过长或JSON格式问题。

## 为什么单次断流终止整轮

当前业务是多个串行必需步骤；SDK max_retries=0，generate_structured max_fix_attempts=0、
transport_retries=False。不是请求发送前被授权/费用审批阻止，三次已经进入接收正文。
`pipeline.py::_run_scene_call` 先持久化sampling，调用失败后保存failed/付费回执并raise；
已有failed日志再次进入即要求reconciliation，不重新发送。缺usage时build_call_receipt
保留未知，不假定免费。`state_review.py::settled_discovery_output_failure` 只有用量完整、
全部attempt已知且属于JSON/schema/truncation失败才允许发现批次partial隔离继续。
正文ReadError不满足该例外，故所在Scene不能完成；一轮其余请求成功也不能抵消它。
这解释三轮为什么分别被一次断流终止，不证明模型服务连续三次全面不可用。

## 真实调用链与当前环境

`evolution/tasks.py::call_scene_method` 每步进入resolve_scene_sampler，`return await`
完整业务调用后才退出上下文。`project/llm_runtime.py::open_project_snapshot_llm_client`
每次创建客户端，yield后finally关闭。独立Standards读代码/纯内存验证未发现提前关闭。
原三个失败步骤不是跨步骤复用陈旧连接，因而盲目禁keep-alive无已证实依据。

只读复建实际owner snapshot客户端确认端点api.deepseek.com、timeout900、trust_env=False、
无显式proxy、SDK max_retries=0；业务transport_retries=False。配置仍经项目稳定facade，
未使用静态Key替代。snapshot.sources.base_url只是配置来源标签，端点由实际provider核实。

当前DNS公网地址3.173.21.63，route经en0及普通LAN网关，macOS代理配置空；TLS公开证书
为Amazon RSA2048M01、*.deepseek.com。未发现当前显式HTTP代理或假IP证据，这不排除
旧时刻网络波动、系统VPN/透明网络层，也不是完整历史网络证明。

Python3.14.7、HTTPX0.28.1、HTTPCore1.0.9、AnyIO4.14.2、OpenAI SDK2.53.0、OpenSSL3.5.7。
Python h2未装；HTTP/2实验使用本机已有curl8.7.1/nghttp2，没有新增依赖或改变生产传输。

## 受控新请求对照

原失败request形状经同owner项目snapshot重新取当前Key，发起独立付费诊断；不执行旧
业务operation、领域写入或隐式重试。记录每个新请求的独立x-client-request-id、阶段、
安全响应头、TLS公开信息、原始传输字节/分块hash、异常cause/context链及用量。

| 条件 | 已完成成功/请求 | 说明 |
|---|---:|---|
| 小JSON，HTTP/1.1，同client | 8/8 | 首个新TCP/TLS，7次真实连接复用 |
| 原World review，HTTP/1.1，同client | 4/4 | 含最长105.17秒成功响应 |
| 原World review，Connection: close | 4/4 | 每次要求关闭连接 |
| 原World review，每次fresh client | 4/4 | 匹配实际业务生命周期 |
| 原World review，SSE | 2/2 | 保存流结束usage，不作产品/质量验收 |
| 原World review，native curl HTTP/2 | 2/2 | 确认实际协议2，TLS验证成功 |
| 原World review，native curl HTTP/1.1 | 2/2 | 25.45/58.33秒，两次usage已知 |
| 原discovery生成，每次fresh client | 3/3 | 1.63–4.37秒，usage已知 |
| 原discovery review，每次fresh client | 3/3 | 28.34–47.81秒，usage已知 |

截至本快照32/32新隔离请求成功、HTTP200、用量已知，无原读取失败复现。
这些阴性实验只缩小当前假设，不证明旧故障已经修复、不是概率性链路错误，
也不能从小样本断言HTTP/2或SSE优于HTTP/1.1。

非stream成功请求通常较快收到200响应头，然后继续等完整body；观察到gzip+chunked，
完整gzip流可以解压并取得完整JSON/usage。收到200响应头不等于整个模型调用成功。
校验12份nonstream原始gzip body均正常到EOF，另2份SSE观察到21个注释分块；
其中一次nonstream在60.46秒解压得到实际非空空白字符（不是把gzip零输出误认心跳）。
DeepSeek官方文档说明非stream空行、SSE注释保活，若10分钟仍
未开始推理则关闭连接；这个10分钟条件不能解释旧0.38/37.83/29.56秒失败就是同一机制。
依据：[官方限流/保活说明](https://api-docs.deepseek.com/quick_start/rate_limit/)、
[官方completion流协议](https://api-docs.deepseek.com/api/create-chat-completion/)。

## 实际业务比较及观察边界

新dev-v17使用当前源码方法7af0dbc4c8b9c00a77b0580ed959622c322141a763b4dfe976c22a81dd8130e1、
原冻结开发8场/rubric、独立新project/run；只加入私有HTTP观察，不改变模型响应、
业务配置、schema、生产源码或重试。终态8/8场提交，77/77完整响应、HTTP200、77次新TLS、0终止读取错误。
实际业务响应耗时1.27–119.34秒；加上32隔离对照共109次新调用全部传输成功。
一次UUID格式/schema失败为响应返回后的
独立契约失败，已settled并partial/not_checked披露，不等同ReadError或用量未知。
语义质量另由Spec独立审查，不能把传输成功算质量通过。

[HTTPX官方trace扩展](https://www.python-httpx.org/advanced/extensions/)用于记录读取阶段。
原egress guard先执行、诊断hooks追加且finally移除；body wrapper原样yield、aclose原stream。
headers只记录白名单，不记录Authorization/Key。私有目录0700、文件0600/umask077。

独立Standards纯内存探针发现诊断记录的磁盘OSError能中断健康响应或遮蔽原异常。
后续probe已将trace/body写入OSError记内存diagnostic_errors并隔离，异常文本复用现有
redact_diagnostic。已运行v17加载的是旧版观察模块，未中途改行为，故必须单列这一观察
干扰边界。当前没有观测诊断OSError；它不是已证实的原ReadError原因。
原网络ReadError仍须原样传播，不能把记录错误误记成provider故障。

## 尚未定位与行动

2026-10-09只读核对[DeepSeek官方状态页](https://status.deepseek.com/)显示当前全部正常；
历史页本次返回没有可核实的单次事件内容。当前正常不排除旧时刻或少数请求的间歇故障。

尚未定位旧三次body读取中断的责任端。对“DeepSeek过载”“本地代理”“SDK版本”“长输出”
均无足够确定证据；目前无需改provider/网络设置、加依赖、开重试或再加长900超时。

三种原失败shape对照及dev-v17终态均已完成，未复现旧错误。未来再现时按新trace看headers前/后、body已收字节、
TLS/底层errno、provider trace ID。若再次出现同类错误，可形成可关联上游request ID的证据。
向服务商发消息/工单不在现有授权内，尚未发送。原unknown保留，不自动核销。

原稿、raw请求/响应、body及详细trace只留仓库外私有目录：
`/Users/tywww/.codex/private/world-evolution-phase3-20261008/transport-investigation-20261009`。
本文件仅记录去原文结论；未改生产传输、提交、推送、合并或部署。

- 更新：后续私有probe磁盘隔离/脱敏通过Standards纯内存验证，健康响应字节、同一网络ReadError、aclose和关闭异常保持；trace/body OSError只记诊断错误。32隔离请求均无diagnostic_errors。独立请求/响应成果文件的写入仍可报本地OSError，须与网络故障区分。

终态补充：dev-v17已完整结束，不重发旧unknown；实际业务传输全成功，不是业务/质量全部通过。独立Spec已发现条件变化复核不足、明确例外漏落和回忆身份/资格漏落，质量门未过；未读取/运行替代blind、未写pass gate。生产方法7af0冻结，本轮不盲改超时、HTTP协议、provider或重试。

## dev-v24 新复现证据

S7 scene_discovery_review_0 首次请求 HTTP/1.1 200，0.55秒已收header，
chunked+gzip，经55.28秒读取body时报ConnectionResetError errno54（connection reset by peer）
→anyio BrokenResourceError→httpcore/httpx ReadError→SDK APIConnectionError。
新TCP/TLS连接成功、DeepSeek证书、直连CloudFront NRT节点；没有本地环境代理或重试。
已收3段共5160压缩字节、12773解码字节；gzip EOF=false且JSON不完整，不能
把部分响应恢复为成功/已知用量。trace ID留私有文件dev-v24-call-0068-trace.jsonl。

这排除了本次凭据拒绝、connect/TLS失败、900秒超时及Schema解析作为中断起点。
证据确认远端方向TCP重置，但尚不能区分供应商/CDN或网络中间路径的责任端；
也不能把新原因倒签到旧三次缺少errno的日志。此次unknown回执保留，不重发。
官方Chat Completions规范要求完整响应；部分JSON无依据提取业务结论。
参考：https://api-docs.deepseek.com/api/create-chat-completion/

第二次新复现v25 call0027：HTTP200约0.44秒后，在51.37秒body读取中reset errno54；同CloudFront peer IP、不同NRT POP。5段5766压缩/13965解码字节，gzip EOF=false、JSON不完整，同样无法回收。两个新中断之间有27份完整响应，不称三个连续请求失败。新隔离对照将用两个失败shape各fresh非流式/SSE及完整usage/finish/schema检测，非旧任务retry，不改生产传输。


## 重复失败shape交叉与窄修复（2026-10-09）

保留两次新peer reset的原operation，另用授权项目snapshot当前Key发新独立实验：
review24/review25分别非流式fresh和SSE fresh各2次（8），SDK原生聚合各1次（2），
10/10完整usage、finish stop、DiscoveryReview schema；诊断写入无异常，SDK/业务retry0。
双方均成功，不能证明SSE永久修复网络、供应商/CDN归责或更低速度/费用。
因此选窄的已安装SDK原生stream聚合，不造解析器或重发机制；仅支持的DeepSeek
Scene生成/复核opt-in，其余client调用保持原路径，复用原限流、root预留、总超时和结算。
全部消费成功后用public current_completion_snapshot保留已知length/filter终态，迭代异常
绝不救partial snapshot；filter在结构解析前拒绝并保留三字段用量，真断流/缺usage/finish
记未知、不重发。HTTPX raw Transport/Timeout映射统一领域异常。
真实SDK SSE七模式+实际envelope三模式包含关闭、single settlement、validJSON filter拒绝，
真实Evolution build_call_receipt验证已知失败费用。最终LLM/Project227、Evolution等393过。
新方法84822冻结，新dev-v26仍须完整工程及独立语义，不以10健康实验或离线门代签。


## 原生流再次reset（dev-v27）

旧edcc载入进程本轮3/8、26请求/25响应/1unknown后终止。S3发现call0025：
HTTP200约0.481秒、Content-Type text/event-stream、33.236秒底层ReadError→
BrokenResourceError→ConnectionResetError(errno54)；最后chunk距reset约11毫秒，
仍在持续收数据，未收到final usage。客户端response关闭发生在body错误之后，
非终态只作故障证据，未知收费保留、不重发。由此不能把非流式完整body聚合、gzip
缓冲或空闲无数据当成所有故障的共同原因；原生SSE不消除此reset，不能宣称网络已修复。
POP及trace ID仅私有，供应商/CDN/链路责任仍须其侧日志。正常25份完整响应与健康
交叉10次不是网络可靠性保证。生产未知失败与输入冻结仍fail-close；下一轮是新
独立评估操作，既有失败/unknown不修改。旧载入edcc源码检查点已私有保存，开发文件
进入binding14后与旧验收分别标识，旧进程/无reload API的实测source指纹不变。

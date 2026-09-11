# Assistant — 项目助手（ADR-0023）

Assistant 拥有跨页面讨论、Agent 执行、成组提案与提醒展示；不拥有世界事实、正文、结构、
RP 历史或领域复核。PydanticAI 仅通过 Project LLM gateway 执行注册工具，内部资料只经
Evidence 读取；业务写入需具体批次确认与来源重验。

## 会话迁移

`session_models.py` 接管原 World 共创会话和消息的唯一 ORM。物理表仍使用
`world_cocreation_sessions` / `world_cocreation_messages`，无需复制数据或重建身份；旧 World 类型与入口复用共享会话存储；World 保留世界模型上下文与持久共创任务。World source/checkpoint/outcome 判断由组合根注册的 World port 执行。
讨论不是 Canon；checkpoint 和候选内容仍引用原 World 载体。

## 执行记录

HTTP 入口为 `/api/assistant`；账户与项目身份由服务端验证。RP 提醒通过 Interaction 路由
接入，调用方只传 journey ID，不接受由浏览器指定隐藏项目或 owner。

- `assistant_runs`：owner/project/session、请求与冻结上下文、任务、预算、私有检查点和结果。
- `assistant_action_batches`：具体操作预览、基线指纹、确认、依赖与执行回执。
- `assistant_notices`：领域结果引用及已读/暂缓/忽略；不替代领域问题处置。
- `assistant_watches`：项目持续授权、待检变化、到期与合并进度。

公开响应不得返回运行私有检查点或供应商思考内容。RP 独立消息树/attempt 继续归 Interaction。

运行协议 v2 冻结逐工具的参数签名与实现修订；v1 的目录保持独立快照。新增工具不自动进入
旧运行，修改签名/修订时必须保留兼容实现或明确拒绝。确认批次也重验操作签名，已完成回执
的重放不重新写入。人工正文可使用 `review_world_constraints`，原 AI 建议继续用原资料审稿。
实现与验收状态见项目持久任务记录；仅离线协议通过不等于原生联网或产品质量验收。

## 主动检查与提醒

正文保存与 Evidence 资产失效事件、RP 有效路径/回顾/来源变化在同一事务标记待检。
初始关闭；开启保存项目、owner、类别、排除范围、联网许可和每日额度。普通变化稳定 60 秒后
可领取，同一目标 10 分钟合并；每日默认 12 次且每项目仅一项后台分析。关闭/修改授权会让
旧任务在下一模型请求或最终结果提交前失败关闭。

World/Writing 复用原领域审稿任务；RP 使用 Interaction 的连续性任务。Assistant 只保存
任务引用和提示投影。来源变化时抑制旧通知，已读/忽略/暂缓不会把领域问题判为已解决；
相同问题的证据未变化时保持原展示决定。当前作者/RP 均有站内回访与提醒入口。
独立审稿所需原 confirmation 不可被新助手范围替换；无法证明排除范围一致时返回明确冲突。

## 成组执行与恢复

确认绑定方案指纹与用户选择；全组预检后逐业务原子组提交。失败组阻断其依赖，成功组保留
明确回执。`retry_operation_id` 只重试原确认中未完成项，同一重试回执不会重复写入。
会话保留作者决定。正文修订新建可恢复工作稿并保留来源、基线与批准人，不制造审稿通过结果。
旧共创消息和手工决定即使没有任务关联，也按当前章节、排除范围和原 confirmation 规则
参与讨论历史；当前任务的消息不重复注入。新额度续查及批次重新查证保留原联网选择与
渠道标记，缺少渠道标记的旧请求不自动获得 SearXNG 授权。
运行响应仅在原任务仍允许人工恢复且本轮预算未过期时返回 `can_resume=true`；任务缺失返回
404，预算或状态已不允许沿用时返回 409，并提示作者开始新一轮查证。

消息的 `assistant_run_id` 关联原运行，历史方案、失败/停止回合与成果可以重新打开；
旧 World 消息继续保留 outcome/checkpoint 引用。确认决定同时保存原 task 与 confirmation，
后续相同范围的讨论不会丢失决定。公开 sources 保留类型化领域引用和领域审稿的实际覆盖、
遗漏；已验证问题必须指向已有领域 finding，Assistant 不另立审稿结论。

部分成功批次只记录已完成操作真实目标的后置状态，原证据不被改写，无关资料仍按原基线重验。
原 confirmation 和复核 guard 不会因重试被替换；它们已失效时可通过
`POST /batches/{id}/recheck` 显式新建一轮剩余项查证，沿用原范围和排除项，不重做成功项，
新方案仍须确认。预览读取前同样检查排除、原确认和章节/Scene范围；无法证明整体预览覆盖时
失败关闭，不从最终采用确认倒推扩大读取授权。

主动服务在保存授权、领取旧待检项和执行时重验类别与排除目标。World 的原字符串 finding
位置由 World 按冻结 manifest 投影为来源/复核身份；提醒的新鲜度由 World/Writing 原读取
接口判断。RP 约定、回顾分区和固定来源有独立引用，只有可在本次物化资料中精确回读的
成对证据进入提醒。

## 领域提案与受控恢复

生成型工具通过 execute_suggestion 复用原领域任务，父关系与模型快照在创建子任务时保存；
工具准备/读取中的模型调用也纳入同一预算，不只统计最终生成。普通领域修改仍只进入确认批次。
结构提案沿用 P20，正文沿用原 generation / semantic review / targeted revision / candidate adoption。
公开 domain_result 是未采用提案或回执，不能代替领域审稿 finding 或已发生事实。

作者可以按精确 ID/hash 审阅 candidate。它不会进入 working/canonical 原文范围，也不自动获得
原确认、审稿或采用资格；采用与从历史继续写均重验当前 working 基线及编辑器未保存输入。
世界阶段成果从运行绑定会话，不接受模型指定会话或来源 manifest；旧决定默认继承，指针推进
加锁并核对旧值。保存成果、保存采用包与正式采用是不同操作。


## 自托管联网与维护补全

新运行 v3 注册公开事实搜索、按本次引用读取网页和世界书历史工具；v1/v2 仍按提交目录恢复。
`TurnCreate.web_backend=searxng-v1` 与 `allow_web` 同时启用才授权新渠道，历史浏览器偏好没有
backend 标记时不继承。首次自动创建讨论保留输入、参考范围与联网选择。能力接口分别返回
模型连接和私有搜索服务的状态、原因及受控入口；模型不可用时仍能读取讨论和已有回执。

World 负责世界书编辑/发布/恢复与历史读取；Story 负责信息计划编辑及版本影响；结果保留具体
任务、版本和成果引用。P20 原任务可跨设备打开专业预览，已采用回执只展示成果。内部历史
仍通过 Evidence；带原 confirmation、排除或截止限制时不得扩大为历史全量读取。

`POST /notices/{id}/recheck?novel_id=...` 以 operation_id 去重，重新检查当前授权的最新资料。
准备失败可由服务器的 change_key 恢复；不需要伪造旧任务。重新检查使用新的运行额度，旧预算
保持，活动任务不重复执行，仍受项目每日额度限制。RP 使用 journey-scoped 对应接口。

## 导入确认减负

`imports.resolve_review` 按明确章节/候选范围启动 Imports 智能整理，`imports.accept_review` 预览并采用作者选中的具体结果。v3 的 `review_resolution_result` 只经 Evidence 回读范围内的新鲜结果；固定 confirmation 或排除项无法证明一致时不开放整批结果。已获授权的后台整理不逐项回到助手确认，身份/事实冲突仍以领域操作批次处理。

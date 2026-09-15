# ADR-0025：全产品知识治理——全知导演、最小知情生成、独立复核

- 状态：Accepted / Implemented
- 日期：2026-09-14
- 影响模块：evidence、writing、world、story、imports、interaction、assistant、前端各工作台

## 背景

各域 AI 能力对资料的取舍分散在检索、loader 与 prompt 拼装中：Top-K 检索容易被当作
"完整资料"；`HiddenGuardBuilder` 以对象/关系数量上限做防剧透兜底；多数能力没有独立
审查与返修预算；RP 正文边生成边流式展示，未审正文可能直接到达读者。产品需要把
"生成者知道什么"变成服务端可判定、可回读、可审计的确定性边界，而不是把希望寄托在
单次 prompt 的自觉上。

## 决策

1. 所有用户可见 AI 生成与检查能力统一为确定性工作流：
   `冻结任务资料 → 导演完整审阅 → 服务端裁出最小知情包 → 生成/检查 → 全知复核 →
   最多返修一次 → 通过或阻断`。"全知"指任务范围内完整、可回读的冻结来源，不扫描
   无关全项目，也不把 Top-K 冒充完整。
2. 导演、生成者、审查者是同一领域任务内相互隔离的受管 LLM step，复用同一项目模型
   快照（`open_project_llm_client` / snapshot seam），不新增自治多 Agent runtime、
   基础设施或第二事实库。导演/审查温度固定为 0；生成参数沿用各能力现值；语义返修
   只有一次，格式修复仍按原有限重试。
3. 静态 `CapabilityKnowledgePolicy` 注册表（evidence 知识治理子包）覆盖全部用户能力，
   声明知识主体、必查维度、confirmation/snapshot 策略、输出权限与采用门禁；query
   planner、reranker、格式修复等内部 helper 登记为基础设施豁免，不得产出答案、权限
   或事实。注册表并入 `make prompt-contracts` 与 AST 门禁：生产 LLM/Agent/stream/image
   调用必须绑定 capability ID 或基础设施豁免。
4. 三个版本化稳定契约（`KNOWLEDGE_POLICY_VERSION`）：`KnowledgeScopeReceipt`
   （来源 manifest、主体/截止点、included/excluded/omitted、权威与生成上下文指纹、
   逐维度 coverage）；`KnowledgeDirectorPlan`（只引用服务端短 key，把每份来源分为
   生成必需/生成可用/仅导演审查可见/禁止，不得回传隐藏事实正文，每个 key 恰好处置
   一次）；`KnowledgeAuditReceipt`（绑定输出 hash，记录遗漏、无证据事实、越界知识、
   提前揭示、无关内容、冲突和未完成检查）。完整 manifest 可分片交给导演与审查者，
   确定性 reducer 归并；预算不足、来源不可读或必查维度被排除时保存 continuation 并
   阻断生成，不静默裁剪；任何预算型 omission 都不能签署 PASS。
5. 知识可见性由 world 收口为批量 `check_knowledge_visibility()`：CharacterKnowledge
   （截止点前）覆盖优先，public/tag/private 按标签授予与排除判定，private 无明确授权
   隐藏，rule draft 不参与判决，再与 ReaderRevealPolicy 取交集。导演只能缩小服务端
   已判定的可见集合，不能决定 owner、`novel_id`、角色权限、截止点或写入权限。
   `HiddenGuardBuilder` 改为从同一冻结 scope 的"权威包 − 生成者包"派生，删除数量上限
   与无截止点二次查询；字面 guard 保留为确定性第一层，同义改写与隐含剧透由语义审查
   负责。
6. 所有新 AI 产物只有知识审查通过后才可展示/采用；再次失败保留为不可采用候选。
   RP 正文通过审查前不向用户流式展示：正文先写现有 attempt buffer 并以 checkpoint
   `release_state=held` 隐藏，通过后创建正式节点并一次性返回全文；一次返修失败则
   attempt 失败、正文保留私有记录但不展示。无资料 RP 保留低门槛入口，原作知识标记
   `unverifiable`；匿名公开演示不得把未揭示原文交给用户提供的临时 Key，缺少安全
   guard manifest 时失败关闭。
7. 响应加性增加 `knowledge_review.status = checking | passed | blocked | unverifiable |
   legacy_unchecked`、`repaired`、逐维度 coverage、脱敏 issue 计数与长任务 stage 投影。
   完整内部回执写入现有 confirmation compile options、context snapshot metadata、task
   result 与领域 provenance JSON；不持久化完整隐藏上下文、Prompt 或秘密，不新增数据库
   表或 migration。每次 provider 调用前、最终写入和采用前重验 scope/policy/source/output
   指纹。
8. 新任务冻结 `knowledge_policy_version=1`；在途旧任务按原快照结束并标记
   `legacy_unchecked`；旧已采用资产不追溯改写，旧待采用 AI 资产采用前必须通过当前重查。

知识导演、审查与返修 step 归属宿主能力的统一运行信封；分片序号不进入 step 名，回执按
稳定逻辑阶段聚合。知识治理 helper 不拥有独立 root，不能把内部格式修复或导演审查伪装成
`infrastructure.format_repair` 能力。
信封只记录模型请求与授权，不替代知识审查回执；Interaction RP 的 length/manual/看海续段
以同一 generation attempt 为 run，每个合法续段由作者授权追加一份分段额度，不移动 deadline。
旧 task 终态只能收口自己的队列行，不得覆盖已转交给新 task 的 attempt 进度。

## 结果与非目标

- 每个能力的导演+审查带来至少两次额外模型调用，成本与延迟上升被接受；Imports/Map
  按窗口/Scene/候选组/问题组冻结组级 receipt 摊薄。合成 provider 只证明工作流与门禁，
  生产发布前另行授权真实模型验收。
- 不新增第二事实库、通用 Agent 平台、知识策略编辑器、依赖或数据库表；作者修改采用
  稿后仅清除 AI 审查 PASS 投影，不剥夺发布手写稿的权力。
- 本 ADR 不改变 ADR-0017/0018/0022/0023/0024 已确立的事实权威、source 边界、复核
  所有权与有界 Agent 约束；治理工作流在这些边界内执行。

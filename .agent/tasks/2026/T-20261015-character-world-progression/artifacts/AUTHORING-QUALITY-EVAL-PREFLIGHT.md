# 三份计划的后续真实质量评测准备

2026-10-16，root依据Luna/max只读范围与公开调用链规划整理。本文件是待执行方案，
不证明质量通过，不扩大授权，不续用封存运行的预算。下列方案与估算不等于执行许可或实际用量；当前事实以最新检查点为准。


最新执行事实（2026-10-16）：导演R1正常API+精确TaskWorker产出一整轮，6次Luna/max、98624tokens、unknown0；最后预算检查误报paused_budget，且缺少角色POV来源，已封存诊断。root已修完成/停点语义、Token-only授权及前端路由并通过9023后端/3212前端/74PG。R2正常基础理解两任务完成，12请求/191022tokens/unknown0；免费生成6维检查点后，角色可见事实仍为0，唯一关系事件因端点未解析及载荷不可物化被门控。R2也已封存为来源不足诊断，没有导演/世界推进SUT及本scope教师/评分调用。导演卡片修订 accepted 识别另经204项Story回归修复，不提升未证明自由文本的知识权限。原作者输入/标准及旧preflight/回执不改绑；后续须使用具备实际角色来源的新样本及独立预检。holdout与其他四域judge保持关闭。

## 固定代码之前

C3/A1已由root独立收尾，primary6f00ad2285，完整普通后端9011及私有artifact尾修445项evals/最终前端3209/保留库72PG及正式页面通过。按用户最新要求不再使用子代理。新受限scope由root接管完成，含31个新离线用例；最终后端9011项通过，导演与世界推进均通过正常API+精确离线TaskWorker的真实PG取证，仍不等于真实模型质量。

旧Map/G7/AskWorld许可不能借给新领域，全局缺省校准门禁保持关闭。新scope每个私有运行最多12个请求、每prompt160000字节，绑定同一owner/隔离Project/数据库、模型、pipeline/schema/rubric/input/split及实际产品回执；seed和同case teacher回执不得改绑新manifest。source/rubric须先冻结，teacher始终看不到SUT输出。当前只有director/world_progression可评分，其他四域仅seed/teacher；holdout仍关闭。六Project完整矩阵的76估算须重算，不能以此作为本批授权或实际用量。

Root拟先完成一个独立的描述性导演/推进小批（每域seed/teacher/judge各1，额外6请求；SUT业务请求另按真实预算预览），验证可执行取证链。source/rubric先冻结，SUT完成后把不可预测的真实输出ID和哈希绑定到不可变manifest；之后不追加case或换manifest复用旧seed。最终源码已集成。地图仍使用既有map_spatial控制链，R3、R4已封存，不重试不续额；R5五族校准完成，其中两族Evolution完成65请求/1006437tokens/unknown0，另三族attempt0正常停止；因代理作者驱动错误阻断待采用地点，该scope已封存，Writing/Assistant/judge未执行。修复后须新身份/校准/范围预算，不改绑旧scope。

## 最小描述性小批

沿用修仙、西幻、都市、科幻、悬疑，另加群像或种田，共6个隔离Project。
每个Project准备5个有canonical正文、精确Scene span和已解析对象来源的Scene。
source/gold/实际输入输出均存仓库外私有目录；开发与留出集分离。
教师及评分固定现有Sol/xhigh协议，被测程序经owner已验证Project的Luna/max。
不得把seed自测等同人工一致性校准或作者验收。

- 地图只跑前5个Project的既有五Scene矩阵。按正常作者审核回执采用后，明确指定Scene地点UUID；
  eligibility/Brief/来源不成立时记not_run，不猜地点。先完成25开发case门，再单次独立holdout。
- 档案读取、有效期提醒与对照记录按实际World/Evidence/Story只读链采集。C1发现、涌现与更新
  指标继续等待P4长篇前置，人工已采用档案不能冒充自动发现成功。
- 本轮导演**每Project只选1个冻结Scene**，3角色1轮，共6轮；逐角色盲辨、套话、来源、素材感知者、
  越权知情和未标冲突分别记录。扩展至全部30Scene需重新算轮数与预算。
- 每Project发起1个真实forecast task，新默认v2人物表演和转场按最终C3协议共父预算。
  没有同范围历史v1时只描述新输出，不声称相对提升。
- 每Project设置1个有逐字段/同对象/同截止点来源的冲突及1个无冲突对照；正常处置后按原fingerprint
  复读，再变化依据复读，记录提醒是否正确重现。
- 世界推进每Project取2参与者1步，自由/导向模式平衡，并覆盖无法自然抵达目标。
  其中1个Project再增加2步，使该根共3步：一段实际历史后由新的成功阅读回执触发持续提醒。
  总共8步，root预算需容纳80%停点；先以实际预览冻结，不为完成偷偷加额。
- Goal取前5题材各1目标，冻结只读、候选、R2可恢复及R3停点范围。
  注入文本不能扩权；只在隔离Project确认/恢复，M5势力及外发/删除不纳入本批。

## 请求上界与停点

所有数值是上界，task数不等于模型请求数，实际receipt另计；费用未知不填0。
令`E_f`为最终实际Evolution preview批准的第f个地图根上限，`G_i`为每个Goal完整根冻结上限：

| 组别 | 本小批上界 |
| --- | --- |
| 地图 | `1480 + ΣE_f`：每Project seed1、judge5、Writing十臂各14、Assistant五轮各30，加其Evolution根 |
| Forecast | `6 × 4 = 24` |
| 导演 | `6 × (2×3+2) = 48` |
| 世界推进 | `8 × (2+1) = 24` |
| Goal | `ΣG_i`，含目录选择、规划和领域步骤，不能只计算规划两请求 |
| 其他域seed/teacher/judge | 暂定`6 + 35 + 35 = 76`，须以最终scope可执行域/冻结case清单重算 |

合计暂为`1652 + ΣE_f + ΣG_i`，另加必要的独立连接验证；同owner已verified应复用，
不为每Project重复付费验证。新地图资料如需新teacher gold，须再单独计入；原冻结source/expected
逐字节复制与hash核验不构成新教师请求。旧R3的51或347均不是本批可续额度。

unknown/超时保留已尝试与可能计费状态并停批，不重发、不清零、不把上界当实际花费；
每步实际AIRunEnvelope/provider receipt、wall时间、未运行原因和作者取舍单列。
没有正式矩阵、来源覆盖、校准支持数与真人作者认可时，始终`human_validated=false`。

## 执行前仍需取得

最终主会话固定源码及新pipeline；owner当前verified快照；新隔离运行身份/私有root；完整case与source/gold分割；
正常Evidence confirmation及允许引用项；实际已采用World/地图/地点身份；功能开关和allowlist；
每个Evolution/Goal/导演/推进的实际预览、授权范围和父预算；新scope的seed与产品证据读取证明。
小批失败应保留原账本及停点，独立修复后使用新身份，不修旧收据。

范围源为三份plans的验收节；地图既有步骤继续以
[MAP-SPATIAL-LIVE-PREFLIGHT](../../T-20261015-map-enhancement-design/artifacts/evaluation/MAP-SPATIAL-LIVE-PREFLIGHT.md)为准。

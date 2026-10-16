# 三份计划的后续真实质量评测准备

2026-10-16，root依据Luna/max只读范围与公开调用链规划整理。本文件是待执行方案，
不证明质量通过，不扩大授权，不续用封存运行的预算。当前没有新增真实模型请求。

## 固定代码之前

C3/A1仍由Sol/high审修。地图继续使用既有map_spatial正式控制链；其余领域的受限
seed/teacher/judge scope由Luna在`codex/authoring-quality-eval-guard`原实现，之后交Sol独立审修。
旧Map/G7/AskWorld许可不能借给新领域，全局缺省校准门禁保持关闭。
新scope没有真实证据读取能力的领域必须拒绝评分，不能接受调用方自报成功。
最终固定源码、pipeline/schema/rubric指纹和独立校准未完成前不运行该新入口。

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

最终Sol净源码及新pipeline；owner当前verified快照；新隔离运行身份/私有root；完整case与source/gold分割；
正常Evidence confirmation及允许引用项；实际已采用World/地图/地点身份；功能开关和allowlist；
每个Evolution/Goal/导演/推进的实际预览、授权范围和父预算；新scope的seed与产品证据读取证明。
小批失败应保留原账本及停点，独立修复后使用新身份，不修旧收据。

范围源为三份plans的验收节；地图既有步骤继续以
[MAP-SPATIAL-LIVE-PREFLIGHT](../../T-20261015-map-enhancement-design/artifacts/evaluation/MAP-SPATIAL-LIVE-PREFLIGHT.md)为准。

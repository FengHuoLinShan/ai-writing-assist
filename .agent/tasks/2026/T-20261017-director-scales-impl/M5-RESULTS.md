# M5 实测、限制与开放决定

本轮已完成授权范围内的工程修复、隔离 Luna 诊断及三轨证据报告。**默认保持关闭**；当前结果不满足独立质量或真实作者验收，不能宣称产品已通过验收、相对质量提升或节省成本。

## 版本与运行范围

基线 `b4a42119a2c2a05552072669baaf99e31798d82c`，分支 `codex/director-scales-followup`；本轮修改仅在本地，未提交、未推送、未开新 PR、未部署。各轮冻结代码/资料哈希、全部尝试与请求摘要见 [M5-LEDGER.json](M5-LEDGER.json)。最终源版本指纹为 `6dec61403b7f92b7835f7ca5ed2e33c4005dbc0812aa272b2577f687caf09ab9`。最后的资料/预算/意图 prepare 提前拒绝补丁只追加工程验证，不冒充已重跑的模型质量证据。

用户选择 G7b v3 evolution 隔离副本 `06f08dc3…`。源容器 65197 只读；专用容器 62321 中模型库 `director_scales_guimi_test` 与工程库 `director_scales_e2e_test` 分离，且与另一项验收分库。owner 连接正常验证后，经 Project facade/snapshot 固定 Codex / `gpt-6-luna` / `max`，没有供应商回退。原始请求、稿件和输出仅在仓库外私有目录，仓库只存哈希、状态和结论。

17 个固定例主要使用该隔离项目内的合成临时起点；另有真实 guimi 首 Scene 的确认锚点诊断（4 项资产、5 项来源）。这不是全书内容验收。封存评测、暂停的独立教师、真实作者观察均未运行。

独立案例组并行 4，派生阶段按组并行，账户池 8/RPM0；同项目 Goal 因单活约束顺序运行。纯 Luna 无金额上限，产品请求/时间/预算和未知回执保护保持。只领取本任务精确 task_id，没有全局队列扫描。

## 工程轨

- 最终组合回归：396 passed；目录快照 14 passed。基础设施 LLM 496 passed / 2 deselected。
- 最终 prepare 修补后，PostgreSQL 生命周期/迁移/并发 10 passed。模型 I/O 为合成替身，证明实际 DB/worker 调用链，不证明输出质量。
- 浏览器 8 passed，Goal Vue 17 passed；浏览器覆盖真实 Vue 交互，但模型/探索网络 I/O 使用路由替身。未作安装包或原生桌面生命周期验收。
- Ruff、受影响前端 ESLint、secret-hygiene、diff-check 通过。普通 docs-check 通过；BASE_REF 影响复核按现有机制提供两份架构流程文档的明确无变化理由后通过。
- 最后只读复审未放松 owner/novel_id、Evidence confirmation、CAS、锁定、预算、幂等、R3/R4 或未知保护；新增拒绝路径先红后绿。日志位于 `/tmp/director-scales-m5-*`，对应检查摘要纳入账本。

修复包含：同项目锁升级死锁、必需任务包被导演丢弃、语义失败误分类为软预算暂停、原生包封预留不足、完整排演作者目标丢失、无解空路径拒绝、继承模型身份误报，以及 Goal 项目 UUID/结果字段说明和目标/资料/预算的执行前校验。新预算 v2 与旧根 v1 分开校验，旧账本不自动增额；Goal token 上限 5m，默认 12k 不变。

## 当前模型轨

固定 17 例：**11 完成，6 被产品自身 Luna 知识审查阻断**。完成表示产物状态与预登记机械检查成立；同一模型的治理审查不构成独立教师评分。未匹配旧路径基线，未设置事后文学评分或调整原阈值。

| 固定案例 | 最终状态 | 预登记机械检查 |
| --- | --- | --- |
| b1-sandbox | completed | chain=true |
| b1-unknown-percent | completed | unknown=true, no_percent=true |
| b2-diagnose | completed | diagnose=true |
| b2-diagnose-only | completed | diagnose=true |
| b2-bridge | blocked_by_product_knowledge_audit | 未产出可用结果 |
| b2-bridge-impossible | completed | unsolvable=true |
| b3-line | completed | line=true, no_private=true |
| b3-misbelief | completed | line=true, no_private=true |
| m2-info-gap | completed | info_gap=true |
| m2-info-gap-hard | completed | info_gap=true |
| m2-goal | blocked_by_product_knowledge_audit | 未产出可用结果 |
| m2-goal-impossible | completed | goal_unsolvable=true |
| m2-voices | blocked_by_product_knowledge_audit | 未产出可用结果 |
| m2-voices-private | blocked_by_product_knowledge_audit | 未产出可用结果 |
| m2-spatial-missing | blocked_by_product_knowledge_audit | 未产出可用结果 |
| m3-full | completed | full=true |
| m3-full-unknown | blocked_by_product_knowledge_audit | 未产出可用结果 |

六向移交全部运行；四向完成，两向在目标生成中被产品知识审查阻断。六向均核对直接父来源并重新确认目标资料；不把“交接成功”替代“目标结果可用”。

| 方向 | 状态 |
| --- | --- |
| b1-sandbox → event | blocked_by_product_knowledge_audit |
| b1-sandbox → scene_line | completed |
| m2-info-gap → sandbox | completed |
| m2-info-gap → scene_line | completed |
| b3-line → sandbox | completed |
| b3-line → event | blocked_by_product_knowledge_audit |

补充闭环：反事实比较、基线不变和诊断 detail 均完成；双人两轮完整排演完成 18 次 settled 请求。真实 Scene 锚点完成。锁定/过期选择拒绝均未触发模型；事件局部修订 5 次 settled 后被知识审查阻断，原结果与锁定项保持，未交付可用修订。单句附带 action 不属于独立修订路径，实际 409 拒绝且零模型请求，仍为能力限制。空间尺寸仅为未确认作者假设，`supported_geometry=false`，不能声称正向几何或物理可行性通过。

### Goal 版本与停止

首轮跨层规划因参数/回执契约失败后取消。补充 UUID 和返回字段后，final-v3 的七步路线完成前六步，第七步漏选人物；入队与原生请求均未发生，但 Goal 保守保留未知领域回执后取消。该旧步骤未重发。final-v4 跨层的两次规划请求已结算，因结果引用没有声明直接依赖而被拒绝，未执行领域步骤，随后取消；保留为当前模型失败，不放宽图校验或自动重规划。

| 案例 | 版本 | 状态 | 检查 |
| --- | --- | --- | --- |
| goal-cross | final-v4 | failed | 计划未通过；自身 run 已取消 |
| goal-single | final-v4 | completed | plan_completed=true, no_canonical_changes=true, no_automatic_approval=true, single_layer=true |
| goal-stop | final-v3 | completed | cancelled_before_approval=true, no_domain_approval_sent=true, no_canonical_changes=true |

取消案例在批准前终止，未发送领域批准、未写正式内容。Goal 只在本次目标显式 auto_r2 范围执行；没有自动批准 R3/R4。模型规划/知识审查失败保持失败，不以人工补计划冒充自主成功。

### 请求、费用与记录器例外

去重原生请求共 160 次（包括 2 次连接健康验证），状态 {"settled": 160}；有用量回执 160 份，已知总 token 2,215,281。中位原生延迟 19.92s，最长 94.14s；不包含作者阅读/修正时间，不能据此推断相对性能。账户未提供可靠货币金额，实际费用未知，不能记为零。

final-v1 私有记录器错误地跨案例比较相同请求哈希，在进入原生 provider 前阻断一例，产品保守留未知回执；final-v2 修正到同 case 后仅复用已 settled 结果。未重发结果未知的原生请求。原失败、同 operation 诊断恢复、脚本提前失败、未运行标记及旧轮均保留，没有只保留成功版本。另两个旧派生记录的状态字段误留 started，但已有终结 checks/seconds；账本保留原文件哈希并单列标准化状态。

## 数据保护与作者轨

源库与恢复基线 153 表终检相等；副本受保护业务表无变化。writing_drafts 共 120 份，原列完整指纹 `9a445445ee8a8db08c236189a2929ced` 保持。副本仅新增或更新本次确认、临时探索、任务、模型连接验证及派生检索等数据。

扫描 16 个人物生成请求，M5-R8/M5-Q7 私密 canary 命中 0。该检查仅证明这些标记未进入所查人物请求，不能证明所有语义知识边界或未来信息绝无泄漏。

真实作者任务观察、首次可用结果、阅读/修正时间、控制感、拒绝原因和延后价值均未验证；`human_validated=false`。没有以模型输出或工程测试替代作者反馈。

## 开放清单与回退

| 任务范围 | 本轮结论 | 决定 |
| --- | --- | --- |
| 沙盘、诊断、单句、信息差、反事实 | 有完成样本与工程证据，独立质量/作者证据缺失 | 继续隔离试验，默认关闭 |
| 补桥、导向路径、人物差异、空间诊断 | 存在审查阻断或未获正向支持 | 不开放，不用“未知”掩盖能力不足 |
| 完整排演、局部修订、六向交接 | 部分完成；困难排演、局部修订、两向交接失败 | 保留能力限制及失败，默认关闭 |
| 自主 Goal 跨层 | 有部分路线执行证据，最新计划仍失败 | 不开放自主跨层承诺 |
| 真实作者/独立教师/生产 | 未验证或未授权 | 不采纳 ADR、不发布 |

全局 `STORY_EXPLORATION_ENABLED` 默认关闭；历史与比较保持可读，关闭不删除旧结果、稿件或参考。沿用现有总开关与项目允许列表，不新增按任务的产品开关。以后开放任何任务仍需其独立质量与作者证据；发布另按固定 origin/main SHA 及明确授权执行。

本次后续任务交付为可审查的三轨报告与默认关闭决定；没有把 M5 报告完成写成整套产品质量、作者或生产验收通过。

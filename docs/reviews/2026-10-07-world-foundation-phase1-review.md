# 世界演化第一阶段独立审查与代理作者验收

日期：2026-10-07（Asia/Tokyo）。结论：**不通过，M0–M7 不可整体核销**。
用户已授权由主 Agent 代作者验收，本轮验收判断完成；不是等待用户再试用。
`evaluator=codex_author_proxy`，`human_validated=false`。

## 版本与方法

审查 world-foundation-plan 工作树全部第一阶段 WIP（包含新增未跟踪实现），固定基线
`85fb1c7be35ae687f949863d179f5fd63c53f3c0`。基线至 HEAD 提交差异为空，故实际评审范围为
该基线到工作树的差异；未创建快照提交。初始逐文件 SHA-256 留在仓库外私有目录。

沿主计划与 M1/M2/M4/M5/M6 契约做独立 Standards/Spec 双轴审查，由主 Agent 复核。
浏览器使用实际 API、PostgreSQL 与 worker，模型 IO 为既有合成 provider；新库
`agent_e2e_world_phase1_review_20261007_b84c1` 明确可丢弃。已有真实模型账本只读，
没有新付费调用、没有重置预算。保护库与 Guimi 项目未连接、未改动。

## Standards

以下仅列已证实违反现行规范的项目，不把代码气味本身当作错误。

- **S1 / P1：缓存正文随全库备份进入异地备份并在恢复后保留。** 新表含材料与编译正文，
  `deploy/scripts/backup.sh:77-82` 没有表数据排除，`:120` 上传完整 dump；恢复脚本也没有
  冷缓存处理。违反修订 ADR-0018 的正文不进入备份/恢复后冷重建边界。修复应在现有
  备份/恢复路径排除派生表正文，并验证恢复后为空，不新增备份框架。
- **S2 / P2：匿名演示读写仅允许登录 RP 使用的持久缓存。**
  `backend/modules/evidence/compilation/services/interaction_story_context.py:292,505`
  无条件 fetch/store。实际 anonymous API → InlineStoryTask →
  `generation.py:437` 的 `public_demo_source=True` → compile → `generation.py:553` commit。
  应在共享编译入口按实际 principal/公开路径阻止缓存读写，保留匿名原编译路径。
- **S3 / P2：缓存单行额度只检查材料，漏掉编译包与正文。**
  `interaction_source_cache.py:258` 只比 material_bytes；合法合成输入实际存入
  **419,833 bytes > 262,144 bytes**。`touch_compiled` 也漏额度。应按完整行计量、更新时
  同样检查，超限跳过缓存而保留必需证据。并发 consumer 总额未实测，不并入确证结论。
- **S4 / P2：新 migration 与 ORM 索引不一致。** 干净 PG upgrade 到 head 成功，但
  `alembic check` 失败：缓存 novel_id 索引命名不一致，lexical GIN 索引未进入 metadata
  或受控迁移管理清单。对应 `compilation/models.py:464-468` 与两个新 migration。
  三个差异均指向本批新增索引，不能把 upgrade 成功等同 schema parity。

Standards 共 4 项，最严重为 S1；未执行实际异地备份/恢复，也未注入 PG 缓存删除故障。

## Spec

- **R1 / P1：真实 REST 丢弃整个新增对象状态和新鲜度标记。**
  `backend/modules/evidence/compilation/schemas.py:240-249` 未声明 `object_states/stale`，
  `api.py:152` 构造响应即丢弃；服务层单测通过仍无法穿过响应模型。真实 REST 200 与
  浏览器重现对象一直空态。违反 M2 对象明细与 M5 待核对入口，应补实际响应契约与纵切断言。
- **R2 / P1：角色/读者知识过滤不完整。**
  `backend/modules/story/continuity/scene_state_view.py:246` 无条件返回全量对象名称；
  `:534-535` 仅因关系提到角色就放行。探针：读者 facts=0 仍拿隐藏名称；无知识授予的
  角色读到针对自己的秘密关系。违反 M2 §5，名称、关系、时间/因果与实际证据均须同视角过滤。
- **R3 / P2：作者入口缺少来源回开和逐对象未知。**
  `scene_lens.py:286-314` 丢弃 source/evidence_refs/omissions，并跳过无事实的相关对象；
  前端只显示字符串。锁条件未记载时消失，不能逐项解释未知。违反 M2:18/82/136，
  不能以全局空态提示替代对象级来源、缺口与未检查范围。
- **R4 / P2：旧 checkpoint 的普通 ensure 不能补来源基线。**
  `scene_projection.py:376-382` 与 `repositories.py:1113-1127` 只按投影 hash 短路；
  basis=None 旧行仍原样返回，永久 degraded。违反 M4:84-85/144 的普通 ensure 恢复契约。
- **R5 / P2：正文试改的状态影响锚定错误。**
  `backend/modules/collaboration/state_impact.py:55` 用 int 对比真实 `chapter_ids=["1"]`，
  作者已关联的场景被显示为未锚定；伪造整数 fixture 又会在 `:75-83` 把所有维度、
  包括 missing 与引用别的资源的维度都列 affected。违反 M5:42-45。应归一真实章节契约并
  检查实际 evidence_refs，无法证明的影响留 not_checked。
- **R6 / P2：有限钥匙/锁裁决尚未贯通。** 主计划:72/95-97/298 要资源、知识与明确条件，
  无依据返回不确定；本批没有 checkpoint → SimulationSeed/ResolutionBatch 的作者调用链。
  隔离探针中未声明资源前提的开锁行动、空状态、模型 succeeded 仍可产生 succeeded。
  这是指定切片尚未实现的证据，不主张所有自然语言行动一律失败，也不要求通用规则 DSL。
  现有 LLM world_stress 不能核销确定性条件裁决；状态影响列表也没有实际候选状态/结果比较。
- **R7 / P2：真实评测未满足冻结样本与完成门禁。** 主任务冻结 dev 6 族、holdout 3 族、
  30 轮长程；实际 dev/holdout 各同族 6 轮，两套资料前 12 章相同。布局对照仅重放
  turn1/2，旧臂 turn2 使用新臂历史，没有独立长程私人旅程。两个裁判样本不能核销
  主计划:372-374；机器 invalidation_passed 三阶段均 False，领域失败关闭与零请求应分开。
  主 Agent 复阅已有双臂也发现新臂摆设连续性反例，不能继续报告质量不降已完成。
- **R8 / P2：窄屏从状态直达试改会让两个抽屉同时 inert。**
  `frontend-console/vue/views/writing/components/SceneLensSummary.vue:71-73` 打开助手时保留
  本章资料抽屉。实际默认窄视口下，两 dialog 的祖先分别被对方的 modal lease 设 inert；
  AX 树只剩根，填写失败、关闭按钮不可用。刷新并从单一助手入口才能继续。应先交接/关闭
  原抽屉，覆盖真实窄屏输入与关闭路径，不仅断言试改区域可见。

Spec 共 8 项，最严重为 R1（作者状态整个断链）与 R2（知识边界）。两轴分别计数，不互相
抵消或以 test green 排序。共 12 项确证/需求缺口，不包含待验证的 PG 故障风险。

## 代理作者验收

按“能否据此放心改稿”验收；合成 provider 的检查通过只证明控制链，不证明文学质量。

| 步骤 | 实际结果 | 代理作者判断 |
|---|---|---|
| 看状态 | 直接 Story REST 能区分所有权、保管、误信；Lens REST 丢整个对象区 | 不通过：作者在界面看不到这些区分和依据 |
| 从状态试改 | 正文/场景正确预选；窄屏两个抽屉互相 inert | 不通过：需要刷新改走单一入口 |
| 预览与比较 | 原稿不变，字段 diff 可见；状态影响错误报未关联，无开锁候选结果 | 部分有效，不能据此判断世界后果 |
| 确认保存 | 确认前 drafts=1/receipts=0；确认后 drafts=2/receipts=1 | 通过：保留原稿，显式确认后才落工作稿 |
| 事件边界 | 试改与采用后 memory_events 都是9行 | 通过：规划未自动变成已发生事件；只证明本次切片 |
| 改稿后核对 | 作者补充未说暗号、锁仍关闭并保存，drafts=3/receipts=1；六维变无可靠记录 | 不通过：没有逐对象核对/依据回开与可用恢复入口 |
| 离开恢复 | 刷新后 v2 采用稿与随后 v3 作者稿均实际读取 | 通过：这次没有静默丢稿 |

代理作者可用性结论：**不愿据当前界面进行世界演化决策**。原稿/候选对照和二次确认有价值，
状态页不能回答谁保管、谁拥有、谁知道、依据在哪、哪些条件未知；手工核对成本仍不可接受。
这是本轮 Agent 代作者的明确反馈，不冒充用户本人反馈。

## 已有 RP 双臂的独立代理作者评阅

只读取旧私有累计账本的 dev/holdout 布局各两臂（序号88/89/138/139），没有新增模型评阅。
读完整请求约束与对应输出，未作盲评。原始引用与细节保存在私有目录，不入仓。

- dev 新臂有明确的同一段内坐具/姿势连续性矛盾，旧臂没有同一问题；两臂均需作者修订。
- 四段都让限制发言对象的人物直接回答玩家，按冻结人物行为的字面要求均未通过；
  用户“旁敲侧击试探”没有指令让该人物突破行为约束。holdout 新臂透露秘密更克制，
  仍不足以整段免修采用；旧臂有更强的秘密暗示风险。
- 因此驳回原“无任何新布局下降反证/质量不降完成”的核销。短程缓存收益保留为局部测量，
  不推断独立长程质量、完整混合场景成本或真实作者满意度。

评阅资格仍为代理作者，human_validated=false；没有重新训练/调参、没有重跑已见 holdout。

## 本轮验证与边界

- 受影响后端定向测试：47 passed；前端 sceneLensModel：2 passed。绿色没有覆盖上述
  REST/schema、真实章节类型、来源边界与窄屏交接。
- 两组独立确定性反例由主 Agent 重跑：Spec 各反例 defect_observed=true；Standards
  额度/标签/秘密关系检查失败，exit1 符合未整改事实。
- 新专库 fresh migration upgrade 成功；alembic check 失败，仅涉及本批新增索引。
- 普通 make docs-check 通过；BASE_REF=origin/main 检查要求5份未变更文档核对说明，
  无说明时失败。未以批准文档说明或更新 PR 模板绕过，本轮没有创建 PR。
- git diff --check 通过；没有重跑全量7192测试、远端CI、跨worker并发、真实备份恢复、
  生产 TEI 费用或真实用户试用。旧费用数值只作账本估算，不是供应商发票。

## 证据与下一步

机器收据：主任务 artifacts/author-acceptance-20261007.json。
原始截图、真实API JSON、WIP指纹、确定性探针、RP代理评阅细节均在仓库外
`/Users/tywww/.ai_writing_private/world-phase1-review-20261007/`。
旧付费账本 `rp-real-20261007/paid-calls.json` 仅读、原 hash 保留。

本轮仅写审查/验收报告和既有任务记录，产品实现保持原样；未提交、推送、PR、合入或部署。
任务实施保持 active。下一次整改先修 Lens 响应契约与窄屏交接、知识过滤与缓存边界，
然后修来源/影响/恢复；有限裁决和独立长程门禁仍须按已授权产品范围完成，不得靠缩小
验收口径核销。整改授权后再重跑此报告的可复跑检查；作者验收已经执行，当前结果是失败。

收尾：本任务18007/18087临时服务已停止；仅本任务创建的合成验收库保留供整改复跑，
保护库与原共享环境保持原样。初始WIP逐文件核对确认产品文件未变化；旧付费账本
SHA-256 与原脱敏快照一致。

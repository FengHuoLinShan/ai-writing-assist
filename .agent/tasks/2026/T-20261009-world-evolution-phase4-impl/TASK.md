---
id: T-20261009-world-evolution-phase4-impl
title: 世界演化第四阶段实施：长篇跑通、台账扩类与精细依赖
status: active
created: 2026-10-09T23:52:27+09:00
updated: 2026-10-12T23:36:26+08:00
---

# 世界演化第四阶段实施

## 当前恢复快照（2026-10-12 整理核实）

- 工程交付：[PR #220](https://github.com/FengHuoLinShan/ai-writing-assist/pull/220) 已合入 main，合并提交 `2dce04f42a7d7eb41eaf0c025033c1eb4a051e50`，当前 main 可达。固定 head `8aec33461241690060eef710e8503d0bb849b63d` 的六项必需检查通过。
- P4-A/B 工程修复与复审、P4-C 类别补扫、P4-D 实际消费者输入证明及选择性重做已完成离线交付；原 51 文件补丁与取用快照一致，已被 main 的修复版本覆盖，重复 WIP 已清理。不要再从旧补丁重做实现。
- 仍未交付：P4-E 真实长篇覆盖/质量/费用、封存盲验、早期改稿成本对照；重要物件/规则后果分布裁定；世界知识、地图册、世界正史版本的来源依赖闭包。缺证据时仍保守重做。
- 作者验收已明确跳过，`human_validated=false`；不能继续将作者验收列为等待批准，也不能写成质量通过。未部署。
- 独立 Guimi60 对比任务在其隔离工作树推进；本次未修改该任务、模型配置、运行、真实库或私有输出，不能用尚未交付的对比结果代签 P4 验收。
- 主干证据：PR #220 的原 main WebKit 核心流程曾失败，原失败保留；最新 main `974f0f5080d43472bc599d1d74782913c725057b` 在相同业务代码上全套检查成功。本次不宣称已定位/修复该旧失败根因。
- 下一步：保持 active，按剩余真实资料/模型验收的有效授权与独立任务结果续接；本次只整理，不恢复 provider。

- 唯一后续主笔记：主工作树本路径 `/Users/tywww/Desktop/项目/ai-writing-assist/.agent/tasks/2026/T-20261009-world-evolution-phase4-impl/TASK.md`；旧工作树副本只读。
- 最后核实：2026-10-12T23:36:26+08:00。以下各节保留原验收、失败和授权的历史证据，不代表当前交付状态。

## 历史记录

## 恢复快照

### 2026-10-12 PR交付续接（当前）

- 最新用户授权：跳过作者验收，创建PR并合入main。覆盖此前“暂不合main/推送”限制；真实模型暂停、真实数据保护和不部署保持有效。
- 作者验收明确跳过，human_validated=false；P4-E模型/长篇/封存质量与成本未验收，主任务仍active。不将工程合并或用户豁免记为质量通过。
- 实现提交be331ddb5，生产代码未再变更；最新origin/main=5a2958660f65b663555a68d445e19c3d0c8ff1c9，已是整理分支祖先。PR还包含先前BR-3/4/5/6集成与7641b7492的Issue修复；相关未提交任务报告仅复制到整理树，原树保留。
- 交付PR：[PR #220](https://github.com/FengHuoLinShan/ai-writing-assist/pull/220)。合并前最新检查点：生产实现be331ddb5已推送，工程CI等待中；PR使用模板的架构无影响说明，检查全部通过后合并，不绕过失败或未完成门禁。最终CI/合并身份以GitHub PR与origin/main为准。
- PR首轮CI：PostgreSQL critical的3项Issue209冷路径计数预期过时：P4继承宿主当前校验固定增加1次查询，8N斜率/暖缓存1查询/来源检查次数仍符合原门禁；已精确更新预期与基准说明，保留全部有效性能和来源断言。调整通过只读复审，完整本地make test-postgresql-critical为95 passed（67.51s），合成库18432；提交后等待新head的全部远端门禁。真实质量/作者验收未启动。其余检查以最新head为准。
- 浏览器CI补正：Scene/剧情线/篇章3条legacy采用夹具缺新增prepare接口，fake task/context无法走真实后端准备，导致停留预览页。仅补与legacy宿主一致的空refs/null指纹响应，并增加prepare与apply请求断言；原编辑、返回、清理、恢复/项目隔离断言保留。3条真实浏览器通过（23.3s），ESLint与只读Standards复审通过；生产代码未变。审读/引导完整套件7项本地通过，助手完整套件1项、规划/试改完整套件9项（1.4m）在专用agent_e2e合成库通过；规划World回看旧summary定位器因新增分组详情匹配两个，改为唯一场景提案标题，原改稿后历史/来源与窄屏断言保留。最终状态查PR最新head。
- 恢复下一步：先查PR #220的state、mergeCommit和最新head checks；若已合并，则本轮工程交付结束，模型暂停及未验证范围保持；若尚未合并，完成工程门禁后按已有授权合入。不得重新发起作者验收或部署。

### 2026-10-12 离线整理续接（当前，旧快照保留历史）

- 当前检查点：本轮离线实现、最终全量门禁与两轴复审已闭合，交付为本地整理分支提交。正式复审结论与验收边界见 [REVIEW-20261012.md](REVIEW-20261012.md)。原2026-10-10八项发现、整合后的话语归属/模糊回忆/容量/宿主分页/补审并发确认问题及续审发现均修复，有固定反例。
- P4-D：实际 Scene sampler、State、World/关系/World组审查、Enrichment及其审查、Discovery生成/独立审查/去重审查均登记消费输入与最终请求/schema/Prompt/runtime、模型快照；实际调用与proof共用请求builder。精确相等才复用已取回结果，不复制旧计费回执，当前来源、父回执、owner、编译与采用照常重验。7场早期改稿实际链只新增4次Scene采样，后3场复用；World两组实际流水线反例只对受影响一组新增调用，根预算只减1，无关组重新物化当前审查回执。旧证据、未知依赖、来源身份无法一对一重绑定时保守重做，不承诺所有改稿达到最少调用。
- P4-C：补扫先独立重读所选场原文，再以原场冻结身份/前序窗口编译来源并独立发现复核；旧观察为空或只记录动作，也能补出外貌原文条目。预览/确认/幂等启动、操作与根预算、手动恢复及按类别覆盖已接；补扫不生成World/Story资产，不改原Scene回执或游标。新操作清除复制来的旧计费日志，World提案SQL分页排除补扫辅助记录。
- 恢复：真实TaskLifecycleService.recover_stale回归覆盖发送前、sampled及unknown；可恢复只显示对应按钮，未知费用禁重发。启动失联保留原操作确认与ID，冲突释放确认，选类/范围变更重做预览；宽/窄屏浏览器回归及截图复核通过。
- 验证：21项P4固定反例通过；最终后端全量7736项、覆盖率86.76%通过，全量前端2968项、专用原生PostgreSQL双连接/改稿/审查并发13项、1280/390px浏览器2项、部署脚本272项通过。依赖审计无已知漏洞；backend/frontend lint、构建资产核验、模块导入棘轮65/65及524/524通过。没有运行provider、写真实库或读取封存盲验。
- 保护：最终四原树HEAD/status/index及WIP文件SHA256核对均一致。整理树仅本地提交，未推送/合main/部署；当前整理分支与提交以Git为准，不向原树任务文件回写。
- 下一步：本轮离线交付后等待用户恢复真实模型与指定隔离副本再执行P4-E、长篇费用/质量与代理作者验收；human_validated=false，原历史失败不改写。主P4任务保持active。重要物件/规则后果类别仍待真实分布裁定；world_knowledge/map_atlas/world_canon_revision消费者接线继续明确unsupported，不能宣称全阶段完成。


- 用户授权：先复审/修复 P4 现有补丁，再补齐 P4-D 精细依赖/选择性重做及 P4-C 新类别补扫，离线验证/复审/更新任务记录，最后提交整理分支。provider 暂停继续有效；不写真实数据、不看封存盲验、不推送/合 main/部署。
- 唯一后续主笔记迁到本整理树本路径：`/Users/tywww/.codex/worktrees/world-evolution-phase4-consolidation/ai-writing-assist`，分支 `codex/world-evolution-phase4-consolidated`，基线 `7641b7492e05fc3375acb995440b5e453bd03fa9`。原规划树 TASK 作为只读历史副本，收尾交付通过本分支记录恢复。
- 保护：四个原工作树（主树、P4 实现树、P4 规划树、引导集成树）HEAD/index/status/所有 WIP 文件 SHA256 已记录于 `/tmp/p4-consolidation-20261012/original-{0,1,2,3}.json`，P4 完整原补丁另存 `p4-existing.patch`。仅新树整合，未修改任何原树。
- 整合：P4 原51个修改/未跟踪文件已复制到新树，三方冲突仅 Evolution README/discovery/ledger/reading，保留最新 #208/#209/#210/#111 与 P4 来源/分组/类别/传播逻辑。未退回旧的无界历史复验或整批容量拒绝。
- 初轮复审：Spec 3项 P1（混合引号话语归属、明确歧义回忆仍绑定事件、单主题容量超限阻止当前新主题）；Standards 2项 P2（8运行截断继承宿主、补审确认缺原任务并发重验）。旧 unknown 费用门禁等5项原修复已复核。当前正修复这些问题和集成回归。
- 初始整合 Evolution 397过/16失败：主要为冲突接线的prefix函数/缓存、精确区间与#209新鲜度兼容、两组容量测试旧结构预期；不能声明整合已验收。修复需保留真实功能断言，容量测试对齐新精确覆盖结构而不是删除检查。
- 下一步：关闭初审五项并跑整合回归，然后以实际各消费者输入登记 read-set、按相同输入复用/不同或未知输入重做，补新类别补扫预览/确认/恢复/覆盖及界面。缺依赖证据始终保守扩大，作者决定不被覆盖。
- 范围解释：新类别补扫针对已引入的语言习惯/外在特征及正式类别注册表的选择范围；重要物件/规则后果仍依原计划待长篇分布裁定，本轮无真实资料授权，不擅自扩类。

### 历史快照（2026-10-11）

- 最新独立 Review：2026-10-10 用户要求审查阶段四；固定实现基线 `aafcc86be8a70c0e0830cc80f6389e2587731d4a` 到当前未提交改动，两轴复核确认 6 项 P1、2 项 P2，详见 [REVIEW-20261010.md](REVIEW-20261010.md)。
- Review 修复（2026-10-11，实施 worktree 未提交改动之上）：8 项发现全部修复并带回归——P1-1 费用未知失败改按 `settled_output_failure` 判定，未核清即 raise 停场景；P1-2 传闻线索优先于说话人线索、引用区间引号错序/嵌套判 dialogue_unattributed；P1-3 S6 新指认须含场合标记且引用折叠后不得被主题 label 包含；P1-4 发现批负载改 slim 索引+按容量分片，300 主题合成反例不再 0 批；P1-5/P2-8 状态指纹规范化派生 mention 身份、剔除 knowledge snapshot_after.id、纳入 scene_events；P1-6 采用门接受显式继承回执所在 live run 的候选（prefix 校验仍逐候选独立执行）；P2-7 `bind_scene_identities` 把审查通过的新人物身份同步进 `utterance_attribution.speaker_resolution`，语言习惯门可认首场台词。Evolution 模块回归 `384 passed, 1 deselected`；ruff、模块导入棘轮、`git diff --check`、`check_architecture_docs.py --base-ref origin/main`（07_outline 沿用 --no-change-reason 说明）均通过。改动均未提交。
- 实际完成：PR #206 已按固定 head 合入且主干 CI 全绿；P4-A 分组 World 审查、旧 `capacity_deferred` 的预览/确认补审及安全检查点恢复入口已实现。独立 Spec 复核后修正分组局部通过时的身份绑定，并补了回归。P4-B 持续发现分批、World ID 召回、来源裁剪及 S3/S6/S7 宿主门已实现；S6 精确身份短语由宿主验证新旧来源出现且只指向同主题一个旧 occurrence。72 场合成回归覆盖远距 World ID 召回、64 项上限、长当前场拆批和超限披露。P4-C 先行两类（语言习惯、外在特征）及按类别覆盖已接入。P4-D 有 Story 精确来源区间、台账引用新鲜度、字段级 Story 失效，以及整场语义相等时的后缀回执继承和读取时传播证明；新增全重算前缀语义校验，但按消费者 read-set 选择后续 Scene/Discovery 主题/World 组的完整执行仍未完成。
- 当前里程碑：2026-10-10 review 的 6 P1 + 2 P2 已全部修复，修复后完整 Evolution 模块回归 `384 passed, 1 deselected`；lint、导入棘轮、文档门、`git diff --check` 通过。较早版本的全量后端快速层 `make test` 为 `7519 passed, 2 skipped, 7 deselected, 1 warning`；全量 Vitest `2891 passed`，前端 lint/build、依赖方向棘轮与目标 Python 格式通过。独立 Standards/Spec 主要差异复核已完成；本轮 review 修复尚未另做独立复核。DeepSeek 请求、封存盲验与 Guimi 长篇流程按用户最新要求暂停。
- 下一步：review 修复可提交后请用户复核确认，再续 P4-D 的消费者 read-set/主题与 World 组重做证明，并保持未知依赖保守扩大；DeepSeek 调用恢复前不启动模型或 Evolution run。随后运行隔离长篇/封存盲验和成本验收。当前无本轮 provider 请求。
- 数据边界：`ai_novel_acceptance_guimi` 与 UX 来源库只读保留。首个副本 `ai_novel_acceptance_phase4_guimi_20261010` 从 UX 来源克隆、已迁移并用于此前读预览，但其有效 Scene 序号不连续，保留不清理。新副本 `ai_novel_acceptance_phase4_guimi_20261010_maincopy` 直接从受保护原库克隆，仅在此副本升到 `20261008_evolution_ledger`；项目 engine/epoch 为 `evolution/2`，60章正文 212,868 字、聚合 MD5 `dc7582b78243e7b422d3680616906b6e`，66个有效 Scene 连续覆盖0–65。全书预览成功，DeepSeek 模型为 `deepseek-flash`、request_limit=1000、指纹 `1f6f93adb7f236cc49cef81d384824004cfd51df09832f2b353a8a2e0854beb7`；只做本地 client 解密预检与只读预览，尚未调用模型或启动运行。共享 DB 健康；镜像/构建缓存已定向回收，容器、卷及原库均保留。
- 工作区：阶段四计划与唯一任务笔记在 `/Users/tywww/.codex/worktrees/world-evolution-phase4/ai-writing-assist`（`codex/world-evolution-phase4-plan`；只写计划/任务记录）；业务实现在 `/Users/tywww/.codex/worktrees/world-evolution-phase4-1425/ai-writing-assist`（`codex/world-evolution-phase4-impl`，基线 `aafcc86be8a70c0e0830cc80f6389e2587731d4a`，本地含未提交 Phase4 改动及本轮 review 修复）。主工作区 WIP 保持不动。
- 最后核实：2026-10-11T01:03:38+09:00。

## 目标与验收

- 目标与交付物：执行阶段四计划 P4-A 至 P4-E，使长篇 World 审查、持续发现、扩类台账和局部重做可以实际完成；在诡秘前 60 章隔离副本记录覆盖、质量、费用与改稿成本，并完成代理作者流程。
- 完成条件：遵守计划 §1 前置条件；逐包满足计划验收；独立 Standards/Spec review、适用工程/数据库/前端/浏览器/文档门禁通过；如实分开报告工程、模型质量和代理作者结果；原 Guimi 数据不写入。
- 非目标：不改写阶段三历史失败或封存集结论，不把代理作者试用称为人类验收；不推送、合并阶段四分支或部署。

## 上下文与边界

- 关键路径与来源：`docs/plans/2026-10-09-world-evolution-phase4.md`；阶段三结果见 `../T-20261008-world-evolution-phase3/TASK.md`。
- 硬约束与授权范围：用户最初明确授权 DS 调用和《诡秘之主》文本测试；最新指令为“先不执行ds调用”，因此当前暂停所有 DeepSeek/provider 请求与依赖模型的验收，离线工程工作可继续。计划使用前 60 章专用隔离副本，原 Guimi 库只读；付费账本、unknown 请求、来源保护和阶段三历史结果沿用既有规则。
- 依赖：计划 §1 要求 PR #206 合入 main 且必需检查全绿；PR 未合入前不启动阶段四实现、模型运行或隔离库写入。取得阶段四分支合并授权前不合并；部署另需授权。
- 已确认事实：PR #206 head `2a9d05f6fbae584de52b9374054cbf998ecf9c1e` 已合入，merge commit 为 `aafcc86be8a70c0e0830cc80f6389e2587731d4a`；其必需 CI 全绿。受保护库与 UX 来源经只读校验后，已在同一 PostgreSQL 服务建立专用副本 `ai_novel_acceptance_phase4_guimi_20261010`；没有写原库或来源库。
- 假设与待决问题：恢复 DS 调用须等待用户明确指示；P4-D 的消费端 read-set 尚未完整登记，不能宣称场景/主题/World 审查组已实现选择性重做。

## 里程碑与进度

- [ ] P4-A：长场景 World 候选分组审查、单组失败隔离、旧运行补审预览/确认和独立账本实现；分组通过身份绑定复核修复及回归已补，等完整回归及长篇副本比例实测。
- [ ] P4-B：发现按区间分批、World ID 优先召回及 S3/S6/S7 宿主门/回归已实现；新增冻结72场合成开发回归通过；S6 新增旧新来源唯一短语宿主门，独立复核、封存9场盲验与真实长篇门未跑。
- [ ] P4-C：语言习惯、外在特征及逐类覆盖已接；重要物件/规则后果按前60章分布决定，不先扩展。
- [ ] P4-D：Story 消费登记按完整记录选择性失效 Scene×维度、台账按精确引用检查新鲜度，已实现；语义未变后缀继承与读取时传播证明已有回归。独立 Spec 复核确认该证明仍不足以支持 boundary 状态不同时的局部继承：sampler、state review、World、enrichment 使用不同前序输入，World relations 还依赖已提交关系历史。新增校验整个重算前缀且允许来源版本变化后语义结果相同，只收紧安全复用，不实现按消费者 read-set 选择后续 Scene。Story 写作变更当前仍可能从起点 supersede 全部 Scene 维度与快照；Discovery 按主题与 World 按组的选择性重做未完成；Map Atlas / World Canon 来源接线仍 unsupported；隔离 PostgreSQL 长篇改稿/失败恢复/并发实测待做。
- [ ] P4-E：隔离长篇实测、成本对照和代理作者浏览器试用。
- 当前进展：P4-A 至 P4-D 已有实质代码，但 P4-D 的消费者 read-set、场景/主题/World 组选择性重做和来源版本接线仍未完整实现。用户最新要求暂停 DeepSeek 调用；模型盲验、隔离 Guimi 长篇运行与代理作者浏览器试用未执行。实现分支仍基于 PR #206 merge commit；所有改动未提交/推送。主工作区和规划 worktree 的非本任务 WIP 保留。

## 决策、发现与失败

- 2026-10-09：不在 PR #206 合入前启动阶段四。计划把合入及必需检查全绿写为开始条件；绕过会让阶段四落在过期基线上并违反任务顺序。
- 2026-10-10：用户后续明确“先处理 PR”；按 PR 独立集成任务修复依赖审计、镜像漏洞和评审发现，固定 head 全绿后合入 PR #206。该授权仅用于 PR #206，不扩展到阶段四分支合并或部署。
- 2026-10-10：P4-A 从整场单组审查切为 DeepSeek thinking 模型的身份/候选组，逐字引用回绑到精确草稿区间。采用仍通过原 `apply_scene_world_candidates` 门；组间只共享必要身份上下文，超限只隔离候选组，审查失败保留付费回执并允许其他已通过组继续。提案回看新增用户语言的分组结果摘要。定向反例修复了“审查组上下文跨组带入全部新身份而互相阻塞”的问题。旧版 `capacity_deferred` 不能自动调用；其补审 action 仍须先预览再授权，执行结果须有独立耐久账本，不能改写已提交的旧回执。
- 2026-10-10：P4-B 将历史召回排序固定为既有主题/证据、World 解析对象 ID、字面表面名，封顶 64 条并披露省略；本场正文以精确观察区间加邻接上下文提供，批次超限细拆，无法映射或单单元超限显式留待核实。新增的话语归属由宿主原文解析；语言习惯需唯一 World 说话人身份，外在特征不回写 World。
- 2026-10-10：P4-C 当前仅新增语言习惯与外在特征；类别常量、Prompt schema/API、筛选标签和按类别覆盖汇总共用 `LedgerCategory`。未知/失败状态不默认为检查成功。其余两类等待长篇观察分布证据。
- 2026-10-10：独立 Spec review 指出历史主题召回缺少 `method_status=current` 限制；现已增加过滤和回归，旧方法结果保留阅读但不再作为自动召回输入。
- 2026-10-10：独立 Standards review 指出补审声明 `manual_resume` 却无领域恢复入口，且未知回执须阻止恢复；现已添加原任务/attempt 的恢复端点、作者按钮与双标记 checkpoint，仅明确失败且无未知调用可继续，unknown 保持 `needs_reconciliation`。
- 2026-10-10：S6 证书旧侧原本只校验非空与可见集合；现已要求恰好一个原始event观察，增加多观察/重复观察反例，具体锚仍由两侧原文的唯一指认核定。
- 2026-10-10：P4-D 通过 Story 投影现场 `read_field_provenance` 记录来源范围；台账 claim freshness 逐条回读证据引用区间，使无关句子修改不令其直接 stale。`world_knowledge` 策略在 Story 视图读取时动态重判；Map Atlas 走独立场景上下文 facade，当前没有 Evolution 消费登记，仍保持显式 unsupported。早停传播与权威性依据仍待实现/实测，不以目前的区间新鲜度冒充完成。
- 2026-10-10：P4-D 为语义未变传播增加 Scene 状态指纹；只忽略运行/来源版本元数据并规范化可证明等价的观察 ID，仍比较语义产物、方法指纹与依赖。复用的旧后缀必须是当前精确来源、最新成功回执、连续父回执，且其前序观察在新前缀中可解析；读取方重新验证传播证明，证明被改写后 fail closed。旧继承链缺口或映射不到的较早观察会停在该处继续重算；这是有意保守边界，尚未合成多次修订的别名映射。
- 2026-10-10：独立 Spec 复核沿调用链确认，boundary 指纹相同只能证明场景结果相同，不能证明后续消费者输入相同；sampler 使用前序观察/覆盖与回执身份，state review、World、enrichment 会读取完整 manifest，World relations 还依赖已提交关系历史。当前 handoff 仅验证 boundary 指纹与观察 ID 可映射，未比较各消费者 read-set。另有新 run 身份进入 enrichment context fingerprint 的伪差异。保守复用门不扩张；P4-D 仍不满足“只重做消费了变化字段的后续场景”。
- 2026-10-10：为消除仅比较终点 boundary 的不安全复用，后缀继承现在校验整个重算前缀与基线语义等价。定向回归最初暴露重算计划未持久化起始 Scene 索引；按有效回执链从 Scene 0 起校验后，目标作用域继承、等价改稿停止传播和 changed-prefix 不继承用例均通过。此改动仍不声称实现消费者 read-set。
- 2026-10-10：用户最新指令暂停 DS/provider 调用；本轮只进行本地代码/文档/合成测试，没有执行模型请求或启动 Evolution run。待用户明确恢复后再做盲验与长篇质量/费用评估。
- 2026-10-10：只读复核发现 `ai-novel-db` 反复在恢复检查点时因数据卷 0 可用空间触发 PostgreSQL PANIC，健康状态为 unhealthy。停止对该容器的创建/写入/恢复操作；镜像与构建缓存未清理。需释放或扩容数据卷并由环境恢复数据库健康后，才能继续 P4-E。
- 2026-10-10：后续依用户授权，按 Docker 可重建性定向清理未用镜像和 BuildKit 缓存，没有 prune 容器或卷。当前 `ai-novel-db` running/healthy，DB 文件系统 59G/13G 已用/43G 可用（23%）；Docker `system df` 显示镜像 2.804GB、BuildKit 缓存 0、23 个容器与 106 个卷均保留，另有 3.411GB 未挂载卷因未确认内容归属而保留。
- 2026-10-10：UX 来源及受保护库此前均经只读 SQL 核验为相同 60 章正文；创建专用副本成功。仅对副本执行 `make migrate`，从 `20260908_unified_map` 升到 `20261008_evolution_ledger`；项目正文行数/章节数/字符数与迁移前哈希不变，`make schema-check` 通过。切换 Evolution owner 与任何模型调用仍未执行。
- 2026-10-10：默认后端全测最初暴露 3 个门禁失败：Evolution 新补审入口使模块依赖棘轮 function-level imports `524→527`，以及 handler 注册不在 `*tasks.py` 静态发现集合。已将正文区间/GroupSource/采用 facade 导入移至模块顶层，将审查 handler 注册挂入 `modules.evolution.tasks`；不修改 ratchet 基线。定向 5 项、模块导入门 `524/524` 通过，随后全量 `make test` 通过。
- 2026-10-10：只读核对 P4-D 消费端：Story 将逐字段来源引用聚合为每个 checkpoint 维度的版本与区间；World 审查组冻结候选成员和逐字来源区间；写作变更实际仍调用 `invalidate_derived_state(from_scene_index, from_chapter)`，其实现从起点 supersede 全部 Scene 维度与快照，尚未按字段/World 组选择性失效。`world_knowledge` 的 ReaderRevealPolicy 当前按读取时揭示章动态判定，但无 Evolution 来源版本登记；Map Atlas 使用独立的 `map_atlas_context` 来源哈希并经 Story 场景上下文 facade，无 Evolution 消费登记；`world_canon_revision` 只在 Scene state view 标记 unsupported，未发现 Evolution 接线。
- 2026-10-10：新增纯合成 `test_synthetic_long_book_keeps_distant_identity_batches_and_discloses_overflow`：72场历史 / 120条当前观察；World ID 跨表面别名召回，64项候选限制和省略原因；当前来源精确裁剪并拆分多批；52k 字符的单条历史上下文未塞入请求而作为 `capacity_unsupported` 明示。专测通过，不调用数据库或模型。
- 2026-10-11：REVIEW-20261010 的 6 P1 + 2 P2 全部修复（实施 worktree，未提交）。关键决定：①未知费用失败从"回执是字典"改为 `settled_output_failure` 语义（usage_complete 且失败均为已知格式类），world 审查组与旧版补审循环对未核清失败 raise `SamplePendingReconciliationError` 而非 block+continue——后者会让费用未知记录永久无人核清；②发现批负载与顶层完整索引分离，批内只带 slim 索引，超容量按 `_chunks` 剩余预算分片（`theme_index_shard`），当前观察组自身超容量记 `unsupported_current_groups`，方法指纹加 `theme_index_payload=slim_sharded_v1`；③S6 旧事件绑定增加两道宿主校验（新指认原句须含场合标记、identity_quote 经动词重叠折叠+去助词后仍不得被 label 包含），occurrence_binding 指纹 14→15；④采用门改为候选集合语义：原 run 状态合法时仍优先，否则尝试 `_inheriting_live_runs`（plan.inherited_receipts 含该回执身份的近 8 个 live run）逐一做 prefix 校验，传播证明本身仍由 prefix 校验独立承担；⑤`bind_scene_identities` 对 direct_dialogue 且 speaker_resolution 未定/new_candidate 的观察，仅在说话人表面名唯一解析为 character 身份时同步 speaker_resolution，rumor/叙述不得借绑定获得说话人；⑥状态指纹剔除派生 mention 身份与 knowledge snapshot_after.id、纳入 scene_events，使仅来源版本变化的修订可语义早停——代价是部署前已存 baseline 的指纹在新函数下不重匹配，修订 run 保守全量重算，分支未发布可接受。

## 验证证据

- 2026-10-10T22:13+09:00 独立 review：Evolution + Story P2 复核用例 390 passed、1 deselected；5个受影响Vue文件54 passed；`make lint`、两工作区 `git diff --check` 通过。默认差异文档门要求07_outline未更新说明；核对其接口未变后用既有 `--no-change-reason` 明确说明，架构文档门通过并保留warning。追加继承候选采用的内存行为检查1 failed、1 passed，证实review第6项；其余反例和限制见 [REVIEW-20261010.md](REVIEW-20261010.md)。不将原有绿色套件当作这些新反例已修复。
- `gh pr checks 206`：PR head `2a9d05f6fbae584de52b9374054cbf998ecf9c1e` 的所有检查全通过；`gh pr view 206 --json state,mergedAt,mergeCommit` 返回 MERGED，merge commit `aafcc86be8a70c0e0830cc80f6389e2587731d4a`。
- `gh run list --branch main --commit aafcc86be8a70c0e0830cc80f6389e2587731d4a` 与 commit check-runs：Production Image CI、Backend CI、Frontend CI（含双 browser shard）、repo-gates、Architecture docs、CodeQL、Dependency Graph 的检查全部 success；`origin/main` 刷新到该 SHA。2026-10-10T01:26+09:00。
- `make docs-check`：Architecture documentation checks passed，实施 worktree 基线 `aafcc86be8a70c0e0830cc80f6389e2587731d4a`。2026-10-10T01:30+09:00。
- 前端回归：全量 Vitest `2891 passed`；`npm run lint` 与 `npm run build`/production asset verifier 通过（16 local references、60 JS bundles、97 published paths）。Vite 输出非 module legacy-script 提示。
- 新增审查回归：Discovery/occurrence/ledger及补审路径 15 项通过；测试安全检查点采样后中断，恢复同一 task 且没有第二次模型调用；unknown 请求显示需核对并拒绝恢复；ReadingFlow 只在 `can_resume` 时显示继续按钮。方法过期历史主题与 S6 多旧观察证书都有宿主回归。
- 本次新回归覆盖合成候选输出超过 45,000 字符后拆为 3 组且来源 quote offset 精确、组级 blocked/invalid-JSON 失败不阻断其他独立候选、跨组新身份依赖与完成后重放不重复调用。
- 本轮新增发现回归覆盖 World ID 别名召回排序和 64 条上限、长场景精确来源摘录、宿主话语归属、语言习惯必须绑定唯一 World 身份、类别覆盖空结果/未检查区分；此前选测 Discovery/occurrence/ledger `49 passed`、ReadingFlow `9 passed`、Panorama `11 passed`、Story 精确区间消费登记 `1 passed`。改动后的完整 Evolution 模块与最终差异文档门已另见下方最新记录；浏览器端到端尚未运行。
- `docker exec ... psql ...` 仅查询 `ai_novel_acceptance_guimi` 的项目总数、owner 数和目标标题；源库无写入。项目数 9、owner 数 1，目标 ID `937c86f1-a2c3-4db5-963d-f3181095f339`。2026-10-10T01:30+09:00。
- `git status --short --branch`、`git rev-parse origin/main`：确认规划 worktree 基于 `2f32edc40`，`origin/main` 为 `b27b84ac0254d82a66c9a028e83a9c1f1f047c64`；阶段四计划与其原有 WIP 保留。
- `git diff --check`：通过。`make docs-check` 通过；差异门检查 `docs/modules/07_outline.md` 后记录其无当前接口/行为变化的理由，`check_architecture_docs.py --base-ref origin/main --no-change-reason ...` 通过。Standards 复核要求补写的 Context 语义已加入 `CONTEXT.md`，并收紧说明派生事件/checkpoint 与聚合快照不同的失效范围。
- 较早版本：`make test` → `7519 passed, 2 skipped, 7 deselected, 1 warning`（既有 Pydantic OpenAPI schema warning）；130 项 Evolution/World/Discovery/Story consumption/workflow 定向测试通过。`make module-import-gate` → `directed_edges=65/65`、`function_level_imports=524/524`；28 个触及的 Python 文件 Ruff 格式通过。整仓 `make format` 历史上报告170个未格式化既有文件；仅格式化本任务触及的文件。
- 2026-10-10T03:37+09:00：新增长篇合成用例 `backend/modules/evolution/tests/test_long_book_discovery.py` → `1 passed`；该文件 Ruff lint 通过，连同相关 Story 改动文件共 3 个 Python 文件 `ruff format --check` 通过；`make docs-check BASE_REF=origin/main` 与 `git diff --check` 通过。完整 `make test` 未为单个纯函数级合成回归重复运行；上次全量门仍为前述 7515 项通过。
- 2026-10-10T09:55+09:00：前缀传播校验修正后，5 项定向回归通过；`make test TESTS='modules/evolution/tests'` → `375 passed, 1 deselected`；`make lint`、`make docs-check`、`check_architecture_docs.py --base-ref origin/main --no-change-reason ...`、`git diff --check` 通过。未执行 provider 请求、隔离库写入或 Evolution run。
- 2026-10-11T01:03+09:00（review 修复轮）：`pytest modules/evolution/tests` → `384 passed, 1 deselected`（含各发现的新增回归：传闻归属 2 例、settled 失败表测试+TimeoutError 集成、S6 两个拒绝用例、300 主题分批合成、继承后缀采用门通过/篡改拒绝、指纹换版不变+语义变化必变、新人物说话人同步+语言习惯门接受/审查未通过不同步）。`ruff check backend/` 全过、触及文件 `ruff format` 通过、`check_module_imports.py` 棘轮 524/524 不增、`git diff --check` 通过、`check_architecture_docs.py --base-ref origin/main --no-change-reason "07_outline…"` 通过（沿用上一轮同一理由，本轮修复未触及 outline 接口）。本机 `make docs-check`/`make module-import-gate` 因系统 python3 为 3.9 无 tomllib 而以 venv python 直跑脚本，与门禁等价。未执行 provider 请求、隔离库写入或 Evolution run；改动未提交。
- 尚未运行：真实 DeepSeek/provider 调用、Guimi 隔离副本 Evolution 链、封存9场盲验、前60章类别分布、关键浏览器实测、代理作者试用与 PostgreSQL 并发门。Map Atlas 与 World Canon 仍明确 unsupported；独立 reviewers 未复核最后这次保守前缀校验修正。

## 历史交付结果（2026-10-11，当前见恢复快照）

- 已交付：P4-A/B 主体、P4-C 两类扩充、P4-D Story/ledger 精确来源登记与保守传播校验，以及本地回归和文档更新。
- 未交付：P4-B 盲验与长篇门、P4-C 余下类别决策、P4-D 字段级传播及版本接线、P4-E 隔离实测/费用账本/代理作者验收；没有提交、推送、合并阶段四分支或部署。
- 交付边界：任务记录仅在本地阶段四规划 worktree；未提交、推送、合并、部署，也未触碰原 Guimi 数据。
- 正式知识与后续任务：实施范围以 `docs/plans/2026-10-09-world-evolution-phase4.md` 为准。

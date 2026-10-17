# 第9单元未知发现请求的续接选择

用户现已直接确认「授权保留缺口继续」，选择B获准；W8已实现确认路径、最终31项专用回归及12项面板测试通过；PG与最终门禁未闭合，真实领域确认/续接未执行。用户随后要求暂停全量，自动化60随后按用户要求已删除；详见PAUSE-SUMMARY.md。不构成最终评测报告或成功结算。

## 已核验事实

隔离项目621ca424-8d03-440d-93ed-ce87a54957cd、同run reading-854195ee-75d8-4151-8864-d660132a7b2f 已完成8/63单元。第9单元同attempt7cabc0d7528940a3ac2090ab6ba68454为verified，已有18条sampled发现日志；只有scene_discovery_12为failed且没有result。其paid_call_receipt为failed_final，但usage缺失、attempts_detail为空，不能作为已核清输出失败。私有原请求8d2935ef-d370-49cc-8880-ce6cdf1e08d3为unknown/CancelledError，无response.txt；原410条记录逐项未变。只读证明在仓库外 /tmp/guimi60-eligible-window/unknown-recovery-proof.json，原稿未外发。

当前领域规则（state_review.has_unreconciled_scene_calls / pipeline._run_scene_call）拒绝恢复，无法在不重发、不造结果/结算的前提下直接执行旧resume。CLI使用ephemeral，原会话未保存；没有可验证的原答案可以补回。

## 选择A：保持原门禁

保留全部状态，不发依赖该未知的业务请求。可继续诊断和独立合成测试；原全量流程无法保证结束，没有恢复答案的证据时不能声称已找到续接点。

## 选择B：用户明确接受一个未检查缺口后，实现有界续接

只在本次隔离项目、同run、当前attempt和这条指定发现日志上，增加显式领域确认路径。原unknown日志、原请求及paid_call_receipt原样保留；不生成替代答案，不改usage_complete、不把unknown改settled，不重发该请求，也不换run/hash重做已完成阶段。

确认后可跳过该发现批次，重用18条真实已完成发现日志，运行其余尚未执行的必要步骤；Scene与角色知识仍逐序提交。原稿、边界、项目owner/snapshot、预算/lease/来源复核、 mandatory 核心生成与World/状态审查不变。

缺失批次必须在discovery coverage、Scene回执、运行状态和最终报告中永久标为“未检查，原生结果未知”。其主题事实不补写，准确度/召回和演化更新覆盖必须计入此缺口。即使随后处理完63单元，也只能称全流程结束，不能声称无缺口完成全部语义验收。

实现门禁须限制到用户确认的精确作用域与原请求hash，来源/输入/owner/版本漂移拒绝；核心Scene采样或必须审查未知仍阻断，API/其它付费供应商未知不适用。无确认时保持现有拒绝。离线测试通过并重新只读核验后，才申请/执行这一次领域确认及正常同run续接，不能直接改数据库追认旧结果。

选择B现已获得针对原问题的直接人类答复「授权保留缺口继续」；原先依据AGENTS.md第11行“改变重大产品语义……须明确授权”的等待已解除。此提案不授权对原验收项目、其他unknown、其他项目或业务模型做变更。

# 初轮 debug 六条输出裁定

日期：2026-10-04。审查者：主 Agent（非真人）。来源：原 v2 dataset、
`deepseek-debug-ledger.jsonl`、`deepseek-debug-result.json`。原报告与账本保留不覆盖。
5 条确定性/教师分歧是六条失败的子集，不是额外五条。

## 标准

1. 允许简短、有明确来源且帮助理解答案的同主体补充背景。主要答案仍须覆盖所有所问属性；
   不允许以无关事实、未知或背景替代答案。来源集合 precision 单独记录，不能当作逐主张忠实度。
2. uncertainty 可以解释真实的证据缺口，无须把证据范围说明当成新的作品事实。
   但不能否认标题/正文/claims 已给出的属性、方向或版本关系。版本关系不等于正典授权。
3. 不同属性不是自动冲突。保管机构与存放地点可同时成立；参考标签也应独立审查。

## 逐条结论

| case | Agent 结论 | 证据与原因 |
|---|---|---|
| archive-stale | 原参考冲突标签错误；原输出仍有失真 | 来源说档案司保管、迁至盐税仓，不能直接认定相同属性冲突；正文标了旧/新版，输出却说没有版本先后，并把机构当成地点。新候选集修正 source_conflict=false、stratum=multi_source；不改旧报告。 |
| ferry-toll-conflict | fail | 并列三/五铜币正确；标题明确“票价修订”，输出仍否认有版本关系。未给日期/正典可以说明，不能连同修订关系一并否认。 |
| courier-route-combo | fail | 证据明确云脊驿→山下镇两天。称单程/往返不明会削弱已给方向与到达用时；行走/休息安排未给是可保留的另一种限定。 |
| guard-captain-conflict | fail | 主张和来源均有旧/新版，uncertainty 称“均未标注来源版本”自相矛盾。保留两名队长、不替作者选版是正确部分。 |
| ember-fair-cause | 语义 pass；来源集合诊断仍可 fail | 举办原因正确；雨季日期有明确来源，帮助理解同一条件，可以作为补充。rain-calendar 未列入核心答案 relevant_source_keys，因此严格集合 precision 不满不等于主张失真。 |
| distractor-similar-bridges | pass | 南桥八十步与石板均来自南桥来源，无串用北桥/西桥。简短的同主体补充不是幻觉或属性替代。 |

这些结论不能转换为 HumanReview 或 human_validated=true。作者是否接受标准、参考与实际回答
须另外记录本人反馈。生成层的 free-form answer/uncertainty 在生产 `_build_response()` 中被
固定文案替换，所以这四条原始输出问题不能直接推断为浏览器已展示的生产缺陷。

## 保留集污染与修复

初轮 teacher-selftest 22 条使用了原 v2 holdout 六个来源族：copper-hill、kiln-street、
harvest-festival、river-mouth-treaty、mist-river、windmill-hill。它们虽未经 DeepSeek 生成，
已用于教师开发验收，不能作为未接触保留集。v2 保留原样用于历史复现。

后续使用 v3：上述六条降为 debug；新增六个不复用这些来源族的保留场景，维持 holdout=12。
教师自测只能选择 debug，缺少防护的旧自测作为历史证据；新自测明确断言 split。
先重跑自测与 debug、记录冻结 hash，再运行保留集一次。保留集结果无论成功或失败都不用于
本次 Prompt、rubric 或参考调参；失败如实交付，不通过重跑刷新结果。

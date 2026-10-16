# 编辑审读盲评任务

## 角色与边界

你是单人盲评者。只读取本文件和以下目录中的 JSON 文件：

`/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016-attempt-4/blind/`

不要读取任务笔记、仓库 diff、评测数据集、`backend/modules/assistant/editorial.py` 或其他实现/系统提示词，也不要查看盲号映射或猜测分组。只评分，不改仓库，不调用其他模型。每个盲评 JSON 都包含 brief、作品正文、评测重点、预期结果和一份审读报告；总计 58 份，逐份独立评分。

## 评分方法

每个评分项取 0、1 或 2 分。每项都写简短理由，并引用该份输出中的原文。没有 finding 时，可引用输出里的空 `findings` 数组或 summary 原文。不要合成总分；后续会按各项报告分布与均值。

| 项目（JSON key） | 0 分 | 1 分 | 2 分 |
|---|---|---|---|
| 来源误读 `source_misread` | 严重误读 | 部分准确 | 准确且范围匹配 |
| 强意见误报 `strong_false_positive` | 多项无据强报 | 有少量误报 | 无明显无据强报 |
| 重大问题漏报 `major_issue_miss` | 漏掉主要问题 | 发现部分影响 | 抓住主要问题 |
| 方向可执行性 `direction_actionability` | 不可执行或扩大改写 | 方向可用但不够聚焦 | 最小且可执行 |
| 作者声音尊重 `author_voice_respect` | 泛化作者表达 | 保留意思但削平声音 | 保留有意声音特征 |
| 改后判断 `post_revision_judgment` | 错称已解决 | 判断部分准确 | 准确保留“仍在/可能改善/无法判断” |
| 有意形式误判 `intentional_form_misjudgment` | 把开放、留白、不可靠叙述或无钩子写成确定错误 | 提及意图仍推必改 | 结合线索与范围描述效果，留作者决定 |
| 口味伪装错误 `taste_as_error` | 把审读者喜好报成缺陷 | 标为偏好但仍高优先或返修 | 默认不报；当前没有单独的风格偏好入口 |
| 理解与不喜欢区分 `understanding_vs_dislike` | 混成一个负面读者结论 | 有区分但证据不清 | 区分可理解性、歧义与审美反应 |
| 回看线索与替代解释 `lookback_and_alternatives` | 不找反证或把未读当不存在 | 找到一类但未核来源/覆盖 | 引用支持和反证，标清未审范围 |
| 最小修订与层级 `minimal_revision_and_level` | 大改、选区修结构问题或扩大范围 | 方向可用但路径不清 | 给最小方向；需取舍时才列备选，结构决策交作者 |
| 作者声音与过度修改 `voice_overediting` | 删除非目标语气、句法或信息 | 留住意思但明显泛化 | 只改 finding 所需范围并保留声音 |
| 意见聚合与处理负担 `issue_aggregation_and_burden` | 同根因拆成多卡或重复症状 | 部分聚合但仍需重复处置 | 每个根因一条主意见，多处依据折叠 |
| 伦理呈现边界 `ethics_presentation_boundary` | 未请求即指控、泛化或宣称 clearance | 有具体依据但口吻仍裁断 | 当前产品不提供该入口；不生成未经请求的伦理观察 |
| 外部事实克制 `external_fact_restraint` | 无资料也断言史实 | 表示疑问但仍推理作答 | 标为待外部查证，不纳入小说内严重度 |

## 意见命中、误报与漏报

按 JSON 的 `expected_result` 判断：

- `report`：对应作品目标指出预期失配的意见标为 `hit`；其他意见标为 `false_positive`。至少一条命中时 `case_outcome` 为 `hit`，一条也没有时为 `miss`，并在 `missed_expected_issues` 写明漏掉的重点（可依据该例的评测重点）。
- `no_report`：有意见时每条都标为 `false_positive`，`case_outcome` 为 `false_positive`；没有意见时 `case_outcome` 为 `no_report`。
- `unchecked`：只有把相关判断正确留作外部查证、未核来源或待作者补充范围时才算 `hit`；把未核事实当成已知、或据此报确定缺陷的意见标 `false_positive`。有命中时 `case_outcome` 为 `unchecked`；没有命中时为 `unchecked_missed`，并写明应保留待核对的重点。

每条 finding 都必须有且仅有一条 assessment。`miss` 和 `unchecked_missed` 是 case 级漏报结果，不是某条现存意见的分类。finding 索引从 0 开始，必须覆盖 `report.findings` 的每一项。

## 评分文件

写入：

`/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016-attempt-4/reviewer-return/sonnet-review.completed.jsonl`

每个盲评 JSON 对应一条 JSONL 记录；`case_id` 使用输入文件的 `blind_id`，`expected_result` 原样照录。固定写入 `reviewer_version`：`AI 盲评（Claude Sonnet 5.5，单评阅者）`。文件必须包含全部 15 个评分 key；每项有 0–2 的 `score`、理由 `reason` 和输出原文 `quote`。所有文本字段不得为空。不要追加其他汇总或解释行。

每条记录结构如下；示例中的值都应按实际输出替换：

```json
{
  "case_id": "<blind_id>",
  "reviewer_version": "AI 盲评（Claude Sonnet 5.5，单评阅者）",
  "expected_result": "report",
  "case_outcome": "hit",
  "scores": {
    "source_misread": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "strong_false_positive": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "major_issue_miss": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "direction_actionability": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "author_voice_respect": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "post_revision_judgment": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "intentional_form_misjudgment": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "taste_as_error": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "understanding_vs_dislike": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "lookback_and_alternatives": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "minimal_revision_and_level": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "voice_overediting": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "issue_aggregation_and_burden": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "ethics_presentation_boundary": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"},
    "external_fact_restraint": {"score": 0, "reason": "填写理由", "quote": "引用输出原文"}
  },
  "finding_count": 1,
  "finding_assessments": [
    {"finding_index": 0, "classification": "hit", "reason": "填写理由", "quote": "引用该意见原文"}
  ],
  "missed_expected_issues": []
}
```

实际文件须是 JSONL：每个完整 JSON 对象占单独一行。`finding_count` 等于 `report.findings` 长度；空 finding 时写 `0` 和 `[]`。允许的 `case_outcome` 只有 `hit`、`false_positive`、`miss`、`no_report`、`unchecked`、`unchecked_missed`；允许的 finding `classification` 只有 `hit`、`false_positive`。

## 局限与后续

单方向意见卡等输出形态可能暴露分组；不要据此推断。单评阅者的模型评分仅作探索性证据，不得登记为独立人工精确率。

完成后把评分 JSONL 交回作者。开发 Agent 将校验导入格式，再解盲，按正例和对照例分别比较两组，并与零意见平凡基线对照。本任务不要求你解释组别或给出总排名。

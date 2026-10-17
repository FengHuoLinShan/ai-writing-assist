# 编辑审读盲评任务

本文件供一个新的 Claude Sonnet 5.5 或 Kimi Code k3 会话在隔离的盲评工作区根目录中使用。下文路径均相对于该目录。

## 任务与边界

你是单人盲评者，为 70 份 AI 编辑审读输出逐份评分。只评分，不改写输出，不给总排名。作者可以在开场消息中指定评阅者标签：`AI 盲评（Claude Sonnet 5.5，单评阅者）` 或 `AI 盲评（Kimi Code k3，单评阅者）`。若作者没有指定，默认使用 Sonnet 标签；整份评分文件只用一个标签。

工作区包含：

- `HANDOFF-blind-review.md`：本文件；
- `blind/`：70 份待评 JSON；每份都包含该例的全部章节，供你核对跨章依据；
- `reviewer-return/`：评分写入目录；
- `check_review.py`：评分文件的格式自检脚本。

只读本文件和 `blind/` 下的 JSON，只写 `reviewer-return/` 下的评分文件。不要读取或搜索工作区之外的任何文件和目录，包括上级目录；不要查找生成这些输出的提示词、代码或分组信息；不调用其他模型或子代理，不联网。

每份 JSON 包含：

- `blind_id`、`expected_result`；
- `scope`、`brief`（作者约定），以及可能为空的 `case_context`、`scope_note`；
- `chapters`（作品正文）、`evaluation_focus`（评测重点）；
- `report`：被评的审读输出，含 `summary`、`findings`、`checked_chapters`、`missing`、`coverage_complete`。

同一篇正文会出现两次，各配一份不同的审读输出。逐份按量表独立评分，不在两份之间比较，也不推断它们来自哪种设置。方向条数等形态差异只按量表中的对应条目判断，例如“最小修订与层级”。

## 工作流程

1. 列出 `blind/` 下的文件并按文件名排序。有的文件名以 `-` 开头，用 shell 读取时写成 `./blind/<文件名>`。
2. 若评分文件已存在，先读出其中的 `case_id`，跳过已评文件，从下一份继续。
3. 每份依次读 brief、全部章节正文、`evaluation_focus`、`expected_result`，再读 `report`；逐条判断 finding，读完该份输出后逐项独立决定 15 项分数和理由，然后立即把这一份的记录追加为评分文件的一行。不要攒到最后一起写。
4. 不要使用脚本给没有逐项判断的条目填默认分或默认理由。脚本仅用于检查格式，不用于评分或补齐内容。全部评完后运行 `python3 check_review.py --reviewer-version "<所选标签>" [文件名]`；若有报错，只改出错的行，再次运行，直到输出以 `OK` 开头。
5. 结束时只回复已评份数和 `check_review.py` 的最终输出，不报告对组别的猜测。

默认评分文件为 `reviewer-return/sonnet-review.completed.jsonl`（Sonnet 标签）或 `reviewer-return/kimi-review.completed.jsonl`（Kimi 标签）。若作者在开场消息中指定了其他文件名，写入 `reviewer-return/<该文件名>`，自检时将其作为 checker 的位置参数传入。

作者可能对同一盲评包复评一次。复评时从头逐份重读全部 70 个 blind 文件，使用不同的输出文件名，不读取或对照第一轮评分；两轮结果由开发 Agent 在揭盲时按固定口径比较。

## 意见命中、误报与漏报

按 JSON 的 `expected_result` 判断：

- `report`：只有点明 `evaluation_focus` 所指目标失配本身的意见才标 `hit`。矛盾类须指出冲突两端；承诺类须指出承诺与未兑现。同一问题区域、有文本依据但未点明目标失配的意见标 `related`；无据、误读或与正文相悖的意见标 `false_positive`。只有 `hit` 决定 case 结果：至少一条 `hit` 时 `case_outcome` 为 `hit`；没有 `hit` 时为 `miss`，并在 `missed_expected_issues` 写明漏掉的重点。
- 例如，评测重点是“前后两个时间状态互斥”，某意见有据地指出时间线读起来跳跃，却没有说清两个状态互不相容，这条意见属于 `related`，不算命中，也不算误报。
- `no_report`：有意见时每条都标 `false_positive`，`case_outcome` 为 `false_positive`；没有意见时 `case_outcome` 为 `no_report`。
- `unchecked`：明确点名该外部事实待查证、且不据此定严重度的意见标 `hit`。主判断是其他问题、只在自己的 `unchecked` 字段顺带提及待核事实的意见标 `related`。把未核事实当成已知、或据此报确定缺陷的意见标 `false_positive`。只有 `hit` 决定 case 结果：有命中时 `case_outcome` 为 `unchecked`；没有命中时为 `unchecked_missed`，并写明应保留待核对的重点。

每条 finding 都必须有且仅有一条 assessment，`finding_index` 从 0 开始，覆盖 `report.findings` 的每一项。`miss` 和 `unchecked_missed` 是 case 级漏报结果，不是某条意见的分类。finding 里的 `unchecked` 字段是审读输出自己写的未核对说明，不等同于 `expected_result` 的 `unchecked`。

## 15 项评分

每项取 0、1、2 分或 `null`，写简短理由 `reason`，并在 `quote` 中逐字引用该份输出的原文。引文可取自 finding、`summary` 或 `missing`；空报告可引用 `summary`。不要合成总分，后续按各项分布汇总。

`null` 表示该项不适用，只允许以下两种情况：

- **依赖意见的五项**：`direction_actionability`、`author_voice_respect`、`minimal_revision_and_level`、`voice_overediting`、`issue_aggregation_and_burden`。`findings` 为空时这五项必须全部填 `null`；有意见时必须全部打分。
- **`post_revision_judgment`**：本批输出都不是对修订稿的复核，一律填 `null`。

填 `null` 时 `reason` 写“无意见，不适用”或“本批不含修订稿复核”，`quote` 写空字符串。其余九项在空报告上照常评分，例如应报样本返回空报告时 `major_issue_miss` 记 0，不应报样本返回空报告时 `strong_false_positive` 记 2。

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

表中“入口”指产品功能：审读输出不应主动给出风格偏好或伦理方面的意见，出现时按对应行扣分。

## 评分文件格式

每份盲评 JSON 对应一行 JSON，`case_id` 填输入文件的 `blind_id`，`expected_result` 原样照录，`reviewer_version` 填作者指定的固定标签；未指定时填 `AI 盲评（Claude Sonnet 5.5，单评阅者）`。有效标签只有 `AI 盲评（Claude Sonnet 5.5，单评阅者）` 和 `AI 盲评（Kimi Code k3，单评阅者）`。`finding_count` 等于 `report.findings` 的长度。只允许下列字段，不要追加汇总或解释行。

允许的 `case_outcome`：`hit`、`false_positive`、`miss`、`no_report`、`unchecked`、`unchecked_missed`。允许的 finding `classification`：`hit`、`related`、`false_positive`。`report` 和 `unchecked` 的 case 结果只看是否有 `hit`；`no_report` 的 case 结果只看输出意见数，有意见就必须全标为 `false_positive`。除 `null` 项的 `quote` 外，所有文本字段不得为空。

有意见的记录示例（值均按实际替换；实际文件每条占一行）：

```json
{
  "case_id": "<blind_id>",
  "reviewer_version": "AI 盲评（Claude Sonnet 5.5，单评阅者）",
  "expected_result": "report",
  "case_outcome": "hit",
  "scores": {
    "source_misread": {"score": 2, "reason": "填写理由", "quote": "引用输出原文"},
    "strong_false_positive": {"score": 2, "reason": "填写理由", "quote": "引用输出原文"},
    "major_issue_miss": {"score": 2, "reason": "填写理由", "quote": "引用输出原文"},
    "direction_actionability": {"score": 1, "reason": "填写理由", "quote": "引用输出原文"},
    "author_voice_respect": {"score": 2, "reason": "填写理由", "quote": "引用输出原文"},
    "post_revision_judgment": {"score": null, "reason": "本批不含修订稿复核", "quote": ""},
    "intentional_form_misjudgment": {"score": 2, "reason": "填写理由", "quote": "引用输出原文"},
    "taste_as_error": {"score": 2, "reason": "填写理由", "quote": "引用输出原文"},
    "understanding_vs_dislike": {"score": 2, "reason": "填写理由", "quote": "引用输出原文"},
    "lookback_and_alternatives": {"score": 1, "reason": "填写理由", "quote": "引用输出原文"},
    "minimal_revision_and_level": {"score": 2, "reason": "填写理由", "quote": "引用输出原文"},
    "voice_overediting": {"score": 2, "reason": "填写理由", "quote": "引用输出原文"},
    "issue_aggregation_and_burden": {"score": 2, "reason": "填写理由", "quote": "引用输出原文"},
    "ethics_presentation_boundary": {"score": 2, "reason": "填写理由", "quote": "引用输出原文"},
    "external_fact_restraint": {"score": 2, "reason": "填写理由", "quote": "引用输出原文"}
  },
  "finding_count": 1,
  "finding_assessments": [
    {"finding_index": 0, "classification": "hit", "reason": "填写理由", "quote": "引用该意见原文"}
  ],
  "missed_expected_issues": []
}
```

空报告的记录与上例相同，只是 `finding_count` 为 `0`、`finding_assessments` 为 `[]`，依赖意见的五项和 `post_revision_judgment` 填 `null`，例如：

```json
{"direction_actionability": {"score": null, "reason": "无意见，不适用", "quote": ""}}
```

## 局限与后续

多名评阅者或多轮评分必须保留为独立文件和独立标签，不得合并后再计算采纳门槛。揭盲后只在 `report` 与 `unchecked` 样本上比较评阅者/轮次的一致性；`no_report` 的结果由输出意见数决定，不计算主观评阅一致性。单评阅者的模型评分只作探索性证据，不得登记为独立人工精确率。

完成后告诉作者评分文件已写好。开发 Agent 会按评阅者分别校验导入格式、解盲并报告结果；所有已完成评阅者均满足固定采纳门槛时才采纳，否则报告“评阅者间不一致”，逐例列出差异并交作者裁定。本任务不要求你解释组别或给出总排名。

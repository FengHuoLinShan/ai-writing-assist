# DS Flash context / effort 调整依据与交付

日期：2026-09-21。实现工作区 `codex/dsflash-balance`，基线 `6e901693a`。
未调用付费模型；以下为重读现有记录，不是新版本的实测收益。

## 已有记录重算

来源：主工作区 `tools/deepseek_scene_probe/runs/`；不同批次 Prompt、输入和版本不同。

| 批次 | 请求数 | length截断 | error_kind非空 | 单请求中位秒数 |
|---|---:|---:|---:|---:|
| ds60-phase1b-full-mt2048 | 57 | 1 | 1 | 12.8 |
| ds60-phase1b-repair-S0008-mt4096 | 1 | 0 | 0 | 10.6 |
| ds60-phase2-world-matrix | 60 | 53 | 53 | 99.5 |
| ds60-phase2-world-charbudget-hi-mt | 16 | 1 | 1 | 150.5 |
| ds60-phase3-structure-matrix | 8 | 5 | 5 | 73.3 |

Phase2首批输出上限8,192/12,288/16,384；后批24,576/32,768。不能据此推断同源质量优劣，
但足以否定“把所有输出上限压到8K就能廉价完成”的策略。Phase1b从2K到4K只是旧简化Prompt样本，
当前完整证据schema不同，未将普通导入32K盲目降为4K。

2026-09-19生成质量报告中的资源、算术和装备问题，曾被模型审查放过；完整资料与审查一致性
仍是硬要求。协作探索记录中单轮审查10–50秒，多步调查96–193秒，且有失败；它不是high/max
对照，不能用来宣称多步或max更优。

## 实际策略

| 路径 | 普通 | 质量优先 |
|---|---|---|
| RP新快照 | high；normal128K、compact192K、summary256K | 账户高级默认extra.reasoning_effort=max；保留normal256K、compact360K、summary256K |
| RP输出/硬边界 | 65,536输出、900秒、400K硬输入 | 相同安全边界；不以价格压缩已知可用输出空间 |
| World生成中心 | 保留普通生成与必需知识审查 | pro全链max，至少65,536输出；保留反例复核、知识审查和1800秒领域护栏 |
| 深度导入 | high及各阶段冻结预算，通常32,768 | high_quality全链max、至少65,536输出、provider至少900秒；Phase3生成与独立证据复核统一 |
| 窄查证/定向补全 | 既有low保留 | 有明确高质量客户端作用域时，质量策略覆盖该客户端的局部低档 |

不更换账户provider/model；高质量只提高执行投入。更大的显式输出上限不被下调；
超时、请求次数、幂等、项目隔离、Context确认、截止点和来源校验不取消。
普通档提前触发历史整理，但单次摘要容量仍保留256K，避免原先可整理的长节点变成预算错误。
原始正文、固定资料和近期完整节拍不因普通档截断；RP继续使用已有whole-node摘要流程。
既有RP冻结max快照按原值恢复；默认调优只影响新快照。

## 依据与限制

官方参数页面：[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)、
[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)，2026-09-21核对
low/high/max合法语义。普通档较早整理历史及从max改high是待验证的平衡策略；没有同一场景、
同一版本和冻结资料的速度/费用/作者质量A/B，不能报告百分比收益或宣称最优。
高质量是尽可能追求质量的资源策略，不等于自动审查已证明内容可用。

## 验证与交付状态

完整后端回归5882 passed、13 skipped（1个既有asyncio标记警告）；最终摘要容量调整后相关111项复跑通过。
lint、diff-aware docs-check和diff空白检查通过。未提交、推送、合并或部署，主工作区原有WIP未改。

原始 summary SHA-256（原目录只读、未复制小说正文）：

- `ds60-phase1b-full-mt2048/summary.jsonl`: `c30b968fd8cebc2d88c82e672bb65dd60448540af83bd5407fa5f9fc2e0a66c8`
- `ds60-phase1b-repair-S0008-mt4096/summary.jsonl`: `5521f61860941909ba762dcbcf201db4baa6cb76223b6039ae1a040d54cc18a8`
- `ds60-phase2-world-matrix/summary.jsonl`: `424bef5d03c60f8afb37f6ecd1704a9807c29675c4ba6084be5aaefeaee15e87`
- `ds60-phase2-world-charbudget-hi-mt/summary.jsonl`: `b58e6b1e1af94050d8c52ed8b6271eb0119d7a4981fdb0926026a619dbe7a0e1`
- `ds60-phase3-structure-matrix/summary.jsonl`: `1c454855c113999b0d8a5afc9ece21326bb4b74cfd64f0619968b690cbc4de1b`

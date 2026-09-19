---
id: T-20260917-ai-generation-quality
title: AI 生成可用性修复与真实质量验证
status: active
created: 2026-09-17T22:00:00+08:00
updated: 2026-09-19T19:10:21+08:00
---

# AI 生成可用性修复与真实质量验证

## 恢复快照

- 三项原始缺陷及本轮证实的跨域输入/返修/权限问题已修复。全部改动仅在本地worktree，未提交、合并、推送或部署。
- 完整CI：后端5836/13 skipped、覆盖率86.16%、前端2503、部署270；后续相关回归2109、World109、Outline/Prompt38通过。Ruff、24 Prompt contracts、secret hygiene、带地图影响说明的文档检查通过。
- 真实模型覆盖World11场景、七类文本、RP、总纲、助手、地图文本，以及数量/知识正反例。最新World资源、三新领域、RP、助手/地图样本通过关键约束复核；所有失败保留。
- **未完成总体质量目标**：最终总纲虽自动PASS，余额与结尾表达仍不一致。现有同模型审查不足以证明所有生成稳定可用；不能关闭此任务或把测试绿灯当质量保证。
- 下一步：基于 artifacts/REPORT.md 的最后总纲缺陷，设计并验证可靠的独立数量核算或受控模型对照；先核费用边界，避免无新假设地重复同一模型生成。可先做离线方案与新样本，图片仍未测试。
- 已完成464次provider调用，按实际token与闲时价估算¥12.68005564，在¥15上限内；连接验证微量调用另计。全部进程结束，无自动重跑。
- 原始证据已归档 `backend/.test-artifacts/ai-generation-quality-20260919/`，报告、可复现脚本、合成fixture、费用表与最终代码hash在 artifacts/。
- 工作区 `/Users/tywww/.codex/worktrees/ai-generation-quality/ai-writing-assist`，`codex/ai-generation-quality`，基线d66eb40cb；主目录宣传录屏等WIP未动，无子代理。

## 目标与边界

修复阶段修改保留回执、终审混入旧候选、精细指令泄入fast三项问题，并改善主要AI生成类型的实际可用性。
复用既有项目账户快照、任务、生成、审查与采用门禁；不新增运行时Agent或外部平台。
仅合成资料和独立内存SQLite；真实小说、保护Guimi库、主目录WIP及.env未修改。
用户要求按DeepSeek低谷价估算，本轮已声明累计估算上限15元；最终约12.68元，连接校验微量调用另计。

## 已实施

1. depth进入内容hash与前端失效；保存API重验有效阶段，旧未绑定depth回执仅能未复核保存，blocked原样拒绝。
2. 终审重建当前candidate/proposal；精细任务卡仅design/pro；依赖字段使用公开alias。
3. World/Story/RP审查同源完整输入，取消二次24K裁剪，返修带原稿；系统保存通知不充当作者要求。
4. 首次结构化请求携带schema；World保留省略字段与前案条目、统一新ID/known_by、固定分类名称。
5. 共创聊天一次知识返修；design反例修正后至多一次知识修正并复审，终审不再循环；v3恢复点避免重复。新任务chat20/24、design24/78，旧额度不扩充。
6. 创作新增与有据回答分开，共创使用proposal、world.ask仍answer；硬资源限制覆盖私人库存，影响方案的算术矛盾不得以候选降级。RP v8保留明确持有物；明确交付物/篇幅优先于默认聊天结构。
7. 总纲明确交付具体结局主方案，原意图/证据审查增加内部数量一致性；原一次语义返修上限不变。
8. CI新发现依赖漏洞，仅更新anyio4.14.1→4.14.2、soupsieve2.8.4→2.9；不改忽略项。审计无已知漏洞，langchain-community archived提示保留。

## 验证与决策证据

- [报告](artifacts/REPORT.md)记录每轮模型结果、主Agent读稿失败、误判和已知局限；不是人类作者盲评。
- [脚本说明](artifacts/README.md)、合成fixture、精确算术负例、费用表与最终代码hash均自包含保存。
- 原始合成请求/输出、失败阶段及日志：`backend/.test-artifacts/ai-generation-quality-20260919/`（Git忽略，无明文Key）。
- 完整CI日志`logs/ai-generation-quality-ci-final-fixed.log`；后续2109项回归`logs/ai-generation-quality-final-regression-v7.log`；总纲38项`logs/ai-generation-quality-outline-final.log`。
- diff-aware docs检查提示地图影响项，已逐项说明原完整schema、51次额度、来源/图片/CAS不变，使用检查器正式no-change-reason通过。无改规则过检。
- 真实失败包括：丢字段、丢返修新实体、知识边界/资源限制漏检、任务卡误读、固定分类名失效、错误算术与合法正例资料不一致。代码、提示或harness分别按根因修复，未隐瞒重跑历史。

## 剩余问题与停止点

最终总纲自动PASS但资金表与结尾余额表述仍不一致；详见报告最后一节和outline-v3原始输出。
精确旧错误现在会被拒绝，但不能据此推断新形式的错误不会漏检；当前没有可靠的自动全面质量保证。
不继续以重复同一模型、增加提示词或删断言来获取表面全绿。下一步需验证独立数量核算或受控模型对照。
图片、其他provider、长篇多轮和浏览器/生产库未验收。任务保持active；本轮进程均结束，未安排后台自动执行。
代码未进入主目录或远端；未提交、合并、推送、部署。

# G6b Ask World 真实模型首轮验收

2026-10-15 已完成独立环境中的模型重校准。教师自测 30/30 匹配；Luna/max 的 34 条 debug
由 Sol/xhigh 完整独立评分，33 条语义通过、1 条失败。该结果是校准基线，业务质量并非全通过。

## 实际配置与证据

被测端使用 owner 正常验证的 Codex gpt-6-luna/max，Project facade 和恢复 snapshot 均核验通过；
教师与评分为独立 Codex gpt-6.1-sol/xhigh，原生诊断确认实际 model/effort。
CLI 固定本机 0.160.0，解决旧 0.144.6 与较新模型目录的不兼容，未改全局模型目录。
专用 PostgreSQL agent_e2e_g6b_calibration 与合成作者项目不含真实稿件，未写共享库或旧账本。

完整原始请求、native stdout/stderr、schema、结构化输出与阶段记录在
`/Users/tywww/.codex/private/g6b-recalibration-20261015/live`。仓库中的
[脱敏账本](artifacts/live-ledger.json) 保存逐调用哈希、原生状态、用量回执（缺失不记零）、
固定材料与源码版本。原运行源码归档与冻结哈希一致；校准后取消回收/环境白名单修复及任务脚本格式调整另记，未重发相同校准请求。

## 覆盖与结果

- 30 个 seeded 教师自测均匹配：14 正例、14 缺陷输出、2 错误参考；全部来自已公开 debug 来源，歧义 0。
- v3 的 34 条 debug 全部生成、逐项有效审查，33 pass / 1 fail，语义通过率 97.06%。
  参考标签接受率 100%，没有用教师判断覆盖确定性失败。六种 strata 均覆盖。
- 39 笔真实 native 调用均正常退出：34 生成、2 教师批次、3 正常连接验证。unknown 0，无自动重发。
  收尾第一次重验在 native 成功后因脚本未注册 ORM 元数据导致数据库事务失败；该失败和原生回执保留，
  修正注册后新一次正常连接验证和事务提交成功。没有把事务失败藏成已保存。
- 354 项相关离线回归通过、2 项可选实验跳过；Ask World API 9 项通过；23-case 离线门禁 ready=true。
  Ruff、文档与差异检查通过。新增取消回收回归先红后绿，子进程不再因教师协程取消而遗留。

## 唯一质量缺口

`ask-probe-treaty-date-conflict`：来源给出两个冲突的历法日期，模型擅自要求具体公历日期，
将可并列说明的来源变成拒答，未产出结构化 claims/citations。人工源文核对与 Sol 教师均支持保留原参考，
失败项为 answerability_mismatch、conflict_sources_not_covered、answerability_unjustified。

本轮保留原输出和失败，不改标签、Prompt 或计分规则追认通过，也不重跑取代这笔结果。
后续整改应在保留该基线的前提下单独复验。

## 不能据此宣称

`human_validated=false`、`blocking=false`。这是已暴露 debug 合成材料的生成层校准，
没有覆盖检索、Evidence 确认、知识审查、引用回开、建议保存或作者满意度。
12 条旧 holdout 未调用，新 family/holdout 属 G6c；其他 reviewer/adjudicator/scene-gold
未因这条路径校准而整体放行。与历史模型分数不能直接比较。

交付仅本地未提交；没有推送、合并或部署。独立校准库和私有回执保留供复核。

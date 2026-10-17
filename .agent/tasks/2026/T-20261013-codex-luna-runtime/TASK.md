---
id: T-20261013-codex-luna-runtime
title: Codex 普通业务 LLM 深度适配与 Luna max 实测
status: completed
created: 2026-10-13T05:00:00+08:00
updated: 2026-10-13T06:51:26+08:00
---

# Codex Luna 业务调用适配

## 恢复快照

- 本机适配与本轮大量实测已交付；原完整《诡秘》60章比较仍未完成，不能由本任务关闭冒充总体目标完成。
- 工作区 /Users/tywww/.codex/worktrees/codex-luna-runtime/ai-writing-assist，分支codex/codex-luna-runtime，基线974f0f5080d43472bc599d1d74782913c725057b；全部本地未提交/推送/合并/部署。根工作树WIP保留。
- 报告docs/acceptance/2026-10-13-codex-luna-runtime.md；指标索引2026-10-13-guimi60-metric-inventory.json含22契约/63表/604字段/20类对象，不等于全部字段已完成语义验收。
- 专用库codex_luna_runtime_test（PG17，18442）；API18444 session41412，Vite18445 session35855。原ai_novel_acceptance_guimi未启动/迁移/写入。
- 预览http://127.0.0.1:18445/#settings，浏览器tab2已markDeliverable，最新真实验证成功；截图/tmp/codex-luna-connection-final.jpg。
- 原完整比较的下一步只读核对T-20261012-guimi60-codex-comparison；禁止盲目重发旧unknown请求。新改动后按影响选择回归，不自动重跑已结算/未知实测。

## 目标与验收

- [x] 本机单用户Codex账户连接默认gpt-6-luna/max、无假Key；公开/foreign owner不可用；显式API连接保留。
- [x] 经既有账户/project facade/LLMClient/信封/恢复入口；CLI本机工具关闭、私有输入输出、有界超时/输出/取消，未知结果不自动重发。
- [x] 结构化封闭schema原生约束，开放字典JSON包封后Pydantic校验；业务工具提案仅由现有服务端有界runtime执行；已执行tool返回继续而非重提。
- [x] 大量真实Luna/max测试、失败分母与限制报告；不另统计费用或用量，保留必要原生恢复回执。
- [x] 受影响回归、权威文档、真实连接UI与可查看交付物。

## 实现与关键决策

- ADR-0033受限普通文本路径，旧ADR-0029 full-tool文字快照仍拒绝；local_agent图片路径不变。
- 0.160.0支持所需开关；默认PATH另一0.144.6失败关闭。专用.env忽略/0600，CODEX_CLI_COMMAND指向已验证NVM绝对路径，无secret。
- codex-text-v2固定native model_instructions_file替换编码persona、AGENTS预算0、skip_host_skill_discovery；禁shell/图片/MCP/插件/hooks/apps/skills/浏览器/电脑/code_mode_host/无限重连。事件仅正文/推理及两个精确匹配的已知启动提示；未知/tool失败关闭。
- 包装版本进入snapshot extra_hash，旧版本/连接失效/主机指纹变化不能静默恢复；fingerprint不证明实际登录账号身份，更换登录需重新验证。
- CLI无API等价温度/硬token上限；max_tokens仅目标，流式完整后延迟交付。client尊重output_token_limit_enforced=false，不把超过目标误作硬截断。unknown-short容量仍保守，针测不证明最大语义容量。
- 每进程Codex两并发闸门跨项目共享，不是跨进程/账户级或供应商容量规格，不降max强度。
- 完整原生结果而包封格式失败保留原生usage，信封/meter/Agent结为已知失败；无完整usage仍unknown，不补零。Agent保留原有12回合上限。
- 未修旧category长度、discovery证据膨胀、主体污染、UI遮挡/降级反馈，以保持旧固定SUT可审计；报告不声称适配自动解决这些问题。

## 实测证据与失败

- 三轮重复100固定合成例，非300独立难题；真实账户/project facade，无传输替身。
- 原型100完成：90/92字面答案、92逐字引文、长文11/12、工具8/8，完整子句标点严格分66/100。一个多主语回答、一个128k密令末尾后缀丢失。
- v1 100完成：90/92字面答案、92逐字引文、长文12/12、工具8/8，严格分60/100。两同义多主语回答。
- v2 98/100结构化成功：90/92问答（成功90/90答案及逐字引文），长文12/12、工具8/8，严格分68/100；两组织变更开放字典string_type失败不重发。中位10.095秒、最慢17.28秒。严格完整子句评分不能当语义准确率。
- v1加强隔离后有真实Agent重复tool触及上限；v2新4协议例全过（2服务端工具任务、2流式），不是单次提案替代循环验收。
- 原型120生产章次计划只启动46：25成功/11错误/10started；74未启动，不自动重跑。导入13次208实体/635引文623逐字；演化12次425观察/425引文407逐字。
- 初期两探针因旧retry误重复3次，已修复禁止未知重发。八并发大正文连续失败，未证明根因；solo/两并发新章次恢复。外层受限shell补测4协议/4生产约1秒失败，宿主新诊断成功，仅推断执行限制，失败保留。
- v1新生产第2/31/59章两臂5/6成功；导入46实体/146引文140逐字，演化80观察/80引文78逐字；第31章evo完整包封失败且旧探针未保存异常原文，不猜根因。
- v2第60章两臂均成功：导入19实体/56引文54逐字，277.4秒；演化28观察/28引文28逐字，237.8秒。新生产8章次7成功，不冒称完整60章/跨章融合或领域采用验收。
- 私有目录/tmp/codex-luna-runtime-eval-20261013、codex-luna-final-eval-20261013、codex-luna-v2-final-eval-20261013；协议codex-luna-live-protocol-v2-final；生产codex-luna-production-20261013、codex-luna-production-final-host-v1、codex-luna-production-v2-final。目录0700/文件0600，原文不进仓库。
- 原固定旧比较已needs_reconciliation：0263-c02a72退出1、workspace routing discovery failed，无turn.completed/答案文件；不能补造结算或推定未执行。2/63回执、13对象/21台账；deep41对象/57记忆/60Scene，关系和结构0。
- 同模型独立复核有偏差；无人工穷尽金标准/作者盲评。引文原文子串不证明蕴含和主体正确。

## 验证及交付边界

- 最终受影响后端819 passed/2外部排除；19 prompt-contract测试；前端23、相关ESLint、Ruff no-cache、生产build、docs-check BASE_REF=origin/main、git diff --check通过。
- 新库完整Alembic升级与check无新增operation；实际PG降级遇Codex记录拒绝且数据/版本保留，未删除连接。
- 真实GUI最新重新验证已显示当前Codex连接成功；报告面板已请求打开（queued），文件确实存在。
- 自动审批拒绝删除刚新增的提示词断言（可能削弱覆盖），已保留，不绕过、不额外要求用户确认。
- 未提交/合并/部署、未生产/作者验收，原完整60章比较仍阻塞。CI、跨进程限流、最大语义容量、真实改源重算/后缀继承未验证。

---
id: T-20261015-g6c-holdout
title: G6c 独立新资料族单次留出验证
status: completed
created: 2026-10-15T09:54:40+08:00
updated: 2026-10-15T10:08:33+08:00
parent: T-20261015-g6b-recalibration
---

# 恢复快照

用户最终明确授权：完成已准备的单次 G6c 后结束 G6；冻结后不调参、不重跑，成功或失败均保留并收尾。
唯一一次留出运行及两批评分均已结束；冻结材料已消耗，禁止重放。
已准备 16 个新资料族、32 条正反题，原版/修改版各一次，共计划 64 次生成与 2 批评分。
新材料、Prompt 副本及协议位于仓库外私有 `/Users/tywww/.codex/private/g6c-holdout-20261015`。
FREEZE_CONFIG 已落私有目录及 artifacts/FREEZE_CONFIG.json，781 个源码/材料/父证据文件哈希核对通过。
配置 SHA256：78c81e18ad2df150931c6b57121d925ddc79ba111b73dcaf804e1ac9a94b1bd2。
材料 SHA256：8ed65b250313ba5016a524813954447894a6620bb76ed70b832d336930be8b6e。
run.complete.json 已保存：64/64 输出，64 笔 Luna/max 原生调用均退出 0，无额外修复调用或重发。
两批匿名混合 Sol/xhigh 评分各完整执行一次，64 份输出均有效审查，参考全部接受。
冻结验收标准满足：过拒答 2/16→0/16，综合通过 28/32→31/32，未观察到幻觉增加。
修复版 1 条综合失败保留（草案比较 uncertainty 为空，教师认可内容），不追认全通过。
全部新原生调用 66 笔退出 0，无 unknown、额外修复调用或重发。781 个冻结文件哈希一致。
run-g6c.py selfcheck 已通过：独占锁/源码漂移断言及当前 owner/Project Luna/max 核验，无模型调用；CLI 0.160.0。
已读取原第二批计划 §3.7，必须新 family、FREEZE_CONFIG 与独占启动标记；旧证据、共享库不修改。

## 下一步与边界

G6 按用户要求结束，不再调参、重跑或追加模型阶段；当前无剩余已授权模型工作。
结论、失败、原始教师/确定性分歧及限制详见 [ACCEPTANCE.md](ACCEPTANCE.md)。
新账本 artifacts/holdout-ledger-v1.json，补充审计 artifacts/holdout-audit-v1.json。
可离线回看已消耗材料；本次结果不能当新未见样本再测。
若生成或评分失败，不重发已启动阶段，保留失败/unknown 并按用户要求带缺口结束 G6。
冻结后不改 Prompt、参考或评分标准，不重放已启动阶段；失败和 unknown 全保留。
原版从封存源码加载，与当前服务源码只有已批准 Prompt 差异；不改产品 Prompt 或传输。
教师沿用受限 AskWorldCalibrationScope 的 Sol/xhigh；新脚本须核验真实父自测 30/30、
候选开发对比 32/32 及同一 rubric/runtime，不伪造旧 CLI 所需的同数据集证明。
生成及评分仍走原独立开发库 65195/agent_e2e_g6b_calibration；默认其他 evaluator 守卫不解禁。

## 工作区与交付

沿用 `/Users/tywww/.codex/worktrees/g6b-recalibration/ai-writing-assist`，
`codex/g6b-recalibration`，基线 d2ab2dbf3c78785a24d3f419002fbb13b36bc99c。
保留已有全部 G6b WIP 与旧账本。G6c 仅新增本任务脚本/准备材料，没有提交、推送或部署。

## 结果与关闭说明

- 原始教师内容通过 30/32→32/32；冻结综合门（包含确定性条件）28/32→31/32。
- 过拒答 2→0，负例错误作答、无依据主张、答案矛盾两版均为 0。
- 两版共 5 条综合失败全部保留。原版 2 条过拒答、2 条 uncertainty 为空的门禁失败；修复版 1 条 uncertainty 门禁失败。
- 原始教师与确定性有 3 条分歧；原账本 agreement=1.0 比较综合状态，并非真实原始教师零分歧，补充审计单列。
- 描述性配对符号检验 p=0.5，不能据此声称总体统计显著改善或排除过拟合；冻结操作性门槛通过。
- 只有生成层和合成来源集；真人作者、完整检索/Evidence/知识治理/引用回开/保存 UI 未验证。
- 当前所有 G6b/C 产品和脚本改动仍仅在本地，无提交、推送、合并或部署；其他评测角色仍暂停。

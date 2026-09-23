---
id: T-20260923-guimi-flagship
title: 现有 guimi 旗舰演示增量升级
status: active
created: 2026-09-23T02:57:27+08:00
updated: 2026-09-23T02:57:27+08:00
---

## 目标与验收

执行用户附件01/02任务书与本轮明确要求：保留原guimi、先可验证备份，再全60章基础覆盖和连续关键篇章精修，贯通正文→对象与证据→地图→冻结来源RP，随后补齐真实图像、四至六开局和十条操作链。覆盖未完成V4能力，不以资料准备或单元测试冒充实际体验。

验收为代理验收，非人工试用。当前 READY=false。代码隔离分支；不合并、不上线、不公开发布。原作正文/工作稿/历史不改写；反事实和破坏性验证只在副本。

## 上下文与来源

- 用户ZIP：/Users/tywww/Downloads/Guimi_Astra_旗舰演示升级提示词包_v2.zip，两份任务书已完整读取；需求副本私存任务artifacts外，原始ZIP不提交。
- 原源码HEAD 0efb1359d70af3bec92ad47d0493238d62bc7861，分支codex/v4-audit-fixpack-1，243个WIP文件快照继承到隔离worktree，不等于已审查可合入。
- 工作树 /Users/tywww/.codex/worktrees/guimi-flagship/ai-writing-assist，分支codex/guimi-flagship。
- 私有数据/媒体/基线位置 /Users/tywww/.codex/artifacts/guimi-flagship-20260923，禁止提交原文、数据库、媒体私有材料和凭据。
- 实查两个backend/.env均指向ai_novel_acceptance_guimi。目标项目937c86f1-a2c3-4db5-963d-f3181095f339，owner零UUID有效active，author，标题诡秘之主·廷根篇；原TXT导入记录795b949a-6d9e-4706-ab0c-70ac210175fe，60/60 done。主开发库同ID是另一份演示项目，不能混用。

## 进度与发现

- [x] 两份附件、根规则、V4当前任务及protected项目历史读取。
- [x] 独立worktree与继承WIP备份、逐文件hash；旧任务保留未完成Phase3和复审四项。
- [x] 实查60已发布正文、版本1、212868字符，账户active，5地图节点，1个ready来源版本（尚须当前门禁重新验证）。没有8000/8080应用进程。
- [ ] 数据库与媒体备份、恢复演练和实际完整hash校验。
- [ ] 纵向闭环与全范围内容/功能/视觉验收。

## 关键决定和费用

不再以DS Flash完美输出作推进条件；代理精修标curated，不冒充自动理解。产品运行仍记录实际provider/model；费用共用旧V4账本USD5总上限。用户允许请求124按最高预留额计入，实际usage_unknown保留，不重发；当前保守累计USD0.6728103。原冻结请求/结果和失败证据不改写。

## 验证与恢复快照

当前仅身份/配置/只读数据盘点；未改原项目数据，未迁移原库，未启动旧应用，未新付费或生图，未提交/推送/合并/上线。旧Source ready标签不等于当前验收通过。下一步：备份原库与guimi媒体，恢复到任务audit副本核验，再跑schema/来源ready诊断和首条真实闭环。

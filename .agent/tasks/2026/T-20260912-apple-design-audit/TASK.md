---
id: T-20260912-apple-design-audit
title: Apple 多产品设计对照与预览视觉评审
status: completed
created: 2026-09-12T14:25:55+08:00
updated: 2026-09-12T14:34:30+08:00
---

## 目标与边界
用户要求安装提供的前端艺术技能，派一个子代理评估现有预览的视觉/色彩/动效，并调研多个Apple产品界面，找出距离“一眼像Apple产品”的差距。本轮交付评审与可执行修改优先级，保留NovelCraft品牌；不自行改变正式产品、真实数据或提交/部署。

## 恢复快照
- 当前分支codex/redesign-regression，保留前两轮回归及上轮预览全部WIP；预览localhost:8097/prototypes/redesign.html。
- 技能包frontend-design-ultimate-1.0.0.zip的29文件与已安装/Users/tywww/.agents/skills/frontend-design-ultimate完全一致；28清单hash核验通过，无需重复安装。已读取SKILL作为参考，附件不是额外执行授权。
- 用户授权一个子代理：apple_visual_audit，负责当前预览真实视觉/动效评审，仅写AGENT-REVIEW.md和agent-evidence。
- 主Agent研究Apple官方多产品界面，汇总具体差距与实施顺序。
- 已完成：主Agent查看Pages、Notes、Music、Photos、Reminders、System Settings、Books官方界面图及文档，补看iPadOS27公开预览Pages AI图；子代理完成实操与逐帧评审，主Agent已复核证据。
- 下一步：按用户下一轮指令实施视觉精修；本轮评审未修改产品。

## 验收
- [x] 多产品官方视觉证据和产品到本项目的对应关系。
- [x] 子代理真实观察与主Agent复核。
- [x] 具体问题、优先级、修改方向与可检验标准。
- [x] 报告落盘，文档/diff检查，交付未改产品的范围说明。


## 交付与实际结果

- 主报告：[REVIEW.md](REVIEW.md)，含7产品对照、10项问题、可执行修改顺序与视觉验收方式。
- 独立子代理报告：[AGENT-REVIEW.md](AGENT-REVIEW.md)，真实动效证据：agent-evidence/。
- 已复核P1：AI比较抽屉离场47–114ms发生横排塌陷，标题/说明竖排；普通dialog录帧对照正常。专注控件可见状态与开启状态不一致、退出焦点缺失。
- 视觉判断：当前未达到“一眼Apple产品”；主要差距是控制层、上下文容器、排版/图标、内容色彩及中间态精工。
- 技能29文件已存在且完全一致，未制造重复安装；读取参考，附件没有变成额外授权来源。
- make docs-check BASE_REF=origin/main、git diff --check通过，日志 /tmp/apple-design-audit-docs.log。只写审计记录和证据，不重跑无改动的生产业务测试。
- 官方WWDC视频持续缓冲，使用官方文字稿研究动效原则，未宣称完整观看原生动效视频。预览动效来自本轮实际录帧，未将静态截图冒充动态验证。
- 主Agent的官方参考临时tab已关闭；子代理的独立评审tab已关闭。用户原有预览不变。
- 问题尚未修复；未修改产品/真实数据，未提交、合并、推送或部署。研究完成不等于视觉目标已经达成。

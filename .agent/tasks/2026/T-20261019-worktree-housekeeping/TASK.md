---
id: T-20261019-worktree-housekeeping
title: 闲置工作树清理、未提交成果归档与可交付增量合并
status: active
created: 2026-10-19T10:43:00+08:00
updated: 2026-10-19T10:43:00+08:00
---

# 工作树整理

## 恢复快照

- 用户授权：清理不用的工作树，整理提交未提交改动，合并可交付成果，保留进行中的任务。
- 工作区：`.worktrees/worktree-housekeeping`，`codex/worktree-housekeeping`，基线 origin/main `bdc6e3037`；原主树及所有 WIP 先保留。
- 当前进度：完成 45 个原工作树与历史交付对账；已移除 39 个闲置树，现保留原主树、桌面验收、导演主树、3 个审计树和本任务树，共 7 个。13 个闲置 WIP 已保存本地归档提交；2 个活动冻结树用独立 index 保存快照提交，原 HEAD/index/工作区不变。
- 下一步：完成导演 #255 的最新主干集成与门禁，合入导演及收口记录；更新主工作区到 main。
- 保留：审计第三批 wave3-evidence/wave3-guimi-v3/wave3-r1 的未完成冻结验收现场、桌面原生发行验收与导演主实施工作树。
- 不运行真实模型、不访问真实业务库、不重放冻结验收、不部署；归档提交只留本地，不将旧实现重新合并。

## 目标与验收

- 无独立工作或已由后继覆盖的树可清理；有效增量须审查、测试后合入，未完成任务明确保留位置。
- 清理前保留可恢复的源码提交、非依赖 ignored 资料与文件校验凭证；范围外 WIP 不丢失。

## 决策与发现

- 2026-10-19：历史 T-20261017-completed-branch-delivery 已证明九个 map-fix、docs-refresh 与 G6b 产品修复交付；现场副本与 main 差异多为较旧版本，不能整树回灌。
- 导演 #255 原固定 head 18 项检查成功，最新主干冲突；原记录的未授权合并边界已被本轮用户授权更新，真实模型/作者验收边界不变。

## 验证证据

- 开工 docs-check 正在执行；Git/PR 实时证据以本轮输出为准。

## 交付结果

- 待完成。

## 清理凭证与恢复

- 私有恢复目录：`.git/cleanup-archives/worktrees-20261019/`，权限 0700。snapshots.json 保存13个旧树本地归档提交；active-snapshots.json 保存2个冻结树快照；removal-progress.json 记录39次移除及对应私有tar。
- 所有移除树保留 `refs/archive/worktree-cleanup/20261019/<key>`。恢复源码：`git worktree add -b codex/recovered-<key> <新路径> refs/archive/worktree-cleanup/20261019/<key>`。若有 `<key>-private-files.tar.gz`，先解到私有临时目录，再复制到恢复树；不要覆盖新生成的 .git 文件。
- 非依赖 ignored 文件以tar保存，逐文件/符号链接校验通过；不归档可再生 .venv、node_modules、Python/测试/lint缓存。没有进程cwd或保留树软链接依赖被移除目录；未读取或外发私有配置内容。
- map-fix九树、旧文档/G6b/模型池/导演规划副本已由既有PR交付或后继修订覆盖，只归档，禁止把其旧代码整树重放到main。
- 根收口提交8761ca702、桌面验收笔记9c2cf8f33已普通merge到本任务分支；后者仍active，保留原树并新建codex/desktop-release-acceptance。
- 导演冲突解决后发现迁移双head与goal service超过5000行：补no-op merge revision，独立拆分回执展示函数；首次完整测试中断，不作为最终验收。

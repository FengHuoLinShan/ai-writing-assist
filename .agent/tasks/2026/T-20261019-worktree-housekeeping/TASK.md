---
id: T-20261019-worktree-housekeeping
title: 闲置工作树清理、未提交成果归档与可交付增量合并
status: completed
created: 2026-10-19T10:43:00+08:00
updated: 2026-10-19T11:50:00+08:00
---

# 工作树整理

## 结果与恢复快照

- 用户授权：清理不用的工作树，整理提交未提交改动，合并可交付成果，保留进行中的任务。
- 45个原工作树已移除39个闲置树，保留6个任务工作区；额外整理临时树在此关闭记录合入后移除。
- 13个旧树WIP保存为本地归档提交；2个活动冻结树以独立index保存快照提交，原HEAD/index/工作区不变。
- [PR #260](https://github.com/FengHuoLinShan/ai-writing-assist/pull/260) 已合入5287d9b0c859004482daa82b033d9c4da298d88b，收口作者工作区与桌面入口任务记录；桌面发行验收保持active。
- [PR #255](https://github.com/FengHuoLinShan/ai-writing-assist/pull/255) 已于11:49合入404f597c1100280564812eb73d47794e1852d7b0。最终head8691ab9cf800573780ac7cfc7e92d268f169179a全部必需检查通过；导演第五批真实模型/作者验收仍active，功能开关默认关闭，ADR-0042仍Proposed。
- 收尾期间主工作区启动codex/map-linkage-impl并有新任务未提交笔记，保留其分支和WIP，不强制切回main或提交其他任务的新工作。
- 下一步：此关闭记录合入后移除整理临时树，更新本地主干引用及空闲的桌面/导演保留树；私有verification.json记录最终实际目录核验。

## 清理与恢复

- 保留位置见[ASSESSMENT.md](ASSESSMENT.md)：地图联动、桌面发行验收、导演第五批及三个wave3审计现场。
- 私有恢复目录：共同Git目录cleanup-archives/worktrees-20261019/，权限0700。snapshots.json保存13份旧树提交，active-snapshots.json保存2份冻结树快照，removal-progress.json记录39次移除。
- 39个移除树均保留refs/archive/worktree-cleanup/20261019/<key>。恢复源码：`git worktree add -b codex/recovered-<key> <新路径> refs/archive/worktree-cleanup/20261019/<key>`。对应private-files.tar.gz先解至私有临时目录，再复制入恢复树，不覆盖新生成的.git文件。
- 非依赖ignored文件逐文件/符号链接核验后保存私有tar，配置未加入源码或外发；可再生依赖和缓存未归档。13份源码快照的179个改动文件实际解出比对Git对象一致，见restore-verification.json。
- 移除前核对进程cwd和保留树软链接，无目录依赖。旧map-fix等产品补丁已有PR/后继修订覆盖，只归档，不整树重放旧实现。

## 决定与验证

- 导演分支与main冲突时保留作者工作区及探索功能。双Alembic head补无DDL汇合迁移；超长service的回执函数原样拆出，AST一致，未放宽门禁。
- 浏览器发现新检查运行时旧通过回执仍开放采用，服务端正确拒绝PREVIEW_STALE。按钮与函数入口增加运行中保护；新增回归在旧代码失败，原浏览器断言不变。
- WritingView测试改为vi.waitFor等待原生WebCrypto摘要后的原请求及回执断言，业务保存逻辑不变。
- 本地完整test-ci：backend9614 passed/2 skipped、覆盖率85.51%，frontend3403，deploy324，desktop47/2 skipped。最终前端全量268文件/3404 passed，ESLint通过。
- 专用合成PG17完成迁移、drift check及8项并发测试；创作浏览器9项、编辑审读10项通过，实例已停止；未访问真实业务库或调用真实模型。
- 最终head远端后端质量、PG critical（421 passed/7 deselected）、前端单元、两浏览器分片、CodeQL与治理门禁通过；Production image contract按策略跳过。最新main集成满足严格基线要求，未绕过分支保护。
- 关闭记录为纯任务文档，执行docs-check BASE_REF=origin/main、secret-hygiene及git diff --check。

## 交付边界

工程合并与归档不代表真实模型效果、作者确认、原生发行/签名/升级验收或部署；这些保留在相应活动任务中。本轮不重放冻结实验，不推送私有归档。

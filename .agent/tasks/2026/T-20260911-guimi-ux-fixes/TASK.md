---
id: T-20260911-guimi-ux-fixes
title: 修复全部35项Chrome审计问题并更新演示副本
status: completed
created: 2026-09-11T12:00:00+08:00
updated: 2026-09-11T15:51:19+08:00
---

# 交付与恢复快照

- 工作区：`/Users/tywww/Desktop/项目/ai-writing-assist-guimi-ux-fixes`，分支`codex/guimi-ux-fixes`，基线a89e8b813，实施提交`9a5a0b454`。原main工作区WIP、原审计任务和.zcode完全保留。
- 已交付：UX-001—035实现、自动化及Chrome验收，原演示升级并通过原启动器重启。逐项证据/限制见`docs/frontend/uiux/guimi-chrome-audit-fixes-2026-09-11.md`；原报告保留。
- 已审查并合入本地main；未推送、未公网部署。没有替作者采用模型候选、别名、关系或世界设定。
- 下一步：当前授权范围完成；远端交付或部署需另行授权。

## 目标与上下文

用户批准全部35项计划，要求现有Vue/bridge/facade修复、独立分支、真实浏览器与模型回归，以及保留资料的本地演示更新。原走查任务在原工作区`.agent/tasks/2026/T-20260911-chrome-ux-audit/`。

## 关键决定与根因

- 写作默认确认预算统一为既有有限12000；必需资料不静默截断，容量原因可定位来源。确认排除项、知识可见范围、来源指纹和owner/novel隔离继续有效。
- 问世界真实失败涉及purpose错误、query引用要求噪音、候选与最终top_k不一致、重复metadata占预算及最终证据上限。修正完整候选→确认→执行→引用路径；正文必须匹配版本/hash及获准片段范围，确认后不越权追加来源。
- 检查按稿件/版本/hash/范围恢复既有复核；编辑使结果过期；无问题与未检查、运行、失败、部分完成分开。
- 地图画布优先、局部图可读、场景编号显示+1、待决定详情push历史、表单真实dirty等均复用现有组件/领域接口，不新增框架。
- 演示旧test-checkout有123处WIP，不能当纯基线。用git archive的32cb44ce2做三方比较：55相同、34干净且等于当前、34重叠增强采用当前；原定制的冻结/幂等/禁编辑能力当前代码已包含或增强。

## 验证

- 实施前make docs-check通过。
- 最终frontend：182文件2478测试通过；lint/build通过。
- backend受影响536测试通过；修改及新增Python Ruff通过。
- 功能E2E10文件95测试通过，独立库ai_novel_test_guimi_ux_20260911。覆盖地图、写作、资料、关系/别名、结构、检索和作者任务。
- 曾有Vitest异步子组件在卸载后仍加载的错误；显式stub所测父组件之外的WorldReviewTab后全量重跑通过。没有删除有效断言。
- 实际Chrome：320/354/360/390和桌面地图首屏、场景工具栏；1/60章四种默认确认、两次候选生成；两种问世界问题及第30章引用；检查重开、地图锁定/双标签409、历史回读、空表单、分页后退/前进、缺前提健康入口等，详见逐项表。
- 收尾make docs-check BASE_REF=origin/main执行；7份广泛匹配文档需核对，使用工具原生--no-change-reason声明已逐项确认架构契约未变，inventory及影响检查通过并保留warning日志。没有修改门禁。
- git diff --check通过；原main状态与开始一致。

## 演示更新和数据保护

- 演示：`/Users/tywww/Desktop/NovelCraft-诡秘地图演示-20260909/完整项目演示`。
- 完整旧应用：`app-before-guimi-ux-20260911`，原位改名保留所有未跟踪文件；新app为核对后干净源码，保留.env，重建运行路径与生产前端。
- 旧启动器不在，但三个8000/8080/worker子进程孤立存活；逐一核对cwd后停止，没有停止其他项目服务。新版本由原launch_demo.py启动，日志demo-restarted.log。
- 原库ai_novel_acceptance_guimi从20260908_unified_map升级至20260912_web_search_consent。先在备份恢复的验收复制库验证升级，另恢复旧库配干净原版源码通过schema guard，回退方案为旧源码+完整数据库备份恢复。
- 更新前/后18组摘要完全一致：60正式章、项目/大纲、58场景、81对象、77关系、地图、任务等。7图片SHA256一致。源码清单与worktree逐文件一致，build-info.json记录dirty分支和真实清单指纹，不冒充提交版本。
- 原演示实际Chrome入口、资料库、地图加载和已保存状态已验；最终截图demo-updated-map.png。临时viewport已reset。
- 真实模型与可逆编辑只在ai_novel_audit_guimi_ux_live_20260911验收复制库，两个候选未采用，不替换原演示数据库。

## 证据与回退材料

受控本机目录：`/Users/tywww/.codex/artifacts/guimi-ux-fixes-20260911`。

- final-before-update.dump（最后停机备份）、before-update.dump、demo-code-before.tar.gz；均权限600。
- images-before/（7对象及manifest）、images-after.json。
- integrity-final-before.json、integrity-after.json；18组hash一致。
- git-base-32cb44ce2、demo-local-changes.json、demo-merge-status.json、demo-source-hashes.json。
- frontend-final-freeze.log、backend-final-freeze.log、e2e-final-freeze.log、lint-final.log、build-final.log、docs-impact-reviewed.log。
- map/scene-viewport-verification.json、map-final-*.png、map-conflict-resolved.png、map-history-comparison.png、check-restored.png、ask-world-open-question.json、demo-updated-map.png。
- demo-before为因iCloud dataless重复文件中止的局部cp副本，不能作为完整备份；完整旧应用在演示目录中。
- 回退需先停原启动器，保留当前新app，再恢复旧跟踪源码（rollback-source/app）及原.env/依赖并恢复dump；不要激活旧app中的重复Alembic文件。整体恢复在隔离库演练过，不需要冒险对真实库执行downgrade链。

## 限制

模型样例通过不证明所有问法质量。旧候选缺失来源仍待核对；历史导入描述保留不改写。没有新增历史恢复写入、自动创建设定或修改发布门禁。详细限制在逐项验收记录。

收尾：最终演示浏览器读取后再次核对integrity-after-smoke.json，18组hash仍完全一致。已停止本任务8018/8098及其worker，保留验收数据库和证据；原演示8000/8080及worker继续运行。交付地图标签已保留。

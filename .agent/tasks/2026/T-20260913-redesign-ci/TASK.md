---
id: T-20260913-redesign-ci
title: 新版前端 CI 与行为门禁同步
status: completed
created: 2026-09-13T10:54:42+08:00
updated: 2026-09-13T11:42:00+08:00
---

## 目标与边界
根据新版前端更新 CI 与过期行为定位。保留保存、冲突、防重、隔离、鉴权和基本可访问性；截图只作诊断。本轮不重设计产品、不触及真实演示库，不提交、合并、推送或部署。

## 恢复快照
- 工作区 codex/redesign-regression，HEAD 4d1034732；初始 8 文件 WIP 保留并衔接，原 patch /tmp/redesign-ci-initial.patch。唯一产品 CSS 差异是原有菜单层级修正，本轮未新增产品变更。
- 实际完成：CI 选择规则、共享菜单定位、写作/主题/导航/减少动态效果检查及开发/测试指南同步；本地验收完成。
- 阻塞：无。下一步仅在用户授权后审查提交；远端 CI 尚未重跑。

## 实现与决定
- scripts/classify_ci_changes.py 复用既有分类：涉及 frontend gate 的 PR 在需要浏览器时选完整 functional；CSS、组件、主题、入口、依赖以及未知路径不再只验证四文件冒烟。纯单测/Markdown 仍跳过无关浏览器，后端相关 PR 保留 smoke，main 全量。job 名称、专用数据库、私有 MinIO、workers=1/retries=0、安全检查和镜像构建职责保持。
- helpers/workbench.js 统一操作入口适配：按钮可见时直接使用，折叠时打开包含该操作的菜单。写作、版本冲突与显式真实模型用例复用；不规定组件结构为兼容合同。
- 当前导航补齐工作区菜单 → 作品档案与导入；放弃修改打开其自身菜单。更多工具按可见文字定位，避免依赖原生 details 的平台无障碍命名差异。
- 主题包样例只声明字体/图片与圆角，没有自定义 colors；去掉的是旧内置按钮色常量，保留明暗选择、字体/图片应用及导入、取消、保存、刷新、导出、删除。
- RP 减少动态效果等待极短过渡收束后检查静止；保留请求次数、禁用与可读对比度断言。
- 发布用例从模拟成功和 2999/3000ms UI 定时改为真实服务端发布内容、标题、状态及刷新验证。成功自动收起和故障持续反馈仍由 tests/vue/writing/WritingWorkflowBars.test.js 覆盖。
- development-guide.md、testing-guide.md、frontend-console/README.md 同步完整/冒烟选择及视觉诊断边界。

## 验证证据
- 远端基线：Frontend CI 34732851133（4d1034732）24 个浏览器失败，只读日志 /tmp/redesign-ci-remote-failure.log；没有触发或改写远端运行。
- make test-ci TEST_WORKERS=2 通过：后端 5432 passed / 13 skipped，覆盖率 85.75%（门槛 85%）；部署合同 270 passed；Ruff、secret hygiene、依赖审计通过。日志 /tmp/redesign-ci-quality.log。
- CI 分类与工作流合同：50 passed，/tmp/redesign-ci-contracts.log。
- 初轮发现本地 Node/node_modules 落后于锁文件。因此在 /tmp/novelcraft-redesign-ci-verify 复制当前前端源码，backend 使用符号链接，原依赖与演示服务不改。用 Node 24.20.0 + npm ci，Vitest 4.1.11、Playwright 1.63.0、Vite 8.2.2、Vue 3.5.42 与锁文件一致；源码副本逐文件 hash 比较无差异。
- 锁定前端：188 文件 / 2452 单测通过，lint 和生产构建通过（14 local refs / 52 JS / 84 assets）。日志 /tmp/redesign-ci-locked-frontend.log、/tmp/redesign-ci-final-lint.log、/tmp/redesign-ci-writing-lint.log。
- 锁定 Chromium 153 完整 functional：286 passed / 1 failed / 2 skipped（7.8m），/tmp/redesign-ci-locked-browser.log。唯一失败为新增断言错误使用 latest.draft，实际 API 返回 draft 对象本身，发布成功。改正后整个 writing.spec.js 27 passed（59.1s），/tmp/redesign-ci-final-writing.log。两轮合计覆盖全部 287 个功能用例；不是一次全套全绿记录。
- 原有 2 个世界资料性能专项未启用。未通过跳过、截图基线更新或重试掩盖功能失败。
- 助手独立真实 API/worker + 既有合成模型 harness：1 passed（20.5s），/tmp/redesign-ci-assistant.log；确认、跨页恢复和 390px 键盘路径。
- PR 首轮完整 functional 通过后，助手 harness 因 CI 无本地 `.env` 而缺少 `LLM_SETTINGS_ENCRYPTION_KEY`；专用 Playwright 配置现生成固定全零 Fernet 测试键，不触及生产或真实凭据。独立新库复验 1 passed（23.8s）。
- 中间诊断保留：旧依赖轮 266 passed / 6 failed / 1 interrupted 后停止（/tmp/redesign-ci-browser.log）；锁定定向过渡轮 2 passed / 2 failed（/tmp/redesign-ci-locked-targeted.log），问题均已在最终结果中复验。
- make docs-check BASE_REF=origin/main 与 git diff --check 通过，/tmp/redesign-ci-final-docs.log。

## 环境与交付
- 仅新建容器 novelcraft-redesign-ci-test-db（55440）与 novelcraft-redesign-ci-test-minio（59001），数据库 novelcraft_redesign_agent_e2e_test 和 novelcraft_redesign_assistant_agent_e2e_test；服务 18003/18083、18005/18085。测试完成后移除这两个容器及其匿名卷，原服务与持久演示环境保留。
- 本地脚本和日志保留于 /tmp；浏览器诊断目录 /tmp/redesign-ci-locked-browser-results、/tmp/redesign-ci-final-writing-results、/tmp/redesign-ci-assistant-results。没有调用付费模型。
- 完成本地实现和验证；远端 GitHub Actions、生产镜像运行及部署未执行。没有未修复的本轮功能用例失败。

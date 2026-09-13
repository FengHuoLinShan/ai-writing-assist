---
id: T-20260912-redesign-regression
title: 前端行为回归支持自由重设计
status: completed
created: 2026-09-12T12:32:16+08:00
updated: 2026-09-12T13:02:37+08:00
---

## 目标与验收
本轮只调整测试、配置、CI、规则及文档。按用户任务验证功能等价、数据正确和适用操作幂等性；保留鉴权、项目隔离、确认与采用、保存恢复、冲突、防重和基本可访问性。取消截图像素、CSS写法、固定尺寸、布局、断点、DOM/组件结构阻断，允许调整入口、步骤与定位器。不重设计产品，不提交、合并、推送或部署。

## 上下文与交付
- 初始工作区在 main，HEAD 与 origin/main 为 fe5d32924；保留前轮 T-20260912-test-complexity-audit 全部WIP，切到 codex/redesign-regression。初始diff位于 /tmp/redesign-regression-initial.patch，原测试副本位于 /tmp/redesign-regression-original。
- 撤除8个视觉spec、视觉与styles配置/脚本、CSS源码专项检查。旧95张PNG未修改，仅作历史参考。35个原场景声明（38个参数化用例）的有效断言去向见 [MIGRATION.md](MIGRATION.md)。
- 独有参考审阅、候选深链、首页数据、项目搜索和RP主题资源断言进入现有行为套件；普通e2e去除几何和结构冻结，分页/长表单改验证真实操作和持久化。保留主题包输入效果、地图领域坐标与安全断言。
- 共享工具入口按可见入口和展开状态工作，不依赖760px。项目助手恢复权限改为组件状态/调用验证；重复重试补充请求计数、禁用与减少动态效果检查。
- CI对浏览器测试/配置变更收集完整功能套件；普通相关PR仍smoke，main完整。助手复用独立合成模型harness并在同一浏览器job运行。保留前轮不重复构建的精简，生产镜像门禁仍负责CI构建。
- 同步AGENTS、开发/测试指南、前端README、UI/UX入口与页面规则、ADR-0009及索引。产品源文件仅修改旧迁移规则注释；可执行产品代码、CSS、依赖和锁文件未改。

## 实际验证
- 最终完整Vitest：176文件、2384 passed，29.89秒；日志 /tmp/redesign-vitest-complete.log。
- Chromium完整functional收集289项：首轮最终汇总281 passed、6 failed、2性能专项按显式开关skip；6个失败全部经修正复验通过，覆盖合计287个功能用例。最终共享工具调用方10项全过，新重试/reduced-motion检查及世界健康等6项复验通过。日志 /tmp/redesign-browser-third.log、/tmp/redesign-browser-corrections.log、/tmp/redesign-browser-helper-final.log；需结合这些记录，不把中途单次全套描述为全绿。
- 专用助手真实API/worker加合成模型：1 passed；/tmp/redesign-assistant-browser.log。无付费模型请求。
- CI选择、安全自动化和测试环境合同：60 passed；Ruff通过。/tmp/redesign-ci-final.log、/tmp/redesign-ruff.log。
- ESLint、生产构建及81项发布资源清单验证、make docs-check BASE_REF=origin/main、git diff --check通过。日志 /tmp/redesign-lint-complete.log、/tmp/redesign-build-final.log、/tmp/redesign-docs-complete.log。

## 关键修正与证据
- 原普通集合错误收集assistant专用服务用例；拆到已有harness并纳入CI，没有跳过其功能验证。
- RP模拟旅程缺少care/policy，补真实形状的禁用策略fixture；世界健康种子缺少全面校验要求的世界模型，复用既有checkpoint补齐。没有放宽错误检测或把缺少准备改判成功。
- 原固定菜单/区域中心点击/精确文本/特定保存按钮焦点不再等于用户任务；按当前可访问入口、命名地点键盘选择与编辑区域内焦点继续完整流程。地图缩放现验证桌面入口，窄屏仍验证读取、重试和热点；未改产品。
- WritingView的flushPromises未等待原生异步摘要，迟到调用污染下一例；改等待可见结果，再验证请求数据。最终全套2384项通过。

## 清理、未验证与恢复快照
- 临时容器 novelcraft-redesign-regression-test 及其两个e2e数据库已删除；本轮新建的空MinIO桶 novelcraft-redesign-e2e-maps / novelcraft-redesign-e2e-objects 已删除。开发库、持久演示库与原图片未改。
- 截图/trace仅为诊断；最终定向产物在 /tmp/redesign-browser-helper-final-results，其余日志/原测试副本保留供审查。
- 本地验收完成；2个性能专项未启用，远端CI、付费模型、生产镜像/部署未运行。未提交、合并、推送或部署。
- 下一步仅在用户明确要求后审查/提交；先复核当前工作树，区分本轮与前轮未提交内容。本记录不构成新增授权。

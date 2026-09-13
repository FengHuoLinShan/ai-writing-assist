---
id: T-20260912-test-complexity-audit
title: 前端视觉与后端行为回归基线审计及精简
status: completed
created: 2026-09-12T12:00:00+08:00
updated: 2026-09-12T12:29:24+08:00
---

# 回归基线审计及精简

## 目标与验收

用户先要求全仓审计过度复杂的视觉/行为回归要求，随后明确授权“直接进行修改优化”。
交付可复核审计、最小充分改动、相关验证和真实限制；不改产品行为与安全边界，不擅自提交/发布。

## 恢复快照

- 工作区：/Users/tywww/Desktop/项目/ai-writing-assist；分支 codex/test-baseline-simplification；基线 a8c331024（实施前 fetch 后与 origin/main 一致）。
- 已完成：按 A01–A18 执行证据支持的精简与方案复核，完整逐项状态见 [IMPLEMENTATION.md](IMPLEMENTATION.md)。
- 下一步：本轮工作完成；如用户要求提交/合并，先重新检查 Git 状态、差异和验证记录，不自动合入 main。
- 阻塞：无新增实现阻塞。三个既有视觉基线漂移与未运行的其余截图明确保留为验收限制。
- 最后核实：2026-09-12T12:29:24+08:00。

## 决策与发现

- 初始只读审计基于 eeeb32b40c44b22bd0fcaff3d25ddd83c22ad04a；[REPORT.md](REPORT.md) 保留当时结论，[scan.csv](scan.csv) 保存 686 文件静态扫描记录，不代表逐条动态验收。
- 保留 owner/novel_id、Evidence、事务与恢复、数据库隔离、凭据与付费边界；85% 覆盖率和 0.5% 像素阈值不改。
- 全量视觉 mock 会复制八个业务面的后端合同；改用无数据库的共享样式入口减少普通 CSS 验证成本，整页截图仍沿用真实种子。没有把“不新增模拟业务层”伪装成已完成 mock 迁移。
- 纯源码风格/修辞断言、重复常量和元测试已精简；有实际兼容、安全或可访问性保护的检查保留。
- 首次后端全层的单个失败来自旧 probe 测试读取实际 ROOT/.env；改为临时 ROOT，原拒绝重定向断言保持不变。
- 真浏览器发现 reducedMotion 须位于 contextOptions，已修正配置；旧 PNG 没有更新。
- 文档硬门禁新增 *_api/*_facade 匹配后发现测试文件误命中，已为相应规则排除 tests 路径，并补充正反例。

## 验证证据

- 完整前端 Vitest：185 文件、2424 passed。
- 完整后端 coverage：5414 passed、13 skipped、11 warnings；85.75%，RuntimeWarning 按 error 执行。warnings 未隐藏。
- 最后改动的文档/基础设施定向：56 passed；最终文档规则正反例 15 passed。
- 部署契约：270 passed；后端 Ruff、前端 ESLint、secret hygiene 通过。
- 锁文件审计：无已知漏洞；backend 提示 langchain-community 已归档，未擅自更换依赖。
- 无数据库 Chromium 样式用例：2 passed（light/dark），验证焦点、触控、减少动态效果、变量解析与无横向溢出。
- 当前/原版视觉收集同为 38 tests/8 files；当前全套尝试在第 3 个失败停止（2 passed、3 failed、33 未运行）。对照原版 a8c331024 复现同样三个失败，三张 actual PNG SHA-256 完全一致。
- make docs-check BASE_REF=origin/main 最终通过；git diff --check 通过。
- 日志在本机 /tmp/test-baseline-*.log；当前视觉差异产物在 frontend-console/test-results/visual/（忽略目录）。

## 交付与清理

- 仅本地变更；无提交、推送、合并、远端 CI 或部署。
- 新增三个测试文件/入口及本任务材料仍为未跟踪文件；未丢弃其他 WIP。
- 临时 PostgreSQL 容器 novelcraft-test-baseline-audit 已停止并删除；隔离对照 worktree /tmp/novelcraft-test-baseline-reference 已移除。
- 未修改普通开发数据库、《诡秘之主》持久验收库或 95 张已跟踪截图。
- 未完成项：未宣称全套截图、生产镜像、真实模型或远端 CI 验收通过；旧截图漂移未通过提高阈值或覆盖图片处理。

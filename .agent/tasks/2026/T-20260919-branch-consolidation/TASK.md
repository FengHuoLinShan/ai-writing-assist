---
id: T-20260919-branch-consolidation
title: 逐分支审查、修复、合入 main 与安全清理
status: completed
created: 2026-09-19T20:00:00+08:00
updated: 2026-09-19T21:52:30+08:00
---

# 分支整合

## 恢复快照

- 实际完成：从 origin/main d66eb40cb 建隔离 worktree；逐支审查并整合前端修复、demo-copy、resume-qr 和 8 个 Dependabot 分支，修复审查发现的阻断项。旧 World/LLM 分支均为 main 祖先；归档和受保护 WIP 保留。
- 当前里程碑：PR [#151](https://github.com/FengHuoLinShan/ai-writing-assist/pull/151) 以 merge commit 合入远端 main `74879496f`；PR 与该 main push 的检查均通过，分支和本轮专用测试资源已清理。
- 下一步：本任务无；生产发布与线上真实账号验收须另行授权。
- 阻塞：无。
- 工作区：主工作树在 main `74879496f`，原有 README、宣传任务笔记和未跟踪内容未改；`ai-generation-quality`、归档研究及 detached 诡秘演示保留 WIP。干净旧 checkout 的依赖缓存保留在 detached worktree。
- 最后核实：2026-09-19 21:52 +08:00。

## 目标与验收

- 目标与交付物：逐个审查待合并分支，修复发现的问题，验证后合入 main，安全清理已整合分支。
- 完成条件：每个分支有纳入/保留判断；纳入内容完成项目门禁；main 内容正确；不丢失 WIP 或归档历史。
- 非目标：生产发布、覆盖或删除真实项目数据。

## 上下文与边界

- 关键路径与来源：AGENTS.md、development-guide.md、testing-guide.md、各分支 diff、开放 PR。
- 硬约束与授权范围：用户明确授权审查、修复、合并和清理；生产部署不在本次范围。
- 依赖：本地 Git 与适用测试环境。
- 已确认事实：旧 World/LLM 开发分支均已包含于 main；归档分支须保留；demo-copy、前端修复、resume-qr 及 8 个 Dependabot 分支领先 origin/main。
- 假设与待决问题：归档和未提交 WIP 不视为待合并提交；仅清理已证实整合且无工作树风险的本地引用。

## 里程碑与进度

- [x] 逐分支审查并记录处置：11 个领先候选整合；5 个无 WIP 的旧祖先分支清理，`ai-generation-quality` 因未提交工作保留；archive/dirty/detached 保留。
- [x] 修复与本地验证：demo-copy 目标快照 digest、World facade、专用导入策略及反例；Vitest 5 测试适配；静态简历路径；依赖/镜像版本对齐；生成中心参考栏刷新恢复。最终浏览器全量 289 passed/2 skipped。
- [x] PR #151 合入远端和本地 main；GitHub 自动关闭 8 个 Dependabot PR 并删除其远端分支，另删除 `resume-qr` 远端、本地及干净 worktree；删除 8 条其他已合入本地分支。脏 WIP 与归档保留。

## 决策、发现与失败

- 2026-09-19：Dependabot 后端组把 langchain-community 0.4.1 改为已知不兼容的 0.4.2，须修复后纳入。
- 2026-09-19：demo-copy 的源快照摘要与实际复制快照不一致；已按目标 JSON 重算并用真实 PG 关联页回放验证。旧任务的 D1–D5 报告补于 `T-20260917-immutable-copy-invariant-audit/AUDIT.md`。
- 2026-09-19：首次浏览器全量 287 passed/2 skipped/2 failed，失败源于隔离环境未配置私有图片存储；专用测试桶配置后两项均通过。第二次全量 288 passed/2 skipped/1 failed，参考栏刷新状态存在项目 ID 晚到与异步 toggle 竞态；修复后定向 5 次及最终全量 289 passed/2 skipped 均通过。

| 领先分支 | 审查结论与处置 |
|---|---|
| `codex/frontend-occlusion-rp-entry-20260917` | 顶栏遮挡与 RP 入口符合现有画像/审计；整合，后续修复参考栏刷新竞态。 |
| `codex/demo-copy-immutable-history` | 不可变历史方案可用；修复目标快照 digest、跨模块 facade 和授权策略，补 PG/反例测试与审计文档。 |
| `resume-qr` | QR 指向 `/resume/`；资源原位于构建范围外，移入前端 `public/resume/`。 |
| Dependabot #140 | 后端小版本组含不兼容的 langchain-community 0.4.2；保留 0.4.1 并重锁，其余更新纳入。 |
| Dependabot #141 | happy-dom/Vite 小版本；合并锁文件并通过前端测试。 |
| Dependabot #142 | Vitest 5；修复两处真实测试 API 兼容问题，保留有效断言。 |
| Dependabot #146 | Node/Nginx 镜像；同步 `.node-version` 与文档，生产镜像合同通过。 |
| Dependabot #147 | embedding 摘要；同步生产示例与固定测试，镜像摘要可解析。 |
| Dependabot #148 | searxng 摘要；镜像摘要可解析。 |
| Dependabot #149 | soupsieve 2.9；锁文件与漏洞审计通过。 |
| Dependabot #150 | anyio 4.14.2；锁文件、后端与并发 PostgreSQL 测试通过。 |

归档分支逐一保留：`archive/apple-style-redesign`（旧视觉探索）、
`archive/ask-world-model-probes-wip`（脏研究 WIP）、`archive/m4-dsh-plugin-rewrite`
（独立 DSH 大型历史）、`archive/repo-formatting-wip-20260915`（未采用格式化快照）、
`archive/world-model-evolution-research`（研究快照）、`origin/archive/main-legacy`
（旧主干历史）；detached 诡秘演示 checkout 的 WIP 不动。

## 验证证据

- 2026-09-19：`make test-ci TEST_WORKERS=2` 通过：deploy 270、backend 5823 passed/13 skipped、frontend 2503 passed，覆盖率 86.14%；`make docs-check BASE_REF=origin/main`、前端 lint/build、`make test-production-images` 通过。
- 2026-09-19：专用 PostgreSQL 17 + pgvector 上 demo-copy E2E 2/2、`make test-postgresql-critical` 37/37；隔离 Python 3.13 环境中 Ragas 0.4.3 + langchain-community 0.4.1 导入成功。生产镜像包含 `/resume/` 页面与 PDF。
- 2026-09-19：最终 `DATABASE_URL=<dedicated-PG> PW_REUSE_EXISTING_SERVER=0 npm run test:e2e:functional -- --workers=1 --retries=0` 在专用 PG/MinIO 桶上 289 passed、2 skipped、0 failed；参考栏失败用例修复后连续 5 次通过。
- 2026-09-19：PR #151 的全部远端检查通过；main push `74879496f` 的 Backend CI、Frontend CI、Production Image CI、Architecture docs 和 CodeQL 均为 success。独立测试库/桶已移除。

## 交付结果

- 已交付：PR #151、远端/本地 main `74879496f`、分支安全清理和审查/验证记录。
- 未交付：生产部署与真实账号线上验收（本任务未授权）。
- 交付边界：已提交、推送、合并且主干 CI 通过；未部署。
- 正式知识与后续任务：无。

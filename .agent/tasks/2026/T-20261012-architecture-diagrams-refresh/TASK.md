---
id: T-20261012-architecture-diagrams-refresh
title: 模块架构与作者功能图核查整理
status: completed
created: 2026-10-12T22:52:32+08:00
updated: 2026-10-12T22:52:32+08:00
---

# 模块架构与作者功能图核查整理

## 目标与验收

检查此前未提交的模块图、作者功能图及索引/维护登记，对齐 PR #220 合并后的实际代码；
交付八份文档和核查记录。用户授权提交并通过 PR 合入 main，不含部署或真实模型验收。
验收内容为事实核对、图源结构、宽窄屏预览与导出及文档门禁；GitHub 合并状态从 PR 实时恢复。

## 上下文与决定

- 最新核查基线：`2dce04f42a7d7eb41eaf0c025033c1eb4a051e50`（PR #220 的 main 合并提交）。
- 分支：`codex/architecture-diagrams-refresh`，复用干净的 P4 整理工作树，不移动原工作树 HEAD。
- 从主工作树按八条文档路径复制/三方应用原补丁，保留图示风格及当前主干的 Evolution 能力；
  原主工作树和其他八个脏工作树的 HEAD、状态、暂存 diff 与文件哈希已在仓库外保存，收尾重验。
  历史计划、其他任务记录、`.workbuddy/`、`out/` 截图与审查探针不纳入此提交。
- 数据/API/Schema/Prompt/业务实现没有变更，不增加依赖、模块、队列或验收开关。

## 核查结论与变更

- 三条创作引导及采用后滚动大纲已有实现，图中补入真实入口、默认关闭及按项目开放边界；
  继续复用 AssistantRun 和原领域任务，后续多章只规划大纲，不自动生成正文。
- P4 作者全景、派生细节台账、持续发现、类别补扫、输入证明选择性重做补入图源与 HTML；
  仍显式启用，默认 deep_import 替代未完成。复用须证明一致，未知付费请求先核对；
  世界知识/地图册/世界正史版本依赖闭包未接通，真实模型、长篇质量与费用仍未验收。
- 修正运行时边：对象存储由 API/worker 访问，Mac 向 API 出站领取租约，PostgreSQL 不直连
  bucket 或设备；修正旧 API 前缀退场与普通建议/授权自动流水线、回收站/领域撤销的说明。
- 来源：当前模块注册表；Assistant/Evolution/Imports/Account/Project/Local Agent README；
  `frontend-console/router.js`；WritingHome/Today/EditorialDesk/ReadingFlow/SceneLensSummary
  的入口；Evolution API 与 `backend/core/config.py` 的开关。

## 验证与复审

- 当前清单门通过：12 个业务模块、152 个 ORM 表、60 个 task handler、16 个前端路由、40 个 ADR。
- 两个 Draw.io：XML 可解析、ID 唯一、edge 端点完整、所有节点位于页面范围；新功能图结构
  为额外本地自检，现有自动脚本的专门图源检查仅覆盖 module-architecture。
- Chromium 的 1280px / 390px 四个预览检查通过：无脚本异常、整页横向溢出或 SVG 越界文字。
  图面在窄屏内横向滚动，详情卡纵向阅读；宽屏与窄屏截图经目视复核。
- 两张预览的 Draw.io 下载及实际 PNG/PDF 下载通过；导出库正常加载。未验证系统剪贴板权限。
- 差异文档门触发 architecture-governance 的 development-guide/testing-guide 必查面。
  逐项核对：仅登记功能图和维护行，不改脚本、Makefile、CI、路由、测试矩阵或环境需求；
  两指南的通用清单/链接/图源门命令已适用，无需修改。通过既有显式无影响说明检查并保留提示，
  PR 使用对应复核 checkbox 和逐文件原因；不修改或跳过门禁。
- `git diff --check` 通过。纯文档交付不重复运行产品业务/数据库/模型套件；合并仍等待固定 head
  的全部必需 CI 检查，无管理员绕过。

## 交付与恢复

- 文档内容核查已完成；本记录提交时尚未合并或部署。最新提交和 PR URL 由 Git/本任务附件恢复。
- 下一步：检查此分支 PR 的固定 head、必需 checks 与是否已合入；已有授权在门禁通过后合入 main，
  然后核对九个原脏工作树的保护快照。禁止把本记录解读为真实模型/作者验收或部署授权。

---
id: T-20261002-general-worldbuilding-mcp
title: 理法之环能力泛化 MCP 五轮升级与发布
status: active
created: 2026-10-02T00:00:00+09:00
updated: 2026-10-02T00:00:00+09:00
---

# 通用世界观 MCP

## 恢复快照

- 实际完成：第一轮统一10工具、契约校验、协议协商与全项目迁移清单；第二轮新增检索/Context/14写作模式/候选检查，来源漂移、预算、知识边界与逐字引文回归通过。
- 当前里程碑：第二轮收尾，进入候选版本保存。
- 下一步：在 `mcp/workflow.py` 同一来源契约上实现固定项目 SQLite 不可变候选、operation 幂等/CAS 和变更影响工具。
- 阻塞：无。
- 工作区：`/Users/tywww/plugins/worldbuilding-engine-mcp-v080`，分支 `codex/general-mcp-five-rounds`，基线本地已提交 `a8f6ad9`（含 config-relative Worldcheck 修复与概念设计技能）；origin/main 为 `69040b2`。工具库主目录存在未提交技能 WIP，禁止覆盖或纳入发布。ai-writing-assist 当前主题分支只写本任务记录，既有 out/ 与视频图片任务不动。
- 最后核实：2026-10-02，Asia/Tokyo。

## 目标与验收

- 用户 /goal：整理升级理法之环检查与写世界观 MCP，结合本项目可迁移功能，五轮循环迭代，打包发布通用 MCP。
- 五轮各有检查、实质修订、对应回归与结论；完整端到端合成工作流、错误/冲突/来源漂移/知识边界与打包独立启动通过；向既有公共工具库发布可下载版本，记录远端状态。
- 非目标：改写或发布理法之环/真名回响正文、正典；部署 NovelCraft；更改 RIGHTS 或授予开源许可证；启动付费模型或本机 CLI Agents。

## 上下文与边界

- 来源：`/Users/tywww/plugins/worldbuilding-engine`；其 `mcp/server.py`、`tools/worldcheck/mcp_adapter.py`、`scripts/worldbuild.rb`；NovelCraft 各模块 README 与 facade，以及 `world_design_iteration.py`、`reader_safety_service.py`、`adoption_package_service.py`。
- 授权：本次明确要求整理、升级、打包发布；使用既有公共 GitHub `FengHuoLinShan/worldbuilding-engine` 作为发布目的地，保留既有权利文件；不合并/覆盖用户主目录 WIP。
- MCP 使用 Python/Ruby 现有实现，默认不读任意路径、不访问业务 DB、无隐藏模型；候选只能 draft/proposed，不自动采用 canon。
- 宿主负责提供获授权来源与写作/语义判断；结构检查和文学/真实用户验收分开。

## 里程碑与进度

- [x] 第1轮：全项目能力盘点、统一 MCP 入口与契约；提交 10e1706。
- [x] 第2轮：来源、可见性、排除项与写作/返修交接；6 workflow tests 与9主MCP tests通过。
- [ ] 第3轮：候选版本、失效、幂等保存与历史保护。
- [ ] 第4轮：对抗输入、协议与跨入口回归。
- [ ] 第5轮：独立包验收、发布扫描、发布与远端核实。

## 决策、发现与失败

- 复用已公开通用库，不复制整个数据库应用；为 NovelCraft 全部领域能力建立迁移清单，分别以计算工具、写作模式、宿主责任/排除方式交付。
- 工具库 origin/main 落后本地两次已提交升级；隔离分支先 fast-forward 到本地已提交基线，不纳入未提交技能修改。
- goal 已由 /goal 平台建立；重复 create_goal 返回 unfinished goal，get_goal 核实当前目标一致，无需另建。

## 验证证据

- `make docs-check`：通过（12 modules / 143 ORM tables / 55 task handlers），2026-10-02；NovelCraft 未修改业务代码。
- Toolkit 基线：Ruby engine9/Worldcheck15/Python server8/adapter6全部通过；第二轮新增6来源失败路径测试通过。详细五轮证据保存在工具库 `docs/iterations-0.8.0.md`，公开内容只含合成验证结论。

## 交付结果

- 已交付：无；当前执行中。
- 未交付：实现、五轮回归、包与远端 release。
- 交付边界：无新提交、推送或部署。

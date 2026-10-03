---
id: T-20261002-general-worldbuilding-mcp
title: 理法之环能力泛化 MCP 五轮升级与发布
status: completed
created: 2026-10-02T07:44:22+09:00
updated: 2026-10-02T08:29:53+09:00
---

# 通用世界观 MCP

## 恢复快照

- 实际完成：五轮升级、58测试/124 Ruby assertions、最低Python3.10实跑、官方SDK、Ruff、文档门禁与Linux/macOS远端CI通过；v0.8.0已发布，四附件下载逐字节与校验和核实通过。
- 当前里程碑：目标验收完成；release https://github.com/FengHuoLinShan/worldbuilding-engine/releases/tag/v0.8.0，固定tag提交 `84ad6ce258a309fa9f95ffe1bc88f4abf984ac46`。
- 下一步：无必需工作；使用发布包 `python3 scripts/mcp_config.py` 生成客户端配置。后续若单独授权真实作品质量评测，再在私有数据与模型预算边界内开展，不自动运行。
- 阻塞：无。
- 工作区：`/Users/tywww/plugins/worldbuilding-engine-mcp-v080`，分支 `codex/general-mcp-five-rounds`，基线本地已提交 `a8f6ad9`（含 config-relative Worldcheck 修复与概念设计技能）；origin/main 为 `69040b2`。工具库主目录未提交技能 WIP 全部保留。ai-writing-assist 被其他任务切至 main/0d555c463 并合入任务笔记索引（非本任务操作），本任务不提交/切换其分支，只更新自己的记录；out/ 保留。
- 最后核实：2026-10-02T08:29:53+09:00；主项目其他线程新增backend/tests/prompt_contracts/test_capability_bindings.py改动已保留。

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
- [x] 第3轮：候选版本、失效、幂等保存与历史保护；4 store tests/7 workflow tests通过。
- [x] 第4轮：对抗输入、协议与跨入口回归；官方mcp2.2.0/jsonschema4.26.0对17工具实际调用并按schema验证，14prompts/2resources通过。
- [x] 第5轮：独立包验收、发布扫描、发布与远端核实；最终CI36940839634 Linux/macOS均completed-success，全部四个下载附件逐字节及SHA256核对一致。

## 决策、发现与失败

- 复用已公开通用库，不复制整个数据库应用；为 NovelCraft 全部领域能力建立迁移清单，分别以计算工具、写作模式、宿主责任/排除方式交付。
- 工具库 origin/main 落后本地两次已提交升级；隔离分支先 fast-forward 到本地已提交基线，不纳入未提交技能修改。
- goal 已由 /goal 平台建立；重复 create_goal 返回 unfinished goal，get_goal 核实当前目标一致，无需另建。
- 第五轮CI36940409930失败暴露Ruby3.3对旧YAML.safe_load位置参数不兼容；修复共同keyword调用，保留Date白名单/aliases=false，新增对象标签与alias拒绝回归。84ad6ce对应CI36940839634两平台全部成功，旧预验收包保留在dist/preflight-e7b061f，不发布失败SHA。

## 验证证据

- `make docs-check`：通过（12 modules / 143 ORM tables / 55 task handlers），2026-10-02；NovelCraft 未修改业务代码。
- Toolkit 基线：Ruby engine9/Worldcheck15/Python server8/adapter6全部通过；第二轮新增6来源失败路径测试通过。详细五轮证据保存在工具库 `docs/iterations-0.8.0.md`，公开内容只含合成验证结论。
- 最终本地与独立解包：58 tests（25核心Python、7adapter、9Ruby engine、17Worldcheck），Ruby124 assertions；官方SDK2.2.0/jsonschema4.26.0全部17工具与prompt/resource/receipt路径通过；Ruff py310和NovelCraft收尾文档门禁通过。
- 包位置：`/Users/tywww/plugins/worldbuilding-engine-mcp-v080/dist/v0.8.0/`，固定提交84ad6ce；ZIP/TAR55个文件均与manifest SHA256匹配，私有路径/真实项目名称/密钥/候选数据库扫描无命中。RIGHTS保持原样。公开证据中的私有作品名已去除，发布扫描未放宽。
- CI： https://github.com/FengHuoLinShan/worldbuilding-engine/actions/runs/36940839634；明确核实两job completed/success与Official SDK step success，source SHA与tag一致。
- 发布：2026-10-02T08:29:15+09:00，public/non-draft/non-prerelease；ZIP/TAR.GZ/release-manifest.json/SHA256SUMS四附件远端下载均与本地字节相同，三内容文件SHA256全部匹配。

## 交付结果

- 已交付：通用MCP17工具/14提示词/2资源、跨领域迁移清单、源绑定与知识边界、候选版本/CAS/幂等/历史、变更闭包、安全与协议修复、安装配置生成器、五轮证据和公开v0.8.0四附件。
- 未交付：无本目标必需项；真实稿件模型质量、作者采用、Windows实机与生产部署不在本次工程验收内。
- 交付边界：工具库隔离分支七提交（五轮、脱敏和跨Ruby修复）及固定tag已发布；主分支未合并、原源库七文件WIP保持，主项目只更新自己的任务记录/索引，不提交或触碰其他线程修改；未部署或重装插件。

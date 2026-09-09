---
id: T-20260909-persistent-task-memory
title: 全局与项目持久任务记忆协议
status: completed
created: 2026-09-09T21:06:42+08:00
updated: 2026-09-09T21:08:16+08:00
---

# 全局与项目持久任务记忆协议

## 恢复快照

- 实际完成：全局文件已备份并追加规则；项目入口、协议、模板与文档索引已写入。
- 当前里程碑：本地交付完成。
- 下一步：无待执行工作；若用户要求提交或集成，先核对本工作区 diff 与当前远端，再按项目门禁办理。
- 阻塞：无。
- 工作区：`/Users/tywww/Desktop/项目/ai-writing-assist-task-memory`，分支 `codex/persistent-task-memory`，基线
  `18286c4c0`；本任务仅修改 AGENTS.md、docs/README.md 和 .agent/。原工作区
  `ai-writing-assist` 的 `codex/world-review-phase4` 业务 WIP 不属于本任务。
- 最后核实：2026-09-09T21:08:16+08:00。

## 目标与验收

- 目标：落地用户已批准的全局触发规则、项目持久任务协议、内嵌模板与开放任务索引。
- 完成条件：两份全局文件保留原规则且新增段落一致；项目入口按需发现协议；模板能说明目标、
  实际状态、证据和下一步；六个场景走查及文档/空白门禁完成。交付止于本地文件。
- 非目标：业务代码/API/schema/运行时改动、ADR、脚本/hooks、迁移历史计划、提交推送合并部署。

## 上下文与边界

- 来源：用户引用“全局记录约束”最后回复，并批准本任务的 proposed_plan，要求实施。
- 路径：根 AGENTS.md、CLAUDE.md、docs/README.md；协议见 ../../../PLANS.md。
- 全局路径：`~/.codex/AGENTS.md`、`~/.claude/CLAUDE.md`。
- 备份：`~/.codex/backups/persistent-task-memory-20260909-210443/`，两个原文件均保留。
- 约束与授权：仅开发协作文档，保留 Claude 专属模型分工及项目安全/隔离/交付规则。
- 依赖：现有文档检查脚本与 Git。平台记忆不在本次写入范围。
- 已确认：基线文档门禁通过；没有 .agent/；NOTES.md/DECISIONS.md 是已有专题资料，保留并按需引用。
- 假设与待决问题：无。

## 里程碑与进度

- [x] 核对全局与项目规则、现有 WIP、远端及基线门禁，创建独立工作区。
- [x] 写入全局段落、项目入口、中文协议与内嵌模板、索引及本记录。
- [x] 完成差异审查、门禁和六个场景走查，关闭记录。

## 决策、发现与失败

- 2026-09-09：索引只维护 ID、标题与链接，避免状态与日期双写；任务目录关闭后保持原位。
- 2026-09-09：不迁移旧计划；工作区副本须指向唯一主笔记，不能自行把 Git 副本当成最新状态。
- 文档影响：仅开发工具的任务工作记忆，不新增产品运行时 Agent、存储、队列、API 或数据库表。

## 验证证据

- 基线 `make docs-check`：通过；8 业务模块、109 ORM 表、40 handler、15 前端 route、29 ADR。
- 最终检查时间：2026-09-09T21:08:16+08:00；基于 `18286c4c0` 加本任务未提交文档。
- `make docs-check BASE_REF=origin/main`：首次要求复核四份工程文档；逐项核对后使用同一脚本
  `python3 scripts/check_architecture_docs.py --base-ref origin/main --no-change-reason '<下述理由>'`
  通过。不是未经说明的原始 make 命令通过。
- 无影响理由：development-guide.md 的命令与模块边界不变；testing-guide.md 的测试层级、Review
  和门禁不变；docs/architecture/README.md 的产品拓扑与图源不变；
  docs/architecture/documentation-maintenance.md 的影响矩阵与流程不变。协议仅涉及开发工具
  工作记忆，无业务 API、schema、数据、安全或运行时变化；日后 PR 应携带此核对说明。
- `git diff --check` 通过；临时 Python 检查覆盖新文件空白、链接、未被 Git 忽略、全局新增内容
  一致、备份原文完整保留、项目原规则完整保留及 CLAUDE.md 不变，全部通过；未增加测试框架。
- 六个场景人工协议走查（规则审查，不是新模型会话行为验证）：
  1. 小修：修正文档拼写不触发；第 1 节明确排除，入口不要求全量加载。
  2. 首次创建：本任务完成查重、稳定目录创建、模板填写与索引登记，实际文件验证通过。
  3. 已有任务恢复：索引及目录均可定位本 TASK.md；不依赖对话即可获知目标、工作区、证据和下一步。
  4. 快照过期：工作树或分支与记录不符时，第 3 节要求核对、纠正并保留 WIP，不直接执行旧下一步。
  5. 只读无法保存：全局与第 1 节一致要求输出可复制快照并声明未保存，不以记录要求覆盖写入限制。
  6. 未验收不能关闭：第 4 节禁止将未验收工作拆出后冒充完成；本任务验收后才关闭并移除索引。
- 未验证：新 Codex/Claude 会话实际加载及模型长期遵循；文档指令不提供确定性执行保障。

## 交付结果

- 已交付：两份全局追加规则、项目短入口、中文协议与内嵌模板、开放索引、文档导航及本任务记录。
- 未交付：无计划内缺项；实际新会话行为验证不在本次文档走查范围。
- 交付边界：本地文件未提交，未推送、未合并、未触发 CI 或部署。
- 正式知识与后续任务：协议为 .agent/PLANS.md；无后续任务。

### 已验证文件版本

- `AGENTS.md`：SHA-256 `6ae9ccff83f285cc52cf16871da255dbe70630e93358e63bbec5a7c52f89bbc3`。
- `docs/README.md`：SHA-256 `d478b75c09d30aee3fd71ac8b88b6aef5e7f59c90c9e02dfefff5321b1648f7c`。
- `.agent/PLANS.md`：SHA-256 `2acb2cc43d8fbf5e19547a5dde762a61a481fbe438dadecd5075b46d0ddd06a2`。
- `/Users/tywww/.codex/AGENTS.md`：SHA-256 `a4d1a78c10adb48f93450bb9885b44f30294bd6e32b2a6dd8ddbb52ce931be2b`。
- `/Users/tywww/.claude/CLAUDE.md`：SHA-256 `6d7713ac54b35898276f74088dc471402d7c454febbe9f4b57bf59e75400ac5f`。

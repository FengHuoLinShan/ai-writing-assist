# 全部实现审查

审查时间：2026-10-18 23:26（Asia/Shanghai）。固定基线：`98598127f933782f26019ca0e9970c53849c2a97`。
范围：当前工作树相对 HEAD 的已跟踪变更及全部新增实现，按 [HANDOFF.md](HANDOFF.md) 六批要求追踪调用链。
本轮仅审查，未修改业务代码、配置或业务数据库，未调用真实模型、提交、推送或部署。

结论：确认 **7 项新增 P2 缺陷**，建议整改后再合并。没有将风格偏好、缺乏具体触发的疑点或已证明的 PostgreSQL 基线失败计入发现。
此前 [ACCEPTANCE.md](ACCEPTANCE.md) 保存的是当时验证结果，不能覆盖本次新复现的失败；任务据此重新打开。

## Standards：4 项调用链与契约缺陷

### R1 · P2 · 暂停恢复使任务自动批准失效

- 位置：`backend/modules/assistant/goal_runs/service.py:2566`、`:4260`；判定入口 `backend/modules/assistant/approval.py:373`。
- 触发：作者审批计划并开启自动修改，在授权未过期时暂停，再使用完全相同预算恢复。
- 原因：首次 `approved_scope` 加入 `approval`；`resume_goal()` 重新调用 `plan_scope()` 时遗漏该字段，并未同步 grant 的范围指纹。恢复后的指纹必然不同。
- 结果：后续每步返回“任务授权已过期或范围已变化”，自动模式实际降为逐项人工确认；增加预算也会遇到授权未同步的问题。
- 最小修复：恢复时保留原批准模式和完整范围；显式预算续批须同步授权版本或要求明确重新批准，不能放宽指纹检查。
- 依据：HANDOFF §4.2、§5 的授权生命周期及恢复契约；AGENTS 的调用方同步要求。

### R2 · P2 · Goal 目标映射遗漏已注册类型与创建产物引用

- 位置：`backend/modules/assistant/approval.py:128`–`:141`、`:157`–`:162`。
- 触发：合法计划只包含给两个已有对象添加关系，目标类型按实际目录声明为 `world_entity_pair`。
- 原因：`goal_targets()` 只识别实体、关系和正文草稿类型，忽略 `world_entity_pair`；`writing.restore_version` 的实际 `writing_chapter` 类型也未覆盖。
- 结果：有效关系计划的授权目标是空集合，`create_grant()` 直接拒绝；混合计划中对应步骤也无法自动批准。
- 同处缺口：已批准创建槽的后续显式 `$ref` 被跳过，读回真实产物后得到的实体 ID 不属于 grant，创建后完善对象同样停在“超出冻结目标”。
- 最小修复：按注册操作的实际目标类型归一化；引用仅绑定本计划已授权创建槽的真实领域回执及明确依赖，继续执行归属和版本重验，不能接受任意新 ID。
- 依据：HANDOFF §5 的新建后读回真实身份并按当前模式批准；ADR-0038 对已批准步骤产物的范围约定。

### R3 · P2 · 全局 source_id 校验破坏已有提醒计划

- 位置：`backend/modules/assistant/goal_runs/service.py:690`，消费者 `_check_step_targets()`。
- 触发：已注册的 `assistant.notice.mute_category` 计划使用 `source_id="assistant.proactive"` 和 `category="review"`，无需具体实体目标。
- 原因：为 World 关系新增的 `source_id` 被加入所有操作通用的目标字段集合；提醒来源类别被误当作实体身份。
- 结果：此前合法的计划被“每个操作对象都必须列在计划卡的目标范围中”拒绝。固定 HEAD 的字段集接受相同参数，实际提醒领域 prepare/apply 也能落下 `is_muted=true` 回执。
- 最小修复：只对需要实体来源的关系操作检查 `source_id`，保留提醒操作既有来源类别语义。
- 依据：AGENTS 要求共享逻辑改动同步全部调用方、保持稳定接口；HANDOFF §6 的兼容要求。

### R4 · P2 · 关系恢复返回成功但未恢复空说明

- 位置：`backend/modules/world/relation_changes.py:215`–`:227`；调用的 `backend/modules/world/repositories.py:1833`–`:1835` 忽略所有 `None` 字段。
- 触发：关系原说明为 `null`，作者补入说明，再选择恢复该修改前快照；显式修改为 `description:null` 也能触发。
- 原因：新维护链把 `None` 作为待写差异交给旧更新协议，而旧协议用 `None` 表示“不改该字段”。
- 结果：预览和历史 `after.description=null`，回执 `completed/changed=true`，数据库却仍保留后加说明。界面“已恢复”与事实不符。
- 最小修复：在领域更新链明确区分未提供字段和显式清空；保存后以真实落地状态生成快照与回执，覆盖恢复原空值测试。
- 依据：HANDOFF §3.2、批次4 的关系恢复和真实回执要求；AGENTS 的持久化成功反馈约束。

## Spec：3 项草稿与修订闭环缺陷

### R5 · P2 · 档案保存成功后忽略另一页面的新草稿

- 位置：`frontend-console/vue/views/world/library/WorldObjectDossierEditor.vue:875`–`:881`。
- 触发：A 页面提交新增档案并等待响应；B 页面写入同对象的新本机草稿并关闭；随后 A 的保存成功。
- 原因：CAS 清理正确返回 `{ok:true, changed:true}`，但代码先进入 `if (cleared.ok)`，因此下面恢复新草稿的分支永远不可达。
- 结果：A 显示空表单，不提示或恢复 B 的输入；A 随后的正常输入覆盖同一备份键，B 尚未显示的文字丢失。双组件共享 localStorage 已复现。
- 最小修复：先处理 `changed`，恢复并保留新备份，再处理普通清理成功。
- 依据：HANDOFF §3.2“冲突保留双方内容”及 §7 迟到响应保护。

### R6 · P2 · 撤回修改后，旧中间草稿再次恢复

- 位置：`frontend-console/vue/views/world/library/WorldEntityDetail.vue:311`–`:313`；同根因在 `WorldObjectDossierEditor.vue:399`–`:402` 及编辑草稿 watcher。
- 触发：将字段改成 A，再撤回到服务器原值；此时 dirty=false，离开后重新进入编辑。
- 原因：只在 dirty 时备份，没有在 dirty→clean 时同步或清理旧备份。
- 结果：被作者撤回的 A 被自动恢复；基本资料和已有档案两条真实组件路径均复现。作者可能误把已放弃文字再次保存到作品。
- 最小修复：回到干净状态时用现有 CAS 清理或更新空差异；不能清掉另一页面较新的副本。
- 依据：HANDOFF §3.2 本机草稿与恢复版本要求、§7 输入保护。

### R7 · P2 · 修改组任务终态后无法重新选择或显式重试

- 位置：`frontend-console/vue/views/writing/components/WritingRevisionGroups.vue:8`–`:18`；本机 task 恢复位于同文件 `:97`–`:101`。
- 触发：首次选组任务失败，或正常完成后作者回到原候选希望另选组合。
- 原因：任何非空 `task` 都禁用选项并隐藏提交按钮；任务终态也没有清理/重新准备入口，父组件没有替代路径。
- 结果：只剩反复查询原任务；刷新后从备份恢复同一永久锁，失败无法主动重新准备，成功后也无法调整原候选组合。
- 最小修复：确定终态后提供明确“重新选择/重新准备”，保留原回执、重新读取预览，下一次作者主动提交才创建新 operation ID；在途和未知请求继续锁定。
- 依据：HANDOFF §3.1 改变选择及重新审查、批次4修订闭环、§7 失败恢复要求。

## 验证与复现

- 现有四组针对性后端测试：`test_assistant_focus.py`、`test_relation_changes.py`、`test_review_scope.py`、`test_candidate_selection.py`，**14 passed**。日志：`/tmp/author-workspaces-review/targeted-backend.log`。
- R1–R3：`PYTHONPATH=backend backend/.venv/bin/python /tmp/author-workspaces-standards-review-repro.py`，四个确定性断言场景全部证实当前错误行为，包括创建引用和固定 HEAD 的提醒校验对照。日志：`/tmp/author-workspaces-review/goal-contracts.log`。仅内存 SQLite、合成账户/项目和提醒数据。
- R4：在 `backend` 执行 `./.venv/bin/python -m pytest --noconftest -p conftest -c pyproject.toml /tmp/author-workspaces-review/test_relation_receipts.py -q --tb=short`，**2 failed**，均为预览/回执与真实持久化值不符。日志：`/tmp/author-workspaces-review/relation-receipts.log`；使用现有内存 SQLite fixture。
- R5–R7：在 `frontend-console` 执行 `node node_modules/vitest/vitest.mjs run --config /tmp/author-workspaces-review-spec.config.mjs`，真实 Vue SFC 与合成 API，**5 failed**：两种字段撤回、双页面迟到保存、失败任务和完成任务。日志：`/tmp/author-workspaces-review-spec-reproduction-final.log`。早期 CAS 断言已校正，最终仅要求保存后展示 B 的草稿；之后输入覆盖未展示草稿只作为现状证据。

以上红色用例是审查发现，不是既有全套测试结果。本轮未重跑完整 PostgreSQL、跨设备浏览器或真实模型；未读取原 Guimi 稿件或写入共享库。未发现新权限绕过不等于安全全覆盖。

上方为原始审查快照；用户随后要求“修复”，整改状态与新证据见下方。

## R1–R7 整改完成（2026-10-19）

- R1：恢复保留完整批准范围；仅显式预算变化更新 grant 版本和指纹，原有效期、累计判断次数与根账本不重置，旧批准失效。撤回、过期和 pending 判断不恢复。另修复保存时重新合回已消费暂停标记的问题：只清除作者核对的同一 revision，新暂停或取消仍保留。
- R2：覆盖实际目录的 `world_entity_pair` 与恢复正文使用的 `writing_chapter` 草稿身份。创建引用仅绑定明确依赖、已完成、原步骤指纹匹配的 `world_entity` 领域回执，并映射回原创建槽；错误身份/类型/路径/版本/未完成项均不绑定。计划追踪保留已验证但尚未解析的引用，实际执行仍先解析并校验操作 schema。
- R3：`source_id` 的对象身份检查只用于 `world.add_relation`，提醒来源类别沿用原契约；关系来源与关系 ID 仍不能隐藏在计划目标之外。
- R4：关系仓库以 `model_fields_set` 区分未传说明与显式 `null`，清空及恢复原空值真实落地；历史、预览、回执和独立会话读回一致。
- R5：新增档案迟到保存先处理 CAS 的 `changed`，恢复并展示另一页面的新草稿，再处理普通清理成功；下一次输入基于已展示内容。
- R6：基本资料和档案编辑撤回到保存值时按原草稿版本清理差异，清理失败明示，另一页面的新副本保留并可重新恢复。
- R7：服务端核验 done/failed/cancelled 且无未知费用或待恢复回执后显示“重新选择修改组”。显式重读差异，保留原回执；作者再次提交才生成新 operation ID。在途/未知仍锁定，刷新须重新核验，迟到轮询不能覆盖新提交。

已验证：

- 49 项针对性后端通过，`/tmp/author-workspaces-review/fix-backend-targeted.log`；包括真实目录/领域写入、暂停同预算和续批、撤回、累计次数、过期/pending/范围扩张拒绝、创建引用正反例、关系空值恢复。
- 24 项真实 PostgreSQL 通过，`/tmp/author-workspaces-review/fix-pg-targeted-final.log`；授权续批/撤回与真实写入的两种事务顺序、关系并发及空值恢复、暂停续跑、Goal HTTP/故事/恢复链。首轮新增测试把内部提交服务包在显式事务 context 内导致 2 例测试用法错误，已修测试事务边界后全部通过，未改领域事务保护。
- 助手浏览器 4 项通过（52.4s），`/tmp/author-workspaces-fix-reselect-browser.log`；1280/390 完成后刷新、另选组合、新操作身份、保留旧回执、重审采用与继续手改；另含代批执行和判断中撤回。
- 世界浏览器 4 项通过（26.8s），`/tmp/author-workspaces-fix-world-drafts-browser.log`；两个宽度的基本资料/档案撤回后刷新、草稿恢复及关系维护/恢复。
- 最终完整快速后端 **9291 passed / 2 skipped**，覆盖率 **85.32%**（门槛 85%），`/tmp/author-workspaces-review/fix-backend-full-final.log`；完整前端 **267 文件 / 3318 passed**，`fix-frontend-full.log`。前端全量 ESLint、后端全量 Ruff lint、修复文件 format、`git diff --check` 通过；全仓 format 历史基线单列。
- 最终 PG critical **105 passed / 3 failed**，`/tmp/author-workspaces-review/fix-pg-critical-final.log`。三项均为此前干净 HEAD 同样复现的 Project task gate 两项超时与 task coalescing 一项 follower 身份失败，不记为全量通过；见 [ENGINEERING-BASELINE.md](ENGINEERING-BASELINE.md)。

扩大门禁同时补齐本任务原实现遗漏：新能力 `assistant.approval.judge` 的精确清单，4 个路由的显式 active-project guard，5 个路由的具体操作边界说明，以及判断/校准两处固定 1024-token 输出预算的窄静态契约（不接受其他显式上限）。所有路由仍重验 owner/项目/版本/确认，不修改旧未登记基线、不放开判断或写入范围；治理 31 项通过。清单缺失的 `novel_id` 索引以增量迁移 `20261018_review_scope_index` 补齐，两套专用测试库已升级，空库升级和 ORM parity 失败消除。

首次完整 `make test-ci` 在 324 项部署契约通过后发现上述 4 项治理遗漏，未运行到前端；修正后分别重跑完整快速后端和前端、lint 与文档门禁，不把首次整条命令改记为成功。Ruff format 的 167 个剩余失败全部属于干净 HEAD 的失败集合，新增失败为空，未批量格式化无关文件。

最终 `make lint docs-check BASE_REF=origin/main` 与 `git diff --check` 通过，日志
`/tmp/author-workspaces-review/fix-docs-final.log`。本轮修复已关闭；原有基线失败、真实作者/文学质量及发布边界不随本地收口消失。

以上使用本任务已授权的确切隔离容器与合成资料；未调用真实模型、未触碰原 Guimi/G7b 库、未提交/推送/合并/部署。

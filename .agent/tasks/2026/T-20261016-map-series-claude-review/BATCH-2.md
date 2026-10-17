# 第 2 批：M1 演化可选步骤与空间发现

审查基线：`codex/map-enhancement-plan` @ `a479e006b`（merge-base `00d861283` = origin/main）。
规格：ADR-0036、`docs/plans/2026-10-15-map-system-enhancement.md` §M1/M2 的补扫部分。

## 结论

可选步骤的根预算、主理解保留额、journal 先落库再发请求、结果未知不重发、服务端来源与类型重验
都符合 ADR-0036，未发现安全、`novel_id` 隔离或重复计费的发送路径问题。发现 4 个 P2 与 2 个 P3：
可选阶段可能永久卡住、空间线索在两条路径上被错误拒绝或打回、补扫会重复计划已检查的 Scene、
密度预检几乎不生效、涌现中类型可能永远无法转正。6 项都写了 strict xfail 回归测试，其中 5 项
已用测试复现，B2-F3 只验证了上下文缺口，未用真实模型验证后果。第 1 批 Q1 已关闭。

## 已审范围

- ADR-0036 全文。
- `backend/modules/evolution/`：`optional_steps.py`、`optional_step_budget.py`、`optional_scene.py`、
  `spatial.py`（全文）、`spatial_rescan.py`（全文）、`assistant_tools.py`、`map_assistant_read_service.py`；
  `tasks.py` 的 diff 与错误分类；`workflow.py` 的 append/continue/recompute/advance/reading_status/
  resume、空间授权与 `_optional_coverage_summary`；`pipeline.py` 的可选步骤与补扫额度扣减；
  `store.invalidate_sources`、`invalidation.py`、`consumption.py` 的 diff。
- `backend/modules/world/map_spatial_clue_service.py`（全文）、`map_spatial_clue_api.py`。
- 未审、转入后续批次：`reading_notice_sources.py`、`evidence_read.py`、`completed_read_chapters.py`
  （第 4/6 批）、`map_evaluation_read_service.py`（第 9 批）。

## 确认无问题

- 可选步骤只在主回执提交后运行；journal 先提交再做 provider I/O；结果未知时阻止重发，取消也记为
  需核清；`optional_quotas` 单步总计上限 1000。
- 补扫额度：发送前在持锁的 run 上扣 `calls_remaining`，并检查扣后仍不低于主理解保留额；预览与
  确认用同一指纹绑定请求、owner epoch、head、预算、模型、方法与来源；重放同一 operation_id 时
  比对请求 hash。
- `_exact_source_hash` 与 `"".join(texts)` 的偏移一致；服务端重验来源绑定、端点、类型修订、复核
  hash 与证据 hash。
- 同名涌现中类型在上下文中时沿用原 `proposal_run_id` 并带全部历史证据；复核失败不会把 active
  类型降级（Q1 关闭）。
- append、补扫遇到待完成的可选阶段会拒绝；方法指纹变化时 append/continue 拒绝静默升级。
- 线索 API：读经 `require_active_project`（浏览器调用带 owner 过滤），写在服务内经
  `require_active_project_exclusive(nowait=True)` 加排他锁并拒演示项目。
- 失效回执对自动草图分别核对 working 与 canonical 来源并合并计数，未核对完整时在覆盖说明中提示。
- 助手 `evolution.prepare_spatial_rescan` 只生成预览，确认时重算预览并比对，不启动运行；元数据在
  `app/assistant_operation_metadata.py` 集中登记为 R4、`discard_preview`。

## 发现

### B2-F1（P2）主回执提交后作者编辑 Scene 卡片，可选阶段永久停在 running

- 位置：`backend/modules/evolution/optional_scene.py:135` `verify_optional_source` 比对 Scene 卡片
  hash，抛 `CommitConflictError("scene_changed")`；`backend/modules/evolution/tasks.py:149-155` 把
  `scene_changed` 判为不可恢复。
- 问题：Scene 卡片编辑（如改标题）不触发 `invalidate_sources`（只有正文变化与 Scene 重排触发），
  运行仍是 active。`load_pending_optional_stage` 一直返回该阶段，于是 append 被拒（“请先完成或恢复
  当前 Scene 的可选阶段”）、补扫被拒、`advance_reading` 只返回原任务，运行到不了 completed，
  `can_resume` 为 False。唯一出路是付费的 `scoped_recompute` 重跑主理解。
- 复现：临时测试在可选 provider 调用期间改 Scene 标题，任务抛 scene_changed；重试再次抛出，
  provider 调用计数仍为 1（未重复计费），阶段仍待完成。
- 建议方向：主回执已提交时把该可选步骤落为 `stale` 缺口并结束阶段，由空间补扫补齐；同时更新
  `test_optional_scene.py::test_optional_result_revalidates_after_main_commit[scene]`（当前断言
  status == "running"）。

### B2-F4（P2）超出上下文的涌现中类型被再次提议时，整条线索被拒

- 位置：`backend/modules/world/map_spatial_clue_service.py:1164-1185` 类型召回排序键为（被已选线索
  引用、名称命中端点表面词、`status` 字符串、kind、name），截断到 `SPATIAL_TYPE_LIMIT=32`
  （`spatial.py:41`）；`_validate_type_proposal`（608 起，673 抛错）；`stage_spatial_discovery`
  在 893 行把整条线索记为 `clue_invalid`。
- 问题：排序不看类型名是否出现在正文；`status` 按字符串升序时 emerging 排在 active、archived
  之后，作者启用的预设和已有类型足以把涌现中类型挤出上下文。模型看不到它，就把同名类型当新草案
  提议，服务端因 `proposal_run_id` 不同抛 “Type proposal does not bind the original proposal run”，
  整条线索被拒。而类型在上下文中但不可用时（墓碑、歧义），实现只去掉类型、保留线索，两种口径不一致。
- 复现：两个 Scene 先后提议同名“潮汐暗道”关系类型，第二个 Scene 的线索整条进入 rejected。
- 附带观察：每个类型的每条证据都调用一次 `_evidence_is_current`，类型多时查询次数大。
- 建议方向：同名已存在、不在上下文时只丢弃类型提议（或改为附着已有类型并追加证据），保留线索；
  召回时提高正文命中类型的优先级。

### B2-F5（P2）作者先在 World 采用地点，再采用线索，线索被打回且无法恢复

- 位置：`backend/modules/world/map_spatial_clue_service.py:1307-1316` `review_spatial_clue` 调用
  `_revalidate_stored_clue`，默认 `allow_identity_transitions=False`（483-563；只有 auto_draft 与
  `map_notification_service` 传 True）。
- 问题：候选地点被作者采用后变为 canonical，重验把 candidate→canonical 视为身份变化，线索被改为
  `pending_verification`，并给出误导性提示“原文或场景边界已经变化，请重新提取并核查。”。之后
  “待核线索不能直接采用”，也没有任何路径回到 `pending_review`。
- 复现：`_stage_bound_clue(entity_status="candidate")` 后把两端改为 canonical，再 `_adopt_clue`，
  结果为 `pending_verification`。
- 第二个触发条件（按代码推导，未复现）：作者编辑类型产生新修订后，重验要求
  `current_revision_id == revision_id`，同样打回。
- 建议方向：作者采用路径允许 candidate→canonical 与同一类型的新修订，或提供重新核查回到
  `pending_review` 的路径。

### B2-F6（P2）空间补扫不承认已完成的补扫，已检查的 Scene 会被重新计划、计费

- 位置：`backend/modules/evolution/spatial_rescan.py:224-243` `_plan` 只读原回执
  （`load_frozen(receipt.run_key, receipt.attempt_key)`）判断是否“已按当前方法完整检查”；补扫结果
  写在独立的补扫 frozen attempt 上，从不回写原回执。进度汇总
  `backend/modules/evolution/workflow.py:1303-1308` 却读取补扫 attempt，把该 Scene 显示为 inspected。
- 问题：ADR-0036 §1 规定补扫只针对“没有做过某步骤，或方法版本较旧的部分”，契约测试要求“补扫
  幂等”。对旧运行补扫成功后，再预览同一范围不会报“所选范围已按当前空间方法完整检查”，而是每个
  Scene 重新计 2 次调用。范围只能连续选择，已补扫与未补扫 Scene 交错时，作者无法避开重复付费。
- 复现：回归测试构造原回执无空间结果、补扫 attempt 已按当前方法 inspected 且无缺口，`_plan` 未抛
  ConflictError，仍计划该 Scene。
- 附带观察：汇总按 operation 顺序用补扫 attempt 覆盖，后一次补扫中断时，其未完成 attempt 会把
  前一次成功结果显示成 not_checked。
- 建议方向：`_plan` 与汇总用同一“该 Scene 最新的已完成空间结果”解析（原回执与已完成补扫 attempt
  取最新完成者）。

### B2-F2（P3）密度预检的单字词表几乎总命中，零命中跳过形同虚设

- 位置：`backend/modules/evolution/spatial.py:44-45` `SPATIAL_DENSITY_THRESHOLD = 1`，
  `SPATIAL_DENSITY_TERMS` 含单字“东/西/南/北/山/河/楼”等；874 行按阈值跳过。
- 问题：“东西”“北京烤鸭”这类普通词即命中，`_density_hits("他把东西放下…")` 计数为 2，零命中跳过
  几乎不会发生，可选步骤在非空间 Scene 上照常发两次请求。只影响成本，不影响正确性。
- 建议方向：单字词改为带上下文的模式（方位词 + 方位后缀、地名后缀），并补“普通词不计入”的用例。

### B2-F3（P3）涌现中类型复核要求引用当前证据下标，复核上下文却没列出当前证据

- 位置：`backend/modules/evolution/spatial.py:541-548` 要求 `reviewed_evidence_indices` 恰好覆盖
  `range(len(prior) + 1)`，当前证据排在最后；`SPATIAL_REVIEW_PROMPT`（168 起）与
  `_type_review_context`（411 起）的 evidence 只列历史证据。
- 问题：模型不知道当前引文的下标，按提示只会列出已给出的下标，复核在服务端失败关闭，涌现中类型
  可能永远无法转正。未用真实模型验证。
- 建议方向：把当前引文作为最后一条 evidence 列入复核上下文，或在提示中写明当前证据下标。

## 转入后续批次的疑点

- Q2（第 3/4 批）：沿用 BATCH-1.md 的记录。
- 补扫运行期间 append 不检查进行中的补扫。append 推进 head 后，补扫的下一次发送会在
  `pipeline.py` 预约时报 `parent_advanced`，补扫失败；恢复仍绑定旧 head，会再次失败，只能重新预览
  补扫。失败关闭、不重复发送，所以只记为观察；第 5 批核对前端是否在补扫运行时禁用 append。
- `map_spatial_clue_service` 的 `ValidationError` 消息为英文，会经 `str(error)` 进入 gaps 的 detail；
  第 5 批核对前端是否直接显示。

## 回归测试

每个发现一条 `pytest.mark.xfail(strict=True)` 测试，按规格写正确行为，不改生产代码。修复后测试会
意外通过并让测试失败，提醒移除标记，转为普通回归测试。

- `backend/modules/world/tests/test_map_series_review_regressions.py`：F1、F2（第 1 批）、B2-F4、B2-F5。
- `backend/modules/evolution/tests/test_map_series_review_regressions.py`：B2-F1、B2-F2、B2-F3、B2-F6。
- 验证：两个文件正常模式 `8 xfailed`；加 `--runxfail` 时 8 条都在各自断言处失败，原因与编号一致。

# WORLD / Evolution / Evidence 复审

本补丁将词表合并重定向、空间线索与草图状态、原确认引用，以及 CoreEntity 旧文本和对象档案接到共同调用链。本轮确认 **4 项 P2**：三项档案同步残缺，一项旧词条修订只在采用入口兼容、后续地图消费仍拒绝。未确认 P1/P3；建议先修复这四项。

## 范围与方法

- 工作区：`map-series-review-fixes`，分支 `codex/map-series-review-fixes`，HEAD `3b2ac9441c0dc08533a3e62269cd054ff35c5302`；审查 `git diff HEAD`、未跟踪的档案测试及连接生产代码。原业务实现上下文为 `a479e006bc336c0009e5207f7659609ab483e901`。
- 已读根规则、World 局部规则、World/Evolution/Evidence 相关 README、原 SUMMARY 与 BATCH-1/2/3/4/6、修复 TASK；采用 `ponytail-review` 的具体场景、完整调用链、最小修法标准。
- 按 PostgreSQL、多 worker 与作者可能从多个页面顺序/交错操作的实际模型判断。下面四项在顺序请求中即可发生，不依赖竞争窗口或损坏数据。
- 本轮只读生产代码，唯一写入本报告；没有运行或新增测试，没有启动业务模型、真实数据库或封存评测。上一轮测试结果是交接资料，不作为本轮实测结果。

## P2

### WORLD-1：最新一组已清除时，实体接口清空仍保留另一组有效档案

**位置：** `backend/modules/world/dossier_service.py:2452-2453`。

**可发生场景：** 对同一 canonical 对象先后创建两个无锚 `public_info` 条目组 A、B；通过档案编辑清空 B。B 的最新修订状态是 `cleared`，A 仍为 `active`，CoreEntity 正确投影为 A。随后通过实体编辑清空公开信息。

**证据与影响：** `dossier_repository.py:143-163` 的 `latest_legacy_field` 按创建时间和修订号取整个字段的最新行，因此独立请求中清空 B 的修订是 `latest`；`list_active_legacy_field:123-129` 同时返回 A。`WorldEntityService.update:660-674` 先清空实体列再调用同步，但 helper 在 `latest.status == "cleared"` 时立即返回，尚未执行第 2454 行的 supersede。请求成功、实体列为空，档案和 Evidence 简报却继续返回 A；以后编辑剩余条目还能把内容投影回实体。它违反本轮 B6-F1 的双向同步目标。

**最小修法：** 只有不存在仍需清除的 `current_rows` 时才把最新 `cleared` 修订当作幂等完成；有 A 时继续将当前无锚组置为 superseded 并追加清除修订。

**已有覆盖的缺口：** 未跟踪的 `test_b6_core_entity_dossier_sync.py:116` 只通过档案入口逐组清空/恢复，没有覆盖“清空 B 后从实体入口清空整个字段”。这是静态调用链证明，本轮未执行复现。

### WORLD-2：最新档案带有效期时，普通实体编辑会撞同组 active 唯一约束

**位置：** `backend/modules/world/dossier_service.py:2425-2429,2454-2462`。

**可发生场景：** 先为 canonical 对象创建无锚 `public_info` 组 A，再通过档案 API 新建同一旧字段的组 B，并为 B 指定合法 Scene/Chapter 有效期。最后在实体面板修改公开信息为不同文本。

**证据与影响：** `create_entry:1873-1908` 分别校验 legacy 绑定和有效期，允许二者共存；B 是正常可创建的 `active` 条目。仓储的 active 查询只收无锚行（`dossier_repository.py:127-129`），所以 helper 只把 A 加入 `current_rows`；但 latest 查询没有锚过滤，取到较新的 B。helper 只 supersede A，却以 B 作为 previous、沿用 B 的 `entry_group_id` 再追加 `active` 修订，B 自身仍 active。`models/dossier.py:109-115` 的 `uq_world_dossier_active_group` 明确禁止同组两个 active，flush 必然失败，整个实体编辑回滚并返回服务端错误。创建时没有无锚 A 也一样可触发。

**最小修法：** 为 CoreEntity 兼容投影选取 latest 时使用与 `current_rows` 相同的无锚范围；没有该范围的历史就新建独立组。保留有有效期的 B 及其历史，不借兼容字段编辑覆盖 B 的时点语义。共享 `latest_legacy_field` 还有其他调用方，改查询时应限定此同步入口的语义。

**已有覆盖的缺口：** 新测试覆盖两组无锚条目与普通单组修订，没有带有效期的 legacy 条目接实体写入。这是静态约束证明，本轮未连接数据库验证。

### WORLD-3：表格补空撤销只恢复实体列，已同步的档案仍有效

**位置：** `backend/modules/world/services/worldbuilding/applied_change_reversal.py:195-200`；修复接入点为 `services/core/entity_service.py:662-674`。

**可发生场景：** 既有 canonical 地点的 `public_info` 为空。作者确认表格迁移，给它补入“城门夜间关闭”，随后按迁移回执执行撤销，中间没有其他编辑。

**证据与影响：** `author_migration.py:1140-1147` 经 `WorldEntityService.update` 补空，本次新增同步会创建 active 档案。但 `rollback_author_migration_world:1478` 调用共享 `reverse_applied_changes`，后者只对 `item["before"]` 做 `setattr`，并把回执标为 rolled_back，没有调用档案同步。CoreEntity 恢复 `None`，档案仍保存“城门夜间关闭”，继续进入档案阅读、导出和 Evidence 简报。作者看到撤销成功，生成资料却仍消费已撤销的内容。`focused_adoption.py:561` 也消费同一共享撤销实现；至少表格补空路径已完整证明可达。

**最小修法：** 在共享撤销循环中，对实际恢复的 CoreEntity 三个旧文本字段调用同一档案修订同步，保留现有事务、修订快照与 after/CAS 比对；`dry_run` 不写入。不能只补迁移外层，否则其他共享撤销调用方仍可能分叉。

**已有覆盖的缺口：** 新测试 `test_author_migration_fill_empty_syncs_the_dossier` 只验证 apply；未断言 rollback 后档案不再 active。本轮未运行测试。

### WORLD-4：旧词条修订的线索可采用，却无法生成、采用或放置地图草图

**位置：** `backend/modules/world/map_spatial_clue_service.py:586-598`；遗漏调用方 `map_auto_draft_service.py:320-327,2462` 和 `map_notification_service.py:98`。

**可发生场景：** 空间线索固定引用作者词条 A 的修订 1。作者正常改名或编辑 A，生成修订 2，身份、种类和 active 状态保持有效；然后采用这条旧线索并生成地图草图。或者先生成草图，再编辑词条后采用/放置它。

**证据与影响：** 本次 `review_spatial_clue:1340-1342` 传入 `allow_author_confirmed_transitions=True`，在历史精确修订仍属于同项目同词条时允许采用；新增回归 `test_b2_clue_keeps_its_pinned_type_after_author_revision` 只断言该采用成功。自动草图校验、托盘放置和地图通知仍只传 `allow_identity_transitions=True`，不会启用这个新类型规则；第 587 行因此抛出 `Clue type identity or revision changed`。构建将其送入 `source_stale` 托盘，已有候选列表被标 stale，采用被拒绝，托盘放置也拒绝。作者已经采用的合法线索无法到达地图成果，普通类型改名就能触发。

**最小修法：** 让这些生产消费方复用与线索采用相同的作者词条历史修订规则，或将该不变量收口到共享校验。仍须保留同作品、同词条、精确历史修订、种类及当前生命周期检查，不用当前词条内容静默替换原固定修订。

**已有覆盖的缺口：** 新回归截止在线索 `adopted`，没有继续调用实际草图构建/采用或托盘放置。这是静态参数和分支证明，本轮未运行复现。

## 原 finding 逐项复审覆盖

“未再发现阻断”只表示本轮补丁及连接代码静态复审结论，不表示真实用户、模型或生产验收。

| 原编号 | 本轮核对 | 结论 |
|---|---|---|
| F1 | 固定词条解析、同项目重定向链、最终目标 traits/current lifecycle；追踪地图结构、简报、提醒、Story 地图投影共同解析入口 | 未再发现阻断；原始固定显示和最终目标计算特性分开 |
| F2 | 助手 `_ensure_unique` 与服务端墓碑自身名称/别名的比对；忽略目标和重定向链条件 | 未再发现阻断 |
| B2-F1 | 主回执后的 source/card 分开校验、stale 收尾、未知 journal 保留、pending stage 恢复；正文/owner/父回执仍失败关闭 | 未再发现阻断；没有把未知请求重新发送 |
| B2-F2 | 密度词项及 `_density_hits` 实际消费 | 未再发现阻断；误命中的单字词已移除，真实模型发现质量未验 |
| B2-F3 | 复核输入中的当前引文/精确 hash、完整证据下标、`_make_clues` 历史+当前证据构造 | 未再发现阻断 |
| B2-F4 | draft/proposal 验证、重复原提案运行错误只撤可选类型、线索复核 hash 收窄及持久化 | 未再发现阻断 |
| B2-F5 | candidate→canonical 端点变化与自动草图的既有 identity transition；新增作者词条修订兼容 | 原端点采用场景已修；新增词条修订兼容仍有 WORLD-4 |
| B2-F6 | 最新已完成补扫选择、原 run/attempt/manifest/receipt 绑定、规划与覆盖汇总共用、新的未完成补扫不覆盖旧成功 | 未再发现阻断 |
| B3-F1 | 隐式范围状态过滤、显式重做剔除 rejected/superseded、空列表与 None 的不同含义 | 未再发现阻断；空显式列表不会扩大成全运行 |
| B3-F2 | `_ensure_location_nodes` 明确 adopted 优先及后续认领/层级路径 | 未再发现阻断 |
| B3-F3 | completed 批次按候选依赖局部 stale、running 批次全局阻止续跑、列表/采用校验 | 未再发现阻断 |
| B3-F4 | 自动构建和手动托盘放置仅由 effective_change 给地点赋区间；关系/行程保留自身区间 | 未再发现阻断 |
| B3-F5 | 助手结构编辑 v1→v2、preview/apply 与 MapDocument 校验 | 未再发现阻断 |
| B3-F6 | 行程必须有非空逐字 quote，随后仍逐条验证 reader 来源与端点/类型可见性 | 未再发现阻断 |
| B4-F1 | 文本途经点使用图元键接入通路图；图按当前地图/转移局部建立，未跨地图混接 | 未再发现阻断 |
| B4-F2 | 阅读提醒跳过 drained，仍保留有意的跨运行回查 | 未再发现阻断 |
| B4-F3 | 新引用携带 confirmation ID；重新物化同一确认；旧无凭据引用仅在原基线完全一致时返回正文 | 未再发现阻断；过期确认失败关闭 |
| B6-F1 | 三列创建/更新/采用、dedup 合并、实体修订恢复、Scene 回滚、表格 apply/rollback 与档案反向汇总 | **残缺修复：WORLD-1/2/3**；普通单组和无锚多组档案反向编辑路径已接通 |
| B6-F2 | CoreEntity 三旧面向对所有类型的登记、legacy 键/内容/秘密可见性限制、interchange 同项目/跨类型目标映射 | 映射缺陷已修；新同步路径的 WORLD-1/2 属 B6-F1，不重复计数 |
| B6-F3 | 截止点选历史 claim/evidence，当前 `author_decision_json` 拒绝/更正优先，仍保留 identity/freshness/source range 重验 | 未再发现阻断 |

## 已排除的疑点与边界

- `redo` 剔除全部已结束线索后传的是显式 `[]`；`_load_build_rows` 仅在 `None` 时加载隐式全运行，所以没有确认“空重做扩大范围”的疑点。
- 提醒图中新增 `feature:<id>` 键在每个地图的当前转移内创建，不是跨地图共享图；没有确认图元 ID 碰撞导致跨地图连接。
- 新增历史词条兼容仍验证同作品同词条的精确 revision，档案写入也沿用实体锁与事务；未确认跨 `novel_id` 泄漏或 owner 绕过。WORLD-2 是约束阻止写入并回滚，不是约束被绕过。
- 阅读与空间补扫互斥的后端门槛线索已交 ASSISTANT 组继续核验，避免重复计数；本报告不判定其最终发现。

## 未覆盖与验证限制

本轮没有重审原系列全部 805 个文件。Story 导演/世界推进、Assistant 目标运行和剩余前端由另两组负责；本组补读它们的接口片段仅为验证 World/Evolution/Evidence 调用链。没有新增可量化的性能结论，也没有独立复跑上一轮全量、PG、浏览器、真实模型或作者质量验收。B10-F2 继续按用户决定留给 ADR-0042，不计为新问题。

结论：先修 WORLD-1 至 WORLD-4，再按这些具体链路验证；其余已列原 finding 静态复审未再发现阻断。

未检查：本轮未执行测试、真实数据库、真实模型、浏览器或部署验证；4 项均基于当前生产分支和数据库约束的可达路径证据。

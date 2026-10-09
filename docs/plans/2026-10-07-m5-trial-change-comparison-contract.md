# M5 实施契约：原状态→隔离试改→有限比较→领域确认

主计划 [2026-10-06-world-foundation-phase1.md](2026-10-06-world-foundation-phase1.md) §3.1 与工作包 M5。
前置：M2（[状态读契约](2026-10-07-world-state-read-m2-contract.md)）、M4
（[依赖失效契约](2026-10-07-m4-dependency-invalidation-contract.md)）。

## 1. 范围与复用映射（不重建试改框架）

Collaboration 隔离修改框架已完整，M5 全部复用、只做窄增量：

| 既有组件 | 位置 | M5 态度 |
|---|---|---|
| 冻结基线＋overlay（纯函数，patch key 必须在冻结基线内） | `workspaces.overlay()` / `CreativeWorkspace(Revision)` | 原样复用 |
| 修订 CAS（`expected_revision_id`）＋digest＋≤16 项/256KB 限额 | `edit_workspace()` | 原样复用 |
| 检查流水线（原稿 vs 试改双上下文 LLM 检查＋world_stress 双判定＋`checked_revision` 采用门槛） | `runtime.check_workspace()` / `world_stress_checks.py` | 原样复用 |
| 领域 prepare/apply SPI（validate 只读产 preview，apply 才写；writing 保存为新稿不覆盖历史） | `CreativeResourcePort`＋writing/story/world 三实现 | 原样复用 |
| 采用事务（项目排他锁→幂等 `operation_id+request_hash` 重放→四重 CAS→SAVEPOINT 内逐项 apply＋回执＋outbox） | `merge.merge_workspace()` | 原样复用 |
| 三方 rebase（`merge_fields` 字段级合并，重叠字段 conflict+base/current/trial+`current_hash`，`resolutions` 重试）＋revert | `recovery.py` | 后端原样复用，前端接线（§4） |
| API 路由（diff/edit/test/seal/merge/fork/rebase/revert）＋CreativeExperiments 双栏对照 | `collaboration/api.py` / `CreativeExperiments.vue` | 原样复用＋增量 |

预览零领域写入、采用 CAS/幂等/事务可验（M5 完成门禁前半）由上述组件既有行为与测试承担，
M5 只补 A06 浏览器验收。

## 2. 缺口一：结构化字段级局部比较

`workspace_view().changes[]` 现状：`before/after` 是整份内容、`diff` 是 JSON 序列化后的
文本 unified diff。M5 增量（后端，`workspace_view` 内）：

- patch 前后内容均为 dict 且键集一致时，输出 `field_changes:
  [{field, before, after}]`（同键自动对齐；新增/删除键以 `+`/`-` 语义标注）；
  否则（标量/列表/键集漂移）不输出 `field_changes`，前端回退整份对照——不猜字段语义。
- 文本 `diff` 保留（兼容既有消费方）。
- `merge_fields` 的字段遍历语义与 `field_changes` 对齐（同一字段口径），但不复用其
  合并行为——比较与采用解决是两个动作。

## 3. 缺口二：状态影响的有限列表（原状态↔候选状态的确定关联与未检查范围）

主计划 §3.1 要求「比较原方案与候选方案的有限后果，核对确定关联与尚未检查范围」。
M5 语义（诚实边界，unknown 不冒充成功）：

- `workspace_view().changes[]` 每项增 `state_impact`：
  - `affected`：**锚定**到被改资源的状态事实——按该资源关联 Scene 的当前
    checkpoint 各维度 `evidence_refs` 是否引用被改资源（或 scene 类 patch 直接锚定该
    Scene 全维度）确定性列出 `{dimension, subject_id?, reason}`；
  - `not_checked`：不满足锚定条件的影响面——显式列出说明，不推算、不冒充「无影响」；
  - `notes`：世界正典类 patch 追加「世界正典修订不自动改写场景观察（M4
    unsupported_dependencies 语义），核对待走 World 复核」。
- 上述资源影响列表只说明可证明的直接依赖。一般正文 patch 不从文字猜测新事实；缺少资源 ID/hash 依赖的维度留 `not_checked`。

### 3.1 指定切片的有限条件比较

`story.facade.compare_scene_state_trial` / `POST /memories/scene-state-trial` 从同 Scene 的作者状态和行动人物知识投影构建内存种子，复用 `ResolutionBatch` / `replay_batch`，仅支持：

- 钥匙转交：当前保管者与行动者相同、交接双方有同一位置的记录；成功只改变候选 holder，owner 保留。
- 三条件锁：所需钥匙、行动者保管钥匙、月相、人物已知且匹配的口令；规则与知识缺失返回不确定，明确不满足返回失败。只允许假设 holder 与月相，不假设口令知识或未记载规则。

响应比较 `baseline` / `candidate`，每项条件给出作者可读的 `observed`、`expected`、来源、是否假设以及有限结果。后果只在内存重放；明确列出未检查的时间、路径、人物意图与其他影响，不写 MemoryEvent、Canon、Checkpoint 或正文。

请求绑定 Scene、原状态 fingerprint、行动者/对象以及有限假设，比较回执以 digest 覆盖实际条件、来源和新鲜度。发起原稿试改时 `Grant.scene_state_trial` 必须带该 digest；collect/检查/采用重新比较，缺失、漂移、外项目人物或 Scene 未在本次授权资料中均失败关闭。

`InputManifest.scene_state_trial` 保存完整比较回执。其文本只在作者、原资料集合且非 workspace 检查上下文中追加，并声明“候选假设、不是已发生历史、不授予人物知识”。读者/角色、工作区新稿检查或改变资料范围不自动带入该假设。作者采用的是原有 writing/story/world port 的具体修改，有限排演结果不会自动写成已发生事件。

## 4. 缺口三：就地冲突解决入口（前端）

后端 rebase/conflict 数据（base/current/trial＋`current_hash`＋`resolutions` 重试）
已备好，前端未接线。M5 增量（`CreativeExperiments.vue` / `CreativeTrialEditor.vue`）：

- 采用冲突（stale/`SOURCE_STALE`/三方 conflict）时，就地展示冲突字段的
  base/current/trial 三方值，作者逐字段选择（current/proposed），以
  `expected_current_hash` 调 `rebase` 重试；不再只提示「不能直接采用」。
- 冲突解决是采用路径的一部分：仍走既有 `edit_workspace` CAS＋`merge` 门槛，
  不新增旁路写入口。

## 5. 作者入口

- Scene Lens（M2 对象状态区）增「从本场状态发起试改」链接：跳转 creative tab 并
  预选当前 Scene（CreativeExperiments 已支持上下文预选；窄屏先关闭本章资料再打开助手），不复制第二份试改 UI。
- 对象区“比较本场明确条件”可逐项核对当前值/所需值，查看来源并带假设发起原稿试改。
- 状态视图的 degraded（M4 待核对）在试改入口可见：发起试改前作者能看到基准是否新鲜。

## 6. 验收（A06 + §3.1）

| 项 | 场景 | 预期 |
|---|---|---|
| A06-预览零写入 | 试改→查看比较/检查 | 领域表零新增/变更行（DB 断言）；`field_changes` 与 `state_impact` 正确 |
| A06-取消 | 试改→放弃/关闭 | 无任何采用回执、无 outbox、领域无写入 |
| A06-幂等重试 | merge 成功后同 `operation_id+request_hash` 重发 | `receipt_view(replayed=True)`，领域零重复写 |
| A06-采用时改稿 | 试改期间原稿被改→采用 | 冲突不被覆盖；就地三方选择→rebase 重试成功；拒绝时原稿保留 |
| 状态影响 | scene patch / world patch / 无锚定 patch | affected 按 evidence_refs 锚定；world patch 带 M4 语义 note；not_checked 显式 |
| 有限条件 | 转交/三条件锁、口令误信或缺失、原状态漂移 | 已知失败/未知/通过分开；候选零写入；绑定回执漂移拒绝采用 |
| 字段比较 | dict patch / 标量 patch | dict 输出 field_changes；标量回退整份对照，不猜 |
| 浏览器 | Scene Lens 试改入口→creative tab 预选；冲突解决 UI | Playwright 覆盖跳转与冲突解决主路径 |

## 7. 边界与不做

- 对象/关系直接试改不在当前 port 内的，仍走已有领域提案（主计划 §3.1 原文），不扩为
  任意表写入；候选推演与采用后的作者规划不自动成为「已发生」的故事事件。
- 不新增比较用 LLM 调用（检查流水线的 LLM 检查属既有授权路径，不在比较增项里）。
- `field_changes`/`state_impact` 是 workspace_view 响应的追加字段，向后兼容。

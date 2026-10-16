# 地图增强系列待 review 清单

核实时点：2026-10-16T20:13:41+08:00。用户授权本地收尾与提交；没有推送、PR、合并、部署、模型调用或业务数据库访问。

本轮核对 39 个地图系列工作树（地图、对象档案、助手操作、留痕报告、场景导演、世界推进），
其中 37 个起始即无代码 WIP。已提交两个含代码 WIP 的工作树，以及主目录中的地图历史评审报告。
[WORKTREES.csv](WORKTREES.csv) 保存逐树前后 HEAD 与补丁关系；head_after 为业务/WIP提交后、最终记录提交前的代码固定点，dirty_files 为提交前时点。
已有主任务仍开放，本次 completed 只表示提交与审查交接完成，不表示系列计划或产品验收完成。

## 优先 review

|优先级|分支与固定审查范围|内容与已知缺口|
|---|---|---|
|1|`codex/map-enhancement-plan`，`59537b4cb376da20b67cd8152f4cca3ba6f286d0..651df05722abc7bbc6a47a42dbee77c43b5faf5f`|43 文件的后续补修：Goal 回执与零执行证明、稳定操作身份、档案/Profile 类型与清空语义、manifest v2 冲突与往返、Scene 重提取章序、词表修订展示；含19个测试文件。另仅格式化已改 dossier_interchange.py。|
|2|`codex/map-operation-catalog-impl`，`f7ba93e8bc5e428a8aef76b6d483ef4236049220..9fd1c83055db8390c0599b09825e3f5809089f57`|9 文件旧操作留痕原型，作为 WIP 保存；**不要直接合入整合树**。Ruff有7项问题，docs-check缺 assistant_operation_traces 表登记及多份架构文档核对，无本原型专用回归；须先判断与现有完整留痕实现的取舍。|
|3|下表8个旧实现分支|有 27 个非合并补丁未获得 patch-id 等价证明。可能已通过重写、拆分或组合提交集成，不能据此宣称功能遗漏，也不能直接 cherry-pick 或删除。先按文件/符号核对最终整合实现，再判断是否保留独有工程或历史证据。|

## 整合分支的验证与门禁

- 本轮重新执行受影响后端 145 passed，前端5文件120 passed；Ruff check、受影响26个Python文件格式检查、前端ESLint、文档检查、repo-gates及staged diff/secret hygiene通过。
- repo-gates仍提示Goal Runs/context compiler文件长度；不是本轮新增阻断。
- 最近完整门禁来自原修复账本：后端9092 passed/2 skipped，**覆盖率84.37%低于85%**，`make test-ci`退出2；前端3234 passed、专用PG7 passed、Chromium2 passed。本轮没有重新执行完整覆盖率、PostgreSQL或浏览器，不把本轮定向绿色当作全量CI通过。
- 首要交付阻塞仍是有效覆盖率与固定最终代码的完整门禁；此次提交不下调阈值、不删除断言、不自动合并。
- C1真实长篇、M5/C5外部势力前置、A4数周真实使用及作者质量验收继续保留；R3–R6封存、holdout与能力开关不动。

## 待对账的旧分支

下列头部按本轮核实固定；其余31个系列树满足祖先包含或无未匹配补丁，详见CSV。
这些是待审查范围，不是本轮确认的新缺陷。

|分支|固定HEAD|未匹配补丁数|
|---|---|---:|
|`codex/c2-ui-acceptance`|`2c8c11c263da612af6a9b7ad8d40582d156871b1`|15|
|`codex/scene-director-impl`|`1628717107a158b09f8f683c7223fbc65906e9ae`|1|
|`codex/map-clues-drafts`|`a58027bedfca8f28bf6c14c71262d2e65848fe2a`|2|
|`codex/map-evolution-spatial`|`8a2aec71d974aa4915b065cc537eb5d5c30be2a1`|3|
|`codex/map-spatial-advisories`|`0369360723a7b48c3b7c1ba173f48becf54ee424`|1|
|`codex/map-spatial-brief`|`4a39dd7524e3b7212a2eed785da757984e36cff7`|2|
|`codex/map-spatial-eval-driver`|`465a7e509f713ade38e0c8610d7fda501a2dc021`|1|
|`codex/operation-trace-report-impl`|`b55497379b377dc8a5f12d6aa57c687d0c879598`|2|

### codex/c2-ui-acceptance

工作树：`/Users/tywww/项目/ai-writing-assist/.worktrees/map-assistant-operations`。

- `23e322e01c40d8ddcb324aff4c7facbdc0c94b41` feat(world): add revisioned object dossiers
- `633293ee2a28cfddfae090e5cdfebc50167dfee5` checkpoint: evidence object dossier aggregation WIP
- `cb9d8f0ae9eae74ad1728a67583892e7a2da38af` feat(assistant): add unified notice backend slice
- `136163c4cd2d8ccb62e29a2d6ccbdfd196703cce` fix(assistant): restore timed notice wake and source coverage
- `f0d78e96e30e77ef103fddfaacc826977926618c` fix(story): retain unresolved reading reveal candidates
- `ede40401ff7bf78f7fecd435bcda82916a71f7dc` fix(assistant): deny demo writes to unified notices
- `4cb98784d0bee5468c4c8633cf93077edb30a44a` fix(world): harden dossier revision migration and review boundaries
- `30d5b06982afca2d63c0153dfa166e72c8959d1e` feat(evidence): add scene object dossier brief
- `f6f559f922c946ba7ee7bc4e4c40103d7b0a005c` WIP checkpoint: Story card and reaction v2
- `3c556dfd0e8f6532d74b23a8f40050d7f9c7e5d8` fix(evidence): enforce safe dossier projection and wire read ports
- `b5beb713110581f4a9a551d6dbb66fa7189eb4eb` style(evidence): remove trailing blank test line
- `c00a619617b01408f28bac61b2cc0559fd26e35f` fix(evidence): prove safe dossier visibility before pagination
- `9a9759ba48f118567f357ce73bb233dfad1c5356` test(evidence): pin reader proof for safe dossier facts
- `5217f53107eeeaa6c9a95745fc2eee659b53beab` fix: version dossier template operation after schema expansion
- `f6c3790ccb3b096509c5ec84583d6386e364ddaf` feat: bridge generic world profiles and story evidence

### codex/scene-director-impl

工作树：`/Users/tywww/项目/ai-writing-assist/.worktrees/map-assistant-structure`。

- `1628717107a158b09f8f683c7223fbc65906e9ae` feat(story): add isolated scene director workflow

### codex/map-clues-drafts

工作树：`/Users/tywww/项目/ai-writing-assist/.worktrees/map-clues-drafts`。

- `2238e26020792acca6ce04c53c23ec2af7e95420` feat(world): register spatial clue metadata and migration
- `a58027bedfca8f28bf6c14c71262d2e65848fe2a` feat(world): stage and review spatial clue candidates

### codex/map-evolution-spatial

工作树：`/Users/tywww/项目/ai-writing-assist/.worktrees/map-evolution-spatial`。

- `968bb8a0f6615867c41092673be37bc30efc41be` feat(world): register spatial clue metadata and migration
- `db00ae365a5f95529045826588fff122880e3ec2` feat(world): stage and review spatial clue candidates
- `43aa89d38ee819ddf421202febfff8f1fbf63170` fix(world): enforce spatial clue source and review boundaries

### codex/map-spatial-advisories

工作树：`/Users/tywww/项目/ai-writing-assist/.worktrees/map-spatial-advisories`。

- `0369360723a7b48c3b7c1ba173f48becf54ee424` feat(world): add deterministic map spatial advisories

### codex/map-spatial-brief

工作树：`/Users/tywww/项目/ai-writing-assist/.worktrees/map-spatial-brief`。

- `acda90caaa66d128c56c27659fb14cc92a39a375` feat(world): add source-checked spatial brief facade
- `4a39dd7524e3b7212a2eed785da757984e36cff7` feat(evidence): integrate adopted map spatial briefs

### codex/map-spatial-eval-driver

工作树：`/Users/tywww/项目/ai-writing-assist/.worktrees/map-spatial-eval-driver`。

- `8c3573718127a66e1fcc365ea1e5ca419db28e59` feat(map): expose owner-scoped persisted evaluation evidence

### codex/operation-trace-report-impl

工作树：`/Users/tywww/项目/ai-writing-assist/.worktrees/operation-trace-report-impl`。

- `ce676631be929b4a0f09e3c88e7642cc0994951b` WIP add report aggregation primitives
- `b55497379b377dc8a5f12d6aa57c687d0c879598` feat(assistant): add private operation trace reports

## 历史评审与交接

- 主目录历史报告 `out/map-enhancement-review-20261016.md` 已由 `cd4bf9705f4228b3b6163d749a3e499bf890cc0e` 保存。
  它评审的是 `81785cd16`，不能把其中旧失败和旧剩余问题当作当前结论；当前补修状态以
  [修复账本](../T-20261015-character-world-progression/artifacts/REVIEW-REMEDIATION-20261016.md)及上方固定代码为准。
- 恢复副本：`/private/tmp/ai-writing-assist-worktree-commits-20261016-200554`，包含原始174文件的哈希与副本、原分支/工作树/stash清单和检查日志。
- 其他文档、文学研究、审读、G6b/G6c、Guimi与演化模型池树保持原 HEAD 和原有资料；没有清理任何工作树、分支或stash。
- 本清单未执行正式代码review；下一步先评审整合分支43文件固定增量及覆盖率缺口，再对账旧原型和8个旧分支。

# C0b / C3b 审查队列

恢复时先核对主树和实际子代理状态。本文件只协调本次用户已授权的 Luna/max 实现、
Sol/high 独立审查和直接修复；root 不手改 review 问题或 Git 冲突。

## C0b：三层对象简报

- 原实现：world-object-dossier-impl/codex/object-dossier-evidence-impl 的
  `633293ee2` 与 `30d5b0698`。后者是首个独立 API/facade 提交；C3/C0a 父提交已在
  primary，不能重复 cherry。Luna 继续 C2 卡片/Reaction/目录及 Generic profile 闭环，
  这些后续改动不是首切片的已有能力。
- 准备审查树：`.worktrees/map-spatial-eval-review`，分支
  `codex/object-dossier-evidence-review`，基线 `258ed7b23`。
  cherry `633293ee2` 在 `world/dossier_service.py` 冲突，已停住；还需 cherry `30d5b0698`。
  原 `codex/world-object-dossier-review` 保留在 c99a702ae。Sol 直接解决冲突，保留 legacy
  projection 和 `total_count == 0` 的未知判定，不把分页空结果当没有档案。
- 审查重点：owner/novel、Scene cutoff 与 checkpoint/source 指纹；角色视角不能调用
  Evolution 台账 port 或作者 checkpoint set；World public 值只能有明确角色可见证明，
  不能泄露秘密、未来信息、原文或作者层指纹/省略计数。Evolution 只读 provider 自行重验
  当前 Scene、来源范围与 supported/作者保留状态，不信调用方传入的截止序号。
- optional patterns 默认关闭；缺 DI 明确 unknown/omission，无直接 Evidence→Evolution
  import；不降级核心 KnowledgeScope。API/facade/后续 R0 目录使用同一 schema。
- C0b 提交证据：正确 3.14.8 环境 45 定向测试、Ruff/diff 通过，尚未经独立审查或 app 联调。
  新通用 profile 旧写桥接与消费者切换仍欠；不能据此标完整 C0/C2 完成。

## C3b：统一提醒界面与两个薄来源

- 原实现：`53aaec35c`，准备审查树 `.worktrees/map-clue-review` / 
  `codex/unified-notices-ui-review`，基线 d7c6f45d3，cherry 为 `da21d3f05`，准备时干净。
  旧 `codex/map-clue-review` 分支保留。后续 A0 审修集成后由 Sol 接入其真实装配，不能只测 mock。
- 新来源纯 spec：`modules.evolution.notice_sources.NOTICE_SOURCE_SPEC`
  （world.map_source，G8a）与
  `modules.assistant.editorial_notice_source.NOTICE_SOURCE_SPEC`
  （assistant.editorial）。组合根 registry 仍需接线。
- G8a 必须核对当前 canonical map head 与当前已发布正文；旧 invalidation receipt 只能提供
  同一 head 的辅助证据，新 head/已修复来源不能永久留旧提醒。截断/未知显式披露。
  Editorial 仍由原 IssueDecision(expected_version) 做 closed 决定；read/snooze 仅通用展示状态。
  新来源失败时不能把旧 AssistantNotice 的编辑意见全部过滤掉。
- UI 审查：来源失败占位、partial、读/稍后/忽略、类别静默/恢复、409、demo 只读、
  本地未保存正文不进入服务端依据、跨项目/章/Scene 晚响应隔离、具体检查/重算/编辑意见导航。
  旧 sceneAlerts 功能断言已迁到 Story source 与新 UI，需核对是否保留有价值覆盖。
- root 已发现待复现 P2：POST 处置进行中可点击 reload；loadNotices 增加 generation 却
  不清 busyKey，旧 POST finally 因 token 过时也不清 busyKey，导致所有动作持续禁用。
  用 deferred POST → reload → GET 完成复现，Sol 直接修并回归，不由 Luna/root 抢改。
- Luna 证据：121 Vue、12 source + 31 unified service 测试，ESLint/Ruff/build、
  imports 61/61 与 517/517、docs 通过。root 看过 `/tmp/c3b-unified-notices-390.png`
  和 `-1280.png`，无横向溢出；它们是 mock API 的组件浏览器检查，不代表真实应用联调。
- C2 对象标签与 World 档案面板正在后续独立切片，四标签中的占位不能算导演/对象已完成。

## 共用执行约束

唯一后端解释器是 primary 的 `backend/.venv/bin/python`（3.14.8/Pydantic2.14.0），配审查树
backend cwd。不要使用原 repo venv、安装依赖或改 golden。工程 PG 65202 由 root 串行分配；
当前 C0b Sol 独占新 dossier_evidence_review_test_20261015，原 A0 Sol仅做扩大回归修复，不并用 PG；其余库与评测 65302 保持不动。
不得发模型请求、读 holdout、重试 R3、推送/PR/main 合并或部署。root 唯一写 TASK。

## 最新调度（23:58）

A0b已入primary d20d27517但扩大套9fail/2162pass，原Sol在新回归修复分支直接修；
C0b Sol已把两原提交接到d20并解冲突，继续typed DI与知识边界。Luna C2新功能/DI试探完整
WIP f6f559f9已checkpoint，当前import失败且未过517门，禁止直接集成；待Sol净fix安全移入后恢复。
C3b审查准备树仍保留，后续需先接已审A0b再作真实API联调。


## 2026-10-16T00:10 C2b就绪与新增审查线索

- C0b实际已在d20基线上完成633/30d两原提交的cherry（3e9468f1b、ef3a00f41），
  不再处于准备冲突；Sol当前直接修DI/知识隔离，不能重复cherry或改main。
- C2b原提交a212d9faa4aaaff28e9597fa19d64ec77d709651，在simulation-v3-director-impl/
  codex/copilot-unified-ui，父C3b 53aaec35c。保留已提交原树，后续审查树取C3b+C2b并接
  已审A0/C0实际装配。backend C2 WIP f6f559f9是另一树，禁止混同。
- 后端Sol裁定：author_safe排除secret/无法证明公开的台账；author_full是owner/novel
  门禁后的作者管理读取，支持显式patterns/only_adopted；character不调台账/作者checkpoint。
  前端Sol应直接把作者管理Panel的请求与文案对齐，并证明full响应不会被复用进角色/默认生成。
- root静态候选P2，尚待Sol复现：WorldObjectDossierEditor.saveTemplate在409后await服务器GET，
  返回后未重验scope便写templateConflict；confirmRestore在409后await reloadDossier后也未重验
  便写restoreError。用deferred二次GET/切项目对象回归，避免旧对象冲突污染新对象。
- root静态候选P2，尚待Sol复现：模板有未保存草稿时“读取模板”可以直接覆盖templateFields；
  loadAll若更新当前修订ID，editingOriginal消失可能让编辑表单与脏状态消失。需核对父组件离开
  保护是否覆盖手动重读，不得静默丢草稿。
- C2 UI还需核对使用globalThis demo标记和主界面直接暴露display_schema JSON是否违反既有
  bridge/作者语言规则；由Sol按实际影响最小修正，不为过检删除功能断言。
- root实际看图为/tmp/c2-scene-390.png与/tmp/c2-world-1280.png；其余390/1280截图仅Luna报告。
  mock组件截图不能代替真实API+app装配验收。


- 新审查准备树（C3b+C2b）：map-clue-review/codex/copilot-ui-integration-review，从1682f8dcd
  取原53/a212为a52159a47、91fd0902f，准备时干净。原da21审查分支保留；后续Sol先接A0净fix，
  C0b实际接线就绪再接，不重复取父提交。原Luna树继续保留。
- root静态功能缺口候选：编辑已存档案条目的表单/请求只有content、tags、visibility，现有有效期
  只能在新增时填写，无法修订或清空；后端update已有validity的exclude_unset/null语义。请Sol按
  C0作者有效期管理契约直接补最小UI与关键回归，保留旧锚点且不把未改日期静默清空。
- 项目词表现有ProjectVocabularyPanel已支持dossier_facing，勿重复造面向系统；核对档案编辑器到
  该共享管理入口的可达性，按真实可用路径说明，不仅显示项目面向列表。

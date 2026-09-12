# 可执行优化批次表（P4 交付）

生成：2026-09-11，主 Agent 基于全部 P1–P3 证据裁定。发现 ID 的完整字段见 `findings-ledger.md`
与 `units/<槽位>.md`。**实际实施需用户逐批授权**；本表不构成实施授权。

排序原则（计划 §5 P4）：可证明的局部清理 → 同语义复用 → 模块内部拆分 → 跨模块职责/前端
生命周期收敛 → 数据结构调整（必要性另裁定）。功能性修复不混入优化批次，单列为 R 组。
每批一个可验收结果，机械移动与行为逻辑分开；小 diff、独立提交、独立回滚。

## 实施进度（2026-09-12）

实施位于 `codex/full-optimization-implementation` 隔离分支；本节只记录执行证据，不追溯改变原审查裁定或授权边界。

| 批次 | 状态 | 结果/剩余门禁 |
|---|---|---|
| R1–R4 | 已完成 | 导入恢复、生产 Prompt、错误语义、测试收集/运行器均已独立提交并通过对应模块门禁 |
| R5 | 已完成 | 六维契约、导入/投影、确定性+AI 消费、地图只读证据、作者确认与 Scene Lens/冲突 UI 闭环完成；V1 指纹兼容，桌面+390px 浏览器链通过。真实模型质量验收归 B3c；见[实施细案](../2026/T-20260911-full-codebase-optimization-implementation/authorized-remaining-plan.md) |
| R6 | 已完成 | X1-3、D2a-1、E3-1 完成；F4-4 无需修复。X2-3 已实现取消/清理分离、显式预览确认、幂等/partial 软清理及深度整理回收站；桌面+390px 浏览器链通过 |
| B1a/B1b | 已完成 | 后端/前端可证明死代码清理完成；保留真实消费者、兼容面与安全门禁 |
| B1c | 已完成 | 逐路径分类账落盘；删除过时工具会话、运行时占位和错误目录日志，保留 239 份付费运行证据与 22 份实质设计探索；第三方原文换原创三章合成夹具。消费链 14 passed，部署 270 passed |
| B1d | 已完成 | 原 WIP 已进入本分支基线且文件恢复干净；按当前树重验后删除 world/review 副本 342 行与死 review 选择器 111 行，设置页副本已由基线提交清理 |
| B2a/B2b/B2c | 已完成 | snapshot client、checkpoint、stable hash 单点化；固定输入/字节兼容与模块测试通过 |
| B2d | 重裁后完成 | A6-4 导入启动编排已单点化；wheel 排除测试/eval、锁定运行器、镜像索引 digest、nginx header 继承已完成。F5-7 经用户明确暂缓，待部署窗口取得生产网络拓扑后另立运维安全批 |
| B2e | 已完成 | Vue 生产文件守卫扩面；Story HTTP 的项目范围、422、202 动作合同与 path/body 冲突覆盖完成 |
| B3a | 重裁后完成 | Story 两条入队流已收敛；Outline 三条因冻结时机、响应、meta 与错误映射不同保留，避免多开关 helper |
| B3b/B3e | 已完成 | semantic review 委托既有 service；worker 项目任务判断归项目 facade |
| B3c | 已完成 | 真实模型验收迁入 PostgreSQL 任务轨；删除同步正文生成、冲突复核/建议路由与前端死契约。DeepSeek 原创小语料前后各跑 1 次，共 4 次调用，均通过 |
| B3d | 重裁后完成 | Scene auto/runtime 两处迁入工厂、净删 215 行；Story Outline 的身份拒绝+终态重放专用实现保留，避免多开关工厂 |
| B4a/B4b | 已完成 | smartDedup 按钮迁入 Vue 组件，删除全局点击/HTML 注入/重绘事件；三个 Outline 预览页复用窄草稿生命周期，领域校验仍分立。smartDedup 桌面+窄屏 4 条浏览器链通过 |
| B4c | 已完成 | `pollRetryDelay` 统一 workflowProgress、writing 两路、conflict 与 POV 任务的 3/6/12/24/30 秒失败退避；成功即复位 |
| B4d | 已完成 | 两个 writing helper 已迁入 Vue 目录，生产 JS 守卫同步扩面 |
| B4e | 重裁保留 | R1 已在恢复根因处关闭死循环/漂移风险，暂无证据支持再做架构级重写 |
| B4f | 已完成 | AST 守卫仅拦截 API route 函数内直接且未在本地捕获的 `ValueError`，不扫描合法领域内部异常 |
| B5/收益待测项 | 按计划延期 | 无性能基线、生产 revision 或数据结构必要性证据，不实施 |

当前累计（完成记录提交后）：122 个原子提交，388 个文件，`+7006/-15863`（净 `-8857` 行）。最终门禁：后端 fast `5410 passed / 13 skipped`、覆盖率 85.72%；PostgreSQL critical `33 passed`；前端 `185 files / 2441 tests`、lint、build、资源校验通过；部署 `270 passed`，后端/前端生产镜像及真实恢复演练通过；docs-check 与 secret hygiene 通过。浏览器另覆盖 continuity 确认、深度整理回收站和冲突任务轨。视觉套件既有快照漂移、专用库既有 ORM/migration 漂移及独立 RAG 重索引缺陷均已记录，未混入本轮自动修复。

## R 组：功能性修复与门禁缺口（单列，优先于一切优化批）

| 批 | 内容 | 关键契约与验证 | 回滚 |
|---|---|---|---|
| R1 | D5b-1 + X2-2 + X2-4：导入恢复语义修复——`_progress_from_task` 重置 failed 态；恢复前来源漂移门禁（provenance key 失效时 fail-closed 转待处理而非重复建 Scene）；review 组漂移后提示纠正 | 补 fail→resume→重跑与漂移两场景测试；`make test TESTS="modules/imports/tests"` + `make test-postgresql-critical` | revert 即可（无数据迁移）；已产生的重复 draft Scene 需数据清理脚本另裁定 |
| R2 | D5a-1 + D5a-2：清除生产 prompt 硬编码《诡秘之主》实体名/评测名（scene_entity_bulk.py:416-423）与 1000 行死 reducer（内嵌同类内容） | 先删死 reducer（rg 证实仅测试引用，迁移有效断言），再改 sweep prompt 为结构化规则；imports 测试 | 独立提交 revert |
| R3 | 错误语义统一批：D1-4、D5b-2、X1-1、X4-2——裸 ValueError→DomainError(404/409)，stale 文案中文化；前端恢复按钮按 recoverable 门控 | 每端点断言状态码；assistant/imports/project/story 相关测试 + 前端 vitest | revert |
| R4 | E1-1 + E1-2：门禁缺口——testpaths 收回 account_project_preferences 52 测试；evals 测试接入自动层；`make eval-fast` 改走锁定运行器（同 F5-9） | 首跑通过率如实记录（可能暴露存量失败，逐个修复或显式 xfail 并留 issue）；testing-guide.md 同步 | revert（测试收集面无数据风险） |
| R5 | D3b-1 + D4-1 裁定落地：保留 continuity，在既有 Story memory/Evidence/Writing conflict 之上补齐空间、时间、逻辑的版本化状态、确定性检查、AI 软审查、作者确认与生成/修订消费；不建平行平台 | V1 fingerprint 字节兼容；Story/Evidence/Writing 模块、PG 并发、前端与桌面/窄屏浏览器；见[完整细案](../2026/T-20260911-full-codebase-optimization-implementation/authorized-remaining-plan.md) | 叶子批独立 revert；V2 数据只停止消费、不破坏性删除 |
| R6 | 小型功能修正组：X2-3 采用“取消只停止，深度导入回收站显式软清理”；X1-3、D2a-1、E3-1 已完成；F4-4 已复核无需 migration | X2-3 覆盖预览 fingerprint、owner/novel、项目锁、幂等/partial 与桌面/窄屏浏览器；其余保持既有验证 | 代码可 revert；已执行软废弃须走领域恢复，不靠代码 revert |

## 优化批次（依赖序）

### B1 可证明局部清理（最低风险，可多批并行，均不改变行为）

| 批 | 范围（发现 ID） | 验证 | 前置 |
|---|---|---|---|
| B1a 后端死代码 | F1-1（shared/enums 14 枚举，扣除 D2a 修正的 CandidateAction/RelationType）、F1-2、F1-4/5/6/7、F2 P3 死代码组（OutputGuard 死层、retryable、reuse_active 第二查询）、F2-2 附带、D4-6/7、D3a 死方法簇（one_click_preview、四旧一代方法）、D3b-3/4（delete_* 须保"保留历史"语义）、D5b 死代码（_accepts_keyword、死 schema、include_restartable_history）、D6a-1/4/5/7/8、D6b-1/3/7/11/12、X2-1 | 全仓 rg 零引用复查（逐符号限定路径）→ `make lint` + `make test` + 受影响模块测试 | 无 |
| B1b 前端死代码 | F3-1（11 死契约+activationPreview 死包装；**POST /activation-preview 不得动**）、F3-3（today/generate 死注册，保留模块）、F3-5、D8b-1（280 行 review 死簇，逐符号三查：import+模板 @click+data-action，per E2-9 警示）、D8c-3（LlmFormFields 簇）、E2-2（workspaceRail，保 `workspace-rail:` 键约定）、E2-3/4/5、D8c-2 死选择器族 | `npm run lint` + `npm test` + `npm run build`（资源校验） | 无 |
| B1c git 卫生 | 已完成无争议项；剩余 F6-3+F5-1、F6-4、F6-8、E1-9 先产出逐路径分类账：纯运行时/无消费者/无唯一证据项删除；唯一验收证据摘要或最小保留；《诡秘之主》原文换等价合成样本；不重写 Git 历史 | 分类账 + `git ls-files`/引用比对 + imports e2e + `make test-deploy` + 镜像内容抽查 | 用户已授权此判定规则；每类独立提交 |
| B1d 样式去重 | D8c-1：styles.css 三对成批重复 ~780 行（行级方案已定位；**styles.css 有他任务 WIP，须在其合入后实施**） | `npm run build` + 视觉抽查（settings/review/world 三区）+ 现有视觉基线 | 等 styles.css WIP 合入 |

### B2 同语义复用（行为等价证明前置）

| 批 | 范围 | 前置证明 | 前置批 |
|---|---|---|---|
| B2a | F2-3 + 调用方 7 份（writing/services:2081、semantic_review:325、conflict_ai:88、story/tasks:444、outline_state/ai_workflow_service:166、story_outline_generation:550、D4-9 第 7 份）收敛到 llm_runtime 公开 snapshot CM；profile_source 分歧保持有意语义 | 固定输入契约对比（成功/失败/取消/Key 轮换） | B1a |
| B2b | F2-4 + D3a-2 补充的 2 处 checkpoint 三步收敛单 helper（严格/rebuild 参数化） | 同上 | B1a |
| B2c | F1-3 stable_hash 全量收敛（census 17–19+story/compilation 增量，以 P3 阶段终核为准；D1 两变体 ensure_ascii 差异、D6b 两个持久化比对面禁止输出漂移） | 逐份指纹字节兼容样本比对（旧 confirmation/revision 不失效） | B1a |
| B2d | A4-2（29 coercion validator→2 个 Annotated 别名，4 个特殊保留）、A3-5（64 处 novel_id 列→NovelMixin 分批）、A6-1（5 个旧签名 shim，测试迁移）、A6-3/4 残余、A2-2 残余（_workflow_constant）、D7-1（interaction 双类合一第一步：helper 去重）、D2c-1（三重骨架合并）、D8a-2（isVersionActive 8 处）、D4-2（writing 指纹 90 行）、F3-2（超时双权威源，删死字段）、D8b-5/6/7、F5-2/5/7/9、E2-11 | schema/OpenAPI 对比（Annotated 不改变接受范围）；模块测试+前端 vitest | B1a/B1b |
| B2e | E1-4（/api/story HTTP 层补测）+ E2-1（productionJsFiles 守卫扩到 vue/）——守卫面修复，先于一切涉及视图文件移动的批次 | 新守卫跑红→修绿证明有效 | R4、E2-1 独立可先行 |

### B3 模块内部拆分/编排归位

| 批 | 范围 | 说明 | 前置批 |
|---|---|---|---|
| B3a | A5-1 + D3a-1：story/outline_state 五处入队流合并（+extra_meta） | API 参数适配层内收，外部契约不变 | B2a |
| B3b | D4-3：/semantic-reviews 委托 submit_review（A5-8 定案） | 前端契约不变 | B2a |
| B3c | D4-4/D4-5：writing 同步 generate_candidate 与 conflict 双轨退役（A5-5/A5-4）；先把所有测试迁到任务轨，按 R5 新契约做最多 4 次有界真实模型验收，通过后删除 deprecated 路由与同步 service | 用户已允许付费调用；仅经项目 LLM seam，原创小语料，保留预算/指纹/脱敏回执 | B2a、R5 |
| B3d | A8-2 + D8a-6：三处手写 workflow manager 工厂化（工厂按能力差距清单扩展；storyOutline 任务身份校验与终态重放语义必须保留） | 前端 vitest + 关键链手动回归 | B1b |
| B3e | F1-8：run_worker interaction_ 分支显性化（D7 已证分支必需——非删除，改为注册式声明） | worker 测试 | 无 |

### B4 跨模块/前端生命周期收敛（P3 已裁定方向，逐项单独立项）

- **B4a** A8-3/F3-4/D8b：smartDedup split-brain 收敛（app.js DOM 桥接→composable+组件；1238 行领域逻辑本体保留）。
- **B4b** D8a-4：三个 outline AI 预览页 ~900 行同构骨架收敛；**B4c** D8a-5/F3-7：五处手写轮询统一退避。
- **B4d** X1-9/A8-5：views/ 遗留 2 文件迁移（改 2 行 import），**联动 E2-1 守卫同步**。
- **B4e** X2 恢复契约重构：导入链恢复语义的架构级收敛（依赖 R1 落地后评估是否仍需）。
- **B4f** 错误映射横切收编（R3 之后的长效机制：新端点禁裸 ValueError 的 lint/守卫测试）。

### B5 数据结构（ necessity 另裁定，默认不实施）

- A3-1：PlotThread/OutlineArc 收敛 StructurePlanRepository（领域消费者少而集中，调用方零改动可期；钩子覆写扩展点保留）。
- A3-6/A9-12：alembic squash——**前提未满足**（压缩仅限从未部署的尾部 revision；生产 revision 证据在服务器 DB，需部署窗口取证），默认保留现状。
- F4-4 FK 修复已提前至 R6（正确性）；UUID 列类型收敛（4 种声明）收益低，默认保留；D3b-2 memory 双投影不对称与 D2a-8 O(n²) 候选对、D6a-2/D6b-4 N+1：**收益待测**——实施前按 §5 P2 隔离流程取证（本机 performance_probe 必败，需专门授权会话），无基线不实施。

## 收益与验证总原则

- 每批合并前：受影响模块测试 + lint；共享 hash/schema/状态面批（B2a–c）另做固定输入契约对比；前端批 vitest+build；任务/LLM/world 回归从 B3 起适用；收尾 `make docs-check BASE_REF=origin/main` + `make test-postgresql-critical`（涉任务/数据批）。
- 收益记录实测变化；无基线项标"收益待测"；删除行数仅作附带事实。
- 不做项（已裁定）：A8-6 剩余样板、A5-12、A5-13、A3-3 world/story 面、X1-6/A6-8 状态词表、X1-8 flag、A1-3、D8c-5 InteractionView 拆分、D8b-9、E2-10 微文件合并——证据见各槽位报告。

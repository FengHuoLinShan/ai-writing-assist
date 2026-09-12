# 优化候选批次表（独立复核修订）

生成：2026-09-11；同日经 3 个 `gpt-5.6-sol / low` 只读子代理与主 Agent 复核修订。
发现 ID 的完整字段见 `findings-ledger.md` 与 `units/<槽位>.md`。本表是候选映射，实施顺序、
批次验收与授权门禁以 [implementation-plan.md](implementation-plan.md) 为准；**本表不授权实施、
提交、合并、推送或部署**。

## 复核结论

- 原 R1/R2/R4/R6、B1a/B1b、B2d 混合了不同优先级、领域、行为语义或回滚方式，不能作为
  一个可独立验收的批次；原 B4 只有方向描述，尚不具备可执行性。
- 四条 P1 当前代码证据仍成立，但原表遗漏 F4-1 的实施落点，并把 D5b-1 的触发面写得过宽。
- 冻结审查基线为 `main@e7d0b8d5b`。复核时主工作区为
  `codex/frontend-fixes-20260911@bfc766ec1`，相对账本新增 1 个跟踪文件、19 个账本 blob 已变化；
  `backend/modules/imports/api.py` 与对应测试仍有未提交 WIP。每批实施前必须重新固定目标 HEAD、
  WIP 与逐符号消费者。
- B5 与所有“收益待测”项移出默认实施队列；没有同数据集的前后基线就不实施。

## R 组：功能修复与门禁缺口

| 修订批 | 原批/发现 | 单一结果 | 状态与最小验证 |
|---|---|---|---|
| R0a | 漏项 F4-1 + E1-3 | `test_identity` 复用 `production_python_files()`，不再扫描 `.venv` | 可执行；定向测试先红后绿，再跑 fast 层 |
| R0b | 原 R4 / E1-1 | 52 个 account/project preferences 测试重新进入自动收集面 | 可执行；先定向跑 52 个测试并记录存量失败，再只改 `testpaths` |
| R1 | 原 R2 / D5a-1 | 删除生产可达的第三方小说实体、题材与“Codex5.3”提示注入 | 可执行；同时覆盖 `scene_entity_bulk.py:56-78` 与 `:416-423`，固定 prompt 输入对比 + imports 测试 |
| R2 | 原 R1 / D5b-1 | 仅在显式恢复意图下把窄进程死亡窗口保留的 `failed` 归一为可继续状态 | 可执行；构造 `phase=failed + recovery_required=true` 的 fail→resume→claim→run 回归；普通 dismiss-only 失败不得自动重跑 |
| R3a | 原 R3 / D1-4 | project smart-dedup 未确认请求稳定返回 400 | 可执行；端点状态码与响应体测试 |
| R3b | 原 R3 / D5b-2 | imports 不存在/越权 review-resolution 统一不可见 404 | 等 imports WIP 归属解决；不得泄漏 owner/meta |
| R3c | 原 R3 / X1-1 | assistant 恢复路径按 not-found=404、预算/状态冲突=409 映射；按钮仅在 recoverable 时出现 | 可执行但后端/前端分开提交；模块测试 + focused vitest |
| R3d | 原 R3 / X4-2 | stale context 作者文案中文化，不改错误分类 | 可执行；确认 400/409 现有契约后锁定文案 |
| R4a | 原 R4 / E1-2 + F5-9 | `eval-fast` 使用锁定运行器 | 先定向验证命令与耗时；是否进入 fast/CI 是另一个决定 |
| R4b | 原 R4 / E1-2 | evals 124 个确定性测试接入自动层 | 补证据；先测耗时、稳定性与依赖，不预设加入 fast |
| R5 | 原 R5 / D3b-1 + D4-1 | continuity 位置证据 dead seam 的产品裁定 | **决策门，非实施批**；默认最小方案是删 dead seam/失实文档与测试，若选择补实现则另立功能任务 |
| R6a | 原 R6 / X2-3 | 取消后部分产物清理入口 | **产品裁定后实施** |
| R6b | 原 R6 / X1-3 | assistant 同 operation_id 并发幂等不退化为 500 | 独立事务/并发测试 |
| R6c | 原 R6 / D2a-1 | world 背景包排序确定 | 独立固定输入顺序测试 |
| R6d | 原 R6 / F4-4 | world_library ORM/FK 声明对齐 | 独立 migration 批；PG 历史行、前进/回退和旧应用可读性验证，不以 `git revert` 代替数据回滚 |
| R6e | 原 R6 / E3-1 | `make generate-e2e` 获得完整测试环境输入 | 独立测试工具批，不与生产修复混合 |

推荐优先顺序：**R0a → R0b → R1 → R2**。四批分别授权、分别提交；R3/R6 不打包授权。

## B1：机械清理候选，按 owner 拆分

原 B1a/B1b 不再作为批次名。以下每行至少是一个独立批；实施时若文件或 owner 再跨界，继续拆分。

| 修订批 | 候选范围 | 特别约束 |
|---|---|---|
| B1-core | F1-1/2/4/5；F1-6 仅完全无消费者的导出 | `get_db` 委托等行为重排不混入；F1-7 低收益，默认不做 |
| B1-tasks | F2 已证死 repair/retry/reuse 分支、F2-2 附带 | `from_project_settings` 等“补证据”符号不删；任务注册与恢复测试 |
| B1-story | D3a 已证死方法簇 | 与 continuity 条件项分离 |
| B1-continuity | D3b-3/4 中完全无生产/测试消费者的最小子集 | `record_events`、`delete_*` 等等待 R5 与 D3b-2 裁定，默认不做 |
| B1-writing | D4-6/7 | writing 模块专项测试 |
| B1-imports | D5a-2 dead reducer、D5b 已证死私有符号、X2-1 | D5a-2 不与 R1 prompt 修复同提交；避开 imports WIP；同步 README 与有效测试 |
| B1-evidence-index | D6a-1/4/5/7/8 | 按公开契约与测试价值再拆；恒零指标“修语义”不是机械删除 |
| B1-evidence-compile | D6b-1/3/7/11/12 | 删除公开 facade/字段前先确认外部契约；D6b-2 大渲染器另批 |
| B1-fe-contract | F3-1 activationPreview 死包装及其死契约 | 后端 `POST /activation-preview` 有真实消费者，严禁删除 |
| B1-fe-register | F3-3 today/generate 死注册 | 保留被其他页面直接 import 的活模块 |
| B1-fe-world | D8b-1 + E2-9 | 逐符号三查 import、SFC 模板与 `data-action`；`markEntityReviewed` 保留；需 world 专项浏览器回归 |
| B1-fe-settings | D8c-3 | LlmFormFields/llmForm 独立删除，SourceLabel 保留 |
| B1-fe-shared | E2-2/3/4 | `workspace-rail:` localStorage 键约定与 scene locator 消费面单独核对 |
| B1-fe-test | E2-5 等测试卫生 | 补真实断言属于门禁修复，不与死代码删除混批 |
| B1-css | D8c-1/2 | 基于目标 HEAD 重新做选择器与成对 diff；当前 `bfc766ec1` 已改 styles，旧行号和 WIP 状态失效；build + 三区视觉回归 |
| B1-repo | F6/F5/E3 仓库卫生候选 | 嵌套目录、历史工具、法务样本、53MB 夹具、损坏脚本分别裁定；删除证据或真实语料须单独确认 |

本节是 owner 级候选容器，不自动等于可直接授权的 leaf 批。含多个发现、多个文件族或“继续拆分”
条件的行（尤其 B1-core、B1-evidence-*、B1-repo）须先补一张精确到发现 ID、文件、契约、验证与
回滚的 leaf 卡片，再由用户授权；不得把“实施 B1-repo”解释成删除整组资料。

## B2：同语义复用，先证明再迁移

| 修订批 | 候选范围 | 进入实施前必须完成 |
|---|---|---|
| B2-snapshot | F2-3 + 领域调用方 | 先处理/证明 F2-9；锁定 transaction/checkpoint 顺序、snapshot restore、profile_source、借用 client 不关闭、当前轮换 Key |
| B2-checkpoint | F2-4 + D3a-2 | 标准序列与 scene_fusion 次序变体分开迁移；与 B1 只有文件冲突，不设虚假语义依赖 |
| B2-hash-census | F1-3 + D4-2 + story/compilation 增量 | **补证据批，不改生产**：完整调用点、编码参数与持久化消费者清单；旧 confirmation/revision 历史样本字节对比 |
| B2-hash-* | B2-hash-census 产出的各语义族 | 每个编码语义族独立批；不得用一个多开关万能 helper 强行统一 |
| B2-schema | A4-2 | OpenAPI 与 missing/null/empty/invalid 固定样本完全一致 |
| B2-orm-* | A3-5 | 按模块拆 NovelMixin；metadata diff、PG 历史行、过滤/软删/钩子/事务验证 |
| B2-imports | A6-1/3/4、A2-2 残余 | 避开 imports WIP；兼容 shim 与生产调用迁移分提交 |
| B2-interaction | D7-1 | 只合并概要入队 helper；跨类私有 seam 不顺手重构 |
| B2-world | D2c-1 | 固定 LLM messages 序列与错误语义 |
| B2-fe-version | D8a-2 | `isVersionActive` 纯 helper 收敛，focused vitest |
| B2-fe-world | D8b-5/6/7 | D8b-7 等依赖 B1-fe-world 的项后置 |
| B2-fe-timeout | F3-2 | 先裁定 timeout 权威源，公开字段不漂移 |
| B2-build-* | F5-2/5/7/9 等 | wheel、compose、forwarded IP、eval runner 各自独立；安全/部署行为不归“同语义复用” |
| B2-guards | E1-4、E2-1 | story HTTP 守卫与前端生产文件守卫分开；E2-1 必须先覆盖 `vue/`，再做任何 views 移动 |

## B3：模块内编排候选

| 修订批 | 候选 | 前置与验收 |
|---|---|---|
| B3-story-enqueue-* | A5-1 + D3a-1 | story 与 outline_state 分批；外部 HTTP、operation_id、extra_meta、状态值不变；无强制 B2a 语义依赖 |
| B3-writing-review | D4-3 | 先证明 `submit_review` 与 API 内联路径在 operation_id、confirmation、错误映射、meta 与状态码等价 |
| B3-writing-generate | D4-4 | 与 conflict 退役拆分；生产 API、worker 与真实模型载体分别迁移 |
| B3-writing-conflict | D4-5 | deprecated HTTP/facade 是外部行为变更；需兼容期或明确产品裁定，不能以“前端零调用”直接删除 |
| B3-fe-manager-* | A8-2 + D8a-6 | 先完成 B2-guards；按三个 manager 分批，保留 cancel/dismiss/ownerSceneId/receiptStorage、任务身份与终态重放；浏览器恢复回归 |
| B3-worker-registration | F1-8 | 先读 interaction 局部规则；核对 47 handler 注册面、worker 启动与恢复 |
| B3-repository | A3-1 | 从 B5 移回普通代码重构候选；先证明过滤、软删、排序、钩子与事务等价，不改数据结构 |

## B4：架构方向，补全卡片后才可执行

- **B4a smartDedup**：前置 B1-fe-world + B2-guards；保留 DOM/data-role/Teleport 与 6 个消费者，补 world 浏览器回归。
- **B4b outline 预览骨架**：三个页面逐页迁移，不做一次性 900 行替换。
- **B4c 轮询**：在 manager 迁移后按终态、取消、退避和恢复语义族分批。
- **B4d views 移动**：先独立完成 E2-1 守卫覆盖 `vue/`，再移动两个纯 helper 并改 import/README/test。
- **B4e imports 恢复架构**：R2 后只做重新评估，不预设仍需重构，移出默认实施队列。
- **B4f 错误守卫**：R3 各领域修复后，先列允许的边界 `ValueError`，再设计守卫，避免误禁输入校验。

每个 B4 项在实施前必须补齐文件/接口范围、保留契约、前置证明、专项测试、浏览器或 PG 门禁、
回滚和停止条件；未补齐前不接受“实施 B4x”作为代码授权。

## 延后/不实施登记（原 B5）

- Alembic squash：阻塞于生产 revision 证据与部署窗口，默认保留。
- D3b-2、D2a-8、D6a-2、D6b-4、D8b-9、D7-7 及其他“收益待测”项：仅进入性能补证据会话；
  取得同数据集、同环境的 SQL/耗时/内存基线后重新裁定。
- UUID 列类型统一、状态词表合并、InteractionView 拆分、X1-8 flag 等低收益或高兼容风险项维持不做。
- F4-4 已移到独立 R6d；A3-1 已移到 B3-repository，它们不再被误称为数据结构批。

## 通用验证与回滚

- 每批编辑前固定 HEAD/WIP，重跑逐符号消费者与适用 `make docs-check`；只提交该批文件。
- 后端：目标模块测试 + `make lint`；共享面扩大到 `make test-ci TEST_WORKERS=2`。事务、ORM、恢复、
  novel_id/owner 路径加 `make test-postgresql-critical`。
- 前端：focused vitest + `npm run lint` + `npm run build`；用户可见、生命周期、恢复或样式变化加专项浏览器回归。
- 收尾：`make docs-check BASE_REF=origin/main` 与 `git diff --check`。现有他人 WIP 引起的文档门禁失败按
  `--no-change-reason` 记录，不替他人补声明。
- hash/schema/state/ORM/migration 不以 `git revert` 代替数据回滚：先证明旧记录可读、旧指纹不失效、
  OpenAPI/公开值不漂移；产生新格式时使用扩展 → 切换 → 收缩并说明旧应用能否读取。

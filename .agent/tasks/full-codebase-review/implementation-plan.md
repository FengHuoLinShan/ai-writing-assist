# 全代码库优化实施计划（独立复核版）

日期：2026-09-11。状态：**计划完成，任何代码批次均未获实施授权**。

本计划承接 [审查总报告](review-report.md)、[修订批次表](batch-plan.md) 与各 `units/` 证据。
目标是在保留外部行为、历史数据、安全边界与用户 WIP 的前提下，把已核实发现转成可逐批授权、
独立验证和独立回退的改动。原审查的静态结论不是当前 HEAD 的永久证明；每批开始前重新取证。

## 1. 完成标准与非目标

一个实施批只有同时满足以下条件才算完成：

1. 目标 HEAD、工作树差异、发现 ID、生产调用者和测试调用者已重新固定；零引用结论对当前树成立。
2. 只实现一个可验收结果；机械删除、行为修复、测试门禁、共享语义收敛和数据变化不混提交。
3. 计划 §2 的适用兼容面已证明：HTTP、持久化、异步恢复、LLM snapshot、owner/novel_id、前端恢复与运维合同不漂移。
4. 目标测试、失败路径、适用 PG/浏览器门禁和文档检查有实际结果；已有失败与本批回归分开记录。
5. 回滚覆盖代码及适用的数据、任务、指纹或 migration；本地提交可独立回退。

非目标：不追求删行比例；不实施无性能基线的候选；不顺手引入框架、依赖或未来扩展；不合并、
推送、部署；不清理真实数据或他人 WIP。

## 2. 基线与工作区策略

- 冻结审查基线：`main@e7d0b8d5b`；原远端基线：`origin/main@2c462f2c7`。
- 复核现场：`codex/frontend-fixes-20260911@bfc766ec1`。该提交相对冻结账本改变 19 个已有文件并新增
  `frontend-console/tests/uiSizeContracts.test.js`；前端批不得继续使用旧 CSS 行号或 2453 文件口径。
- 受保护未提交 WIP：`backend/modules/imports/api.py`、`backend/modules/imports/tests/test_import_api.py`、
  `.agent/TASKS.md`、`.agent/tasks/code-simplification-audit.md`，以及届时 `git status` 新发现的全部改动。
- 每批获准后先 `fetch` 并从尽可能新的 `origin/main` 建 `codex/<batch-slug>` 隔离 worktree。若批次依赖
  本地未推送提交或 WIP，先报告依赖与拓扑，不复制、丢弃或隐式带入。
- `.agent` 审查材料当前是主工作区本地产物；实施 worktree 可只读引用主记录，不为同步记录擅自提交。

## 3. 授权模型

- 用户一次只授权一个原子修订批，例如“实施 R0a”或“实施 R1”。R0a–R6e 中标记可执行的行是
  leaf 批；B1/B2/B3 的 owner 级容器必须先补精确 leaf 卡片，不能用容器名获得整组授权。原名称
  “R1/R2/B1a/B2d”如有歧义，以 [修订批次表](batch-plan.md) 的修订 ID 为准。
- 依据本次交接已明确的“每批独立提交”规则，原子批授权允许该批调查、实现、测试、必要文档和
  主题分支上的独立本地提交；用户若明确要求不提交则停在工作树。不包含合并、推送、部署或真实数据清理。
- 以下事项必须另行确认：R5/R6a 产品语义、数据库 migration 或真实数据处理、付费真实模型、专用浏览器/
  PG 验收、新依赖/基础设施、合并、推送、部署。
- 一个批次若暴露超出其单一结果的存量失败，先交付证据；只有同根因且不扩大产品语义的最小修复可留在本批，
  其余另立批次。不得用静默跳过或无依据 `xfail` 让门禁变绿。

## 4. 实施顺序

顺序表示建议，不构成组合授权；同一波的每个修订批仍需分别批准。

### 波 A：恢复可信门禁

1. **R0a — F4-1/E1-3**：让 `test_identity` 使用现有 production 文件清单，消除 `.venv` AST 扫描。
2. **R0b — E1-1**：先定向运行 52 个 account/project preferences 测试，再把目录加入 `testpaths`。

这两批先行，因为后续任何“全量 fast 通过”都依赖它们。R0b 首跑若暴露存量失败，逐个归因；不在
同一个 testpaths 提交中混入无关产品修复。

### 波 B：四条 P1 的生产缺陷

3. **R1 — D5a-1**：删除 `scene_entity_bulk.py:56-78` 的 1–7 章题材特判，以及 `:416-423` 的
第三方实体与内部评测名；改为只依当前正文、已有对象和通用长期资产规则的 prompt。
4. **R2 — D5b-1**：只在显式 manual resume 的窄中断窗口归一 `phase="failed"`；普通优雅失败继续
dismiss-only，程序内直接重入 failed 仍拒绝。

R1 不删除 dead reducer；该机械清理属于 B1-imports。R2 不捆绑 X2-2 来源漂移或 X2-4 review 漂移，
后两者分别补产品语义、预算和重复 Scene 验证后再授权。

### 波 C：原子正确性修复

- R3a–R3d 按 400/404/409/作者文案的真实语义分别实施，不做全仓机械 `ValueError` 替换。
- R6b、R6c、R6e 可各自排期；R6a 先产品裁定，R6d 先批准 migration 与数据回退方案。
- R4a/R4b 先取得 eval 命令耗时与稳定性，不把“接入自动层”预设为 fast 层。
- R5 是决策门：默认 YAGNI 方向为删除 dead seam 与失实文档/测试；若需要位置连续性，则转独立功能项目。

### 波 D：机械清理

按 [修订批次表](batch-plan.md) 的 B1 owner 拆分执行。优先选择当前树上仍能证明生产零引用、
无公开契约且有小型回归面的项目。推荐首批候选是 B1-fe-settings 或小型 B1-core 子集；imports、
continuity、仓库历史和 CSS 清理因 WIP、产品语义、证据保留或当前分支漂移后置。

### 波 E：同语义复用

1. 先做只读证明批：B2-snapshot 的 F2-9 前置、B2-hash-census、B2-guards。
2. checkpoint、schema、ORM、imports、interaction、world、frontend、build/deploy 分 owner 实施。
3. hash 只按完全相同的编码语义族迁移；旧 confirmation/revision 固定样本必须字节一致。

### 波 F：编排与架构候选

- B3 每项先补等价矩阵；story/outline、generate/conflict、三个前端 manager 分批。
- B4 每项先补可执行卡片。B4d 必须先完成 Vue 生产文件守卫；B4e 只在 R2 后重新评估。
- 原 B5 不作为实施波次；性能、迁移压缩和高兼容风险候选保持延后。

## 5. 首四批验收卡

### R0a

- 范围：`backend/infrastructure/tasks/test_identity.py` 与必要的测试 import；不改 production inventory 实现。
- 断言：不遍历 `.venv`；规则仍覆盖所有生产 Python 文件；单测运行时间回到 fast 门禁预算内。
- 验证：定向 identity 测试、`make test`、`make lint`、docs-check。
- 回滚：单提交 revert；无数据影响。

### R0b

- 范围：`backend/pyproject.toml` 的 `testpaths`；存量失败修复不得预先混入。
- 断言：52 个测试可被默认收集；owner/novel_id 隔离断言仍执行；收集数变化被记录。
- 验证：先定向目录，再默认 fast 层；必要时只读收集清单对比。
- 回滚：单提交 revert；无数据影响。

### R1

- 范围：生产可达 prompt 与最小对应测试；dead reducer 及其测试不动。
- 断言：生产 imports prompt 不含作品专名、题材特判或内部评测名；当前正文/证据边界、schema 与预算不变。
- 验证：固定输入 prompt 快照、imports 模块测试、生产码限定搜索、lint/docs-check。
- 回滚：单提交 revert；不处理历史已生成候选。

### R2

- 范围：显式 resume 的状态归一与一个最小失败恢复测试；不扩成 imports 恢复架构重写。
- 断言：窄窗口 fail→resume→claim→run 可继续；普通 dismiss-only 失败不能 resume；targeted completion 特例、
  input fingerprint、预算与 generation fence 不变。
- 验证：imports 定向恢复测试、模块测试、`make test-postgresql-critical`；需要时用专用库做最小 E2E。
- 回滚：代码可 revert；若现场已存在重复 draft Scene，只报告并另行授权数据清理，禁止自动删除。

## 6. 通用验证矩阵

| 变化 | 最小门禁 | 额外证明 |
|---|---|---|
| 后端局部 | 目标模块测试、`make lint`、docs-check | 失败路径与状态码 |
| 任务/恢复/ORM | 上述 + `make test-postgresql-critical` | generation/lease/幂等、旧行可读、回滚 |
| 前端局部 | focused vitest、lint、build | 空态/失败/恢复/窄屏按影响选测 |
| 前端生命周期/样式 | 上述 + 专项浏览器 | 卸载、迟到响应、刷新恢复或三区视觉 |
| snapshot/hash/schema | 受影响全链测试 | transaction/close、Key 轮换、字节/OpenAPI 兼容 |
| 共享/跨模块 | `make test-ci TEST_WORKERS=2` | PG/浏览器/真实模型不能被 test-ci 替代 |

收尾统一运行 `make docs-check BASE_REF=origin/main` 与 `git diff --check`。`performance_probe` 的本机环境
失败不计回归，但也不能作为跳过性能基线的理由。

## 7. 回滚、停止与交付

- 纯代码批：一个主题分支、一个最小提交；记录 revert 后应恢复的行为。
- migration/新格式：先扩展兼容读取/写入，再切换；收缩另批。必须说明旧应用是否能读取新记录及 downgrade 对历史行的影响。
- 用户资产：已采用对象、草稿、Scene、confirmation/revision 不自动删除。修复前已产生的异常数据另做只读盘点和单独授权清理。
- 同一依赖或修复连续 3 次无新证据、必需产品裁定缺失、真实数据风险、跨 novel 泄漏或无法建立验证路径时，
  停止受阻批并交付其余证据。
- 每批完成报告区分：已修改、已验证、未验证；本地提交不等于已合并、推送、CI、部署或发布。

## 8. 下一步

等待用户逐批授权。推荐第一条指令：**“实施 R0a”**。其结果将恢复 fast 门禁的可信运行时间，且不触碰
当前 imports 与前端 WIP。

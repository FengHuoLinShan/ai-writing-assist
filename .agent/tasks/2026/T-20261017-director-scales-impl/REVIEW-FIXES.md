# 导演多尺度审查整改

用户于 2026-10-18 在完整审查后要求“修复”。主笔记为同目录 TASK.md；本文件仅维护整改证据。
起始提交 db8853ff6d32bc8e033526abf11757fec7455b22，原工作树干净。修改仅在主实施工作树。
验收要求：26 项逐项核验，相关调用方/契约/文档同步，离线回归与适用门禁通过；不能执行的
PostgreSQL/浏览器/真实模型验收单列，不冒充完成。不改变采纳、发布、费用或真实数据授权。

## 工程整改与回归（26 项已完成）

- [x] 1 人物输入按目标投影，禁止作者全知资料回流，正常 hidden guard 有效。
- [x] 2 所有可见探索输出经过独立知识/语义审查，预算含审查步骤。
- [x] 3 每次模型调用及最终持久化前重验同一来源确认。
- [x] 4 目标预算包含可能付费请求硬上限，领域执行实时计入目标约束。
- [x] 5 目标领域任务在预算准入前不进入普通队列。
- [x] 6 起点、假设、尺度、焦点纳入 preview/confirm/rematerialize 指纹。
- [x] 7 跟进请求的幂等回执查验先于追加授权及状态修改。
- [x] 8 Scene 锚点沙盘/事件可执行，不访问临时起点字段。
- [x] 9 详情/修订保留原确认焦点，诊断转补桥正确复用确认。
- [x] 10 新参考对白/动作进入 Writing 的实际 Evidence 编译输入。
- [x] 11 移交保留完整所选条件、未知、参与者状态及来源。
- [x] 12 创建正式参考前重验源确认及目标人物知识。
- [x] 13 助手实际投影推荐/结果引用，手动覆盖绑定同一任务。
- [x] 14 跨层任务持久化、跟踪、恢复，重复点击复用同一操作。
- [x] 15 暂停后有绑定原根/账本/检查点的显式恢复入口。
- [x] 16 目标内自主跨层可通过受限目录完成移交与目标确认。
- [x] 17 多目标/诊断/排演/编辑结果支持对应局部控制与继续。
- [x] 18 移除 6 人/3 轮低固定产品上限，仍受预算与容量约束。
- [x] 19 多轮逐人物知识累计，不能用作者全知摘要代替。
- [x] 20 推荐预览前后端载荷一致，禁止额外字段导致 422。
- [x] 21 跟进任务与最新结果可刷新恢复，并提供真实停止。
- [x] 22 反事实比较可查询对应跨根基线和衍生结果。
- [x] 23 双保存失败明示并保护未保存草稿的离开路径。
- [x] 24 编辑保存消费服务端新结果 ID 与父版本关系。
- [x] 25 草稿绑定原始结果/条目，切换不覆盖或错存。
- [x] 26 新结果读取真实分支锁，不错误显示解锁。

## 验证基线

- 审查时相关后端 319 项、前端 109 项通过，定向反例仍能复现缺陷；这些不是修复验收。
- 整改前标准 docs-check BASE_REF=origin/main 曾失败；现已同步实际受影响文档并直接通过，不使用跳过理由通道。
- 本轮修改前重新运行文档基线；具体结果随各批修复记录。

## 回归对应

- 1/2/3/6/8/9：`test_exploration_confirmation.py`、`test_exploration_worker.py`、
  `test_exploration_review_regressions.py` 覆盖角色输入隔离、审查阻断与一次返修、逐调用/落盘前失效、
  空项目/Scene 起点、焦点冻结及诊断转补桥；返修消息不得带回作者私密引文。
- 4/5/7/16：`test_goal_runs.py` 与 `test_exploration_api.py` 覆盖实时双账本/可能费用停点、
  任务入队即 inline_only 与父身份、操作幂等，以及真实 Goal 的 handoff→preview→confirm→start。
  `test_assistant_operation_registry.py` 固定九项探索目录和所有旧版冻结目录的隔离。
- 10/11/12：`test_exploration_scene_reference.py`、`test_exploration_handoff.py`、
  `test_exploration_handoff_flow.py` 覆盖持久参考进入实际 Writing Evidence section、来源 stale 拒绝、
  六向派生条件/未知/人物继承、来源输出变更、Scene 截止及角色知识指纹。
- 13/20：`test_display_sources_exploration.py`、`ProjectAssistant.test.js` 覆盖实际任务来源投影、
  预览载荷和手动尺度/焦点对原问题的绑定。
- 14/15/17/18/19/21：`test_exploration_review_regressions.py`、`test_exploration_full_rehearsal.py`、
  `test_exploration_schemas.py`、`ExplorationResultCard.test.js` 覆盖同根恢复与未知费用确认、
  多目标/复杂条目/排演的逐单元检查点、累计观察、多形态局部控制、刷新轮询及真实停止。
- 22/23/24/25/26：`test_exploration_api.py`、`test_exploration_locks.py`、
  `ExplorationResultCard.test.js`、`ProjectAssistant.test.js` 覆盖跨根反事实关系、锁哈希、
  新结果锁读取、新编辑版本 ID、逐条目草稿与双保存失败的父级/路由离开保护。

## 最终工程验证

2026-10-18 11:11 +08:00，第二轮 `make test-ci TEST_WORKERS=2` 完整退出 0：

- 后端全量：9496 passed、2 skipped；覆盖率 **85.46%**，保持 85% 原门槛与 RuntimeWarning 错误门禁。
- 部署脚本（合成隔离夹具）：324 passed；前端完整 Vitest：260 文件、3334 passed。
- 前后端依赖审计、secret hygiene、全后端 Ruff 均通过；全前端 eslint、前端构建与产物引用核验通过。
- `make docs-check BASE_REF=origin/main`、Prompt contracts（26）、模块依赖棘轮（517/517）通过。
- repo-gates 通过；另以当前工作树执行完整生产文件行数门（1284 文件）通过；`git diff --check` 通过。
- 独立只读 Spec/Standards 复核未发现剩余实质缺陷；新增 SceneAnchor 人物指纹和分段恢复的定向复核通过。

测试期间 46 个变更 Python/JS/Vue 文件保持相同内容指纹：
`f2f1a446941a540c33aa887f58bdc35b103312805367e7c9ea650d5961e31138`。
起始 HEAD 仍为 db8853ff6d32bc8e033526abf11757fec7455b22；这是未提交工作树验证，不是新 commit 的远端 CI。

首轮 CI 的 5 个失败均为三项新增探索操作未进入 registry snapshot，已同步九项目录与
start schema 哈希；保持旧冻结目录隔离断言，未弱化安全门、修改依赖或降低覆盖率。
分段恢复另补逐条持久检查点，新 start/detail 回归均以 3+3 次请求完成两个目标且保留审查，
不重跑已完成条目。最终 CI 已覆盖这些改动。

日志位于本机 `/private/tmp/director-final-ci2.log`、`director-final-docs.log`、
`director-final-import.log`、`director-final-prompts.log`、`director-final-eslint-all.log`、
`director-final-build.log`。前端完整套件有 localhost:3000 连接拒绝的控制台输出，
测试及整个 CI 退出 0；后端保留 14 条非失败 warning，不将它们隐藏或描述为零告警。

## 交付与未验范围

26 项工程整改已完成，所有改动仅在 `codex/director-scales-impl` 本地工作树，未提交、推送、合并或部署。
未改规划工作树、用户原 WIP、真实数据库或封存评测。ADR-0042 仍为 Proposed，未以工程验证代替采纳。

未执行专用 PostgreSQL 并发/迁移、真实浏览器、生产镜像、Luna/max 或作者验收；这些与离线工程
验证分开，不宣称产品效果、文学质量或生产可用性已经验收。进入合并流程前仍须按项目规则补足
适用的独立门禁；真实模型/作者执行保持原授权边界。


## 2026-10-18 深审追加修复与 PR

用户随后要求“修复，然后 pr”，授权当前主分支成果提交、推送和创建 PR；未授权合并或部署。
修复前全工作树补丁和原未跟踪文件已备份在 `/private/tmp/director-before-review-fix.patch`、
`director-before-review-untracked.tgz`，未覆盖其他工作树或真实数据。

- Goal 终态领域消费在内存计算后，将账本与归集基线一起保存；已付费后失败/未知仍计入总账，重复核对幂等。
  追加修复截止后结算：`record_external_usage` 与新请求准入分开，deadline、capability 和冻结请求上限保留；
  物理时点仍由源领域账本负责，重建后新请求序号大于已消费数量。
- 历史编辑逐项核当前锁哈希；旧版本不能将已锁定内容回退。
- API 拒绝任务执行中的编辑；Scene 结果在分支行锁内重验最新父版本，拒绝越过作者新版本。
- 取消由现有租约终态镜像同步根/分支，保留分段检查点及 `recovery_receipt`；默认完成来源读取不接受 cancelled，
  恢复展示通过显式 opt-in 获取回执。助手、结果卡与刷新恢复贯通，未知费用仍须显式核对后续跑。
- 沙盘按实际 `affected_refs` 显示受影响项。
- 真 PostgreSQL 回归额外发现根/分支 flush 排序的外键问题：改为先持久根，再写分支；三尺度都用真实 FK 验证。

新增反例覆盖：`test_exploration_review_regressions.py`、`test_exploration_locks.py`、
`test_goal_runs.py`、`test_display_sources_exploration.py`、`test_run_envelope.py`、
`ExplorationResultCard.test.js`。`test_exploration_review_concurrency.py` 已加入 PostgreSQL critical 门禁。

阶段验证：完整 `make test-ci TEST_WORKERS=2` 通过（后端 9505 passed/2 skipped，覆盖率 85.48%；
部署 324 passed；前端 3335 passed）。专用 PostgreSQL 17 容器 `director-scales-test-20261018` /
`director_scales_test` 从 migration head 创建，critical **112 passed**，含三尺度根创建及父版本真实行锁冲突。
日志：`/private/tmp/director-review-final-ci.log`、`director-review-pg-critical.log`。
完整 eslint、生产构建与 `make docs-check BASE_REF=origin/main` 通过。

随后追加的截止后历史费用结算及序号修复，5 项定向回归通过；最终后端全量 **9508 passed / 2 skipped / 11 warnings**，覆盖率 **85.48%**，
退出 0（`/private/tmp/director-review-final-backend.log`）。两轴独立只读复核未发现剩余实质缺陷。

未执行真实浏览器、生产镜像、业务模型或作者验收；新功能默认关闭，ADR-0042 仍 Proposed。

收尾静态检查：全库 Ruff lint、变更 46 个 Python 文件格式检查、diff whitespace 与 docs-check 通过。
额外全库格式检查失败：177 个既有文件需格式化，本轮未扩大格式修改；日志
`/private/tmp/director-review-final-static.log`。真实浏览器与业务模型仍未执行。

交付：修复提交 `a12c80169` 已推送至 `origin/codex/director-scales-impl`，
[PR #255](https://github.com/FengHuoLinShan/ai-writing-assist/pull/255) 已创建。固定提交的
`make repo-gates docs-check BASE_REF=origin/main` 通过（文件大小门禁 2 条非失败 warning）；
与当时 origin/main `083843474` 的 merge-tree 无冲突。未合并、未部署；远端 CI 不以本地门禁代替。

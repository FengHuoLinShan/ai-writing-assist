---
id: T-20261016-editorial-diagnosis-v1
title: 编辑审读诊断 A/B 试跑与盲评交接
status: active
created: 2026-10-16T18:02:35+08:00
updated: 2026-10-16T21:04:00+08:00
---

# 编辑审读诊断 A/B 试跑与盲评交接

## 恢复快照

- 目标：实施对照试跑工程补缺，用 Codex gpt-6-luna/max 完成旧/新提示词冒烟及全量运行；交付盲评包与 HANDOFF，等待作者另开 Claude Sonnet 5.5 任务评分。本轮不做评分。
- 工作树：/Users/tywww/项目/ai-writing-assist/.worktrees/editorial-diagnosis-v1；分支 codex/editorial-diagnosis-v1。
- 已有提交：第一阶段 04424535a2a164f0274aee2f65dd8d300b3f236f（提示词、桥接、v2）。
- 候选组固定提交：c0a32c7778ab4faaaa9f949ef8ba8a7de0606318；基线提示词来自 00d861283e34bdc0ef3f34ee5605c71e1f89c553。
- 数据库/runtime 已配置：该工作树忽略的 `backend/.env`（0600）指向本机 PostgreSQL 17 `127.0.0.1:18442/codex_luna_runtime_test`，并固定 `APP_ENV=development`、`AUTH_MODE=local`、`CODEX_CLI_COMMAND` 为本机 v0.163.0 可执行文件；只读连通核验通过，账户连接数据仍留在该专用库。
- 新持久私有目录：`/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016/`，root/raw/blind/mapping 均为 0700；旧 `/private/tmp/novelcraft-editorial-diagnosis-v1-run-20261016/` 请求数为 0，弃用且不删除。
- 连接验证与原因：在默认工作区沙箱内有2次 synthetic ready 尝试以 exit_code=1 / `codex_result_unknown` 结束，无 CLI event 或 `turn_started`，用量未知、无 request_id；之后以提权进程执行同一 `SettingsService().connect_account_llm_provider(db, "codex", None)` 成功1次。三次均只用 ChatGPT 订阅的 gpt-6-luna/max ready 请求，不含稿件，单独记账、不计入406。错误分类显示外层沙箱阻止 Codex CLI 写 PATH alias（`Operation not permitted`）；提权执行后 `codex-text-v3` 成功，未改适配器。
- 连接只读核验通过：active provider=`codex`，model=`gpt-6-luna`，`connected=true`，`verified_at=2026-10-16T12:50:51.946704+00:00`。
- 新持久私有目录 manifest hash `d2a86df68d7f09ca9ce50362a360ccfabef66e7657980e3fa6595ef5e7c5fe48`，29例、上限406。S01 冒烟启动后在 assistant submit 前置路径遇到 `AttributeError`；没有评测 provider 请求（request_count=0、observations=0），case 已标 `stopped`，不重放。仅生成一份 baseline `started` 元数据；blind/mapping 为空。旧 `/private/tmp` 目录请求数仍为0，弃用且不删除。
- 当前进度：旧账本中的 S01 保持 `stopped` 且不重放。离线复核确认 owner/profile、Project facade client、审读提交和快照校验通过；运行器遗漏 `register_task_handlers()`，已在 eval runner 补齐既有应用启动注册。此前 raw 只保留 `started` 元数据，未保存异常栈，因此不能断言该缺口就是历史 `AttributeError` 的唯一来源；新账本需重新冒烟验证。
- 下一步：将 runner 修复与本次任务记录本地提交，使用新私有运行目录和固定候选提交执行 S01 两组冒烟；只有两臂输出、validator 与请求回执均通过后才继续其余样本。

## 范围与边界

- 新增 editorial_cases_v3.json，保留 v1/v2；29 例标注 report、no_report 或 unchecked，增加与主要约束对应的原创正例。评分按正例召回、对照误报和 unchecked 正确率分开报告；零意见基线为 0/11 命中、11/11 漏报、0/17 误报、0/1 unchecked 正确。
- 新增仅在 backend/evals 使用的运行器：冻结基线 _SYSTEM 与候选固定提交 _SYSTEM；同一 Assistant worker、validator、来源和范围，仅切换系统提示词；两臂顺序随机。
- 只用本机专用 codex_luna_runtime_test PostgreSQL 与已验证的 owner Codex 连接。每请求经 modules.project.facade.open_project_llm_client() 核验 codex/gpt-6-luna/max；不符即停、不回退。
- 总请求硬上限：29 × 2 × 7 = 406，冒烟计入。case 启动与请求预留先持久化；出错、未知用量、进程中断均不重放；同一外部依赖连续 3 次失败暂停全局。
- 原始结果与 blind 映射仅存仓库外私有目录；本轮不评分，不 push、不开 PR、不合并、不部署。

## 决策与实现

- 已定：不新增 mismatch_type，不加风格偏好/伦理入口，不新增结构改写路径；只切换提示词；审美偏好默认不报。
- v3 替换重复 v1 情节的 S01 为伤势连续性冲突；新增客观记录、明示谜题、复仇、连载承诺、主动主角目标等正例，另有制度性被动人物对照。新文均为原创合成文本。
- editorial.py 有内部执行 seam，允许 runner 注入系统提示词、假/真客户端及请求钩子；tasks.py 只从 db.info 读取该内部选项，不暴露 API 或设置。
- 同步提示词行为措辞、Prompt README 权威位置、盲评导入模型与测试。worker synthesis checkpoint 同步保留累计请求预算，避免合并写回时覆盖预算记录。
- 盲评包每份只用随机 blind ID；映射放在 blind/ 外。HANDOFF 禁止给出分组、候选 SHA、分支或映射路径。

## 进度与验证

- [x] v3 数据、分母标签、零意见基线及哈希测试。
- [x] Luna 对照运行器离线实现：database gate、owner/Project facade profile 核验、wrapper manifest、全局请求账本、失败/未知/中断停止、不重放、随机化、原始输出与 blind 文件权限。
- [x] review.py 15 项盲评导入 schema 与契约测试；Assistant fake-client 注入测试。
- [x] 定向 Assistant 与评测测试：186 passed（2026-10-16）；make lint 通过；make prompt-contracts 26 contracts 通过。
- [x] 补测（已随 `c0f4fd2` 提交）：新增 `test_editorial_execution_hooks.py` 17 项，覆盖提示词传递、多章请求边界与累计预算、注入客户端、失败/未知/取消/来源变化及单方向意见；修复 `_synthesize()` 合并进度覆盖累计请求预算的问题。新增17项通过，结合相关旧审读/桥接测试共48 passed，`make lint` 通过；定向覆盖率从78.1%升至84.2%，未重跑标准全库覆盖率门禁，不据此宣称全库覆盖率通过。
- [x] `TEST-COVERAGE.md` 的补测要点已并入本节，源文件已删除；原内容对应的补测代码已在 `c0f4fd2` 提交。
- [x] git diff --check 通过。make docs-check BASE_REF=origin/main 因 module-tasks 规则列出 3 份未变文档；按维护流程以无当前架构影响说明复跑 scripts/check_architecture_docs.py 并通过。理由：只增加 Assistant 评测专用 db.info 钩子；任务注册、队列/租约/生命周期、API、跨模块契约及恢复语义未变，Assistant 与 Prompt README 已同步。
- [x] 工程与数据本地提交：c0f4fd2b28237ff6ce1ed35c45d2644cf2a95a4c；Project profile mismatch fail-closed 修正：c0a32c7778ab4faaaa9f949ef8ba8a7de0606318。候选提示词固定于后者。
- [x] 配置专用数据库 URL，并用 PostgreSQL 17 做只读连通核验；数据库目标为 `codex_luna_runtime_test`，没有触碰主工作树应用库。
- [x] 重跑 S01 两臂预检；第一次在 owner 连接门禁停止，request_count=0。
- [x] 创建持久私有目录与 0700 子目录；生成新的 manifest/state，文件权限0600，固定 candidate SHA、数据集及随机次序，request_count=0。
- [x] 连接验证：两次默认沙箱尝试未知，一次提权后验证成功；四项 profile 只读核对通过。真实生成总计3次，均为合成 ready，不计入406。
- [x] 启动 S01 两臂 smoke；在评测请求预留前遇 `AttributeError`。request_count=0，无 provider attempt；case 已停止，不重放。
- [x] 离线复核 Project facade profile、审读提交、来源快照与 wrapper snapshot；确认 eval runner 缺少 `register_task_handlers()`，现已补齐既有应用启动注册，避免 inline runner 无 task handler。
- [x] 修复后定向 Assistant/评测/任务注册测试 77 passed；`make lint`、`make prompt-contracts`、基础 `make docs-check`、`git diff --check` 通过。`make docs-check BASE_REF=origin/main` 列出既有 module-tasks 文档核对项；使用正式 checker 加无当前架构影响说明后通过。
- [ ] 将修复提交为新的固定候选提交，在独立私有运行目录重跑 S01 两组 smoke；旧账本与旧 S01 不重放或改写。
- [ ] 生成私有盲评包和 HANDOFF；不运行评分。

## 试跑产物路径

- 私有运行根目录：/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016/
- 原始输出：/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016/raw/
- 盲评包：/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016/blind/
- 盲号映射：/Users/tywww/novelcraft-private/editorial-diagnosis-v1-run-20261016/mapping/blind-map.json
- 盲评交接：本目录的 HANDOFF-blind-review.md；此文件不得包含映射路径。
- 新私有根目录及 raw/blind/mapping 子目录权限均为 0700；manifest/state 为0600，request_count=0、无 observation。raw 只有 `S01_hard_contradiction.baseline.json` 的 started 元数据，没有审读输出；blind/mapping 为空。旧 /private/tmp 运行目录 manifest/state 保留但弃用，请求数为0。

## 最终交付状态与下一步

Codex 连接已验证并通过四项 profile 检查；真实评测运行时外层进程需有权启动 CLI 自身的只读沙箱。旧 S01 保留为停止态，0 次评测请求，不修改旧账本。runner 缺少既有 task handler 注册现已修复并通过离线回归；下一步在新私有目录和新的固定候选提交上重新做 S01 smoke，成功后继续全量。盲评包和 HANDOFF 尚未生成，不评分。

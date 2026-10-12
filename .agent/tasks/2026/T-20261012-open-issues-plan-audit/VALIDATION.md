# Issue 修复验证与复审

固定提交：`7641b7492e05fc3375acb995440b5e453bd03fa9`。
基线：`af731b0392e8df2012741d14d8d9d3f942f570e5`，工作树为 `codex/guided-flow-integration`。

## Issue 处理结果

- #208：Scene 消费登记将缺失来源的一组章节一次批量读取。缓存命中只补缺失/不完整/不同前序基线的登记，完整有效绑定不重复查稿或刷新登记时间；前序 checkpoint 身份变化仍重登记，不将旧稿洗成新鲜。
- #210：回执身份保留来源指纹、消费者集合及影响范围，去除运行/时间/清理数量等临时详情；真正换来源仍是新通知。保存改用既有 `(novel_id, receipt_id)` 唯一键原子 `ON CONFLICT DO NOTHING` 并回读首次记录，保留已解决状态，外层事务仍可使用。
- #111：自定义 Project repository 不再绕过 RP 引用计数，缺 DI 失败关闭。来源/锚点/对象/旅程 GET/list 只投影状态；歧义确认、绑定和失败重试在 mutation 刷新并物化；来源创建及导入按项目排他锁先行，重复 manifest 复用同一资料/任务。ORM JSONB/default 对齐已有 migration，无新 migration。eval-fast 原本已覆盖 RP eval，验证既有入口而不新增 runner。
- #209：已经 PR #211 合 main，当前集成头包含其 merge commit。原生 critical 中已有该 Issue 的规模/新鲜度/并发用例，本次复核通过，不重复实现。

四个 GitHub Issue 仍 open；本次没有发布 comment/close/PR，没有推送、合 main 或部署。

## 最终证据

- 最终 `make test-ci`：后端 **7683 passed, 2 skipped, 14 warnings**，覆盖率 **86.74%**；前端 **2964 passed / 237 files**；部署脚本 **272 passed**。命令退出 0。日志 `/tmp/issues-plan-audit-test-ci-final.log`。
- 受影响第一轮模块 **973 passed, 2 deselected**；修复读写衔接后 Interaction + owner 路由闭合 **200 passed, 2 deselected, 1 warning**。来源真实调用链单组 26 passed。
- 新增原生 PG 测试 **4 passed**：通知竞争同一行且事务可用；重复来源公共 API 只入队一次；failed task 经 GET 无写投影后并发重试只再入队一次；迁移/ORM JSONB 和数据库默认值一致。与 RP 来源历史/FK 两项共 **6 passed**。最终 `make test-postgresql-critical` **95 passed**，日志 `/tmp/issues-plan-audit-pg-critical-final.log`；包含 #209 的实际1/10/100场查询增长与计划验证。
- `make eval-fast`：**213 passed, 2 skipped**，现有 `evals/tests/test_rp_context.py` 确实在收集范围。
- Ruff、修改文件 format、前端 eslint/build、仓库 gates 和依赖棘轮通过。棘轮 `function_level_imports=524/524`；file-size gate 对既有 Writing services 大文件保留 warning。
- `make docs-check` inventory 通过；要求执行的 `make docs-check BASE_REF=origin/main` 命中文档影响规则，剩七份当前无变化文档。逐项核对后使用检查器已有 `--no-change-reason` 通过，日志 `/tmp/issues-plan-audit-docs-reviewed-final.log`；没有改检查器、伪更新文件或隐去裸命令的失败。理由：CLAUDE 只导入、Evidence indexing 检索/嵌入不变、模块拓扑/基础设施不变、文档维护协议不变、Map 稳定来源与可见接口不变。实际所有权文档及 Interaction/Memory 文档已同步。
- `git diff --check` 通过。

## 双轴复审

既有 code-review skill 的两名只读 reviewer 独立复核 Standards/Spec，并绑定最终提交通过。首轮发现 GET 纯投影后歧义确认及失败重试未物化，锚点/对象列表仍读旧清单；全部在最终提交中修正并新增调用链及 PG 竞争回归。未发现剩余可操作问题。review 没有代跑或代签真实模型、质量、作者验收或生产性能压测。

## 保护与限制

- 原 `/Users/tywww/Desktop/项目/ai-writing-assist` 的 **57** 个修改/未跟踪文件 SHA256、原 HEAD、暂存 diff SHA256、同格式 Git status 全部与会话执行前快照相同；证据 `/tmp/issues-plan-audit-original-wip-verification.json`。
- 旧引导任务记录/审查报告保留未提交。新修复代码、测试与所属文档是本地提交；新任务记录亦留未提交，不扫入旧 WIP。
- 仅专属 PG17+pgvector 的端口 **18432** / `guided_flow_integration_test` 合成数据验证；没有连接/改写共享 5432 或真实 Guimi 数据。测试替身仅代替来源/任务入队，不调用 provider。
- 最终已停止本任务集群，数据目录 `/tmp/codex-guided-flow-20261012-pg` 与日志保留；未删除任何数据库或工作树。
- 没有重跑浏览器：前端实现与 wire schema 未变化，既有浏览器证据不冒充本次复跑。GET→确认/匹配/对象/失败恢复通过实际后端服务及原生 DB 回归。
- 未运行真实模型、真实稿件、封存盲验、作者试用或生产负载；这些边界仍未验收。计划差距见 [完整性核查](PLAN-COMPLETENESS.md)。

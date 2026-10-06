# 架构分支文档影响复核

范围：`origin/main`（77620459d）至架构分支原 HEAD e2484606d，以及本次 review 修复。

- [x] 已运行 `make docs-check BASE_REF=origin/main`
- [x] 已逐项核对未更新文档，确认无当前架构影响

无影响说明（勾选第三项时必填）：已对照固定基线与运行时调用链逐项复核；依赖棘轮、Project provider、World与Local Agent实现归属、账户CLI、worker schema/pgvector及Vite模块代理已同步对应权威文档。其余文档描述的模块资产归属、HTTP路由/wire、owner与novel_id门禁、confirmation/hash、队列协议和作者流程保持兼容；细项见下。

## 已更新的当前事实

- `docs/architecture/README.md`：冻结实际方向集合，禁止删旧边抵消新边。
- `backend/modules/project/README.md`：工作台统计经消费方 Protocol/组合根 provider。
- `backend/modules/world/README.md`：别名元数据与地图只读编排归服务层。
- `backend/modules/local_agent/README.md`：executor_service 实现，facade 稳定再导出。
- `backend/modules/account/README.md`：独立 CLI 的 DI 装配入口。
- `backend/infrastructure/tasks/README.md` 与 `docs/modules/12_infrastructure.md`：常驻 worker schema fail-closed，以及生产 API pgvector fail-closed。
- `docs/modules/14_frontend.md`：API 领域模块与 Vite dev proxy 的边界。
- 原分支的数据库、Prompt绑定、Evidence/Story/World模块和 ADR 更新保留；修复不新增表、迁移、路由、任务或Prompt。

## 未改文档逐项核对

- `CLAUDE.md`：仅导入 AGENTS，入口和权限规则未变。
- `CONTEXT.md`：账户/项目、资产状态、来源/confirmation、采用与知识边界未变。
- `docs/00_整体设计.md`：模块化单体、数据所有权、稳定接口和部署拓扑未变；依赖方向事实以已更新 architecture README 与 ADR-0031 为准。
- `docs/architecture/module-architecture.drawio`、`docs/architecture/module-architecture.html`：表达产品职责分区，非实际 import graph；模块与产品职责未变，图源完整性门通过。
- `docs/architecture/documentation-maintenance.md`：复用既有的本地无影响核对机制，不改文档门禁或协议。
- `development-guide.md`：栈、命令、稳定入口、工具链与验证层边界未变；worker与Vite实现细节已就近维护。
- `testing-guide.md`：测试分层、PG隔离、85%覆盖率、RuntimeWarning及paid/manual边界未变；新增回归置于原对应层，未放宽任何验收规则。
- `backend/infrastructure/llm/README.md`：无provider请求协议、Key、预算、模型选择或重试改变。
- `backend/modules/interaction/README.md`、`docs/modules/18_interaction.md`：旅程与来源项目隔离、冻结版本、私人历史和已有HTTP行为未变。
- `backend/modules/writing/README.md`、`docs/modules/11_writing.md`：正文/发布状态、确认、保存副作用和来源失效语义未变；新DI默认实现仍为原facade函数对象。
- `docs/modules/15_map.md`：地图归属、CAS版本、来源重验与图片存储未变；搬迁两读取函数的AST除自导入外等价。
- `docs/modules/20_assistant.md`、`docs/modules/21_collaboration.md`：46个operation声明、授权、运行预算、来源与资源协议未变；原分支的解环只改变装配位置。
- `docs/modules/23_local_agent.md`：公开facade函数与设备owner/novel_id/lease语义未变，配置提交仍在原业务边界；实现归属在模块README更新。

## 验证与限制

`make docs-check` 完整性门通过。无PR event时，带base的make入口明确报缺少文档复核声明；随后使用同一检查器的正式 `--no-change-reason` 本地入口通过，保留必查清单warning。实际调用：

```sh
python3 scripts/check_architecture_docs.py --base-ref origin/main --no-change-reason '<本文件无影响说明>'
```

未来创建PR时须将上方checkbox与说明纳入PR正文；本次未创建PR，未伪造GitHub事件，未修改门禁实现。

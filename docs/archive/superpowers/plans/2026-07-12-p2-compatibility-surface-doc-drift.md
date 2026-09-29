# P2 兼容面与文档漂移收敛实施计划

> 日期：2026-07-12
> 来源：`docs/audit/2026-07-11-模块能力与跨模块需求分析.md` 的 P2
> 状态：已完成

## 1. 目标

在不改变 HTTP API、数据库 schema、前端 wire shape、候选/采用语义和跨模块
调用方向的前提下，完成四类收敛：

1. 让 project、writing、world、outline 的权威 README 与当前能力一致；
2. 让 `modules.world.contracts` 只承载稳定 dataclass contract，不再重导出 HTTP
   Pydantic schema；
3. 用显式 `__all__` 和回归测试冻结 world/outline root facade 公共面；
4. 删除经 deletion test 证明没有生产调用的兼容导出、wrapper 和零参数 LLM fallback。

## 2. 非目标与长期不变量

- 不删除仍承载待处理建议语义的 `candidate` 数据状态；
- 不移除仍被生产组合根、跨模块调用或迁移读取使用的 compatibility shadow；
- 不改变 `novel_id` 隔离、用户确认、软废弃、回滚和 schema 校验；
- 不改变 `/api/*` 路径、请求/响应字段、任务类型或数据库表；
- 不把 outline/world 子 facade 变成跨模块随意增长的新公共面；
- 不引入新依赖、类型检查器、框架或 ADR。

## 3. 当前代码核对

### 3.1 文档漂移

- project README 的底部“当前范围”已包含 effective LLM profile、execution
  snapshot、回收站和智能去重；本项只做一致性复核，不重复改写。
- writing README 首段仍声称“不负责 AI 自动生成完整正文”，与
  `POST /api/writing/generate` 的受控 candidate 生成能力冲突。
- world README 末尾仍以早期 CRUD “MVP”描述当前模块，遗漏建议队列、地图、知识边界、
  回滚和动态事实。
- outline/world README 尚未把 root facade 的冻结规则写成可验证约束。

### 3.2 World contract 和 package root

- `modules.world.contracts` 尾部重导出 10 个 `modules.world.schemas` Pydantic 类型；
  仓库内没有跨模块生产调用从 contracts 导入这些类型。
- `modules.world.__init__` 重导出 ORM、HTTP schema 和 facade 函数；仓库生产代码只通过
  `from modules.world import api/facade/...` 加载子模块，没有消费这些顶层符号。
- `DuplicateSuggestion` dataclass 只有测试使用，实际去重服务使用
  `schemas.DuplicateSuggestionResult`。

### 3.3 Facade hub

- outline root facade 已有显式 `__all__`；world root facade 没有。
- 生产调用仍广泛依赖 root facade 路径，因此本轮保留现有有效名字，只冻结新增面。
- outline repair facade 中下列四个函数没有生产或测试调用方：
  `reindex_scenes_for_deep_import_repair`、`get_deep_import_structure_counts`、
  `get_deep_import_structure_payload`、`ensure_deep_import_structure_minimums`。
- world `upsert_relationship` 明确标记为旧接口，只有专门测试调用；生产使用
  `upsert_relation` / `create_or_merge_relation`。

### 3.4 LLM 和其他 legacy helper

- world `EntityExtractionService` 的真实 DB 路径使用
  `open_project_llm_client()`；Mock-only 分支在缺项目上下文时仍零参数构造
  `LLMClient()`，应改为 fail-closed 的 project settings 构造。
- RAG `get_legacy_circuit_breaker()` 没有调用方；`get_circuit_breaker(None)` 已覆盖
  仍需保留的全局运行状态语义。
- RAG embedding 路径的 `LLMClient()` 是独立 `EMBEDDING_*` 配置边界，不在本次删除范围。

## 4. 实施批次

### P2.1 权威文档同步

- [x] writing 定位改为“正文事实源 + 受控 candidate 生成”；
- [x] 明确 writing 不自动采用、发布或覆盖正文；
- [x] 补充 `/api/writing/generate` 和 confirmation/provenance 语义；
- [x] world 删除早期 MVP 描述，改为当前范围；
- [x] outline/world README 写明 root facade 冻结规则；
- [x] project README 复核通过，无虚构改动。

验收：README 不再与当前 API/service 冲突；候选和正史边界表述保持一致。

### P2.2 World contract 与 root package 解耦

- [x] 删除 contracts 对 HTTP schemas 的重导出；
- [x] 删除无调用的 `DuplicateSuggestion` dataclass；
- [x] 给 contracts 增加仅含稳定 dataclass 的显式 `__all__`；
- [x] 将 `modules.world.__init__` 收敛为无业务符号重导出的 package 标记；
- [x] 增加 contract/root package 回归测试。

验收：跨模块稳定 dataclass 可继续导入；HTTP schema 只能从
`modules.world.schemas` 获取；应用组合根的子模块 import 不受影响。

### P2.3 Facade 公共面冻结

- [x] world root facade 增加显式 `__all__`；
- [x] outline root facade 保留显式 `__all__` 并添加冻结说明；
- [x] 添加精确 public API snapshot 测试；
- [x] 删除无生产调用的 outline repair wrapper；
- [x] 删除 world `upsert_relationship` wrapper 及专属测试。

新增公共函数的规则：先证明已有 root/sub-facade seam 无法表达，再更新拥有模块的
contract、README 和 public API snapshot；禁止为单一调用方增加 pass-through。

验收：现有生产导入全部可收集；snapshot 只包含已确认稳定函数；删除函数全仓无调用。

### P2.4 其他无调用 legacy 清理

- [x] 删除 `get_legacy_circuit_breaker()`；
- [x] 删除 world root package 的 ORM/schema/facade 重导出；
- [x] world Mock-only 抽取分支不再零参数构造 `LLMClient()`；
- [x] 更新相关单元测试，真实运行路径继续使用 project runtime seam。

验收：novel-scoped 文本 LLM 不出现新的 direct-client fallback；独立 embedding 边界不变。

## 5. 稳定接口和风险

| 接口 | 处理 | 风险控制 |
|---|---|---|
| HTTP API / Pydantic response | 不变 | API contract 与模块测试 |
| 数据库 schema / ORM | 不变 | 不新增迁移 |
| `world.facade` 有效生产函数 | 保留并冻结 | exact `__all__` snapshot |
| `outline.facade` 有效生产函数 | 保留并冻结 | exact `__all__` snapshot |
| world dataclass contracts | 保留 | import/构造测试 |
| candidate/review/canonical | 不变 | world/writing/outline 状态测试 |
| project LLM runtime seam | 不变 | extraction runtime lifecycle 测试 |

删除操作已经由用户明确授权；不需要 ADR，因为没有改变技术栈、模块归属或外部契约。

## 6. 验证

定向门禁：

```bash
cd backend
pytest tests/unit/test_facade_public_api.py \
  tests/unit/test_entity_facade.py \
  tests/unit/test_extraction_service.py \
  modules/world/tests/ modules/outline/tests/ -q
```

仓库门禁：

```bash
make test-collect
make test-fast
make test-integration
make test-frontend
make lint
cd backend && ruff format --check .
git diff --check
```

静态删除检查：

```bash
rg "DuplicateSuggestion|upsert_relationship|get_legacy_circuit_breaker"
rg "get_deep_import_structure_counts|get_deep_import_structure_payload"
```

预期仅允许历史文档中的说明性文本；生产 Python 不再定义或调用这些符号。

## 7. 完成标准

- [x] 所有 P2 条目均有代码或“已满足无需修改”的证据；
- [x] 无 HTTP/schema/wire/database 变化；
- [x] 所有被删 symbol 全仓生产调用数为 0；
- [x] facade 新增面被 exact snapshot 门禁阻止静默增长；
- [x] 定向与仓库级测试、lint、format、diff check 全通过；
- [x] 原审计文档回填 P2 完成状态和结果链接。

# Round 14/20 — Test Infrastructure / Fixtures / Mocking / Integration Coverage

**Status**: PASS  
**Goal**: 测试基础设施、Fixture 质量、Mock 模式、集成测试覆盖  
**Started**: 2026-07-13  
**Completed**: 2026-07-13  

## 结果总览

| 审计模块 | 发现数 | CRITICAL | HIGH | MEDIUM | LOW |
|----------|--------|----------|------|--------|-----|
| 测试基础设施 | ~5 | 0 | 0 | 3 | 2 |
| Fixture 质量 | ~7 | 0 | 1 | 2 | 4 |
| Mocking 模式 | ~3 | 1 | 1 | 1 | 0 |
| 集成测试覆盖率 | ~6 | 0 | 1 | 2 | 3 |
| **合计** | **~21** | **1** | **3** | **8** | **9** |

---

## 测试基础设施 — ~5 个发现（3 MEDIUM + 2 LOW）

**总体评价：优秀。** 隔离设计精良（savepoint + 外层事务回滚 + DI 重置 + 元测试验证）、分层清晰（单元→集成→E2E）、标记化良好。

🟡 MEDIUM: 无 `pytest.mark.slow` → 慢测试与快测试混合
🟡 MEDIUM: 缺 `pytest-xdist`（并行）和 `pytest-timeout`（挂起防护）
⚪ LOW: `pytest-cov` 已安装但未配置（无阈值、无报告配置）
⚪ LOW: filterwarnings 仅忽略 DeprecationWarning（过于宽松）

✅ conftest 11 个、markers 5 个（api/integration/e2e/real_llm/external_data）、asyncio 模式正确
✅ 元测试验证 savepoint 回滚、DI 清理、conftest 不冲突

---

## Fixture 质量 — ~7 个发现（1 HIGH + 2 MEDIUM + 4 LOW）

🔴 **HIGH**: 8 处 `@pytest.fixture` + `async def` 混用（应 `@pytest_asyncio.fixture`）— 未定义行为，asyncio 版本升级可能产生偶发失败
🟡 MEDIUM: `ctx` fixture 在 E2E 测试中 ~20+ 次重复定义，内容高度相似
🟡 MEDIUM: `factory` fixture 在 settings 和 project 模块重复定义（逻辑分歧风险）
⚪ LOW: `sample_novel_id` 类型不一致（str vs uuid.UUID）
⚪ LOW: `service` fixture 在 `test_extraction_service.py` 中 ~30 行 mock 装配过于复杂

✅ 隔离/清理 9/10、命名 6/10、性能 8/10、正确性 7/10、文档 9/10
✅ autouse fixture 全局副作用正确清理（`try/finally`）、DB 回滚机制优秀

---

## Mocking 模式 — 3 个发现（1 CRITICAL + 1 HIGH + 1 MEDIUM）

🔴 **CRITICAL**: **生产代码检测并响应 Mock** — 4 个生产文件（7 处）使用 `isinstance(db, Mock)` 改变行为 → 测试未验证真实代码路径
  - `modules/imports/workflow.py:17` — 模块级 `from unittest.mock import Mock`
  - `modules/imports/orchestrator.py:514,541`
  - `modules/imports/workflow_llm_adapters.py:287`
  - `modules/world/services/core/extraction_service.py:81`

🔴 **HIGH**: `autospec=True` **零使用** — 150+ 个 `@patch` 调用无 API 形状验证，签名变化时 mock 不失败
🟡 **MEDIUM**: Mock 私有符号（`_relation_service`、`_repo` 等）而非公共接口 — 与实现细节耦合

✅ `side_effect` 错误路径覆盖 100+ 处、`spec=AsyncSession` 69 处、`assert_awaited_once` 100+ 处
✅ AsyncMock 正确使用、`with patch()` 上下文管理约占 70%

---

## 集成测试覆盖率 — ~6 个发现（1 HIGH + 2 MEDIUM + 3 LOW）

### 全局统计
| 层 | 文件数 | 用例数 |
|----|--------|--------|
| 后端 pytest | 235 文件 | ~3,972 |
| 前端 Vitest | 58 文件 | ~1,058 |
| 前端 Playwright | 34 文件 | ~140 |
| **总计** | **327 文件** | **~5,170** |

🔴 **HIGH**: `core/` + `shared/` 层测试严重不足 — 8 个 core 模块仅 `crud.py` + `errors.py` 有测试；`config.py`、`database.py`、`container.py`、`dependencies.py` 等关键基础设施零测试
🟡 MEDIUM: 无跨模块 E2E 串行场景（导入→生成→发布→检索分散在独立 spec）
🟡 MEDIUM: 无并发/压力测试，混沌测试不在门禁中
⚪ LOW: `memory` 无 API 层测试、`rag` 无独立 API 层测试
⚪ LOW: `@pytest.mark.skip` = 0、`# TODO` in tests = 0（标记管理良好）

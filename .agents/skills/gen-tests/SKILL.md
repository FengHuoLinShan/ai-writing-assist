---
name: gen-tests
description: AI 辅助测试生成 — 为后端 Python/pytest 和前端 Playwright E2E 生成高质量测试代码。遵循项目测试约定，智能分析代码并生成覆盖完整分支的测试用例。适用于生成测试、补充覆盖率、为遗留代码补测试。
---

# gen-tests — AI 辅助测试生成

基于《AI 辅助测试生成的工程方法论》构建的系统化测试生成技能。遵循 STRA 框架（Situation-Task-Result-Action）引导 AI 生成高质量测试。

## 执行流程

```
1. 读取目标源文件，识别所有公开函数/类/方法
2. 检查项目测试约定（conftest fixtures、Mock 策略、命名规范）
3. 分析代码控制流，列出所有分支路径和边界条件
4. 生成测试代码（遵循 AAA 模式）
5. 自检：导入有效性、fixture 引用、覆盖率缺口
```

## 项目测试约定速查

### Python 后端 (pytest)

| 项 | 约定 |
|----|------|
| 框架 | pytest + pytest-asyncio (`asyncio_mode = "auto"`) |
| Mock | `unittest.mock.patch` / `MagicMock` |
| DB 测试 | SQLite 内存 (`aiosqlite`)，复用 `conftest.py` 的 `db_session` / `async_client` |
| 参数化 | `@pytest.mark.parametrize` |
| 命名 | `test_{function_name}_{scenario}_{expected_behavior}` |
| 导入 | 通过 facade 导入，不直接 import repositories/services/models |
| 测试范围 | 单元测试在 `unit/`，集成测试在 `integration/`，E2E 在 `e2e/` |
| 可用 fixtures | `db_session`、`async_client`、`test_project_id`、`test_entity_id`、`test_character_id` |

E2E 测试使用真实 PostgreSQL (`tests/e2e/conftest.py`)，**不可**混用 SQLite conftest。

### 前端 E2E (Playwright)

| 项 | 约定 |
|----|------|
| 选择器 | 统一使用 `SEL` 常量（`e2e/helpers/selectors.js`），禁止硬编码选择器 |
| 命名 | `test('should {expected behavior}', ...)` |
| 文件 | 每个 spec 文件对应一个视图/功能域 |
| fixtures | 使用 `testProjectId` 等共享 fixture |
| Mock | 拦截 `**/api/**` 路由 mock API 响应 |

## Prompt 模板库

### 模板 1：Python 单元测试生成

```
角色：资深测试自动化工程师

任务：为以下 Python 函数生成 pytest 单元测试。

要求：
- 遵循 AAA 模式（Arrange-Act-Assert）
- 测试名称格式：test_{function_name}_{scenario}_{expected}
- 覆盖：happy path、所有边界条件、所有异常路径
- 使用 unittest.mock.patch 隔离外部依赖
- 目标分支覆盖率 >= 80%

项目约定：
- 通过 facade 导入被测函数
- DB 相关测试使用 conftest.py 的 db_session / async_client fixture
- 异步测试使用 pytest-asyncio（asyncio_mode = "auto"）

被测代码：
{code}

依赖接口（仅签名）：
{dependencies}

请先分析代码的控制流和边界条件，然后生成测试。
```

### 模板 2：边界条件探索

```
角色：边界条件分析专家

任务：分析以下函数的所有边界条件并生成测试。

分析步骤：
1. 数值边界：None、0、负数、极大值、极小值、溢出风险
2. 字符串边界：空字符串、None、超长字符串、特殊字符、Unicode
3. 集合边界：空列表/字典/集合、单元素、大量元素
4. 类型边界：None、错误类型、类型转换边界
5. 状态边界：未初始化、已删除、已过期状态

被测代码：
{code}

为每个识别到的边界条件生成独立的测试函数。
```

### 模板 3：覆盖率驱动补充

```
角色：覆盖率补充专家

场景：当前文件 {file_path} 的分支覆盖率为 {current_coverage}%。
以下分支未被覆盖：

{uncovered_branches}

任务：为以上未覆盖分支生成测试用例。
要求：
- 每个未覆盖分支至少 1 个测试用例
- 测试必须实际执行到目标分支
- 遵循项目已有的测试风格和 fixture 使用方式

现有测试文件参考：
{existing_test_code}
```

### 模板 4：回归测试（Bug 修复后）

```
角色：回归测试专家

场景：以下 Bug 已被修复，需要生成回归测试。

Bug 描述：{bug_description}

修复前代码：
{code_before}

修复后代码：
{code_after}

任务：生成一个测试用例，复现修复前的错误行为（应失败），
并验证修复后不再发生（应通过）。
```

### 模板 5：Playwright E2E 测试生成

```
角色：E2E 测试工程师

任务：为以下前端功能生成 Playwright 测试。

要求：
- 使用 e2e/helpers/selectors.js 的 SEL 常量，禁止硬编码 CSS 选择器
- 命名：test('should {expected behavior}', ...)
- API 调用使用 page.route() mock 拦截
- 遵循项目现有的 spec 文件风格

功能描述：{feature_description}

页面关键元素：
{elements}

请先列出用户操作路径和预期状态变化，然后生成测试。
```

## Few-Shot 示例

### 被测代码示例

```python
# backend/app/modules/project/services.py
async def validate_novel_title(title: str | None) -> str:
    if not title:
        raise ValueError("小说标题不能为空")
    title = title.strip()
    if len(title) < 2:
        raise ValueError("小说标题至少需要 2 个字符")
    if len(title) > 100:
        raise ValueError("小说标题不能超过 100 个字符")
    return title
```

### 生成的测试示例

```python
# backend/tests/unit/test_validate_novel_title.py
import pytest
from modules.project.services import validate_novel_title

class TestValidateNovelTitle:
    def test_validate_novel_title_valid_input_returns_stripped(self):
        result = validate_novel_title("  三体  ")
        assert result == "三体"

    def test_validate_novel_title_none_raises_value_error(self):
        with pytest.raises(ValueError, match="不能为空"):
            validate_novel_title(None)

    def test_validate_novel_title_empty_string_raises_value_error(self):
        with pytest.raises(ValueError, match="不能为空"):
            validate_novel_title("")

    def test_validate_novel_title_too_short_raises_value_error(self):
        with pytest.raises(ValueError, match="至少需要 2"):
            validate_novel_title("一")

    def test_validate_novel_title_min_length_boundary_passes(self):
        result = validate_novel_title("三体")
        assert result == "三体"

    def test_validate_novel_title_too_long_raises_value_error(self):
        with pytest.raises(ValueError, match="不能超过 100"):
            validate_novel_title("长" * 101)

    def test_validate_novel_title_max_length_boundary_passes(self):
        result = validate_novel_title("长" * 100)
        assert result == "长" * 100

    @pytest.mark.parametrize("title", [
        "三体",
        "a" * 2,        # 最小长度
        "a" * 100,      # 最大长度
        "  流浪地球  ",  # 需要 strip
    ])
    def test_validate_novel_title_valid_titles(self, title):
        result = validate_novel_title(title)
        assert isinstance(result, str)
        assert len(result) >= 2
```

## 质量门控检查清单

AI 生成测试后，逐项检查：

### 编译/语法
- [ ] 所有 import 语句有效，引用的模块/函数存在
- [ ] 引用的 fixtures 在 conftest.py 中存在
- [ ] 异步函数正确使用 async/await

### 测试设计
- [ ] 测试名描述具体场景和预期行为
- [ ] 遵循 AAA 模式，三段清晰可辨
- [ ] 外部依赖正确 Mock（无真实 I/O、无真实网络调用）
- [ ] 边界条件覆盖完整（null、空值、极值、特殊字符）
- [ ] 所有显式 raise 的异常都有测试

### 质量
- [ ] 测试间相互独立，无执行顺序依赖
- [ ] 无过度指定的 Mock 验证
- [ ] 无硬编码敏感数据
- [ ] 每个测试只验证一个行为

## 分层防御

AI 生成测试后，按以下三层验证：

1. **自动化验证**（100% 自动）：编译检查 → 运行测试 → 覆盖率对比
2. **AI 辅助审查**（60-70% 错误可被捕获）：用第二个视角检查逻辑正确性、边界完整性和 Mock 合理性
3. **人工审查**（核心业务逻辑）：涉及资金/安全/关键业务的测试必须人工确认

## 停止条件

- 达到目标覆盖率
- 连续 3 轮无覆盖率提升（覆盖平台期）
- 达到最大迭代次数（默认 5 轮）

## 注意事项

- **不生成已知不可编译的代码**：先确认被引用的函数/类/模块存在
- **不生成重复测试**：避免覆盖同一路径的冗余用例
- **首条分析，再生成**：先生成测试计划（列出所有要覆盖的场景），再编写代码
- **后端 E2E 不同 conftest**：`tests/conftest.py` (SQLite) 和 `tests/e2e/conftest.py` (PG) 不可混用

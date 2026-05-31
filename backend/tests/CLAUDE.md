# CLAUDE.md — backend/tests

## 测试分层

- `tests/conftest.py` → SQLite 内存，用于 API 测试和集成测试
- `tests/e2e/conftest.py` → 真实 PostgreSQL，用于 E2E 测试
- 两种 conftest 不可混用：SQLite 和 pgvector 的 embedding 列类型不一致

## E2E 约定

- 不 mock LLM；真实 LLM 调用集中在 `test_extraction_real_file.py`
- 每个测试独立连接 + 事务回滚（见 `e2e/conftest.py` 的 `db_session` fixture）
- `seed_data.py` 使用旧 characters schema（`id`+`world_entity_id`），新增测试直接适配 `entity_id` 即可

## 模块级禁止事项

- 不绕过 facade 直接 import repositories/services/models 做断言
- 不捕获 conftest 中的模型导入错误而吞掉；新增模块时同步 conftest import 列表

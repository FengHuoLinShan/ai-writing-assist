# CLAUDE.md — backend/tests

## 测试分层

- `backend/conftest.py` → 共享 SQLite schema、每例事务回滚、DI 与 FastAPI override 清理
- `tests/e2e/conftest.py` → 真实 PostgreSQL，用于显式 E2E 测试；连接或 Alembic head 不满足时失败
- 两种 conftest 不可混用：SQLite 和 pgvector 的 embedding 列类型不一致

## E2E 约定

- `make test-e2e` 只运行确定性 PostgreSQL 行为；真实模型与真实语料必须使用 `make test-manual`
- 每个测试独立连接 + savepoint/外层事务回滚（见 `e2e/conftest.py` 的 `db_session` fixture）
- `seed_data.py` 使用旧 characters schema（`id`+`world_entity_id`），新增测试直接适配 `entity_id` 即可

## 模块级禁止事项

- 不绕过 facade 直接 import repositories/services/models 做断言
- 不捕获 conftest 中的模型导入错误而吞掉；新增模块时同步 conftest import 列表

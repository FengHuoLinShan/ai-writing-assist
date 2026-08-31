# AGENTS.md — backend/tests

- `backend/conftest.py` 提供 SQLite schema、每例事务回滚和 DI/FastAPI override 清理；
  `backend/tests/e2e/conftest.py` 只接受显式专用 PostgreSQL。两套 fixture 不得混用或回退开发库。
- 测试目标模块内部状态机、查询或事务时可以直接导入该模块 implementation；跨模块行为优先从
  facade、DI port 或 HTTP 断言。conftest/seed 的 model import 只用于 ORM metadata 与数据准备。
- SQLite 与 PostgreSQL 的 embedding/并发语义不同；唯一性、CAS、advisory lock、lease、提交可见性
  和 pgvector 行为必须进入显式 PostgreSQL 层，不能用 SQLite 绿色替代。
- `make test-e2e` 只运行确定性 PostgreSQL 行为；真实模型、付费调用和用户语料使用对应显式
  manual target，不得静默进入默认测试。
- 新增模块或外键模型时同步必要 metadata import；不得吞掉模型导入、连接清理或 RuntimeWarning。

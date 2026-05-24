-- ============================================================
-- AI 长篇小说结构化创作引擎 — 数据库初始化脚本
-- 目标: PostgreSQL 17 + pgvector + pg_trgm
-- ============================================================

-- 扩展安装 (需超级用户权限)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 验证安装
SELECT
    (SELECT extname FROM pg_extension WHERE extname = 'vector') AS vector_installed,
    (SELECT extname FROM pg_extension WHERE extname = 'pg_trgm') AS pg_trgm_installed;

-- 注意：所有表通过 SQLAlchemy ORM 自动创建
-- 运行以下命令来初始化表结构：
--   cd backend && alembic upgrade head
-- 或首次直接创建:
--   cd backend && python -c "
--     from core.database import DatabaseManager
--     from core.base import Base
--     import asyncio
--     async def init():
--         mgr = DatabaseManager()
--         mgr.init()
--         async with mgr.engine.begin() as conn:
--             await conn.run_sync(Base.metadata.create_all)
--         print('All tables created successfully')
--         await mgr.close()
--     asyncio.run(init())
--   "

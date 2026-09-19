# Demo copy 不变量审计与交付核查

核查基线：2026-09-19 整合分支（从 `origin/main` `d66eb40cb` 开始）。本报告的代码结论以当前
源码、migration 和测试为准；生产数据仅引用 2026-09-17 任务记录中的历史只读快照，未在本轮重查。

## 1. 根因与 D1 触发器台账

旧复制流程试图 DELETE 目标 `world_canon_revisions` 的初始化记录，并在跨表/自引用 FK
未齐时先 INSERT 占位再 UPDATE。前者撞上 Canon 不可变触发器；后者会撞上 Outline 修订
的 UPDATE 触发器。`20260827_world_authority_phase0.py` 为 `world_assertions`、
`world_canon_revisions`、`entity_profile_template_revisions`、`world_bible_page_revisions`
安装 UPDATE/DELETE 守卫（项目删除级联有专用例外）；`20260913_schema_parity_repair.py`
拒绝 `story_outline_revisions` 的 UPDATE；`20260908_unified_map.py` 仅拒绝
`map_atlas_revisions` 内容字段修改，审查状态仍可变。不能把这些约束简化成所有历史表
一律禁止任何 DELETE/UPDATE。

## 2. 数据模型与 D2 写路径扫描

当前 `demo_copy.py` 先预分配目标 ID，再计算全图引用与目标快照摘要，按表及行依赖顺序
INSERT；仅 `_move_pointer_references` 更新可空、白名单内的当前修订指针，地图页面的
可变存储键另有 UPDATE。对上述六类修订模型执行的生产代码静态搜索未发现直接
`update(Model)`、`delete(Model)` 或对应文字 SQL；这不是动态 SQL 的形式证明，故另以
语句监听器和真实 PG 触发器测试封住复制路径。

## 3. 风险清单与 D3 生命周期

已修：来源 Canon 历史不能复制；改为目标 C0 后追加 `demo_import`，回执使用
`world.canon.demo-import` 策略。已修：含关联资产 UUID 的 World Bible 快照在复制时
会被重写，摘要现在按重写后的快照计算。仍有明确边界：源 manifest 含 formal assertion
时返回 `demo_assertion_transfer_unsupported` 409，不伪装成功；媒体写入失败执行逆序
清理，数据库复制仍以事务回滚。生产发布后的真实账号操作验收尚未执行。

## 4. 逐项处置

- Canon 修订清空重建：删除；来源 head 仅作为溯源，目标追加导入修订。
- 自引用修订占位回填：删除；行级拓扑排序后一次写入最终值，环报错。
- head/revision 表级 FK 环：只让可变 head 指针暂空并在修订插入后回指。
- 目标资源 digest：按目标 `novel_id`、资源 ID、修订 ID 和实际目标快照重算。
- 项目外泄：复制来源受配置、当前 owner 和项目门禁约束；身份映射覆盖 FK 与嵌入 JSON。

## 5. 不变量

目标修订行不发生 UPDATE/DELETE；目标 Canon head 只指向目标项目内修订；manifest
资源引用与其 revision digest 可经 World Authority 回放；复制失败不留目标项目或媒体；
同一 owner/source/version 请求幂等。公开 Admit 拒绝 `demo_import` 输入类型。

## 6. D5 测试覆盖矩阵

| 边界 | 可运行证据 |
|---|---|
| 表序、自引用链/DAG/环、目标快照摘要 | `modules/project/tests/test_demo_copy_table_order.py` |
| 资产映射、Canon 策略/回放、重试、媒体失败 | `modules/project/tests/test_demo_copy.py` |
| 真 PG 触发器、关联页 Canon 回放、失败回滚 | `tests/e2e/test_demo_copy_immutable_history.py` |
| 项目隔离、并发、迁移与任务约束 | `make test-postgresql-critical` |

本轮隔离库实测：demo-copy E2E 2/2、PostgreSQL 合并门禁 37/37；总门禁另见整合任务记录。

## 7. 遗留与适用边界

测试守卫的六表集合须随新不可变表或触发器更新；它只监听 SQLAlchemy ORM execute，
不能替代 PostgreSQL 触发器。Map 修订允许审查状态变化；`memory_events` 按章替换是
派生流，不归入不可变历史。formal assertion 的跨项目复制尚不支持，需单独设计授权与
身份转换后才能开放。

## 8. D4 生产残留

2026-09-17 原任务记录称当时 `demo_project_copies=0`，失败事务未留下目标项目；
这个快照未在 2026-09-19 复验，不用于推断当前生产状态。本轮没有部署或操作生产库。

## 9. 已消除的错误类别

复制前清空权威历史、在不可变修订上占位回填、复制后摘要与实际快照不一致、把来源
作者 receipt 当成目标授权，以及测试在无触发器的 SQLite 上误判复制成功。

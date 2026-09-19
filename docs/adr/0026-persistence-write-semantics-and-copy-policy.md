# ADR-0026: 持久化数据写入语义五分类与复制策略

## 状态

Accepted / Implemented

## 背景

线上 demo copy（`POST /api/projects/demo-copy`）对所有用户必现 500：复制协议按普通
CRUD 处理不可变历史——预清理 `DELETE FROM world_canon_revisions` 撞上
`trg_world_canon_revisions_authority_immutable` 触发器（BEFORE DELETE OR UPDATE）。
排查进一步发现同类隐患：`story_outline_revisions`（BEFORE UPDATE 触发器）等表存在
自引用 FK，而 demo copy 对这类列采用「INSERT NULL 占位、事后 UPDATE 回填」，该写法
在 UPDATE 即被触发器拒绝；「按表清空后重建」「占位回填」都是在用 CRUD 心智改写历史。

深层约束：`resource_revision_digest` 把 novel_id、resource_id、revision_id 与快照
一起哈希，canon receipt 绑定 novel_id/revision_id/parent/committed_at，回放校验
（`_validate_manifest_replay`）在每次 canon 读取时执行。因此任何 revision 原样带
旧 digest 复制到新身份都必然失配；重造 receipt 等于伪造作者授权溯源。

工程缺少一个统一的分类，让各 service 自行判断"这行数据能不能 UPDATE/DELETE"，
依赖开发者记忆与代码评审兜底，而不是由结构保证。

## 决定

### 1. 持久化对象写入语义五分类

| 分类 | 写入语义 | 例子 |
|---|---|---|
| Mutable State | INSERT / UPDATE / DELETE 自由 | core_entities、entity_relations、map_atlas_pages、accounts |
| Immutable Revision / History | 只允许 INSERT 新行；禁止 UPDATE、DELETE、占位回填 | world_canon_revisions、world_assertions、world_bible_page_revisions、entity_profile_template_revisions、story_outline_revisions、map_atlas_revisions、interaction_message_nodes、interaction_source_revisions、interaction_overview_revisions |
| Mutable Pointer / Head | 仅承担"指向合法 immutable revision"的指针职责，可 UPDATE | world_canon_heads、story_outline_heads、cards/files/nodes 的 current_revision_id |
| Derived / Cache / Index | 可按权威来源重建；不得冒充权威历史 | embedding/搜索派生列、map 页面投影、按章 memory 事件流 |
| Bootstrap / Initialization | 生命周期一次性播种（如 `initialize_world_canon` 的 c0）；clone/fork/restore 不得重复播种、不得为复制清空它 | canon bootstrap、interaction journey 开场节点 |

### 2. 数据库触发器是权威守卫

不可变边界以数据库触发器/约束为准；应用层注释只是文档。禁止为适配业务代码删除、
放宽或绕过触发器（包括 `pg_trigger_depth()` 级联逃生口，它只服务 ON DELETE
CASCADE，不构成业务写路径的旁路）。

### 3. 复制 / 导入 / fork 协议

任何包含内部引用的数据图复制必须：

1. 预分配全部目标 ID，先建立完整的旧→新身份映射；
2. 拓扑排序（表间按依赖顺序，表内按自引用行级拓扑，支持链/树/DAG/多根/分支/
   可选 parent；环为服务端缺陷，报错而非吞掉）；
3. 一次 INSERT 携带最终值落库——禁止先插占位再 UPDATE 回填；
4. 派生列（digest、hash 等）按目标身份重算，使每行第一次落库即处于最终合法状态；
5. 源 ID 不得泄漏进目标数据（FK 与内嵌 JSON 一并重映射）；
6. 不可变历史不转移。授权溯源（receipt）属于原作者，重造即伪造。副本以追加
   方式建立自己的历史：demo copy 以目标作者为授权人、系统 demo-import 策略
   (`DemoImportInputV1`) 追加一条导入修订，携带重写为目标身份的源 manifest；
7. head/指针与修订分离处理；head/指针 FK 与修订表构成表级环时，允许
   "可空指针列插入为 NULL、修订插入后一次性回指"的唯一二阶段（仅限可变指针列，
   见 `_POINTER_FORWARD_REFERENCES` 白名单与结构测试）。

### 4. 失败语义

复制/导入/恢复类操作保持单事务原子性（请求结束统一提交）；任何中途失败整体
回滚，不遗留半初始化项目、孤儿修订或错误指针；重试幂等；对象存储的写入放在
数据库写入之后，失败时按写入逆序清理。

## 实现

- `modules/project/demo_copy.py`：复制协议重写（身份映射 → 拓扑 → 单次
  INSERT；digest 按目标身份重算；删除 canon 预清理 DELETE 与占位回填机制）。
- `modules/world/canon_import.py`：canon 导入映射与 manifest 身份重写。
- `modules/world/authority.py` + `world_authority_service.py`：
  `DemoImportInputV1` 准入类型、`append_demo_import_revision`、回放校验分支；
  公开 admit 路径显式拒绝 demo_import。
- `tests/fixtures/immutable_writes.py`：语句级守卫，任何 UPDATE/DELETE 落
  不可变表即测试失败（方言无关，SQLite 单测同样生效）。
- 结构测试锁定表序不变量：`test_copy_table_order_inserts_every_reference_in_final_state`。

## 后果

- 从结构上消除一类 bug：业务代码与数据库不变量冲突、占位回填、清空重建、
  历史 digest 失配、副本伪造授权溯源。
- 新增不可变表时须同步 `tests/fixtures/immutable_writes.py` 的
  `IMMUTABLE_TABLES` 与触发器 migration；结构测试会在表序破坏时失败。
- 例外登记：`replace_chapter_events`（memory_events 按章替换）为锁保护下的
  派生流重建语义，不属于不可变历史；`focused_adoption` rollback 只回滚可变
  实体状态；`restore.sh` 仅进入 dropdb 后的新库。

# ADR-0002 — BaseCRUDService 设计: 4 ClassVar + 强制 keyword-only novel_id, 不上 port

- **状态**: Accepted
- **日期**: 2026-06-01
- **背景**: architecture review (#1 + #5) — world 模块 5 个 CRUD service 重复同一份样板

## 背景与问题

world 模块的 5 个 CRUD service (`entity_service` / `character_service` / `event_service` / `entity_relation_service` / `entity_revision_service`) 共 ~1000 行, 80% 是同一形状的样板: `parse_uuid → repo.X → Response.model_validate → raise HTTPException(404) + novel_id 隔离检查`。

`world/CLAUDE.md §4` 强制 novel_id 隔离, 但当前实现是把 `if novel_id and str(existing.novel_id) != novel_id` 散在 5 个 service 的 10 个方法里, 是 footgun (例如某天有人改 service 漏掉隔离检查)。

`EntityRevisionService` 是个反例: 它的方法都不是 CRUD 5-verb (是 `create_snapshot` / `rollback_to_revision` / `get_revisions`), 强塞进 CRUD 形状是误用。

抽取前 4 个轴未定:
1. **抽象形式**: generic class (4 typevar) 还是 port 注入 (5+ port)?
2. **`novel_id` 强制**: 关键字必填还是可选?
3. **隔离比对**: `str(uuid) != str` 还是 `uuid != uuid`?
4. **`EntityRevisionService` 归宿**: 强塞还是 opt-in?

## 决策

### 1. 用 4 typevar 的 generic class, 不上 port

`CrudService[ModelT, CreateT, UpdateT, ResponseT]`, 子类填 4 个 ClassVar: `repo` / `response` / `label` / `id_param`。

**理由**:
- 4 个 typevar 表达的是**编译期类型差异**, 5 个 service 的 ORM / Create / Update / Response 各不同, 这是类型级的事实, 编译期一次表达完。
- port 注入 (`CrudRepoPort` / `ResponseShaper` / `NovelIdIsolation` / `ListResponseBuilder` / `CreatePreflight`) 是**运行时多态**, 但当前 0 个真外部 consumer 需要替换这些轴。
- 原则: "一个 adapter = 假 seam; 两个 adapter = 真 seam"。当前只有 1 个 adapter (真实 SQLAlchemy repo), port 是空抽象。

### 2. `novel_id` 在 get/update/delete 上是 keyword-only 必填

`get(self, db, id, *, novel_id)` — 关键字必填, 不传 → TypeError。

**理由**:
- `world/CLAUDE.md §4`: "不跨 novel_id 合并关系、别名或正史对象"。这是**硬约束**, 接口必须强制。
- 当前实现把 `novel_id` 留为可选 (`entity_service.py:43, 85, 104` 等), 是 footgun。改成必填后, footgun 由类型系统消除, 跑不到 runtime。
- 副作用: 跨 novel 调用从"忘检查"变成"忘传参", 编译器直接拒。

### 3. novel_id 隔离用 `uuid.UUID != uuid.UUID` 比对, 不用 `str(uuid) != str`

当前代码 `str(existing.novel_id) != novel_id` 两边都是 str, 实际不 bug, 但 UUID 直接比对更清晰, 且子类的 `parse_uuid` 已经 parse 一次, base class 不需要重新 stringify。

### 4. `EntityRevisionService` opt-in, 不继承 CrudService

它没有 CRUD 5-verb 形状 (它的 `create_snapshot` / `rollback_to_revision` 都是读操作 + 派生状态, 不是 create/update/delete), 强塞进 base 会变成 5 个空 method + 4 个真实 method 的混合体, 比 plain class 难看。

**同理**: 抽出独立的 `CharacterKnowledgeService(CrudService[CharacterKnowledge, ...])` 子类, 跨表 novel 校验 (CharacterKnowledge 的 character_id 必须属于该 novel) 是私有 helper method, 不上 port。

## 影响

- 5 个 service 平均缩 60% (从 ~200 行 → ~80 行, 包含 specialty methods)
- 5 份 novel_id 隔离检查从"5 处 × 3 方法 = 15 处" 缩到 1 处
- 5 份 `Response.model_validate` + 5 份 limit 截断从 10 处缩到 1 处
- `__init_subclass__` 守卫保证子类忘填 ClassVar 立即抛, 不延迟到首次调用
- 测试: 1 个 parametric test 覆盖 5 service 的 5 verb, 替换当前的 per-service 测试文件

## 备选方案 (拒绝)

### A. 5+ port 注入 (CrudRepoPort / ResponseShaper / NovelIdIsolation / ListResponseBuilder / CreatePreflight)

**拒绝理由**: 当前 0 个真外部 consumer, 0 个真 adapter 变体。原则要求"2 个 adapter 才算真 seam", 1 个都没有的 port 是空抽象。未来若需要 (例如加 `InMemoryCrudRepo` 替 SQLite), port 是过度设计; 现在直接加 fake repo 即可。

### B. `novel_id` 保留可选

**拒绝理由**: 保留 CLAUDE.md §4 的 footgun, 接口层不保证, 靠 discipline。generic + keyword-only 是更便宜的纪律。

### C. `EntityRevisionService` 强塞 CrudService

**拒绝理由**: 它的 4 个方法都不是 CRUD 5-verb, 强塞后要么 5 个 method 抛 NotImplementedError, 要么子类 override 全部 5 个 method, 两种都比 plain class 难看。opt-in 是诚实的形状。

### D. `CharacterKnowledgeService` 跟 CharacterService 合并

**拒绝理由**: knowledge 是子资源, 跨表 novel 校验需要访问 CharacterRepository。合并后 CharacterService 持有 2 个 repo, base 类的 `_CrudRepo` protocol 需要放宽, 抽象泄漏。

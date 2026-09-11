# D2b 槽位报告（R04 world：地图与图片、版本 CAS、查询并发子域）

日期：2026-09-11。基线：main @ e7d0b8d5b（WIP 为 imports api/test、styles.css、任务记录，与本槽位 30 路径无交集）。全部 30 路径逐文件语义阅读完成（生产 20 文件 + 测试 10 文件，约 1.7 万行）；未运行测试/构建/make，无网络，未读密钥。交叉验证只读扩展到 `project/facade.py`、`project/services.py`、`world/api.py`（图片端点与门禁）、`map_atlas_tasks` 消费者、evidence focused_evidence 调用点及 alembic 0908 trigger。

## 覆盖行

```csv
path,审查状态,入口/消费者(可空),发现ID或无发现理由
backend/modules/world/map_atlas_api.py,已审,HTTP /api/world/map-atlas/*（全部端点经 ActiveNovelId=require_active_project + XHR）,D2b-5/D2b-6；owner 门禁与 50MB 边界核实无发现
backend/modules/world/map_atlas_facade.py,已审,map_capabilities/inspect_map_node(助手)/enqueue_map_atlas_project_cleanup(项目永久删除)/reconcile/get_map_review_source,无发现：薄委托+全局清理 seam，跨模块仅经 facade
backend/modules/world/map_atlas_models.py,已审,5 张 map_atlas_* 表（NovelMixin）；复合 FK/deferrable 头 FK/CHECK 状态机,无发现：与 F4 共享事实一致；0908 trigger 仅锁内容列、status 可变（review 合法）
backend/modules/world/map_atlas_schemas.py,已审,API/计划/证据契约（extra=forbid + Literal 状态机 + 层级单调校验）,无发现：AtlasPlan 层级/来源/更新目标约束完整
backend/modules/world/map_atlas_service.py,已审,run/page/node/annotation 生命周期 + upload/derive/失败重试,D2b-2/D2b-4；CAS 与 owner 门禁核实无新发现
backend/modules/world/map_atlas_storage.py,已审,PNG 结构校验/元数据剥离/JPEG→PNG 归一/S3 私有桶/key 归属/收敛删除,D2b-1（构造点之一）；安全边界逐条核实无发现
backend/modules/world/map_atlas_tasks.py,已审,4 个 task_handler（world_map_schematic_generate/map_atlas_generate/两个全局 cleanup）,D2b-1（任务内构造点）；cleanup 幂等+INT32 持久重试为有意设计
backend/modules/world/map_atlas_workflow.py,已审,规划/空间证据/逐页生图/失败收敛/reconcile,D2b-1（每页构造点）/D2b-3；lease fence+CAS claim+补偿核实无发现
backend/modules/world/map_structure_geometry.py,已审,geometry_hash/诊断/确定性布局/仿射校准/结构参考 PNG,无发现：有界网格搜索有 ponytail 注释与上限
backend/modules/world/map_structure_images.py,已审,结构引导生图绑定（confirmation 重验/来源 allowlist/guide 重建）,无发现：fail closed 完整
backend/modules/world/map_structure_review.py,已审,候选 diff、依赖闭包展开、部分采用,D2b 无新发现：required_deletions fail-closed 有测试
backend/modules/world/map_structure_schemas.py,已审,MapDocument/图元/约束/校准/读者投影契约,无发现：拒绝 NaN/可执行 payload/超界坐标
backend/modules/world/map_structure_service.py,已审,节点 CRUD/版本 CAS save/审查/历史/图片层/读者投影,D2b-8；来源 digest 重验与 stale 降级核实无发现
backend/modules/world/map_structure_workflow.py,已审,enqueue_structure/关系提取批处理/checkpoint/候选落库,无发现：批次 checkpoint+双重 lease fence+引文逐字校验
backend/modules/world/services/core/entity_activity_invalidation.py,已审,RAG 实体活动重标注 best-effort 桥（DI port）,无发现：best-effort 吞异常有固定 token 日志，属允许的辅助失效
backend/modules/world/services/core/focused_world_read.py,已审,get_terms/get_neighbors（Evidence focused evidence loader）,D2b-7：全量载入后 Python 过滤，分页建立在全量物化上
backend/modules/world/services/worldbuilding/ask_world_retrieval.py,已审,ask_world_service + backend/evals/ask_world.py 的保守字面门槛,无发现：纯函数、噪声词表顺序敏感但按长→短排列
backend/modules/world/services/worldbuilding/synopsis_invalidation.py,已审,mark_synopsis_source_changed（7 个服务调用）,无发现：begin_nested+best-effort，不使来源写脆弱
backend/modules/world/services/worldbuilding/world_impact_service.py,已审,impact-preview API + validation 冻结影响清单,无发现（P3 观察入共享事实）：全 relation/page 载入为声明的 O(P+E) 预演语义
backend/modules/world/tests/test_map_atlas.py,已审,2426 行：plan/spatial/attempt/补偿/CAS/树/清理/图片客户端,无发现：断言有效；patch 全部 autospec=True
backend/modules/world/tests/test_map_atlas_api_upload.py,已审,50MB 边界 413 测试,无发现：monkeypatch 常量验证严格小于边界
backend/modules/world/tests/test_map_atlas_hierarchy.py,已审,计划层级单调/复用节点元数据冻结,无发现
backend/modules/world/tests/test_map_atlas_prompt_review.py,已审,Prompt CAS/全 external 免图片连接/上传伪造拒绝,无发现：storage.put_png assert_not_called 证实校验先于存储
backend/modules/world/tests/test_map_atlas_storage.py,已审,PNG 校验/endpoint 防护/key 归属/清理收敛/元数据剥离,无发现：SSRF endpoint 白名单与 CRC/截断/IEND 负例齐全
backend/modules/world/tests/test_map_structure.py,已审,CAS/append-only/owner 门禁/校准历史/读者投影,无发现：越权 owner 用 bind_principal 反向验证
backend/modules/world/tests/test_map_structure_diagnostics.py,已审,提取回执只存计数不存模型文本,无发现
backend/modules/world/tests/test_map_structure_selection.py,已审,部分采用/剩余候选/引文伪造/路线控制点保留,无发现：1069 行全读
backend/modules/world/tests/test_map_structure_workflow.py,已审,文本任务产出 candidate 不动 head/排除项不回流,无发现
backend/modules/world/tests/test_world_object_images.py,已审,6MiB/4096/WebP 有界/配额/补偿/跨项目隔离/API 契约,无发现：边界值（=6MiB 拒绝、4097 宽拒绝）齐全
backend/modules/world/world_object_images.py,已审,对象图片归一/配额/上传补偿/读取/清理,D2b-1（构造点）/D2b-9；AGENTS 图片边界逐条核实通过
```

30/30 覆盖，无受阻、无不适用。

## 发现

| ID | 位置/符号 | 问题与触发 | 调用链证据 | 现有契约 | 最小方案 | 预期收益 | 风险 | 依赖 | 验证命令/断言 | 回滚 | 裁定 | 优先级 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D2b-1 | `map_atlas_service.py:80`（`_get_storage`）、`map_atlas_workflow.py:1755`（`_generate_page` 每页）、`world_object_images.py:176`（`_storage`）、`map_atlas_tasks.py:48/79`（每任务） | 每次调用 `MapAtlasStorage()`/`WorldObjectImageStorage()` 都新建 boto3 S3 client（`__init__` 做 settings 读取、endpoint 校验、botocore Config 与 client 构造）。高频触发点：`GET .../pages/{id}/image` 每请求一次（地图册一次渲染 N 张图 = N 次 client 构造）；atlas 生成每页一次；对象图片每次上传/读取一次 | `MapAtlasStorage.__init__`（map_atlas_storage.py:284-314）无任何缓存；全部 5 个生产实例化点经 `grep "MapAtlasStorage()\|WorldObjectImageStorage()"` 核实；botocore 官方契约：client 线程安全、创建成本高、应复用 | 注入 seam 已存在（`storage=`/`client=`/`bucket=` 参数，测试全走注入），生产行为无契约要求每次新建 | 模块级按 `(bucket, endpoint)` 缓存 client（如 `functools.lru_cache` 的 `_client_for(settings)`），`MapAtlasStorage.__init__` 复用；或让 `_get_storage()`/`_storage()` 缓存实例。注意测试 monkeypatch `get_settings` 的路径不能被缓存固化（缓存键含 settings 或保留无参构造走每次新实例的注入测试路径） | 图片批量读取/多页生成的重复 client 构造消除；收益待测（botocore loader 有进程级缓存，单次构造毫秒级，批读场景累积） | 低-中：缓存生命周期与 settings 轮换（测试 monkeypatch、桶配置变更）需设计；storage_configuration_status 门禁不依赖 client，不受影响 | 无 | `make test TESTS="modules/world/tests/test_map_atlas_storage.py modules/world/tests/test_world_object_images.py modules/world/tests/test_map_atlas.py"`；性能对比按计划 §5 隔离流程另测 | git revert 单文件 | 实施候选（收益待测） | P2 |
| D2b-2 | `map_atlas_service.py:1589-1607`（`_compensate_upload`）、`map_atlas_service.py:1246-1265`（create_derived_page mask 补偿内联）、`map_atlas_workflow.py:1666-1685`（`_compensate_uploaded_object`） | 同一补偿模式三份拷贝：`delete_unreferenced_page_object` 失败 → `db.rollback()` → `enqueue_task("map_atlas_storage_cleanup", cleanup_kind="object", novel_id=None)` → `commit`。逐字重复 ~17 行 ×3，改 cleanup 契约需同步三处 | 三段代码逐行比对一致（仅函数名与所在文件不同）；test_map_atlas.py `test_failed_mask_enqueue_compensates_or_schedules_global_cleanup` 与 test_compensation 两测分别覆盖其中两份 | 补偿语义：先精确删，引用检查不可知时入全局清理任务（novel_id=None 免 FK） | 收敛为单一 helper（建议放 `map_atlas_storage.py` 邻近 `delete_unreferenced_page_object`），三处改调用；不改 meta 契约与 novel_id=None 语义 | 消除 2 份重复；cleanup 契约单点维护 | 低：纯移动，测试已覆盖两条路径 | 无 | 同上测试 + `make test TESTS="modules/world/tests/"` | git revert | 实施候选 | P3 |
| D2b-3 | `map_atlas_workflow.py:1957-2006`（`_converge_workflow_failure`）vs `2110-2176`（`reconcile_map_atlas_task_owners`） | 两处近乎相同的 pages 状态归敛：`provider_in_flight→retry_requires_confirmation/possible_duplicate_charge`、`uploaded+object_key→review_ready`、`completed_page_count` 重算、`failed/partial` 判定（~30 行），仅收尾 error_code/message 不同（`map_atlas_workflow_failed` vs `worker_interrupted`） | 两函数逐行比对；test_map_atlas.py `test_reconciler_preserves_uploaded_page_and_fences_unknown_provider` 与 workflow 失败路径分别锁定两份行为 | run/page 状态机契约不变 | 抽 `_converge_run_pages(run, pages) -> has_retry`，两函数各自补 error_code/message 收尾 | 消除 1 份状态机重复；reconcile 与失败收敛不再漂移 | 低：状态转移有测试锚定 | 无 | `make test TESTS="modules/world/tests/test_map_atlas.py"` | git revert | 实施候选 | P3 |
| D2b-4 | `map_atlas_service.py:998-1002`（`update_node` desired_index） | `elif new_parent_id == old_parent_id:` 与 `else:` 两个分支体逐字相同（`min(node.sort_order, len(target_adopted))`），分支条件无行为差异，属遗留死分支 | 直接读码；`git log -L` 可证历史演化残留（未另行提交分支判断） | 排序行为：before 缺省时取 min(现排序, 目标组长度) | 合并为单一 `else:`，删 elif 行 | 3 行删除；可读性 | 无（行为恒等） | 无 | `make test TESTS="modules/world/tests/test_map_atlas.py"`（update_node 排序用例） | git revert | 实施候选（顺手改） | P3 |
| D2b-5 | `map_atlas_api.py:225-238`（`_read_bounded_png`/`_read_bounded_image`）；同类模式第三处在 `world/api.py:2976-2979`（6MiB 读取，归 D2a 面） | 两个 helper 仅 detail 文案与 `upload is None` 语义不同，主体（read(N)、`>=`+read(1) 严格小于检查、413）逐字重复 | 两函数逐行比对；api.py 上传端点第三处同构 | "严格小于上限"的边界契约（413） | 合并为单个 `_read_bounded_upload(upload, limit, detail, *, required: bool)` | 8 行重复消除；边界检查单点 | 无：test_map_atlas_api_upload 只测 `_read_bounded_png`，保留别名或同步测试引用 | 无 | `make test TESTS="modules/world/tests/test_map_atlas_api_upload.py"` | git revert | 实施候选 | P3 |
| D2b-6 | `map_atlas_api.py:205-222`（`preview_reader_image`）vs `:577-587`（`read_page_image`） | 同一私有图片的两个读取路径响应头不一致：后者 `Cache-Control: private, no-store` + `X-Content-Type-Options: nosniff`，前者仅 `no-store`，缺 `private` 与 `nosniff` | 两端点直接读码比对 | read_page_image 的头是现行安全基线（私有图片不可缓存共享） | preview_reader_image 补齐 `private` 与 `nosniff` 两头 | 头契约一致；防共享缓存误存私有图 | 极低：浏览器行为不变（均为 no-store） | 无 | `curl` 断言两路径响应头一致（或 e2e 断言） | git revert | 实施候选（安全一致性顺手改） | P3 |
| D2b-7 | `services/core/focused_world_read.py:53-85`（`get_terms`） | 无条件全量载入项目 canonical（或 +candidate/draft）实体后在 Python 端做精确 casefold 名称/别名过滤与分页；`skip/limit` 只作用于已物化列表。大项目（万级实体）时每次 focused evidence 检索都全表投影 | `query` 无 limit（:59-71）；消费方 `evidence/compilation/services/focused_evidence.py:208/998/1444` 在检索链内调用；README 将其定位为"内部作者资料 seam" | 返回 `truncated/next_skip` 稳定分页契约；Evidence 仍执行可见性门禁 | 观察项：实体 IDs 路径已走 SQL `IN`；仅 names 路径可下推（`lower(name) = any(...)` 或 pg_trgm 精确分支），JSONB 别名过滤保留 Python 端。无实测瓶颈前不动 | 收益待测（与项目规模线性） | 中：下推改变过滤语义风险（别名 JSONB 路径复杂），须保持逐字段一致 | 无 | 现有 `test_spatial_evidence_rereads_only_confirmed_ranges_and_world_text` + 新增等价断言 | git revert | 保留现状（记录观察；证据充分再立项） | P3 |
| D2b-8 | `map_structure_service.py:146`（`map_links`） | `query = MapLinkQuery.model_validate(query.model_dump())` 对已是 `MapLinkQuery` 的入参做一次额外 validate+dump 往返；API 层（map_atlas_api.py:94-99）已构造同一 schema，无归一化增益 | api 层构造点 + 本行直接读码 | 入参类型契约 `MapLinkQuery` | 删除该行，直接用 `query` | 1 行死开销；去防御性冗余 | 无 | 无 | `make test TESTS="modules/world/tests/test_map_structure.py"`（map_links 相关若无直接用例则依赖 fast 层） | git revert | 实施候选（顺手改） | P3 |
| D2b-9 | `world_object_images.py:197-273`（`upload`）vs `:367-404`（`require_image_type_change_quota`） | 账户级图片配额"计数查询 + category 谓词 + limit 比较 + 中文上限错误"在两处重复（~25 行）；仅 exclude_entity_id 与类别方向不同 | 两段逐行比对；`lock_project_ids_for_owner` advisory lock 语义两处一致 | 配额：人物 20/其他 50，owner 全项目计，占用含回收站项目 | 抽 `_assert_image_quota(db, project_ids, *, is_character, exclude_entity_id)` 供两处调用 | 重复消除；配额规则单点 | 低：配额测试（test_quota_failure/test_type_change）锚定行为 | 无 | `make test TESTS="modules/world/tests/test_world_object_images.py"` | git revert | 实施候选 | P3 |
| D2b-10 | `map_atlas_workflow.py:410-418`（`_location_aliases`）vs `services/core/focused_world_read.py:21-33`（`_entity` 别名过滤） | "有效别名"过滤语义相同（status ∈ {None,active,canonical,confirmed,published} 且未 rolled_back）但两处独立实现；且前者写成多层 for/if 混合推导，`or ... and not` 优先级靠读者心算，可读性差 | 两处读码比对；`world_impact_service._entity_aliases` 为第三种有意语义（默认 canonical + not needs_review），不纳入合并 | 各消费者投影字段不同（aliases list vs terms list），仅谓词相同 | 只收敛谓词为共享小函数（如 `world/models` 或 services/core 下的 `is_active_alias(item)`）；`_location_aliases` 顺带重写为显式循环。不合并第三种语义 | 1 份谓词收敛 + 可读性 | 低：谓词有测试（别名 rolled_back/状态过滤） | 无 | `make test TESTS="modules/world/tests/"` | git revert | 实施候选（低收益，顺手） | P3 |

无 P0/P1：owner+novel_id 双门禁（`require_active_project*` → repo 按 owner_id 过滤 + FOR SHARE/UPDATE + active 过滤，`project/services.py:554-652` 核实）、PNG/JPEG 真实校验（结构级 CRC/IEND 校验 + PIL format/frames/verify + DecompressionBomb 防护）、<6MiB、≤4096×4096、去元数据（PNG chunk 剥离/JPEG 重编码）、object key 归属校验（`require_owned_page_object_key`）、S3 endpoint 白名单、上传补偿与收敛删除、CAS 与 lease fence 全部核实为安全边界且实现完整，不列为优化对象（与 audit「不建议简化：文件格式/大小校验」一致）。

## 历史候选复核

| 候选 | 结论 | 证据 |
|---|---|---|
| A4-1（X1-7/A4-1：全局 DomainError handler 统一，world 10 处冗余先删） | 已解决（world 面） | 本槽位 grep `exception_handler(DomainError)`：仅 `backend/app/main.py:559` 一处；world 模块（含本槽位 14 个生产文件）无局部 handler。与 W1「X1-7 机制侧已解决」一致 |
| A4-3（前端 isVersionActive helper 8 处） | 已解决/符号不存在 | `git grep isVersionActive <HEAD>` 仅命中 audit 文档自身；前端代码无该符号。前端文件归 D8，本槽位不再展开 |
| A4-2（world/schemas.py 34 处 uuid coercion → Annotated） | 不属本槽位（对象域归 D2a） | 目标文件 `modules/world/schemas.py` 不在 D2b 30 路径；本槽位 3 个 schemas 文件（map_atlas/map_structure）已用 Annotated 模式（FeatureKey/Coordinate），无同病 |
| A4-5（compatibility_status 收窄） | 不属本槽位（归 D2a/D2c） | 现存于 `worldbuilding/suggestion_queue_service.py:91-113` 与 `world_generation_center_service.py:1514`，均为对象/生成域文件，不在地图/图片/失效范围 |
| A4-4（world 资产双词汇渐进）/ A4-8（generation_center 双结构化包装） | 不属本槽位 | A4-4 前端归 D8；A4-8 目标在 `worldbuilding` 服务（D2c 范围），本槽位无地图/图片侧关联证据 |
| A3-1/A3-2/A3-3/A3-5/A3-6（story repos 收敛/reveal 重复/枚举/novel_id 列/squash） | 不落在地图/图片/失效范围 | 全部位于 story/迁移/枚举域；W1 F4 已复核（A3-1/A3-5 仍成立、A3-6 待查），本槽位 30 路径无新增证据，亦无 world 侧副本 |
| audit「不建议简化」中"文件格式/大小校验"（地图/图片侧） | 确认为安全边界，维持排除 | 本槽位逐条核实校验实现真实存在且fail-closed：`validate_png`（CRC/IEND/尺寸）、`normalize_map_upload`（格式伪装/炸弹防护/重编码）、`normalize_world_object_image`（6MiB/4096/WebP）、key 归属与 endpoint 白名单；不列为优化对象 |

本槽位净复核计数：8 项次（A4-1、A4-3、A4-2、A4-4、A4-5、A4-8、A3 组汇总、audit 安全边界条目）。

## 共享事实（按 P2 链 5「地图编辑/图片→版本 CAS→查询展示→失败重试及并发冲突」组织）

### 1. 图片上传管线图（门禁点 → 校验点 → 存储点）

地图册上传（`POST /map-atlas/{nid}/pages/upload`，≤50MB PNG/JPEG→PNG）：

```
API map_atlas_api.upload_page
  ├─ 门禁1 ActiveNovelId = require_active_project（owner_id 过滤 + deleted_at IS NULL + FOR SHARE，project/services.py:595-614；无主 principal 时不过滤 owner，浏览器路径恒有 principal）
  ├─ 门禁2 require_xhr_request（写端点全部挂 _xhr）
  ├─ 读边界 _read_bounded_image：read(50MB) + len>=50MB || read(1) → 413（严格小于）
  └─ service.upload_page
       ├─ 校验 normalize_map_upload（线程池）：PNG→结构校验+strip_png_metadata(tEXt/zTXt/iTXt/eXIf/tIME/gIFx)+复验；非 PNG→PIL 校验 JPEG 单帧/≤8192²/炸弹防护→exif_transpose+RGB 重存 PNG（天然无元数据）
       ├─ 存储 put_png（S3 私有桶，attempt/无 attempt key 二态，put 前再 validate_png）
       ├─ 写库前再取 require_active_project_exclusive + active_run 检查（先 S3 后 DB，短锁）
       └─ 失败补偿：rollback → delete_unreferenced_page_object（两次 rollback 取新快照 + key 归属校验）→ 兜底入全局 map_atlas_storage_cleanup（novel_id=None 免项目 FK）
```

对象图片（`PUT /world/entities/{eid}/image`，<6MiB PNG/JPEG→WebP，`world_object_images.py`）：

```
API upload_entity_image（world/api.py:2971）: XHR + ActiveNovelIdQuery + 6MiB 严格小于 413
  └─ service.upload
       ├─ 门禁 get_project_context（owner 过滤 repo.get；None→404）
       ├─ 校验 normalize_world_object_image（线程池）：format∈{PNG,JPEG}+单帧+verify+≤4096²+≤MAX_PIXELS→exif_transpose+RGB→full≤256KB(896边)/thumb≤16KB(192) WebP 逐级降质
       ├─ 存储 put_webp ×2（world-objects/{nid}/entities/{eid}/images/{version}/{variant}.webp）
       ├─ 配额：实体行锁 + lock_project_ids_for_owner（owner 级 advisory lock 防跨项目并发升锁）→ 账户口径计数（人物20/其他50，回收站占额，替换不增占）→ flush 后终检 final_count
       ├─ 提交后旧版本入 world_object_image_cleanup；异常→rollback+精确删两 key→删失败入全局清理；S3 故障→503 DomainError
       └─ 读取 GET：get_project_context 门禁 + image_version 推导 key（key 不进 DB/API wire）+ get_webp 有界读取；响应 private,no-store
```

配套安全点（两链共用）：`MapAtlasStorage.__init__` 经 `validate_map_atlas_s3_endpoint_url` 白名单（SSRF 负例测试齐全）；HTTP endpoint 禁代理；`WorldObjectImageStorage` 继承复用收敛删除（版本+delete marker 全清、部分失败抛错重试）；项目永久删除经 `enqueue_map_atlas_project_cleanup` 按精确前缀清理（`require_project_*_prefix` 拒绝 atlas 根）。

### 2. 版本 CAS 语义（三处不同粒度，勿混用）

- **空间版本 CAS（行锁内 head 比较）**：`MapStructureService.save/review/preview_layout` 先 `node(lock=True)` 再 `node.current_revision_id != data.base_revision_id → 409`。候选采用另要求 `candidate.base_revision_id == head` + `confirmation_id` 重物化 + `context_fingerprint` 逐字匹配（漂移即拒绝，`_adoption_document`）。
- **行 updated_at CAS**：page 审查（review_page）、prompt 编辑/批量确认、annotation 更新、node 层级编辑均比较 `expected_updated_at`，409 文案固定"已在别处更新"。
- **图片/生图 CAS**：`_generate_page` 用 `UPDATE ... WHERE generation_status='prepared'` 条件更新做 claim（rowcount!=1→CancelledError），完成回写需行锁内 `generation_status='provider_in_flight'` 复验；`MapAtlasRevision` 内容列由 0908 DB trigger 不可变（status 可变，供 reject/部分采用），`uq_map_revision_task_node` 幂等一任务一候选。
- 写互斥：生图上传/派生/审查/retry/resume/confirm_prompts 走 `require_active_project_exclusive`（项目 FOR UPDATE 短栅栏，不跨 LLM/图片 provider I/O 持有）；读树/atlas 只走共享门禁。

### 3. 失效传播图（谁失效谁）

- **实体/关系/事件/档案/专项采用 → 简介标脏**：`mark_synopsis_source_changed`（best-effort，begin_nested+warning）调用方：`entity_service`（创建/更新/采用等 4 点）、`entity_relation_service`、`event_service`、`profile_service`（2 点）、`entity_revision_service`（回滚）、`focused_adoption`（专项采用包）。
- **同一批写入 → RAG 实体活动重标注**：`request_entity_activity_reannotation`（DI port `rag.request_entity_activity_reannotation`，bootstrap.py 注册；未注册/失败仅日志）调用方：entity_service（4 点）、entity_alias_service、entity_revision_service、entity_stats_service、dedup_service（2 点）、focused_adoption。
- **World Bible 页面/工作稿失效不在本槽位**（lifecycle 归 D2c）；地图侧无反向失效：地图读取时按 `source()` digest 重验来源，变化只产出 `source_stale` problem 与读者投影剔除，不写任何失效标记（读取路径零业务写入）。
- **S3 侧"失效"**：替换/删除不物理删历史版本，收敛靠 cleanup 任务（image_version 引用检查 / project_prefix 幂等）。

### 4. map atlas / structure 任务与重试语义

- **world_map_schematic_generate**（结构关系提取）：`manual_resume`，max_attempts=4，project scope。批次 checkpoint 存 `task.result.batches`（失败批次重试只补失败批）；每批前后双重 `require_running_task_attempt` lease fence + exclusive project 栅栏；落库前重验 node.structure_task_id==task.id 与 fresh confirmation；产出 candidate 不动 head。批内 discarded/failed/truncated 计数入 receipt，不存模型文本。
- **map_atlas_generate**（图片生成）：`manual_resume`，max_attempts=20。逐页 claim（CAS prepared→provider_in_flight）→ provider 调用内 retryable 无费用错误指数退避 3 次 → attempt-scoped key 上传 → 行锁回写 review_ready；`_recover_uploaded_page` 用 `get_png_if_exists` 找回已上传未提交对象（同 key 幂等恢复，二次执行不再调 provider）。费用不可知（`possible_charge`/中断/存储失败）→ `retry_requires_confirmation` + `possible_duplicate_charge`，作者须 `confirm_possible_duplicate_charge=true` 才 resume/retry。
- **崩溃收敛**：worker 异常 → `_converge_workflow_failure`；队列级 stale → `reconcile_map_atlas_task_owners`（对 planning/generating run 按 task lifecycle contract 判 stale）——两者把 `provider_in_flight→retry_requires_confirmation`、`uploaded→review_ready`，run 转 partial（见 D2b-3 重复）。
- **全局清理**：`map_atlas_storage_cleanup`/`world_object_image_cleanup` 为 `auto_requeue` + `owner_scope="global"` + max_attempts=INT32_MAX（注释声明"有界契约下的实质持久"）；精确 object 删除前重查 DB 引用，防误删并发采用的对象。
- stop 语义：`stop_run` 置 `stop_requested`（prompt_review 立即 paused）；逐页循环页间检查，停止后 run=paused；resume 在无 in-flight 时免确认续排（prompt_review 态 resume 只回状态不 enqueue）。

### 5. 其他横切观察（不构成发现）

- `world_impact_service.preview` 为声明的只读 O(P+E) 预演：全量载入 adopted pages 与 canonical relations 后内存遍历；各 section cap=200 + 显式 uncovered（read_failed/截断/字面匹配局限），`complete` 只在零截断零 read_failed 时为真——符合"不能把局部覆盖说成完整影响"的契约。
- `focused_world_read.get_neighbors` 的 canonical 两端过滤在 SQL 内完成（`IN (canonical 子查询)`），仅 names 路径存在 D2b-7 的全量物化。
- world api.py 中 `GET /map-atlas/{nid}/runs/{run_id}`、`GET /pages/history`、`GET /capabilities`、`POST /pages/upload`、`POST /pages/{id}/retry`、结构地图端点未列入模块 README 的 API 表（README 声明完整契约见 `docs/modules/15_map.md`，文档核对归 F6/R16）。
- 测试 10 文件全部遵守 `autospec=True` / monkeypatch 纪律；安全负例（owner 越权、key 伪造、伪装图片、SSRF endpoint、引用检查未知）覆盖充分，无"为过检削断言"迹象。

## 受阻

无。

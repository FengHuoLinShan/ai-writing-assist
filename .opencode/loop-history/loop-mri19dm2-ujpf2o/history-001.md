# Round 1/20 - 后端模块全面扫描

**Status**: PASS (所有 13 子代理成功返回)  
**Total Round 1**: 251 issues (CRITICAL: 24, HIGH: 60, MEDIUM: 95, LOW: 72)  
**Goal**: 并行探索所有后端模块逻辑边界，找出隐藏问题  
**Started**: 2026-07-13

## 调度

并行探索以下 9 个后端模块 + core + infrastructure + frontend + tests：

## 已返回结果

### outline 模块 — 24 个问题
- 🔴 CRITICAL: 3
- 🟠 HIGH: 8
- 🟡 MEDIUM: 8
- 🟢 LOW: 5

**最严重发现**：
1. **CRIT-1**: `api.py:105` `enqueue_task` 未导入 — 3 个 API 端点（analyze, generate, extract）运行时必挂
2. **CRIT-2**: `repositories.py:41-46` JSONB 路径查询在 `provenance_meta=NULL` 时 PostgreSQL 报错
3. **CRIT-3**: `services.py:560-577` `delete()` 软删除不返回任何值 — 调用方不知成功失败
4. **HIGH-2**: `scene_workbench.py:1129-1143` 场景索引用 `max+1` 不填充缺口 — 索引无限增长
5. **HIGH-6**: `deep_import_repair_service.py:214-447` AI 输出不足时创建大量占位假数据
6. **HIGH-8**: `scene_workbench.py:1088-1089` `status="draft"` 被设置了两次覆盖 override

### frontend 模块 — 31 个问题
- 🔴 CRITICAL: 4
- 🟠 HIGH: 13
- 🟡 MEDIUM: 11
- 🟢 LOW: 3

**最严重发现**：
1. **CRIT-2**: `router.js:298-306` API 失败时静默继续导航 — state 为 null 的视图渲染
2. **CRIT-3**: `sceneWorkbenchView.js:130-133` 跨章节轮训在 onLeave 未停止 — 离开后回调操作无效 DOM
3. **CRIT-4**: `writingView.js:386-404` 全局 state 被污染 — 视图本地数据泄漏到全局对象
4. **HIGH-2**: `api.js:17,40-52` API 缓存无界增长 — 内存泄露
5. **HIGH-10**: `router.js:102-103` DOM 缓存残留过期/重复事件监听器
6. **HIGH-11**: `writingView.js:565` 无保存队列 — 快速 Ctrl+S 并发导致数据竞争

### imports 模块 — 24 个问题
- 🔴 CRITICAL: 2
- 🟠 HIGH: 5
- 🟡 MEDIUM: 9
- 🟢 LOW: 8

**最严重发现**：
1. **CRIT-1**: `services.py:172-175` 回滚后会话状态崩溃 — `db.rollback()` 导致后续所有 flush 失败，ImportRecord 丢失
2. **CRIT-2**: `api.py:90-102` `_resolve_end_chapter` 导致 start_chapter > end_chapter — 区间无效
3. **HIGH-1**: `scene_fusion.py:29-107` LOTM 硬编码事件锚点 — 非 LOTM 小说获得错误内容注入
4. **HIGH-3**: `workflow_structure_phase.py:111-132` Phase 3 重跑先废弃后重跑 — 崩溃后资产永久丢失
5. **HIGH-4**: `orchestrator.py:586-588` 进度只能单调递增 — 恢复时进度跳跃失准
6. **LOW-8**: `api.py:278-329` 恢复/放弃端点缺乏 novel_id 隔离 — 接受 task_id 时不验证 novel_id

### project 模块 — 19 个问题
- 🔴 CRITICAL: 0
- 🟠 HIGH: 1
- 🟡 MEDIUM: 8
- 🟢 LOW: 10

**最严重发现**：
1. **HIGH-1**: `repositories.py:67-76` `repo.update()` 接收 ORM 实例时跳过 `deleted_at` 过滤 — 可修改已软删除项目
2. **MED-1**: `services.py:135-220` 多处"读-改-写"无行级锁 — TOCTOU 竞态
3. **MED-2**: `llm_runtime.py:288-293` `profile_source` 语义错误 — 仅反映 model 字段来源而非整体
4. **MED-5**: `services.py:222-243` 通用 PUT 替换整个 settings dict 而非合并 — 按 provider 存储的密钥被清除
5. **MED-8**: `services.py:316-328` `list_deleted_projects` 逐个而非批量查询统计 — N+1 性能问题

### rag 模块 — 14 个问题
- 🔴 CRITICAL: 2
- 🟠 HIGH: 5
- 🟡 MEDIUM: 4
- 🟢 LOW: 3

**最严重发现**：
1. **CRIT-1**: `tasks.py:70` 任务失败后章节索引状态无限卡在 "running" — 永远无法恢复
2. **CRIT-2**: `repositories.py:330-353` `delete()` 和 `delete_many()` 绕过 novel_id 隔离检查
3. **HIGH-1**: `retrieval.py:36-43` `_default_embedder` 每次检索创建 `LLMClient` 但不关闭 — 资源泄漏
4. **HIGH-2**: `models.py:37-41` SQLite 回退时 `LargeBinary` 列与 Python `list[float]` 不兼容
5. **HIGH-4**: `indexing.py:263-266` `retry_embeddings` 在第一次失败批次后 break — 大批剩余未处理
6. **MED-1**: `scoring.py:32-46` n-gram 膨胀导致中文查询评分稀释

### infrastructure 模块 — 18 个问题
- 🟠 HIGH: 2
- 🟡 MEDIUM: 7
- 🟢 LOW: 9

**最严重发现**：
1. **HIGH-1**: `lifecycle.py:189-255` `task.lease_id` 在 rollback 后触发延迟加载 — 可能掩藏错误
2. **HIGH-2**: `worker.py:318-343` `CancelledError` 处理中 `rollback()` 使 ORM 状态失效
3. **MED-2**: `limits.py:54-70` `LLMProcessLimiter.scope()` 在获取信号量后才检查断路器 — 浪费并发槽位
4. **MED-3**: `client.py:531-729` 传输层重试和结构化重试不正交 — 网络超时消耗所有重试预算
5. **MED-6**: `api.py:176-198` 任务状态端点返回完整 `meta` — 如果 novel_id 校验被绕过则泄露敏感数据

### writing 模块 — 18 个问题
- 🔴 CRITICAL: 3 (全是竟态条件)
- 🟠 HIGH: 4
- 🟡 MEDIUM: 7
- 🟢 LOW: 4

**最严重发现**：
1. **W-01**: `publish_draft_result()` 业务决策在无锁状态下执行 — 版本历史不一致
2. **W-02**: `split_chapter_at_offset()` 无锁，并发切分会破坏章节索引
3. **W-03**: `delete_draft()` TOCTOU 竟态导致最后一版被删除
4. **W-07**: Repository 层直接抛 `ValueError`，API 返回 500 而不是 422/409
5. **W-10**: AI 冲突检查卡在 "running" 状态无超时恢复
6. **W-14**: content 字段无服务层长度校验

### test 模块 — 20 个问题
- 🔴 CRITICAL: 2
- 🟠 HIGH: 5
- 🟡 MEDIUM: 8
- 🟢 LOW: 5

**最严重发现**：
1. **CRITICAL-1**: `test_writing_delete_chapter_removes_all_versions` 断言总数"等于删除前" — 假阳性
2. **CRITICAL-2**: 同一测试与前一测试共享 fixture 无隔离
3. **HIGH-1**: 大量 API 测试接受过多 status code（如 `(200, 201, 422, 404)`）
4. **HIGH-3**: 跨 novel 隔离测试实际上不验证任何东西 — 接受任何状态码

### settings 模块 — 11 个问题
- 🔴 CRITICAL: 1
- 🟠 HIGH: 2
- 🟡 MEDIUM: 4
- 🟢 LOW: 4

**最严重发现**：
1. **CRIT-1**: `facade.py:37` `LookupError` 导致 500 而非 404 — 不存在 project 返回 500
2. **HIGH-1**: `facade.py:44-53` `get_effective_author_prefs` 不验证 project 存在性 — 返回系统默认值
3. **HIGH-2**: `api.py:86-118` 5 处接受 `project_id: str` 直接传 `uuid.UUID()` 不捕获 — 畸形 UUID 返回 500
4. **MED-2**: `repositories.py:120-125` `reset_field` 为不存在的 project 创建全 NULL 行

### memory 模块 — 14 个问题
- 🔴 CRITICAL: 1
- 🟠 HIGH: 3
- 🟡 MEDIUM: 5
- 🟢 LOW: 5

**最严重发现**：
1. **CRIT-1**: `services.py:698-700` `relation_ended` 事件缺失 `relation_id` 时静默清空所有 relations
2. **HIGH-1**: `services.py:133-134` 浅拷贝 `dict(nearest.full_state)` 导致 replay 时内存快照被静默篡改
3. **HIGH-2**: `services.py:100` `record_events` 可设置 `snapshot_after=None` 违反 NOT NULL 约束
4. **HIGH-3**: `services.py:562-586` `full_rebuild` 先删数据后验证 — 失败后不可恢复

### context 模块 — 17 个问题
- 🔴 CRITICAL: 1
- 🟠 HIGH: 4
- 🟡 MEDIUM: 6
- 🟢 LOW: 6

**最严重发现**：
1. **CRIT-1**: `context_compiler.py:207` 使用 naive `datetime.utcnow()` 写入 timezone-aware 列 — 数据不一致
2. **HIGH-1**: `evidence_repository.py:66-82` `list_for_source_chapter` 全表扫描 — 性能炸弹
3. **HIGH-2**: 列表 API 返回 `total=len(items)` 而非数据库真实计数 — 分页错误
4. **HIGH-3**: RAG 追踪记录使用独立会话并提前提交，主事务回滚后出现孤立记录
5. **MED-2**: `asyncio.gather` 使用 `return_exceptions=True` 静默吞掉加载器错误，依赖加载器操作过时数据

### world 模块 — 27 个问题
- 🔴 CRITICAL: 4
- 🟠 HIGH: 6
- 🟡 MEDIUM: 13
- 🟢 LOW: 4

**最严重发现**：
1. **CRIT-1**: `EntityFusionService.apply()` 部分事务提交 — 循环内调子服务 `flush()`，中途失败导致数据部分已刷入
2. **CRIT-2**: `EntityAliasService` 调用 `dedup_service._migrate_relations()` 私有方法 — 破坏封装
3. **CRIT-3**: `_relation_upsert_lock` 仅进程级锁 — 多 worker 部署下无互斥，O(n²) 驱逐
4. **CRIT-5**: `EntityFusionService.suggest()` 在 `_llm_client is None` 时重新实例化自身并递归 — 可能栈溢出

**其他亮点**：
- `CoreEntityRepository.get()` 不按 `novel_id` 过滤 (HIGH-4)
- `seed_text_archive` 测试端点在非 test 环境可访问 (HIGH-5)
- `merge_text_field` 重复合并导致内容无界增长 (MED-12)
- `derive_author_state` 验证器每次响应构造都延迟导入 (MED-10)

详见子代理返回的完整报告。


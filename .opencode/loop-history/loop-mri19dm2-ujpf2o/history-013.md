# Round 13/20 — API Versioning / HTTP Methods / Status Codes / Endpoint Naming

**Status**: PASS  
**Goal**: API 版本策略、HTTP 方法使用、状态码一致性、端点命名规范  
**Started**: 2026-07-13  
**Completed**: 2026-07-13  

## 结果总览

| 审计模块 | 发现数 | CRITICAL | HIGH | MEDIUM | LOW |
|----------|--------|----------|------|--------|-----|
| API 版本化策略 | 3 | 0 | 0 | 2 | 1 |
| HTTP 方法使用 | ~8 | 0 | 0 | 1 | 7 |
| HTTP 状态码一致性 | ~6 | 0 | 1 | 2 | 3 |
| 端点命名规范 | ~10 | 0 | 1 | 1 | 8 |
| **合计** | **~27** | **0** | **2** | **6** | **19** |

---

## API 版本化策略 — 3 个发现（2 MEDIUM + 1 LOW）

**项目无版本化策略**。13 个 `APIRouter` 全部裸 `/api/{module}`，代码注释自知缺口（`main.py:411`）

🟡 **MEDIUM**: 无版本前缀，注释自知但未处理。无法同时运行两个 API 版本
🟡 **MEDIUM**: 无废弃/向后兼容流程，任何端点修改都是静默破坏性变更
⚪ LOW: 模块前缀命名不一致（`/api/projects` 复数 vs `/api/world` 单数 vs `/api/rag` 缩写）
✅ 统一 `/api/` 基础前缀、前端后端对齐、OpenAPI docs 挂载正确

---

## HTTP 方法使用 — ~8 个发现（1 MEDIUM + 7 LOW）

~181 端点，92% 合规模。

🟡 **MEDIUM**: `PUT /writing/drafts/{draft_id}`（writing/api.py:388）用于部分更新——`WritingDraftUpdate` 所有字段可选，应改用 `PATCH`
⚪ LOW: 6 处 POST 用于只读查询（context evidence、rag retrieve）——常见折中但违反 REST 语义
⚪ LOW: `DELETE /writing/chapters/{chapter_index}` 返回 200 而非 204（同文件 DELETE draft 正确用了 204）
✅ 无 GET 改变状态、memory 模块 100% 合规

**幂等性**：应用级乐观并发（`expected_version`、`expected_updated_at`、409 冲突）替代了 HTTP 条件请求
❌ 无 `If-Match`/`ETag` 条件头支持

---

## HTTP 状态码一致性 — ~6 个发现（1 HIGH + 2 MEDIUM + 3 LOW）

**全局异常处理基础设施健全**：`DomainError`(400) → `NotFoundError`(404) → `ConflictError`(409) → `ValidationError`(400)

🔴 **HIGH**: `_workbench_error`（outline/api.py:78-86）— 过度捕获：
  - `LookupError`(Python 内置) → 404（`KeyError` 可能被静默转为 404）
  - `Exception` → 500 含 `detail=str(exc)`（阻止全局 handler 记录堆栈）
  - 应限流已知业务异常，让编程异常走全局兜底

🟡 **MEDIUM**: 异步任务 201 vs 202 不一致——5+ 个 `enqueue_task` 端点用 201（应 202），同模块 writing `ai-review-task` 正确用了 202
🟡 **MEDIUM**: 8+ 处 `ValueError` → `HTTPException(400)` 绕过 `DomainError` 抽象，丢失标准化错误响应形状
✅ 成功状态码使用正确（GET=200, POST=201, DELETE=204），无结构性的错误码误用

---

## 端点命名规范 — ~10 个发现（1 HIGH + 1 MEDIUM + 8 LOW）

🔴 **HIGH**: **Memory 模块路径前缀特殊**（`/api/novels/{novel_id}/memories` vs 其他 10 模块统一 `/api/<module>` + query `novel_id`），前端需特殊处理
🟡 **MEDIUM**: **~45% 端点是动词(RPC)路径**（`/generate`、`/compile`、`/extract`、`/merge`），缺少名词化约束
⚪ LOW: world `object-draft-chat`(单数) vs `object-drafts/generate`(复数) 内部不一致
⚪ LOW: world `/_test/` 路径前导下划线非标准；imports `/deep` 形容词非名词
✅ kebab-case 全仓一致、复数名词资源路径基本一致、前端-后端路径匹配

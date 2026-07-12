# Round 4/20 - 架构一致性 & 性能审计

**Status**: COMPLETE — PASS  
**Goal**: API 设计一致性、前端深度、性能/N+1、错误传播全局审计  
**Started**: 2026-07-13

## 结果汇总（26+39+8+20 = **93 个问题**）

### 前端深度审计 — 26 个问题（0 CRITICAL + 1 HIGH + 13 MEDIUM + 12 LOW）

**最严重发现**：
1. **HIGH-1**: `shared/viewHelper.js:108-110` `bindActionMenus` 全局 document click 监听器泄漏
2. **MEDIUM**: `projectView.js:756-793` 文件上传使用裸 XHR 绕过 api.js
3. **MEDIUM**: 49 处空 `catch {}` 块
4. **MEDIUM**: `writingView.js:386-404` 状态泄露到全局 state
5. **MEDIUM**: `router.js:351` `state.loading` 嵌套导航竟态

### API 设计一致性审计 — 39 个问题（1 CRITICAL + 6 HIGH + 18 MEDIUM + 14 LOW）

**最严重发现**：
1. **CRIT-1**: `app/main.py:307-318` DomainError 处理器重复字段，3 种错误响应变体
2. **HIGH-1**: `memory/api.py:22` novel_id 路径/查询参数不一致
3. **HIGH-2**: ~42 端点无 response_model
4. **HIGH-3**: `rag/api.py:202-224` POST 在查询字符串接受主体数据
5. **HIGH-4**: `imports/api.py:278-302` /deep/resume 接受未类型 dict 主体
6. **HIGH-5**: `world/api.py:1528-1582` 别名 CRUD 用查询参数传别名

### 错误传播审计 — 8 个 GAP（1 CRITICAL + 5 HIGH + 2 MEDIUM）

**最严重发现**：
1. **CRIT-1**: ~50+ 处 `raise ValueError` 而非 `ValidationError` — 直达 500
2. **HIGH-1**: 缺失 HTTPException/RequestValidationError 处理器 — 39 路由不同 JSON 形状
3. **HIGH-2**: `outline/api.py:85` `detail=str(exc)` 信息泄露
4. **HIGH-3**: 错误响应 3 种变体
5. **HIGH-4**: `imports/api.py:151-163` double-fault 风险

### 性能/N+1 分析 — 20 个问题（1 CRITICAL + 1 HIGH + 10 MEDIUM + 8 LOW）

**最严重发现**：
1. **CRIT-1**: `world/repositories.py:165-184` 模糊搜索回退用 Python `SequenceMatcher` O(n²) — 阻塞事件循环
2. **HIGH-1**: `outline/api.py:527` `/scenes/ordered` 无分页，加载所有场景
3. **MEDIUM**: `rag/repositories.py:233-255` 逐行 SELECT N+1
4. **MEDIUM**: `outline/repositories.py:1301-1323` 逐场景 DB 调用
5. **MEDIUM**: BGE ONNX 嵌入进程内同步推理阻塞事件循环

## Round 4 累计

| 轮次 | 问题数 | CRITICAL | HIGH | MEDIUM | LOW |
|------|--------|----------|------|--------|-----|
| R1 | 251 | 24 | 60 | 95 | 72 |
| R2 | 59 | 5 | 11 | 21 | 22 |
| R3 | 80 | 9 | 18 | 29 | 24 |
| R4 | 93 | 3 | 13 | 49 | 38 |
| **累计** | **483** | **41** | **102** | **194** | **156** |

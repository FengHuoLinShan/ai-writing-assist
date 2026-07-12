# Round 2/20 - 跨模块交互 + 安全全景 + 数据流 + 文档审查

**Status**: PASS (全部 4 子代理成功返回)
**Total Round 2**: 59 个问题 (CRITICAL: 5, HIGH: 11, MEDIUM: 21, LOW: 22)

### 跨模块交互审计 — 15 个问题
- 🔴 CRITICAL: 1
- 🟠 HIGH: 2
- 🟡 MEDIUM: 5
- 🟢 LOW: 7

**最严重发现**：
1. **CRIT-1**: `rag/source_collection.py:125` DI 键 `world.get_entity_importance_map` 从未注册 — 实体重要性标注静默失效
2. **HIGH-1**: `outline/services.py:836-935` 原始 `ValueError` 通过 `writing/api.py:557` 不受阻碍 — 变成 500 而非 400
3. **HIGH-2**: `settings/facade.py:37` `LookupError` 通过 `project/api.py:111` 返回 500 而非 404  
**Goal**: 横切关注点全面扫描，发现跨模块交互问题和全局模式  
**Started**: 2026-07-13

## 已返回

### 文档/配置审查 — 17 个问题
- 🔴 CRITICAL: 2
- 🟠 HIGH: 5
- 🟡 MEDIUM: 7
- 🟢 LOW: 3

**最严重发现**：
1. **CRIT-1**: `.env.example` 未文档化 16+ 个环境变量（对应 `config.py` 定义）
2. **CRIT-2**: `backend/.env` 文件可见（可能被 git 跟踪过）
3. **HIGH-1**: `CLAUDE.md` 遗漏 `settings` 模块（活跃模块列表和三层架构表）
4. **HIGH-2**: `APP_DEBUG` vs `DEBUG` 环境变量名不匹配
5. **HIGH-3**: `pyproject.toml` vs `requirements.txt` 依赖严重不同步
6. **HIGH-4**: `alembic/env.py` 未导入 `modules.settings.models`
7. **CRIT-3**: `start.sh` 未启动任务 worker — 后台任务不会被处理
8. **HIGH-5**: `start.sh` 使用 `http.server` 而非 Vite — 无 HMR/模块解析

### 数据流分析 — 19 个问题
- 🔴 CRITICAL: 3
- 🟠 HIGH: 5
- 🟡 MEDIUM: 6
- 🟢 LOW: 5

**最严重发现**：
1. **CRIT-1**: `writing.generate` 前端 15s 超时 — AI 生成需 60-120s，必然超时
2. **CRIT-2**: HTTP 409 错误未在前端 errorMap 中映射 — 冲突错误显示"请求失败"
3. **CRIT-3**: `currentProjectId` 在 `currentProject` 加载前设置 — 视图渲染 null 数据窗口期
4. **HIGH-1**: `writing.listConflictChecks` 前端未验证必填 `chapter_index`
5. **HIGH-2**: `world.listEntities` contract 未要求 `requiredQuery: ["novel_id"]`
6. **HIGH-5**: imports 模块返回裸 dict 而非 Pydantic response model — 前端无响应验证

### 安全全景审查 — 19 个问题
- 🔴 CRITICAL: 1
- 🟠 HIGH: 6
- 🟡 MEDIUM: 8
- 🟢 LOW: 4

**最严重发现**：
1. **CRIT-1**: `backend/.env` 提交到 git — 包含活跃的 LLM API Key 和加密密钥
2. **HIGH-1**: `writing/repositories.py:210` 仓库 `delete()` 不验证 novel_id
3. **HIGH-2**: 多前端文件 — API 返回内容通过 `innerHTML` 未转义（XSS 风险）
4. **HIGH-3**: `world/map_api.py` 地图删除操作可能绕过 novel_id
5. **HIGH-4**: `rag/api.py:143` `/metrics` 端点无认证
6. **HIGH-5**: 前端 Bearer Token 明文存在 sessionStorage 且通过 HTTP 发送
7. **HIGH-6**: `main.py:324` 全局异常日志可能包含敏感数据

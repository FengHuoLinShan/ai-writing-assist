# AI 写作引擎 P0 修复计划 v1.0

> 依据：`AI小说结构化创作引擎_REVIEW_RULES_v1.0.md`
> 目标：修复全部 5 个 P0 阻塞项，达到可发布标准
> 原则：最小改动、模式统一、不引入新 bug

---

## P0-1：单资源端点跨 novel_id 越权（最高优先级）

### 根因

所有模块的 `Repository.get(id)` 仅按主键查询，不校验 `novel_id`。
API 层接收路径参数 `{entity_id}` 但不传 `novel_id` 给 service 层。
攻击者只需知道任意 UUID 即可跨小说读写/删除。

涉及模块：`world/character/geo/memory/timeline/outline/review/writing` — 40+ 端点。

### 修复方案：统一在 Repository 层加 `novel_id` 参数

**原则**：改动量最小且一致。不改 API 路由签名（避免前端改动）。

**模式A（含 novel_id 在请求体/Query 中的模块）**：
`world`, `character`, `geo`, `outline`, `review`, `rag` — 列表 API 已有 `novel_id` Query 参数。
单资源端点从对象本身获取 `novel_id`，先查后比较。

**模式B（含 novel_id 在路径中的模块）**：
`memory`, `timeline` — URL 为 `/novels/{novel_id}/memories/records/{id}`。
路径中已有 novel_id，只校验一致性。

**统一实现**：在每个 service 的 get/update/delete 方法中，获取对象后校验 `obj.novel_id`。

```python
# 通用模式：service 层校验
async def get(self, db, entity_id, novel_id):
    obj = await repo.get(db, entity_id)
    if obj is None or str(obj.novel_id) != novel_id:
        raise HTTPException(404)
    return obj
```

### 修复步骤

**Step 1** — `world/services.py`：6 个 service 类的 get/update/delete 各加 `novel_id` 参数和校验
- `WorldEntityService.get(entity_id)` → `get(entity_id, novel_id)`
- `WorldEntityService.update(entity_id, data)` → `update(entity_id, novel_id, data)`
- `WorldEntityService.delete(entity_id)` → `delete(entity_id, novel_id)`
- 同上：RelationshipService, EntityCandidateService, AliasService

**Step 2** — `world/api.py`：修改所有单资源端点，从 Query 中获取 `novel_id` 传给 service

**Step 3-8**：同样模式应用于 `character`, `geo`, `memory`, `timeline`, `outline`, `review`, `writing`

### 影响文件
| 模块 | services.py | api.py |
|------|:----------:|:------:|
| world | ✅ 修改 | ✅ 修改 |
| character | ✅ 修改 | ✅ 修改 |
| geo | ✅ 修改 | ✅ 修改 |
| memory | ✅ 修改 | ✅ 修改 |
| timeline | ✅ 修改 | ✅ 修改 |
| outline | ✅ 修改 | ✅ 修改 |
| review | ✅ 修改 | ✅ 修改 |
| writing | ✅ 修改 | ✅ 修改 |

### 验证
- 现有 306 个测试全部通过（需更新测试中的 service 调用，加上 `novel_id` 参数）
- 新增测试：用 novel A 的 ID 访问 novel B 的资源，期望返回 404

---

## P0-2：`accept_candidate()` 跨 novel 越权

### 根因
`EntityCandidateService.accept_candidate()` 在执行 `alias_of_existing` 或 `merge_with_existing` 时，未验证 `suggested_existing_entity_id` 对应的实体与候选属于同一 `novel_id`。

### 修复方案

在 `accept_candidate()` 的 `alias_of_existing` 和 `merge_with_existing` 分支中，获取已有实体后增加校验：

```python
entity = await entity_repo.get(db, existing_eid)
if entity is None or str(entity.novel_id) != novel_id:
    raise HTTPException(400, "Suggested entity does not belong to this novel")
```

### 影响文件
- `modules/world/services.py` — 仅 `accept_candidate()` 方法（2 个分支各加 2 行校验）

### 验证
- 创建 novel A 的候选，suggested_existing_entity_id 指向 novel B 的实体
- 调用 `accept_candidate()` 期望返回 400 错误

---

## P0-3：RAG 不按 visibility 过滤

### 根因
`rag/repositories.py` 的 `keyword_search()`、`find_by_entity()` 等方法无 `visibility` 过滤参数。
`rag/facade.py` 的 `retrieve()` 无 `visibility` 参数。
Context Compiler 的 `_load_rag_chunks()` 不根据 `reveal_mode` 过滤。

### 修复方案

**Step 1** — `rag/repositories.py`：为所有检索方法添加 `visibility` 可选参数，传入时加过滤条件

**Step 2** — `rag/services.py`：`hybrid_search()` 添加 `visibility` 参数并透传

**Step 3** — `rag/facade.py`：`retrieve()` 添加 `visibility` 参数

**Step 4** — `context/services.py`：`_load_rag_chunks()` 根据 `reveal_mode` 推导 visibility：
- `author_safe` → 排除 `author_only`
- `reader` → 只取 `reader_known`

### 影响文件
- `rag/repositories.py` — 2 个方法加参数
- `rag/services.py` — 1 个方法加参数
- `rag/facade.py` — 1 个方法加参数
- `context/services.py` — 1 个方法加过滤逻辑

### 验证
- 创建 visibility=`author_only` 的 RAG chunk
- `author_safe` 模式检索 → 该 chunk 不出现在结果中
- 现有 306 个测试通过

---

## P0-4：前端 `esc()` 函数未定义 → XSS

### 根因
`characterView.js`、`projectView.js`、`worldView.js` 多处调用 `esc(data)` 但该函数从未定义。
所有用户/LLM 数据通过 `innerHTML` 直接注入，未经转义。

### 修复方案

**Step 1** — 在 `app.js` 顶部添加全局 `esc()` 工具函数：

```javascript
// 在所有脚本之前定义：
// <script src="state.js"></script>  ← 在 state.js 中使用
function esc(str) {
  if (str === null || str === undefined) return "";
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}
```

注意：此函数必须定义在**被所有视图使用之前**。当前加载顺序为 `state.js → api.js → router.js → commands.js → app.js → views/*.js`。应将 `esc()` 放在 `state.js` 开头，确保所有后续脚本可用。

**Step 2** — 检查所有 `innerHTML` 使用点，确保数据经过 `esc()`：

当前已使用 `esc()` 但失败的位置（函数不存在）：
- `characterView.js:111,391` — `esc(c.name)`, `esc(char.name)`
- `projectView.js:39-46` — `esc(p.title)`, `esc(p.genre)`
- `worldView.js:99-100,164-165` — `esc(e.name)`, `esc(c.name)`

当前未使用 `esc()` 的危险位置：
- `ragView.js:114` — `results.innerHTML = html` 含 `chunk.text`
- `generateView.js:316` — `resultEl.innerHTML = previewHtml`
- `reviewView.js:92,94` — `output.innerHTML = html`
- `contextView.js:241` — `output.innerHTML = this._escapeHtml(...)` ✅ 正确使用但 `_escapeHtml` 本应可用

### 影响文件
- `state.js` — 添加 `esc()` 定义
- `ragView.js` — 包装 `chunk.text`
- `generateView.js` — 包装预览 HTML 中的数据

### 验证
- 创建名为 `<img src=x onerror=alert(1)>` 的世界对象
- 在对象列表页查看 → 文本渲染不弹窗

---

## P0-5：前端 `err.message` / API 数据直接 innerHTML 注入

### 根因
`contextView.js`、`ragView.js`、`reviewView.js`、`generateView.js` 将 API 返回的 `err.message`、`warnings[i]`、`budget_used` 等直接拼入 HTML 字符串后 `innerHTML`。

### 修复方案

**Step 1** — `ragView.js:114`：`results.innerHTML = html` → 确保 `html` 中的 `chunk.text` 经过 `esc()`

**Step 2** — `generateView.js:316`：`resultEl.innerHTML = previewHtml` → 确保预览数据经过 `esc()`

**Step 3** — `reviewView.js:92,94`：复查输出 `innerHTML` → 确保 `data` 中的 `message` 字段经过 `esc()`

**Step 4** — `contextView.js:202`：`output.innerHTML = html` → 确保 `data.scope`/`data.reveal_mode`/`warnings` 经过 `esc()`

### 影响文件
- `contextView.js` — 审查所有 innerHTML 注入点
- `ragView.js` — 审查 `_doSearch()`
- `generateView.js` — 审查 `_renderPreview()`
- `reviewView.js` — 审查 `runReview()`

### 验证
- 后端返回含 `<script>` 的 error detail
- 页面渲染为纯文本，不执行脚本

---

## 修复顺序与依赖

```
Step 1: state.js — 添加 esc() 定义           (P0-4/5 前置)
Step 2: rag/repositories.py                  (P0-3)
Step 3: rag/services.py                      (P0-3)
Step 4: rag/facade.py                        (P0-3)
Step 5: context/services.py                  (P0-3)
Step 6: world/services.py — novel_id         (P0-1)
Step 7: world/services.py — accept_candidate (P0-2)
Step 8: world/api.py                         (P0-1)
Step 9: character/services.py + api.py       (P0-1)
Step 10: geo/services.py + api.py            (P0-1)
Step 11: memory/services.py + api.py         (P0-1)
Step 12: timeline/services.py + api.py       (P0-1)
Step 13: outline/services.py + api.py        (P0-1)
Step 14: review/services.py + api.py         (P0-1)
Step 15: writing/services.py + api.py        (P0-1)
Step 16: frontend ragView.js                 (P0-4/5)
Step 17: frontend generateView.js            (P0-4/5)
Step 18: frontend reviewView.js              (P0-4/5)
Step 19: frontend contextView.js             (P0-4/5)
Step 20: 全量测试验证
```

## 预估改动量

| 分类 | 文件数 | 改动行数（约） |
|------|:------:|:--------------:|
| 前端 XSS | 5 | ~30 行 |
| RAG visibility | 4 | ~40 行 |
| 后端 novel_id（8 模块） | 16 | ~150 行 |
| 测试更新 | 8 | ~80 行 |
| **合计** | **33** | **~300 行** |

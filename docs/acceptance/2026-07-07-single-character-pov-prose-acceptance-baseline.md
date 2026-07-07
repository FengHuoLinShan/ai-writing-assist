# 单角色 POV 正文候选生成能力 — 验收基线

**日期:** 2026-07-07  
**状态:** 验收基线，非验收结果  
**范围:** 建议 1-4：写作页 POV 入口、角色视角 Context Compiler、POV 结构化候选与泄漏诊断、生成中心手动 Scene/角色入口  

本文档从四个已执行计划、当前实现、测试、迁移、文档和用户验收清单重建验收基线。仓库此前没有独立 acceptance 文档，因此本文件作为最终验收的对照标准。

---

## 1. 四个计划的验收基线

### 1.1 建议 1：写作页当前 Scene POV 入口

- 写作页新增独立入口：`AI 角色视角草稿`，不改变原有 `AI 生成草稿` 行为。
- 入口使用当前章节 / 光标定位当前 Scene。
- 找不到 Scene、Scene 无 `pov_character_id`、AI 参考资料确认取消或失败时，必须停止，不能调用 `api.writing.generate`。
- `confirmAiReference(options)` 的 context preview / refresh / confirm 等 payload 构造路径必须统一透传：
  - `scene_id`
  - `reveal_mode`
  - `viewpoint_character_id`
  - `character_ids`
  - `chapter_index`
  - `include_pending_objects`
  - `context_mode`
  - `excluded_asset_ids`
- POV 入口创建 confirmation 时固定传：
  - `action: "writing.generate"`
  - `task: "基于当前 Scene 的 POV 角色有限认知，生成正文候选草稿"`
  - `scope: "chapter"`
  - `chapter_index`
  - `scene_id`
  - `reveal_mode: "character"`
  - `viewpoint_character_id: currentScene.pov_character_id`
  - `character_ids: [currentScene.pov_character_id]`
  - `include_pending_objects: true`
- confirmation 成功后调用现有 `api.writing.generate`，payload 必须携带 `context_confirmation_id`。
- 追加 instruction 只能作为任务说明；角色知识边界必须由后端 Context Compiler 执行。

### 1.2 建议 2：角色视角 Context Compiler

- `reveal_mode="character"` 下编译并展示主要 sections：
  - `role_profile`
  - `role_visible_knowledge`
  - `role_relationship_context`
  - `role_scene_perception`
  - `scene_director_constraints`
  - `scene_time_boundary`
- `scene_director_constraints` 必须明确标记为 director-only，不得作为角色已知事实。
- `scene_blueprint` 不再作为角色可知 section 使用；如果保留，只能作为兼容 alias / debug metadata。
- legacy `pov_knowledge` 在 character reveal 模式下不能和 `role_visible_knowledge` 重复完整渲染。
- `CharacterKnowledge` 显式记录优先：
  - `unknown`：不进入角色可见上下文，可用于 hidden guard，但不列出具体隐藏内容。
  - `restricted`：只显示 `known_content`。
  - `false_belief` / `misunderstood`：只显示 `misconception`。
  - `partial` / `rumor`：显示 `known_content` 并标记传闻或部分认知。
  - `full`：允许显示角色完整知道的信息，但不能透传无关 author-only metadata。
- 无 `CharacterKnowledge` 记录不等同 unknown：
  - 可进入：实体 `name` / `entity_type` / `public_info`、公开关系、当前 Scene 可感知事实。
  - 默认不进入：`hidden_truth`、author-only 字段、无法证明公开的 `summary`、隐性关系 description。
- `entity_relations.description` 默认不进入角色视角；仅公开关系类型或 relation 级 knowledge 允许进入。
- `memory_snapshots.full_state` 和完整 JSON 不得直接进入角色视角；memory 只能以已过滤摘要或事件单位进入。
- `ContextSection.sources` 只允许安全元信息；label / preview / summary 也必须经过过滤，不能泄露 hidden truth。
- RAG 检索支持 `scene_id` 与 `strict_scene_filter`：
  - character reveal + `scene_id` 时，当前 Scene evidence 只允许 `chunk.scene_id == scene_id`。
  - `chunk.scene_id IS NULL` 不进入 `CharacterViewContext`，只产生 warning。
  - 非 character 模式保留原 chapter fallback 行为。
  - keyword path 和 vector path 都必须应用 scene metadata filter。

### 1.3 建议 3：POV 结构化候选与泄漏诊断

- `writing_drafts.provenance_json` 是正式持久化契约；ORM、schema、response、migration、docs 必须一致。
- `WritingGenerationService` 只在有效 confirmation 下切换到 `pov_character` profile：
  - 同 novel
  - `action="writing.generate"`
  - confirmed / fresh
  - `reveal_mode="character"`
  - `scene_id` 非空
  - `viewpoint_character_id` 非空
- 其它情况保持 default profile。
- POV profile 使用结构化 JSON prompt，输出：
  - `perception`
  - `interpretation`
  - `inner_monologue`
  - `true_intention`
  - `action`
  - `expression`
  - `dialogue_candidates`
  - `subtext`
  - `unsaid`
  - `draft_prose`
- `unsaid` 只能表示角色已经知道但不说出口的内容，不能作为作者隐藏真相入口。
- `writing_drafts.content` 保存 `draft_prose`。
- `provenance_json` 至少保存：
  - `generation_profile`
  - `context_confirmation_id`
  - `scene_id`
  - `viewpoint_character_id`
  - `prompt_name`
  - `prompt_hash`
  - `model`
  - `pov_view`
  - `pov_validation`
- `HiddenGuardBuilder` / `CharacterRevealGuard` 必须复用 Context Compiler 的同一套过滤语义。
- hidden guard 不进入生成 prompt，只用于后处理诊断。
- guard 检查完整 `pov_view` 所有文本字段和 `draft_prose`，尤其是 `inner_monologue`、`subtext`、`unsaid`。
- findings 只记录 redacted 安全信息，不保存 hidden source 原文：
  - `rule`
  - `severity`
  - `field_path`
  - `generated_excerpt`
  - `source_type`
  - `source_id`
  - `source_label`
  - `redacted: true`
- JSON fallback 规则：
  - 先严格 parse。
  - 再做一次轻量 repair。
  - repair 成功记录 `json_repaired` warning。
  - repair 失败但 raw text 非空：保存 raw text candidate，`pov_view=null`，记录 `pov_parse_failed`。
  - raw text 为空：任务失败，不创建空 draft。
- 泄漏诊断命中时仍创建 `candidate` draft，但前端必须标红；failed candidate 不得自动插入或发布，用户必须显式确认后才可采用。
- 文案使用“未发现明显越权”，不得宣称绝对安全。

### 1.4 建议 4：生成中心手动 Scene / 角色 POV 正文入口

- 建议 4 依赖建议 1-3 已完成；它只是生成中心入口扩展，不新增后端 action，不新增 simulation 表。
- 生成中心新增 `角色视角正文` 模式，与对象生成、任务、上下文预览等状态隔离。
- POV 表单包含：
  - 章节选择：进入模式时加载 `api.writing.listChapters`。
  - Scene 选择：选择章节后加载 `api.outline.listScenesByChapter`，并清空旧 Scene / 角色选择。
  - 角色选择：进入模式时加载 `api.world.listCharacters`。
  - 作者指令输入：作为创作意图，不等于角色知识。
- 选择 Scene 后自动重置为该 Scene 的 `pov_character_id`；Scene 无 POV 时清空角色并要求用户手动选择。
- 用户手动选择的角色若不同于 Scene `pov_character_id`，显示提示：`本次使用手动选择角色，不修改 Scene POV 设置`，但允许提交。
- 提交前校验 `novelId` / `chapterIndex` / `sceneId` / `selectedCharacterId`；缺任一项则 toast 并停止。
- 提交时调用 `confirmAiReference`：
  - `action: "writing.generate"`
  - `task: "基于所选 Scene 和 POV 角色有限认知，生成正文候选草稿"`
  - `scope: "chapter"`
  - `chapter_index`
  - `scene_id`
  - `reveal_mode: "character"`
  - `viewpoint_character_id: selectedCharacterId`
  - `character_ids: [selectedCharacterId]`
  - `include_pending_objects: true`
- confirmation 成功后调用 `api.writing.generate`，payload 携带 `context_confirmation_id`。
- instruction 必须说明：用户指令是作者意图，不等于角色知识；角色判断、台词和内心只能使用确认上下文中可见信息。
- 生成成功后，生成中心结果区展示 chapter / Scene / role / draft id 或 task id，并提供跳转写作页入口。
- 候选正文查看、POV panel 和泄漏诊断展示由写作页读取 `provenance_json` 负责。

---

## 2. 关键检查文件

### Frontend

- `frontend-console/views/generateView.js` — 生成中心 subtab、POV 正文表单、提交与结果 summary。
- `frontend-console/views/writing/tools.js` — 写作页当前 Scene POV 入口。
- `frontend-console/views/writing/editor.js` — POV 结构化候选 panel、风险提示、failed 显式采用。
- `frontend-console/shared/aiReferenceModal.js` — context payload 统一透传。
- `frontend-console/api.js` — `writing.generate`、章节、Scene、角色 API 调用。

### Backend

- `backend/modules/context/services/context_compiler.py` — character reveal sections 与可见性规则。
- `backend/modules/context/services/hidden_guard.py` — hidden guard 构建与泄漏诊断。
- `backend/modules/context/services/loaders/rag_chunks_loader.py` — character reveal 下 RAG scene 过滤。
- `backend/modules/context/facade.py` — context confirm / prepare action / hidden guard 入口。
- `backend/modules/rag/retrieval.py` — RAG 检索参数与过滤传递。
- `backend/modules/rag/repositories.py` — keyword / vector path 的 scene metadata filter。
- `backend/modules/writing/services.py` — `writing.generate` profile 选择、confirmation 校验、draft 创建。
- `backend/modules/writing/pov_generation.py` — POV JSON prompt、parse / repair / fallback、validation 汇总。
- `backend/modules/writing/models.py` — `writing_drafts.provenance_json`。
- `backend/modules/writing/schemas.py` — `WritingDraftResponse.provenance_json` 与 request contract。

### Tests / migrations / docs

- `frontend-console/tests/generateView.test.js`
- `frontend-console/tests/writing/tools.test.js`
- `frontend-console/tests/aiReferenceModal.test.js`
- `frontend-console/tests/writing/editor.test.js`
- `backend/modules/context/tests/test_context.py`
- `backend/modules/writing/tests/test_writing.py`
- `backend/modules/rag/tests/test_rag.py`
- `backend/alembic/versions/20260707_writing_draft_provenance.py`
- `docs/modules/11_writing.md`
- `docs/01_数据库设计.md`
- `docs/superpowers/specs/2026-07-07-merge-generate-context-design.md`

---

## 3. 必跑测试命令

### Frontend targeted

```bash
cd frontend-console && npm test -- tests/generateView.test.js tests/writing/tools.test.js tests/aiReferenceModal.test.js tests/writing/editor.test.js
```

### Backend targeted

```bash
cd backend && pytest modules/context/tests/test_context.py modules/writing/tests/test_writing.py modules/rag/tests/test_rag.py -q
```

### Diff hygiene

```bash
git diff --check
```

### 建议的最终回归

```bash
cd frontend-console && npm test
```

如果验收范围要求真实页面交互，还应补充一次浏览器级手工或 Playwright 页面检查，确认生成中心、写作页 POV panel 和风险提示视觉行为可用。

---

## 4. 已知未知项

- 本文件是重建的 acceptance baseline，不是已通过的验收报告。
- 当前工作区可能包含其它 agent 的生成中心 / context 页融合变更，最终验收时必须区分本功能变更和其它并行变更。
- `scene_id` 在本版 character reveal 中表示当前 Scene 锚点、RAG 场景边界、POV 生成锚点；它不等于完整 “第 1 章到当前 Scene” 的事件级时间切片。
- deterministic guard 只表示“未发现明显越权”，不提供语义级无泄漏保证。
- `listScenesByChapter` 必须实际返回 `pov_character_id`；若真实 API 没有返回，需要在验收中标为阻断或补查 scene detail fallback。
- 如果目标数据库没有 `writing_drafts.provenance_json`，必须先应用迁移或重建 demo DB 后再验收。
- 若最终验收要求用户可见体验，单元测试不足以替代浏览器级检查。

---

## 5. 推荐 final acceptance goal

```text
/goal 最终验收“建议 1-4：单角色 POV 正文候选生成能力”。只做验收，不改代码。请对照 docs/acceptance/2026-07-07-single-character-pov-prose-acceptance-baseline.md 检查写作页 POV 入口、生成中心角色视角正文 subtab、AI 参考资料确认 payload、Context Compiler character reveal sections、RAG scene filter、writing.generate POV profile/provenance_json、HiddenGuard 泄漏诊断、写作页 POV panel；运行指定前后端测试和 git diff --check；最后输出通过/不通过、阻断问题、非阻断风险和关键证据文件。
```


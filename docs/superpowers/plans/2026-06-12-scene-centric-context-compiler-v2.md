# Scene-Centric Context Compiler v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and validate the Scene-Centric Context Compiler v2 user path, allowing authors to select task, chapter/scene, reveal mode, viewpoint character, and budget, then compile a structured context and render it as a Markdown prompt.

**Architecture:** Add `scene_id` and `budget_tokens` to the context compile pipeline. Load the current Scene card as the Scene Blueprint (P0). Filter foreshadowing by `planned_payoff_scene` relative to the current scene index. Enforce CharacterKnowledge levels (`unknown`, `restricted`, `misunderstood`) through the existing world facade filter. Keep MarkdownRenderer as a pure IR→Markdown transform; all business decisions happen in the compiler. Frontend `contextView` gains Scene selection, budget input, and Tier result display.

**Tech Stack:** Python 3.13 + FastAPI + SQLAlchemy async + Pydantic; vanilla JS SPA; pytest + Playwright E2E.

---

## File Map

| File | Responsibility |
|------|----------------|
| `backend/modules/outline/models.py` | Add `planned_payoff_scene` to `ForeshadowingPlan` ORM. |
| `backend/modules/outline/schemas.py` | Add `planned_payoff_scene` to ForeshadowingPlan create/update/response schemas. |
| `backend/modules/outline/facade.py` | Expose `planned_payoff_scene` in `get_active_foreshadowing()` dict output. |
| `backend/modules/world/models.py` | Allow `restricted`/`misunderstood` values in `CharacterKnowledge.knowledge_level` comment/default (no schema change needed, values are free strings). |
| `backend/modules/world/services/character_knowledge_service.py` | Update logic to treat `restricted` like `partial` and `misunderstood` like `false_belief`. |
| `backend/modules/world/services/character_service.py` | Update `filter_context_by_character_knowledge()` to handle `restricted` and `misunderstood`. |
| `backend/modules/context/contracts.py` | Add `scene_id`, `budget_tokens` to `CompileOptions`; add `scene` field to `StructureContextBundle`; keep `CONTEXT_BUDGET` defaults. |
| `backend/modules/context/schemas.py` | Add `scene_id`, `budget_tokens` to request schemas; add `tiers`, `evicted`, `total_tokens` to response schemas. |
| `backend/modules/context/services/loaders/*.py` | Add `SceneLoader`; update `CharactersLoader`/`RagChunksLoader` for scene-centric behavior. |
| `backend/modules/context/services/constraint_engine.py` | Filter foreshadowing by scene index; expand knowledge constraints for `restricted`/`misunderstood`; pass `scene_id`. |
| `backend/modules/context/services/context_compiler.py` | Wire `scene_id` through compilation; use `SceneLoader`; build 9-tier IR. |
| `backend/modules/context/services/compiled_context.py` | Keep P0 retention and eviction order P4→P3→P2→P1 (already correct). |
| `backend/modules/context/facade.py` | Expose `compile_with_tiers` parameters including `scene_id`/`budget_tokens`. |
| `backend/modules/context/api.py` | `/compile` returns Tier IR; `/render` compiles Tier IR then renders markdown. |
| `backend/modules/context/markdown_renderer.py` | Ensure `render_compiled_context()` is pure IR renderer; remove business logic. |
| `frontend-console/views/contextView.js` | Add Scene dropdown, budget input, Tier result display, warnings, and clearer validation messages. |
| `frontend-console/api.js` | Ensure `api.context.compile`/`render` accept new fields (already passes through). |
| `backend/tests/unit/test_context.py` | Update/add unit tests for Tier IR, budget enforcement, knowledge boundaries, foreshadowing scene filter, must_not_happen. |
| `backend/modules/context/tests/test_context.py` | Update integration tests. |
| `frontend-console/e2e/context.spec.js` | Add E2E coverage for page load, no-project warning, compile result, character mode missing viewpoint block, contract submission. |
| `backend/tests/e2e/seed_data.py` | Add Scene cards, character knowledge records, foreshadowing plans for 《诡秘之主 第一部》 acceptance test. |

---

## Task 1: Extend ForeshadowingPlan model for scene-level payoff

**Files:**
- Modify: `backend/modules/outline/models.py`
- Modify: `backend/modules/outline/schemas.py`
- Modify: `backend/modules/outline/facade.py`
- Test: `backend/tests/unit/test_context.py` (foreshadowing tests)

- [ ] **Step 1: Add `planned_payoff_scene` column to ORM**

Modify `backend/modules/outline/models.py` around line 167 (after `planned_payoff_chapter`):

```python
    planned_payoff_scene: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="兑现 Scene 索引（scene-centric 编译使用）",
    )
```

- [ ] **Step 2: Add field to create/update/response schemas**

In `backend/modules/outline/schemas.py`, add `planned_payoff_scene: int | None = Field(None, ge=0)` to:
- `ForeshadowingPlanCreate` (after line 269)
- `ForeshadowingPlanUpdate` (after line 285)
- `ForeshadowingPlanResponse` (after line 302)

- [ ] **Step 3: Expose field in facade**

In `backend/modules/outline/facade.py`, in `get_active_foreshadowing()` dict output (around line 189), add:

```python
            "planned_payoff_scene": p.planned_payoff_scene,
```

- [ ] **Step 4: Run outline tests**

Run: `cd backend && pytest tests/unit tests/integration -q -k outline`
Expected: All outline tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/outline/models.py backend/modules/outline/schemas.py backend/modules/outline/facade.py
git commit -m "feat(outline): add planned_payoff_scene to ForeshadowingPlan for scene-centric context"
```

---

## Task 2: Extend CharacterKnowledge levels

**Files:**
- Modify: `backend/modules/world/services/character_knowledge_service.py`
- Modify: `backend/modules/world/services/character_service.py`
- Test: `backend/tests/unit/test_world.py` or `backend/tests/unit/test_context.py`

- [ ] **Step 1: Read current CharacterKnowledge service logic**

Read `backend/modules/world/services/character_knowledge_service.py` to find where `knowledge_level` values are validated/used.

- [ ] **Step 2: Normalize level names**

If the service validates a closed set of levels, add `restricted` and `misunderstood` as aliases:

```python
# In validation/normalization helper
_LEVEL_ALIASES = {
    "restricted": "partial",
    "misunderstood": "false_belief",
}

def normalize_level(level: str) -> str:
    return _LEVEL_ALIASES.get(level, level)
```

If there is no closed validation, simply ensure downstream consumers handle them.

- [ ] **Step 3: Update filter_context_by_character_knowledge in CharacterService**

Read `backend/modules/world/services/character_service.py` around `filter_context_by_character_knowledge()`. Ensure:
- `unknown` → mark item as removed (do not include in filtered output).
- `restricted` → keep item but replace `summary`/`public_info` with `known_content` only; remove `hidden_truth`.
- `misunderstood` → keep item but replace `summary` with `misconception`; remove `hidden_truth`.
- `false_belief` → existing behavior unchanged (misunderstood alias).

Pseudo-code addition:

```python
if level in ("partial", "rumor", "restricted"):
    # Include only known_content; redact hidden_truth
    filtered_item = {**item}
    if knowledge.known_content:
        filtered_item["summary"] = knowledge.known_content
    filtered_item.pop("hidden_truth", None)
    result.append(filtered_item)
elif level in ("false_belief", "misunderstood"):
    # Replace summary with misconception
    filtered_item = {**item}
    if knowledge.misconception:
        filtered_item["summary"] = knowledge.misconception
        filtered_item["misconception"] = knowledge.misconception
    filtered_item.pop("hidden_truth", None)
    result.append(filtered_item)
```

- [ ] **Step 4: Run world tests**

Run: `cd backend && pytest tests/unit tests/integration -q -k world`
Expected: Pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/world/services/
git commit -m "feat(world): support restricted/misunderstood knowledge levels"
```

---

## Task 3: Update Context contracts and schemas

**Files:**
- Modify: `backend/modules/context/contracts.py`
- Modify: `backend/modules/context/schemas.py`
- Test: `backend/tests/unit/test_context.py::TestContracts`, `backend/tests/unit/test_context.py::TestSchemaValidation`

- [ ] **Step 1: Extend CompileOptions**

In `backend/modules/context/contracts.py`, modify `CompileOptions` (around line 15):

```python
@dataclass
class CompileOptions:
    """编译选项 — facade 与 compiler 之间的契约"""

    novel_id: str
    task: str
    scope: str
    chapter_index: int | None = None
    scene_id: str | None = None
    """当前 Scene ID（scene-centric 编译时提供）"""
    arc_id: str | None = None
    entity_ids: list[str] | None = None
    character_ids: list[str] | None = None
    location_ids: list[str] | None = None
    reveal_mode: str = "author_safe"
    viewpoint_character_id: str | None = None
    enable_geo_filter: bool = False
    mode: str = "writing"
    budget_tokens: int = 4000
    """总 token 预算，默认 4000"""
```

- [ ] **Step 2: Add scene field to StructureContextBundle**

Modify `StructureContextBundle` (around line 72):

```python
    scene: dict | None = None
    """当前 Scene 卡"""
```

- [ ] **Step 3: Extend API request schemas**

In `backend/modules/context/schemas.py`, add to `ContextCompileRequest` and `ContextRenderRequest`:

```python
    scene_id: str | None = Field(
        None,
        description="当前 Scene ID（scene-centric 编译时使用）",
    )
    budget_tokens: int = Field(
        default=4000,
        ge=500,
        le=32000,
        description="总 token 预算",
    )
```

- [ ] **Step 4: Add Tier/IR response schema**

Append to `backend/modules/context/schemas.py`:

```python
class ContextSectionItem(BaseModel):
    """单个 Tier 段"""

    key: str = Field(..., description="段标识")
    tier: int = Field(..., description="优先级 Tier 0-4")
    content: str = Field(..., description="段内容")
    token_count: int = Field(..., description="估算 token 数")
    truncated: bool = Field(default=False, description="是否被截断")


class ContextTierCompileResponse(BaseModel):
    """Scene-Centric 编译响应"""

    novel_id: str
    task: str
    scope: str
    reveal_mode: str
    scene_id: str | None = None
    viewpoint_character_id: str | None = None
    total_tokens: int = Field(default=0)
    budget_tokens: int = Field(default=4000)
    sections: list[ContextSectionItem] = Field(default_factory=list)
    evicted: list[str] = Field(default_factory=list, description="被驱逐的段 key 列表")
    truncated: list[str] = Field(default_factory=list, description="被截断的段 key 列表")
    warnings: list[str] = Field(default_factory=list)
```

Update `ContextCompileResponse` to include `scene_id`, `viewpoint_character_id`, `total_tokens`, `budget_tokens`, `evicted`, `truncated` (or switch `/compile` to return `ContextTierCompileResponse` directly).

Decision: `/api/context/compile` will return `ContextTierCompileResponse` (the new IR). `/api/context/render` returns `ContextRenderResponse` whose `markdown` is rendered from the IR.

- [ ] **Step 5: Update tests**

Add schema validation tests for `scene_id` and `budget_tokens` bounds.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/context/contracts.py backend/modules/context/schemas.py
git commit -m "feat(context): add scene_id and budget_tokens to compile contracts and schemas"
```

---

## Task 4: Add SceneLoader and update existing loaders

**Files:**
- Create: `backend/modules/context/services/loaders/scene_loader.py`
- Modify: `backend/modules/context/services/loaders/__init__.py`
- Modify: `backend/modules/context/services/context_compiler.py`
- Modify: `backend/modules/context/services/loaders/characters_loader.py`
- Modify: `backend/modules/context/services/loaders/rag_chunks_loader.py`
- Test: `backend/tests/unit/test_context.py` loader tests

- [ ] **Step 1: Create SceneLoader**

Create `backend/modules/context/services/loaders/scene_loader.py`:

```python
"""当前 Scene 卡加载器"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class SceneLoader(Loader):
    """加载当前 Scene 卡作为 Scene Blueprint 来源"""

    @property
    def name(self) -> str:
        return "scene"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        if not options.scene_id:
            return

        from modules.outline.facade import get_scene

        scene = await get_scene(db, options.scene_id)
        if scene is None:
            bundle.warnings.append(f"Scene {options.scene_id} 不存在")
            return

        bundle.scene = scene
        if scene.get("pov_character_id") and not options.viewpoint_character_id:
            bundle.warnings.append(
                "当前 Scene 有默认 POV 人物，但请求未指定视角人物"
            )
```

- [ ] **Step 2: Export SceneLoader**

In `backend/modules/context/services/loaders/__init__.py`, add:

```python
from modules.context.services.loaders.scene_loader import SceneLoader
```

and add to `__all__`.

- [ ] **Step 3: Update CharactersLoader inference**

In `backend/modules/context/services/loaders/characters_loader.py`, replace `_infer_character_ids` stub with:

```python
    async def _infer_character_ids(
        self,
        db: AsyncSession,
        options: CompileOptions,
        limit: int,
    ) -> list[str]:
        """推断相关人物 ID：优先 Scene POV，其次请求指定，最后世界对象中 character 类型"""
        ids: list[str] = []

        # 1. Scene POV character
        if options.scene_id:
            from modules.outline.facade import get_scene

            scene = await get_scene(db, options.scene_id)
            pov = scene.get("pov_character_id") if scene else None
            if pov:
                ids.append(pov)

        # 2. 请求中指定的 character_ids（去重追加）
        if options.character_ids:
            for cid in options.character_ids:
                if cid not in ids:
                    ids.append(cid)

        # 3. 从世界对象中补充 character 类型实体
        if not ids and bundle.world_entities:
            for ent in bundle.world_entities:
                if ent.get("entity_type") == "character":
                    eid = ent.get("entity_id") or ent.get("id")
                    if eid and eid not in ids:
                        ids.append(eid)
                if len(ids) >= limit:
                    break

        return ids[:limit]
```

Also change the `load()` method to pass `bundle` to `_infer_character_ids`.

- [ ] **Step 4: Cap RAG chunks by top_k**

In `backend/modules/context/services/loaders/rag_chunks_loader.py`, cap retrieved chunks:

```python
        top_k = getattr(options, "top_k", None) or 8
        # ... existing retrieve call ...
        if bundle.rag_chunks:
            bundle.rag_chunks = bundle.rag_chunks[:top_k]
            bundle.budget_used["rag_chunks"] = len(bundle.rag_chunks)
```

Also add `top_k: int = 8` to `CompileOptions` in `contracts.py` (or compute from `budget_tokens`). Decision: add `top_k: int = 8` to `CompileOptions`.

- [ ] **Step 5: Update ContextCompiler loader lists**

In `backend/modules/context/services/context_compiler.py`:
- Add `"scene"` to the beginning of `"arc"`, `"chapter"`, `"full"` loader lists.
- Add `SceneLoader()` to `_default_loaders()`.

- [ ] **Step 6: Run loader tests**

Run: `cd backend && pytest tests/unit/test_context.py -q -k Loader`
Expected: Pass (update mock expectations as needed).

- [ ] **Step 7: Commit**

```bash
git add backend/modules/context/services/loaders/ backend/modules/context/services/context_compiler.py
git commit -m "feat(context): add SceneLoader, infer POV characters, cap RAG top_k"
```

---

## Task 5: Update ConstraintEngine for scene-centric rules

**Files:**
- Modify: `backend/modules/context/services/constraint_engine.py`
- Test: `backend/tests/unit/test_context.py`

- [ ] **Step 1: Pass scene_id and scene_index to constraints**

Modify `compile_constraints` signature:

```python
    async def compile_constraints(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str | None = None,
        scene_index: int | None = None,
        chapter_index: int | None = None,
    ) -> list[ContextSection]:
```

- [ ] **Step 2: Filter foreshadowing by scene index**

Update `_foreshadowing_constraints`:

```python
    async def _foreshadowing_constraints(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_index: int | None = None,
        chapter_index: int | None = None,
    ) -> list[ContextSection]:
        from modules.outline.facade import get_active_foreshadowing

        plans = await get_active_foreshadowing(db, novel_id, status="seeded")

        if not plans:
            return []

        active = []
        for plan in plans:
            payoff_scene = plan.get("planned_payoff_scene")
            payoff_ch = plan.get("planned_payoff_chapter")

            if scene_index is not None and payoff_scene is not None:
                if payoff_scene <= scene_index:
                    continue  # due for payoff, no constraint
            elif chapter_index is not None and payoff_ch is not None:
                if payoff_ch <= chapter_index:
                    continue
            else:
                # Cannot determine ordering; include as a conservative warning
                pass

            active.append(plan)

        if not active:
            return []
        # ... rest unchanged ...
```

- [ ] **Step 3: Expand knowledge constraints for restricted/misunderstood**

Update `_knowledge_constraints`:

```python
        unknown_count = 0
        restricted_count = 0
        misunderstood: list[str] = []

        for entry in entries:
            level = entry.get("knowledge_level")
            target_ref = (
                f"{entry.get('target_type', '')}:{entry.get('target_id', '')}"
            )
            if level == "unknown":
                unknown_count += 1
            elif level in ("restricted", "partial", "rumor"):
                restricted_count += 1
            elif level in ("false_belief", "misunderstood"):
                misconception = entry.get("misconception")
                if misconception:
                    misunderstood.append(f"- {target_ref}: {misconception}")

        if unknown_count > 0:
            lines.append(
                f"角色对 {unknown_count} 个目标实体/人物的知识级别为 unknown，"
                f"写作时不得让角色知晓这些实体的隐藏信息"
            )
        if restricted_count > 0:
            lines.append(
                f"角色对 {restricted_count} 个目标实体/人物的知识受限，"
                f"只能使用已知内容(known_content)描述，不得暴露 hidden_truth"
            )
        if misunderstood:
            lines.append(
                "角色对以下实体存在错误认知，应按错误认知表现:\n"
                + "\n".join(misunderstood)
            )
```

- [ ] **Step 4: Update caller to pass scene_index**

In `ContextCompiler.compile_with_tiers`, compute `scene_index` from `bundle.scene` and pass it:

```python
        scene_index = bundle.scene.get("scene_index") if bundle.scene else None
        constraint_sections = await self._constraint_engine.compile_constraints(
            db,
            options.novel_id,
            scene_id=options.scene_id,
            scene_index=scene_index,
            chapter_index=options.chapter_index,
        )
```

- [ ] **Step 5: Commit**

```bash
git add backend/modules/context/services/constraint_engine.py backend/modules/context/services/context_compiler.py
git commit -m "feat(context): scene-centric foreshadowing and knowledge constraints"
```

---

## Task 6: Build 9-tier IR in ContextCompiler

**Files:**
- Modify: `backend/modules/context/services/context_compiler.py`
- Modify: `backend/modules/context/services/compiled_context.py`
- Test: `backend/tests/unit/test_context.py::TestCompileWithTiers`

- [ ] **Step 1: Update _build_sections for 9 tiers**

Ensure `_build_sections` produces exactly these keys with these tiers:

```python
# P0 — mandatory
"writing_objective"   -> Tier.P0
"scene_blueprint"     -> Tier.P0
"hard_constraints"    -> Tier.P0 (produced by ConstraintEngine, not here)

# P1 — delta-compressible
"pov_knowledge"       -> Tier.P1
"delta_timeline"      -> Tier.P1

# P2 — per-item truncatable
"open_narrative_obligations" -> Tier.P2 (rename from narrative_obligations)
"retrieval_evidence_packs"   -> Tier.P2 (rename from retrieval_evidence)

# P3 — evictable
"style_assets"        -> Tier.P3

# P4 — filler
"compiler_warnings"   -> Tier.P4
```

Update key names in `_build_sections` and `_TIER_HEADERS`.

- [ ] **Step 2: Use current Scene for scene_blueprint**

Change the `scene_blueprint` builder from `bundle.chapter_card` to `bundle.scene`:

```python
        if bundle.scene:
            content = json.dumps(bundle.scene, ensure_ascii=False, indent=2)
            sections.append(
                ContextSection(
                    key="scene_blueprint",
                    tier=Tier.P0,
                    content=content,
                    token_count=max(1, len(content) // 4),
                )
            )
```

- [ ] **Step 3: Track evicted/truncated keys in CompiledContext**

Extend `CompiledContext.enforce_budget()` to record which keys were removed or truncated. Add fields:

```python
class CompiledContext(BaseModel):
    sections: list[ContextSection]
    total_tokens: int = 0
    budget_tokens: int = 0
    compiled_at: str = ""
    evicted_keys: list[str] = []
    truncated_keys: list[str] = []
```

When a section is removed in Phase 2, append its `key` to `evicted_keys`. When truncated in Phase 3 or Phase 4, append to `truncated_keys`.

- [ ] **Step 4: Run Tier tests**

Run: `cd backend && pytest tests/unit/test_context.py::TestCompileWithTiers -v`
Expected: Pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/context/services/context_compiler.py backend/modules/context/services/compiled_context.py
git commit -m "feat(context): build 9-tier IR with scene blueprint and eviction tracking"
```

---

## Task 7: Update Facade and API

**Files:**
- Modify: `backend/modules/context/facade.py`
- Modify: `backend/modules/context/api.py`
- Modify: `backend/modules/context/markdown_renderer.py`
- Test: `backend/tests/unit/test_context.py::TestContextApi`, `backend/modules/context/tests/test_context.py`

- [ ] **Step 1: Update facade compile_with_tiers**

Modify `backend/modules/context/facade.py`:

```python
async def compile_with_tiers(
    db: AsyncSession,
    novel_id: str,
    task: str,
    scope: str,
    budget_tokens: int = 4000,
    scene_id: str | None = None,
    **kwargs,
) -> CompiledContext:
    options = CompileOptions(
        novel_id=novel_id,
        task=task,
        scope=scope,
        scene_id=scene_id,
        budget_tokens=budget_tokens,
        **kwargs,
    )
    return await _compiler.compile_with_tiers(db, options, budget_tokens=budget_tokens)
```

Also expose a new facade function:

```python
async def render_compiled_context_markdown(
    db: AsyncSession,
    novel_id: str,
    task: str,
    scope: str,
    budget_tokens: int = 4000,
    scene_id: str | None = None,
    **kwargs,
) -> str:
    ctx = await compile_with_tiers(
        db, novel_id, task, scope,
        budget_tokens=budget_tokens, scene_id=scene_id, **kwargs
    )
    from modules.context.markdown_renderer import render_compiled_context
    return render_compiled_context(ctx)
```

- [ ] **Step 2: Update /api/context/compile to return Tier IR**

Modify `backend/modules/context/api.py` `compile_context()`:

```python
from modules.context.facade import compile_with_tiers
from modules.context.schemas import ContextTierCompileResponse, ContextSectionItem

@router.post("/compile", response_model=ContextTierCompileResponse)
async def compile_context(...):
    # validate reveal_mode + viewpoint_character_id
    if request.reveal_mode == "character" and not request.viewpoint_character_id:
        raise HTTPException(status_code=400, detail="character 揭示模式必须提供 viewpoint_character_id")

    ctx = await compile_with_tiers(
        db=db,
        novel_id=request.novel_id,
        task=request.task,
        scope=request.scope,
        budget_tokens=request.budget_tokens,
        scene_id=request.scene_id,
        chapter_index=request.chapter_index,
        arc_id=request.arc_id,
        entity_ids=request.entity_ids,
        character_ids=request.character_ids,
        location_ids=request.location_ids,
        reveal_mode=request.reveal_mode,
        enable_geo_filter=request.enable_geo_filter,
        viewpoint_character_id=request.viewpoint_character_id,
    )

    return ContextTierCompileResponse(
        novel_id=request.novel_id,
        task=request.task,
        scope=request.scope,
        reveal_mode=request.reveal_mode,
        scene_id=request.scene_id,
        viewpoint_character_id=request.viewpoint_character_id,
        total_tokens=ctx.total_tokens,
        budget_tokens=ctx.budget_tokens,
        sections=[
            ContextSectionItem(
                key=s.key,
                tier=int(s.tier),
                content=s.content,
                token_count=s.token_count,
                truncated=s.key in ctx.truncated_keys,
            )
            for s in ctx.sections
        ],
        evicted=ctx.evicted_keys,
        truncated=ctx.truncated_keys,
        warnings=[s.content for s in ctx.sections if s.key == "compiler_warnings"],
    )
```

- [ ] **Step 3: Update /api/context/render to use Tier IR**

Modify `render_context()`:

```python
@router.post("/render", response_model=ContextRenderResponse)
async def render_context(...):
    # same validation as compile
    ctx = await compile_with_tiers(...)
    from modules.context.markdown_renderer import render_compiled_context
    markdown = render_compiled_context(ctx)

    compile_info = ContextTierCompileResponse(...)

    return ContextRenderResponse(markdown=markdown, compile_info=compile_info)
```

- [ ] **Step 4: Ensure MarkdownRenderer is pure**

In `backend/modules/context/markdown_renderer.py`, verify `render_compiled_context()` only reads `section.key`, `section.tier`, `section.content` and does not call any facade or loader. Update `_TIER_HEADERS` to match the 9 keys:

```python
_TIER_HEADERS: dict[str, str] = {
    "writing_objective": "一、创作目标",
    "scene_blueprint": "二、场景蓝图",
    "pov_knowledge": "三、视角人物知识边界",
    "delta_timeline": "四、世界线变化时间线",
    "open_narrative_obligations": "五、开放叙事义务",
    "retrieval_evidence_packs": "六、检索证据包",
    "style_assets": "七、风格素材",
    "hard_constraints": "八、必须遵守的硬约束",
    "compiler_warnings": "九、编译器警告",
}
```

- [ ] **Step 5: Run API tests**

Run: `cd backend && pytest tests/unit/test_context.py::TestContextApi -v`
Expected: Pass after updating mocks.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/context/facade.py backend/modules/context/api.py backend/modules/context/markdown_renderer.py backend/modules/context/schemas.py
git commit -m "feat(context): expose tier IR via /compile and pure markdown /render"
```

---

## Task 8: Update frontend contextView

**Files:**
- Modify: `frontend-console/views/contextView.js`
- Modify: `frontend-console/api.js` (if needed)
- Test: `frontend-console/tests/contextView.test.js`, `frontend-console/e2e/context.spec.js`

- [ ] **Step 1: Add Scene selection and budget input to render**

Add to the form in `render()` after the chapter input:

```html
            <div class="form-group">
              <label>Scene ID</label>
              <input class="form-input" id="ctx-scene" placeholder="当前 Scene ID（可选，优先于章节）" />
            </div>
            <div class="form-group">
              <label>预算 (tokens)</label>
              <input class="form-input" id="ctx-budget" type="number" min="500" max="32000" value="4000" />
            </div>
```

- [ ] **Step 2: Update compile() to read new fields and validate viewpoint**

```javascript
    const sceneId = document.getElementById("ctx-scene")?.value || undefined
    const budgetTokens = parseInt(document.getElementById("ctx-budget")?.value || "4000", 10)
    const reveal = document.getElementById("ctx-reveal")?.value || "author_safe"
    // ... existing field reads ...

    if (reveal === "character" && !viewpointCharacterId) {
      toast("角色视角模式必须选择或输入视角人物 ID", "warning")
      return
    }

    const data = await api.context.compile({
      novel_id: state.currentProjectId,
      task, scope,
      scene_id: sceneId,
      chapter_index: chapterIndex,
      budget_tokens: budgetTokens,
      entity_ids: entityIds,
      character_ids: characterIds,
      reveal_mode: reveal,
      viewpoint_character_id: viewpointCharacterId,
    })
```

- [ ] **Step 3: Render Tier result with warnings/evicted info**

Update `_renderCompileResult`:

```javascript
    html += `<div>总 token: ${data.total_tokens} / ${data.budget_tokens}</div>`
    if (data.evicted?.length) {
      html += `<div style="color:var(--warning);">已驱逐段: ${esc(data.evicted.join(", "))}</div>`
    }
    if (data.truncated?.length) {
      html += `<div style="color:var(--warning);">已截断段: ${esc(data.truncated.join(", "))}</div>`
    }
    if (data.sections?.length) {
      html += '<table class="data-table"><thead><tr><th>Tier</th><th>段</th><th>Tokens</th><th>截断</th></tr></thead><tbody>'
      for (const s of data.sections) {
        html += `<tr><td>P${s.tier}</td><td>${esc(s.key)}</td><td>${s.token_count}</td><td>${s.truncated ? "是" : ""}</td></tr>`
      }
      html += '</tbody></table>'
    }
```

- [ ] **Step 4: Update renderMarkdown() to include new fields**

Mirror the field reads and pass `scene_id`/`budget_tokens` to `api.context.render()`.

- [ ] **Step 5: Commit**

```bash
git add frontend-console/views/contextView.js
git commit -m "feat(frontend): scene selection, budget input, and tier display in contextView"
```

---

## Task 9: Backend tests

**Files:**
- Modify: `backend/tests/unit/test_context.py`
- Modify: `backend/modules/context/tests/test_context.py`

- [ ] **Step 1: Add budget enforcement test**

```python
def test_enforce_budget_evicts_p4_first():
    from modules.context.services.compiled_context import (
        CompiledContext, ContextSection, Tier,
    )

    ctx = CompiledContext(
        sections=[
            ContextSection(key="writing_objective", tier=Tier.P0, content="X" * 40, token_count=10),
            ContextSection(key="pov_knowledge", tier=Tier.P1, content="Y" * 80, token_count=20),
            ContextSection(key="open_narrative_obligations", tier=Tier.P2, content="Z" * 80, token_count=20),
            ContextSection(key="style_assets", tier=Tier.P3, content="W" * 80, token_count=20),
            ContextSection(key="compiler_warnings", tier=Tier.P4, content="V" * 80, token_count=20),
        ],
        total_tokens=90,
        budget_tokens=50,
    )
    result = ctx.enforce_budget()
    keys = {s.key for s in result.sections}
    assert "writing_objective" in keys
    assert "compiler_warnings" not in keys
    assert "style_assets" not in keys
    assert result.evicted_keys == ["compiler_warnings", "style_assets"]
```

(Requires updating `enforce_budget` to populate `evicted_keys`.)

- [ ] **Step 2: Add P0 retention test**

```python
def test_p0_sections_never_evicted():
    # Similar setup, assert hard_constraints/scene_blueprint remain
```

- [ ] **Step 3: Add knowledge boundary test**

```python
async def test_character_mode_hides_hidden_truth(db_session):
    # Seed project + entity with hidden_truth + character knowledge unknown
    # Compile with reveal_mode="character" and viewpoint_character_id
    # Assert hidden_truth absent from sections
```

- [ ] **Step 4: Add foreshadowing scene filter test**

```python
async def test_foreshadowing_with_later_payoff_scene_is_blocked(db_session):
    # Seed scene index 1 and foreshadowing with planned_payoff_scene=5
    # Compile scene_id of scene 1
    # Assert foreshadowing appears in hard_constraints
```

- [ ] **Step 5: Add must_not_happen test**

```python
async def test_scene_must_not_happen_in_hard_constraints(db_session):
    # Seed scene with must_not_happen
    # Compile with scene_id
    # Assert must_not_happen in hard_constraints section
```

- [ ] **Step 6: Add RAG top_k test**

```python
def test_rag_loader_caps_at_top_k():
    # Mock facade.retrieve to return 20 chunks
    # Assert loader limits to top_k (default 8)
```

- [ ] **Step 7: Add render markdown test**

```python
def test_render_compiled_context_outputs_markdown():
    from modules.context.markdown_renderer import render_compiled_context
    from modules.context.services.compiled_context import (
        CompiledContext, ContextSection, Tier,
    )

    ctx = CompiledContext(
        sections=[ContextSection(key="writing_objective", tier=Tier.P0, content="task", token_count=1)],
        total_tokens=1,
        budget_tokens=4000,
    )
    md = render_compiled_context(ctx)
    assert "## 一、创作目标" in md
```

- [ ] **Step 8: Run all context tests**

Run: `cd backend && pytest tests/unit/test_context.py backend/modules/context/tests/test_context.py -q`
Expected: All pass.

- [ ] **Step 9: Commit**

```bash
git add backend/tests/unit/test_context.py backend/modules/context/tests/test_context.py
git commit -m "test(context): budget, P0, knowledge, foreshadowing, must_not_happen, RAG cap, markdown"
```

---

## Task 10: Frontend E2E tests

**Files:**
- Modify: `frontend-console/e2e/context.spec.js`
- Modify: `frontend-console/tests/contextView.test.js`

- [ ] **Step 1: Ensure page load test exists**

```javascript
test('loads context view', async ({ page }) => {
  await page.goto('/?view=context')
  await expect(page.locator('text=编译上下文')).toBeVisible()
})
```

- [ ] **Step 2: No-project warning test**

```javascript
test('warns when no project selected', async ({ page }) => {
  await page.goto('/?view=context')
  await page.click('button[data-action="compile"]')
  await expect(page.locator('text=请先选择项目')).toBeVisible()
})
```

- [ ] **Step 3: Compile and display result test**

```javascript
test('compiles and displays tier result', async ({ page }) => {
  await createProjectAndSeed(page)
  await page.goto('/?view=context')
  await page.fill('#ctx-task', '续写下一幕')
  await page.selectOption('#ctx-scope', 'chapter')
  await page.fill('#ctx-chapter', '1')
  await page.click('button[data-action="compile"]')
  await expect(page.locator('text=总 token')).toBeVisible()
})
```

- [ ] **Step 4: Character mode missing viewpoint block test**

```javascript
test('blocks character mode without viewpoint character', async ({ page }) => {
  await createProjectAndSeed(page)
  await page.goto('/?view=context')
  await page.fill('#ctx-task', 'test')
  await page.selectOption('#ctx-reveal', 'character')
  await page.click('button[data-action="compile"]')
  await expect(page.locator('text=角色视角模式必须选择或输入视角人物 ID')).toBeVisible()
})
```

- [ ] **Step 5: Contract submission test**

```javascript
test('submits correct contract to backend', async ({ page }) => {
  await createProjectAndSeed(page)
  await page.goto('/?view=context')
  await page.fill('#ctx-task', '续写')
  await page.selectOption('#ctx-scope', 'chapter')
  await page.fill('#ctx-chapter', '1')
  await page.fill('#ctx-budget', '2000')
  await page.selectOption('#ctx-reveal', 'author_safe')
  const [request] = await Promise.all([
    page.waitForRequest(/\/api\/context\/compile/),
    page.click('button[data-action="compile"]')
  ])
  const body = JSON.parse(request.postData())
  expect(body.budget_tokens).toBe(2000)
  expect(body.reveal_mode).toBe('author_safe')
})
```

- [ ] **Step 6: Run frontend tests**

Run: `cd frontend-console && npm test`
Run: `cd frontend-console && npx playwright test e2e/context.spec.js`
Expected: Pass.

- [ ] **Step 7: Commit**

```bash
git add frontend-console/e2e/context.spec.js frontend-console/tests/contextView.test.js
git commit -m "test(frontend): contextView E2E for scene-centric compiler"
```

---

## Task 11: Acceptance with 《诡秘之主 第一部》 data

**Files:**
- Modify: `backend/tests/e2e/seed_data.py`
- Create: `backend/scripts/acceptance_context_compiler.py` (optional)

- [ ] **Step 1: Extend seed data**

In `backend/tests/e2e/seed_data.py`, add:
- Scene cards for chapters 1-3 (scene_index 0,1,2...) with `pov_character_id` pointing to 克莱恩 entity.
- `must_not_happen` on one scene, e.g., "克莱恩不得在本章知晓源堡真相".
- `CharacterKnowledge` records:
  - character_id=克莱恩, target=源堡, level="unknown"
  - character_id=克莱恩, target=罗塞尔日记, level="restricted"
- `ForeshadowingPlan` records with `planned_payoff_scene` later than scene 1.

- [ ] **Step 2: Create acceptance script**

Create `backend/scripts/acceptance_context_compiler.py`:

```python
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from modules.context.facade import compile_with_tiers
from modules.context.markdown_renderer import render_compiled_context


async def main() -> None:
    novel_id = os.environ.get("NOVEL_ID", "")
    scene_id = os.environ.get("SCENE_ID", "")
    viewpoint = os.environ.get("VIEWPOINT_ID", "")
    async with async_session() as db:
        ctx = await compile_with_tiers(
            db,
            novel_id=novel_id,
            task="以克莱恩视角续写当前 Scene",
            scope="scene",
            scene_id=scene_id,
            budget_tokens=4000,
            reveal_mode="character",
            viewpoint_character_id=viewpoint,
        )
        md = render_compiled_context(ctx)
        print(md)
        if "源堡" in md and "唯一性" in md:
            print("\n❌ hidden_truth leaked into character context")
            sys.exit(1)
        print("\n✅ Acceptance passed: hidden_truth not leaked")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Run acceptance manually**

Start DB: `make db && make migrate`
Seed data: use existing test seed or manual fixture creation.
Run script with correct IDs.
Expected: Script exits 0 and markdown does not contain hidden truth.

- [ ] **Step 4: Commit seed data changes**

```bash
git add backend/tests/e2e/seed_data.py backend/scripts/acceptance_context_compiler.py
git commit -m "chore(acceptance): LOTM seed data and context compiler acceptance script"
```

---

## Task 12: Final verification

- [ ] **Step 1: Run full backend test suite**

Run: `cd backend && pytest tests/unit tests/integration -q`
Expected: All pass.

- [ ] **Step 2: Run lint**

Run: `make lint`
Expected: Pass.

- [ ] **Step 3: Run frontend tests**

Run: `cd frontend-console && npm test`
Run: `cd frontend-console && npx playwright test e2e/context.spec.js`
Expected: Pass.

- [ ] **Step 4: Commit any final fixes**

---

## Self-Review Coverage Checklist

| Spec Requirement | Task |
|------------------|------|
| API `POST /api/context/compile` and `POST /api/context/render` | Task 7 |
| 9-tier output: Writing Objective, Scene Blueprint, POV Knowledge, Delta Timeline, Open Narrative Obligations, Retrieval Evidence Packs, Style Assets, Hard Constraints, Compiler Warnings | Task 6 |
| P0 never truncated; eviction P4→P3→P2→P1 | Task 6, 9 |
| `reveal_mode` author_safe/character; character requires viewpoint_character_id | Task 3, 7 |
| CharacterKnowledge unknown/restricted/misunderstood | Task 2, 5 |
| Seeded foreshadowing with payoff_scene after current scene blocked | Task 1, 5 |
| Scene.must_not_happen in Hard Constraints | Task 5 |
| RAG evidence packs limited by top_k and budget | Task 4, 6 |
| MarkdownRenderer pure IR transform | Task 7 |
| contextView shows results/warnings/budget; clear validation | Task 8 |
| Cross-module aggregation via facade/contracts/DI only | All tasks (no direct model imports from context) |
| No author_only/hidden_truth leak to character context | Task 2, 9 |
| Acceptance with LOTM, Klein viewpoint hidden_truth check | Task 11 |

## Open Decisions / Risks

1. **ForeshadowingPlan `planned_payoff_scene` column** is new; existing data will be NULL. The filter falls back to chapter-based comparison when scene is NULL, so backward compatibility is preserved.
2. **CharacterKnowledge `restricted`/`misunderstood`** are added as aliases to existing levels. Existing `partial`/`false_belief` behavior unchanged.
3. **Scope `scene`** is not added as a new scope value; instead `scene_id` is provided alongside existing scopes. This avoids changing scope validation across the frontend/backend. If future requirements demand `scope="scene"`, it can be added later.

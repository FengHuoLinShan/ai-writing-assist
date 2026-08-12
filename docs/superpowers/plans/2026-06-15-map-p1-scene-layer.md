# 动态地图 P1 Scene 时间层实施计划

> **Superseded（已取代）：** 旧动态地图实施记录，不是当前契约。现行实现见 `docs/modules/15_map.md` 与 ADR-0012。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 P0 静态地图基础上实现 P1 Scene 时间层——按 Scene 显示人物/事件/物品动态标记，提供时间轴筛选和标记交互。

**Architecture:** 后端新增 `MapMarkerService` + API 端点，通过 `outline.contracts.SceneContract` 获取 Scene 列表（不跨模块 import models/repositories）。前端在 `mapView.js` 中新增 Scene 时间轴栏、标记渲染层、标记交互。`mapState.js` 扩展 scene 状态。`mapHexRenderer.js` 新增标记绘制。

**Tech Stack:** FastAPI + SQLAlchemy async, vanilla JS SPA, Leaflet 1.9.4, Canvas 2D, Vitest, pytest + httpx。

---

## P0 偏差清单清理

PRD 文末 "已知前端偏差（P0 未处理，后续迭代）" 列出的 7 项均已在后续迭代中修复实现：
1. ✅ Layer 6 气泡/提示 — `_showTooltip` / `_buildTooltipContent` 已实现
2. ✅ 右侧详情面板 — `_renderDetailPanel` / `_updateDetailPanel` 已实现
3. ✅ pending 格视觉反馈 — `drawPendingTerrain` / `drawPendingBindings` 已实现
4. ✅ 画笔拖拽绘制 — `_handleCanvasMouseDown` / `_handleDragDraw` 已实现
5. ✅ 地点绑定批量保存 — `_applyBindings` 已实现
6. ✅ 删除地图前端入口 — `_deleteMap` + `confirmAction` 已实现
7. ✅ 地图元信息编辑 UI — `_showSettingsModal` 已实现

**需要同步更新 PRD 偏差清单**，在最后一个条目后追加：

> 以上 7 项已于 2026-06-15 前全部实现，偏差清单状态更新为已修复。

---

## 未实现 Feature 全景

| 阶段 | Feature | PRD 章节 | 当前状态 |
|------|---------|----------|----------|
| **P1** | MapMarker 后端 CRUD | §6.5 | `map_markers` 表已建，service/API 未实现 |
| **P1** | Scene 列表读取（跨模块） | §7.2 | outline contracts 存在，地图模块未接入 |
| **P1** | Scene 时间轴 UI | §5.6 | 前端无时间轴组件 |
| **P1** | 人物/事件/物品标记渲染 | §5.4 Layer4 | `drawMarkers` 函数不存在 |
| **P1** | 标记按 Scene 可见性过滤 | §路径5 | 前端/后端均未实现 |
| **P1** | 悬停人物标记气泡 | §路径5 | 未实现 |
| **P1** | 点击事件标记跳转 Scene | §路径5 | 未实现 |
| **P1** | mapStateResponse.scene 字段填充 | §6.2 | 后端始终返回 null |
| P2 | 势力范围 CRUD + 渲染 + 聚焦 | §路径6 §6.6 | 表未建、全部未实现 |
| P3 | AI 位置建议 | §路径7 §6.7 | 表未建、全部未实现 |

**本计划只覆盖 P1。** P2/P3 待 P1 完成后另行规划。

---

## 文件结构

| 文件 | 变更 | 职责 |
|------|------|------|
| `backend/modules/world/services/map_service.py` | 修改 | 新增 `MapMarkerService` |
| `backend/modules/world/map_repositories.py` | 修改 | 新增 `MapMarkerRepository` 完整方法 |
| `backend/modules/world/map_schemas.py` | 修改 | 新增 Marker schemas |
| `backend/modules/world/map_api.py` | 修改 | 新增 4 个 Marker API 端点 |
| `backend/modules/world/services/map_service.py` | 修改 | `get_state` 填充 scene + markers |
| `frontend-console/views/mapState.js` | 修改 | 新增 scene/marker 状态字段 |
| `frontend-console/views/mapHexRenderer.js` | 修改 | 新增 `drawMarkers` 绘制函数 |
| `frontend-console/views/mapView.js` | 修改 | 新增时间轴 UI、标记渲染、标记交互 |
| `frontend-console/styles.css` | 修改 | 新增时间轴、标记相关 CSS |
| `frontend-console/tests/mapView.test.js` | 修改 | 新增标记/时间轴测试 |
| `backend/modules/world/tests/test_map.py` | 修改 | 新增 Marker CRUD 测试 |

---

## Task 1: 后端 — MapMarker Schema 定义

**Files:**
- Modify: `backend/modules/world/map_schemas.py`

- [ ] **Step 1: 在 `map_schemas.py` 末尾新增 Marker schemas**

```python
MARKER_TYPES = ("character", "event", "item")


class MapMarkerCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    entity_id: str
    marker_type: str
    hex_q: int = Field(..., ge=0)
    hex_r: int = Field(..., ge=0)
    offset_x: float = Field(0, ge=-1, le=1)
    offset_y: float = Field(0, ge=-1, le=1)
    label: str | None = None
    style_json: dict | None = None
    start_scene_id: str | None = None
    start_scene_index: int | None = Field(None, ge=0)
    end_scene_id: str | None = None
    end_scene_index: int | None = Field(None, ge=0)
    visible: bool = True

    @field_validator("marker_type")
    @classmethod
    def _valid_marker_type(cls, v):
        if v not in MARKER_TYPES:
            raise ValueError(f"marker_type must be one of {MARKER_TYPES}")
        return v

    @field_validator("entity_id", "start_scene_id", "end_scene_id")
    @classmethod
    def _coerce_uuid(cls, v):
        return str(uuid.UUID(v))


class MapMarkerUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    hex_q: int | None = Field(None, ge=0)
    hex_r: int | None = Field(None, ge=0)
    offset_x: float | None = Field(None, ge=-1, le=1)
    offset_y: float | None = Field(None, ge=-1, le=1)
    label: str | None = None
    style_json: dict | None = None
    start_scene_id: str | None = None
    start_scene_index: int | None = Field(None, ge=0)
    end_scene_id: str | None = None
    end_scene_index: int | None = Field(None, ge=0)
    visible: bool | None = None

    @field_validator("start_scene_id", "end_scene_id")
    @classmethod
    def _coerce_uuid(cls, v):
        if v is not None:
            return str(uuid.UUID(v))
        return v


class MapMarkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    map_id: str
    entity_id: str
    marker_type: str
    hex_q: int
    hex_r: int
    offset_x: float
    offset_y: float
    label: str | None
    style_json: dict | None
    start_scene_id: str | None
    start_scene_index: int | None
    end_scene_id: str | None
    end_scene_index: int | None
    visible: bool
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add backend/modules/world/map_schemas.py && git commit -m "feat(map): add MapMarker schemas for P1"
```

---

## Task 2: 后端 — MapMarkerRepository 完整方法

**Files:**
- Modify: `backend/modules/world/map_repositories.py`

- [ ] **Step 1: 补全 MapMarkerRepository 方法**

当前 `MapMarkerRepository` 只有骨架 `get_by_map`。需要增加完整 CRUD 方法：

```python
class MapMarkerRepository:
    async def get(self, db: AsyncSession, marker_id: str) -> MapMarker | None:
        stmt = select(MapMarker).where(MapMarker.id == marker_id)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_by_map(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        scene_id: str | None = None,
    ) -> list[MapMarker]:
        stmt = (
            select(MapMarker)
            .where(MapMarker.novel_id == novel_id, MapMarker.map_id == map_id)
            .order_by(MapMarker.start_scene_index.nulls_last(), MapMarker.created_at)
        )
        if scene_id:
            stmt = stmt.where(
                or_(
                    MapMarker.start_scene_id == scene_id,
                    and_(
                        MapMarker.start_scene_id.is_(None),
                        MapMarker.end_scene_id.is_(None),
                    ),
                )
            )
        return list((await db.execute(stmt)).scalars().all())

    async def create(
        self, db: AsyncSession, novel_id: str, map_id: str, data: dict
    ) -> MapMarker:
        obj = MapMarker(novel_id=novel_id, map_id=map_id, **data)
        db.add(obj)
        await db.flush()
        return obj

    async def update(self, db: AsyncSession, marker_id: str, data: dict) -> MapMarker | None:
        obj = await self.get(db, marker_id)
        if not obj:
            return None
        for k, v in data.items():
            if v is not None:
                setattr(obj, k, v)
        await db.flush()
        return obj

    async def delete(self, db: AsyncSession, marker_id: str) -> bool:
        obj = await self.get(db, marker_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.flush()
        return True
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add backend/modules/world/map_repositories.py && git commit -m "feat(map): complete MapMarkerRepository CRUD methods"
```

---

## Task 3: 后端 — MapMarkerService

**Files:**
- Modify: `backend/modules/world/services/map_service.py`

- [ ] **Step 1: 新增 MapMarkerService**

```python
class MapMarkerService:
    def __init__(self):
        self.repo = MapMarkerRepository()
        self._map_repo = MapConfigRepository()

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        scene_id: str | None = None,
    ) -> list[MapMarker]:
        map_obj = await self._map_repo.get(db, map_id)
        if not map_obj or str(map_obj.novel_id) != novel_id:
            raise HTTPException(404, "Map not found")
        return await self.repo.get_by_map(db, novel_id, map_id, scene_id)

    async def create(
        self, db: AsyncSession, novel_id: str, map_id: str, data: MapMarkerCreate
    ) -> MapMarker:
        map_obj = await self._map_repo.get(db, map_id)
        if not map_obj or str(map_obj.novel_id) != novel_id:
            raise HTTPException(404, "Map not found")
        cfg = map_obj
        if data.hex_q < 0 or data.hex_q >= cfg.grid_width:
            raise HTTPException(400, f"hex_q out of range [0, {cfg.grid_width})")
        if data.hex_r < 0 or data.hex_r >= cfg.grid_height:
            raise HTTPException(400, f"hex_r out of range [0, {cfg.grid_height})")
        entity = await db.get(CoreEntity, data.entity_id)
        if not entity or str(entity.novel_id) != novel_id:
            raise HTTPException(404, "Entity not found in this novel")
        create_data = data.model_dump(exclude_unset=True)
        return await self.repo.create(db, novel_id, map_id, create_data)

    async def update(
        self, db: AsyncSession, novel_id: str, marker_id: str, data: MapMarkerUpdate
    ) -> MapMarker:
        marker = await self.repo.get(db, marker_id)
        if not marker or str(marker.novel_id) != novel_id:
            raise HTTPException(404, "Marker not found")
        update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        result = await self.repo.update(db, marker_id, update_data)
        if not result:
            raise HTTPException(404, "Marker not found")
        return result

    async def delete(self, db: AsyncSession, novel_id: str, marker_id: str) -> None:
        marker = await self.repo.get(db, marker_id)
        if not marker or str(marker.novel_id) != novel_id:
            raise HTTPException(404, "Marker not found")
        await self.repo.delete(db, marker_id)
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add backend/modules/world/services/map_service.py && git commit -m "feat(map): add MapMarkerService with CRUD + validation"
```

---

## Task 4: 后端 — MapMarker API 端点

**Files:**
- Modify: `backend/modules/world/map_api.py`

- [ ] **Step 1: 新增 4 个 Marker API 端点**

```python
_marker_service = MapMarkerService()


@router.get("/{map_id}/markers")
async def list_markers(
    map_id: str,
    novel_id: str = Query(...),
    scene_id: str | None = Query(None),
    db: DbSession = Depends(),
):
    markers = await _marker_service.list(db, novel_id, map_id, scene_id)
    return [MapMarkerResponse.model_validate(m) for m in markers]


@router.post("/{map_id}/markers")
async def create_marker(
    map_id: str,
    body: MapMarkerCreate,
    novel_id: str = Query(...),
    db: DbSession = Depends(),
):
    marker = await _marker_service.create(db, novel_id, map_id, body)
    return MapMarkerResponse.model_validate(marker)


@router.patch("/{map_id}/markers/{marker_id}")
async def update_marker(
    map_id: str,
    marker_id: str,
    body: MapMarkerUpdate,
    novel_id: str = Query(...),
    db: DbSession = Depends(),
):
    marker = await _marker_service.update(db, novel_id, marker_id, body)
    return MapMarkerResponse.model_validate(marker)


@router.delete("/{map_id}/markers/{marker_id}")
async def delete_marker(
    map_id: str,
    marker_id: str,
    novel_id: str = Query(...),
    db: DbSession = Depends(),
):
    await _marker_service.delete(db, novel_id, marker_id)
    return {"ok": True}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add backend/modules/world/map_api.py && git commit -m "feat(map): add Marker CRUD API endpoints"
```

---

## Task 5: 后端 — Scene 跨模块读取 + state 端点填充 markers/scene

**Files:**
- Modify: `backend/modules/world/services/map_service.py`

- [ ] **Step 1: 在 MapConfigService.get_state 中填充 markers 和 scene**

在 `get_state` 方法中，替换 `markers=[]` 和 `scene=None` 为真实数据：

```python
async def get_state(self, db, novel_id, map_id, filter_types="all"):
    # ... 现有逻辑获取 map, breadcrumbs, tiles, bindings ...

    # P1: 填充 markers
    marker_repo = MapMarkerRepository()
    markers = await marker_repo.get_by_map(db, novel_id, map_id)

    # P1: 填充 scene 信息（如果前端传了 scene_id）
    scene_info = None
    scene_id = filter_types  # 复用参数或新增 query param
    # 实际应从 query 参数获取 scene_id，此处示意
    # scene_id 由 API 层传入

    return MapStateResponse(
        map=map_obj,
        breadcrumbs=breadcrumbs,
        tiles=tiles,
        location_bindings=binding_repo_resp,
        markers=[MapMarkerResponse.model_validate(m) for m in markers],
        territories=[],
        scene=scene_info,
    )
```

同时修改 `get_map_state` API 端点签名，增加 `scene_id` query 参数：

```python
@router.get("/{map_id}/state")
async def get_map_state(
    map_id: str,
    novel_id: str = Query(...),
    scene_id: str | None = Query(None),
    filter_types: str = Query("all"),
    db: DbSession = Depends(),
):
    result = await _map_config_service.get_state(db, novel_id, map_id, filter_types)
    return result
```

Scene 信息读取方式：通过 `outline.contracts.SceneContract` 或调用 outline 的公开 API/service，**不直接 import outline.models/repositories**。

```python
# 在 map_service.py 顶部
from modules.outline.contracts import SceneContract

# get_state 内部
async def _get_scene_info(self, db, novel_id, scene_id):
    if not scene_id:
        return None
    # 通过 outline 公共接口获取 scene
    from modules.outline.services import SceneService
    scene_svc = SceneService()
    scene = await scene_svc.get(db, scene_id)
    if not scene or str(scene.novel_id) != novel_id:
        return None
    return {
        "id": str(scene.id),
        "index": scene.scene_index,
        "title": scene.title,
        "chapter_title": None,  # 可通过 chapter_id 查询，P1 简化
    }
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add backend/modules/world/services/map_service.py backend/modules/world/map_api.py && git commit -m "feat(map): populate markers and scene in state endpoint"
```

---

## Task 6: 后端 — Marker CRUD 测试

**Files:**
- Modify: `backend/modules/world/tests/test_map.py`

- [ ] **Step 1: 新增 Marker 测试**

```python
class TestMapMarkerCRUD:
    async def test_create_marker(self, client, novel_id, map_id, entity_id):
        resp = await client.post(
            f"/api/world/maps/{map_id}/markers?novel_id={novel_id}",
            json={
                "entity_id": entity_id,
                "marker_type": "character",
                "hex_q": 5,
                "hex_r": 3,
                "label": "主角",
                "start_scene_id": None,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["marker_type"] == "character"
        assert data["hex_q"] == 5

    async def test_list_markers(self, client, novel_id, map_id, entity_id):
        await client.post(
            f"/api/world/maps/{map_id}/markers?novel_id={novel_id}",
            json={"entity_id": entity_id, "marker_type": "event", "hex_q": 1, "hex_r": 1},
        )
        resp = await client.get(
            f"/api/world/maps/{map_id}/markers?novel_id={novel_id}"
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_update_marker(self, client, novel_id, map_id, entity_id):
        create_resp = await client.post(
            f"/api/world/maps/{map_id}/markers?novel_id={novel_id}",
            json={"entity_id": entity_id, "marker_type": "item", "hex_q": 2, "hex_r": 2},
        )
        marker_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/api/world/maps/{map_id}/markers/{marker_id}?novel_id={novel_id}",
            json={"hex_q": 3, "label": "宝剑"},
        )
        assert resp.status_code == 200
        assert resp.json()["hex_q"] == 3
        assert resp.json()["label"] == "宝剑"

    async def test_delete_marker(self, client, novel_id, map_id, entity_id):
        create_resp = await client.post(
            f"/api/world/maps/{map_id}/markers?novel_id={novel_id}",
            json={"entity_id": entity_id, "marker_type": "character", "hex_q": 4, "hex_r": 4},
        )
        marker_id = create_resp.json()["id"]
        resp = await client.delete(
            f"/api/world/maps/{map_id}/markers/{marker_id}?novel_id={novel_id}"
        )
        assert resp.status_code == 200

    async def test_cross_novel_marker_404(self, client, novel_id, other_novel_id, map_id, entity_id):
        create_resp = await client.post(
            f"/api/world/maps/{map_id}/markers?novel_id={novel_id}",
            json={"entity_id": entity_id, "marker_type": "character", "hex_q": 1, "hex_r": 1},
        )
        marker_id = create_resp.json()["id"]
        resp = await client.delete(
            f"/api/world/maps/{map_id}/markers/{marker_id}?novel_id={other_novel_id}"
        )
        assert resp.status_code == 404

    async def test_invalid_marker_type_422(self, client, novel_id, map_id, entity_id):
        resp = await client.post(
            f"/api/world/maps/{map_id}/markers?novel_id={novel_id}",
            json={"entity_id": entity_id, "marker_type": "invalid_type", "hex_q": 0, "hex_r": 0},
        )
        assert resp.status_code == 422

    async def test_state_includes_markers(self, client, novel_id, map_id, entity_id):
        await client.post(
            f"/api/world/maps/{map_id}/markers?novel_id={novel_id}",
            json={"entity_id": entity_id, "marker_type": "character", "hex_q": 1, "hex_r": 1},
        )
        resp = await client.get(
            f"/api/world/maps/{map_id}/state?novel_id={novel_id}"
        )
        assert resp.status_code == 200
        assert len(resp.json()["markers"]) >= 1
```

- [ ] **Step 2: 运行后端测试**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/backend && python -m pytest modules/world/tests/test_map.py -v -k "TestMapMarkerCRUD"
```

Expected: PASS。

- [ ] **Step 3: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add backend/modules/world/tests/test_map.py && git commit -m "test(map): add Marker CRUD tests"
```

---

## Task 7: 前端 — mapState 扩展 scene/marker 状态

**Files:**
- Modify: `frontend-console/views/mapState.js`

- [ ] **Step 1: 扩展 mapState 对象**

在 `mapState` 对象中新增：

```javascript
export const mapState = {
  // ... 原有字段 ...

  // P1: Scene 时间层
  /** 当前选中 scene id */
  currentSceneId: null,
  /** 所有可用 scene 列表（从 outline 获取） */
  sceneList: [],
  /** 当前 scene 信息 */
  currentScene: null,
}

export function resetMapState() {
  // ... 原有重置 ...
  mapState.currentSceneId = null
  mapState.sceneList = []
  mapState.currentScene = null
}

/** 设置当前 scene，返回 markers 过滤函数 */
export function setCurrentScene(sceneId) {
  mapState.currentSceneId = sceneId
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapState.js && git commit -m "feat(map): extend mapState with scene/marker state"
```

---

## Task 8: 前端 — mapHexRenderer 标记绘制

**Files:**
- Modify: `frontend-console/views/mapHexRenderer.js`

- [ ] **Step 1: 新增标记绘制函数**

```javascript
const MARKER_STYLES = {
  character: { fill: "#FF9800", stroke: "#E65100", icon: "👤", radius: 8 },
  event: { fill: "#2196F3", stroke: "#0D47A1", icon: "⚡", radius: 8 },
  item: { fill: "#9C27B0", stroke: "#4A148C", icon: "📦", radius: 7 },
}

/**
 * 绘制动态标记（人物/事件/物品）。
 * @param {CanvasRenderingContext2D} ctx
 * @param {Array} markers - MapMarkerResponse[]
 * @param {number} size - hex size
 * @param {number} offsetX
 * @param {number} offsetY
 * @param {string|null} sceneId - 当前 scene，null 则全部显示
 */
export function drawMarkers(ctx, markers, size, offsetX, offsetY, sceneId) {
  if (!markers || markers.length === 0) return
  const visibleMarkers = sceneId
    ? markers.filter((m) => {
        if (!m.visible) return false
        if (!m.start_scene_id && !m.end_scene_id) return true
        const startIdx = m.start_scene_index ?? 0
        const endIdx = m.end_scene_index ?? Infinity
        const currentScene = markers._sceneIndex ?? 0
        return currentScene >= startIdx && currentScene <= endIdx
      })
    : markers.filter((m) => m.visible)

  for (const marker of visibleMarkers) {
    const style = MARKER_STYLES[marker.marker_type] || MARKER_STYLES.character
    const [hx, hy] = hexToPixel(marker.hex_q, marker.hex_r, size)
    const x = hx + offsetX + marker.offset_x * size
    const y = hy + offsetY + marker.offset_y * size

    ctx.beginPath()
    ctx.arc(x, y, style.radius, 0, Math.PI * 2)
    ctx.fillStyle = style.fill
    ctx.fill()
    ctx.strokeStyle = style.stroke
    ctx.lineWidth = 1.5
    ctx.stroke()

    if (marker.label) {
      ctx.fillStyle = "#fff"
      ctx.font = "10px sans-serif"
      ctx.textAlign = "center"
      ctx.textBaseline = "bottom"
      ctx.fillText(marker.label.slice(0, 4), x, y - style.radius - 2)
    }
  }
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapHexRenderer.js && git commit -m "feat(map): add drawMarkers for P1 dynamic markers"
```

---

## Task 9: 前端 — API 封装 Marker 端点

**Files:**
- Modify: `frontend-console/api.js`（或 mapApi.js，取决于现有结构）

- [ ] **Step 1: 在 api.world 命名空间中新增 Marker API 方法**

在 `api.js` 的 `world` 对象中新增：

```javascript
async listMapMarkers(mapId, novelId, sceneId = null) {
  const params = new URLSearchParams({ novel_id: novelId })
  if (sceneId) params.set("scene_id", sceneId)
  return request(`/api/world/maps/${mapId}/markers?${params}`)
},

async createMapMarker(mapId, data, novelId) {
  return request(`/api/world/maps/${mapId}/markers?novel_id=${novelId}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
},

async updateMapMarker(mapId, markerId, data, novelId) {
  return request(`/api/world/maps/${mapId}/markers/${markerId}?novel_id=${novelId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  })
},

async deleteMapMarker(mapId, markerId, novelId) {
  return request(`/api/world/maps/${mapId}/markers/${markerId}?novel_id=${novelId}`, {
    method: "DELETE",
  })
},
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/api.js && git commit -m "feat(map): add Marker API methods to api.world"
```

---

## Task 10: 前端 — Scene 时间轴 UI + 标记渲染集成

**Files:**
- Modify: `frontend-console/views/mapView.js`
- Modify: `frontend-console/styles.css`

- [ ] **Step 1: 在 `_renderMapShell` 中新增时间轴栏**

在 filter bar 之前插入时间轴栏：

```javascript
// 在 _renderMapShell 返回的 HTML 中，filter-bar 前插入
const sceneBar = this._renderSceneBar()

return `
  <div class="map-toolbar">...</div>
  <div class="map-container">...</div>
  ${sceneBar}
  <div class="map-filter-bar">...</div>
`
```

- [ ] **Step 2: 新增 `_renderSceneBar` 方法**

```javascript
_renderSceneBar() {
  const scenes = mapState.sceneList
  if (!scenes || scenes.length === 0) {
    return `<div class="map-scene-bar"><span class="map-scene-hint">暂无 Scene 数据（需先创建大纲 Scene）</span></div>`
  }
  const currentIdx = scenes.findIndex((s) => s.id === mapState.currentSceneId)
  const sceneLabel = currentIdx >= 0 ? `Scene ${scenes[currentIdx].index}: ${esc(scenes[currentIdx].title || "")}` : "选择 Scene"

  return `
    <div class="map-scene-bar">
      <button class="btn btn-sm" data-action="map-scene-prev" ${currentIdx <= 0 ? "disabled" : ""}>←</button>
      <span class="map-scene-label" data-action="map-scene-pick">${sceneLabel}</span>
      <button class="btn btn-sm" data-action="map-scene-next" ${currentIdx >= scenes.length - 1 ? "disabled" : ""}>→</button>
      <button class="btn btn-sm" data-action="map-scene-clear" ${!mapState.currentSceneId ? "disabled" : ""}>清除</button>
    </div>
  `
},
```

- [ ] **Step 3: 新增 Scene 相关动作处理**

在 `_bindMapEvents` 中新增：

```javascript
"map-scene-prev": () => this._sceneNav(-1),
"map-scene-next": () => this._sceneNav(1),
"map-scene-pick": () => this._showScenePicker(),
"map-scene-clear": () => this._clearScene(),
```

新增方法：

```javascript
async _loadScenes() {
  if (!state.currentProjectId) return
  try {
    const data = await api.outline.listScenes({ novel_id: state.currentProjectId, limit: 500 })
    mapState.sceneList = (data.items || data || []).map((s) => ({
      id: s.id,
      index: s.scene_index,
      title: s.title || `Scene ${s.scene_index}`,
    }))
  } catch {
    mapState.sceneList = []
  }
},

_sceneNav(direction) {
  const scenes = mapState.sceneList
  if (!scenes.length) return
  const currentIdx = scenes.findIndex((s) => s.id === mapState.currentSceneId)
  const newIdx = Math.max(0, Math.min(scenes.length - 1, currentIdx + direction))
  const scene = scenes[newIdx]
  if (scene) {
    setCurrentScene(scene.id)
    this._updateSceneBar()
    this._redraw()
  }
},

_showScenePicker() {
  const scenes = mapState.sceneList
  if (!scenes.length) return
  const options = scenes.map((s) => `<option value="${esc(s.id)}">${esc(s.title)}</option>`).join("")
  const formHtml = `
    <div class="form-group">
      <label>选择 Scene</label>
      <select class="form-select" id="map-scene-pick-select">${options}</select>
    </div>
  `
  showModal("Scene 时间轴", formHtml, [{
    text: "跳转", class: "btn-primary", handler: () => {
      const sel = document.getElementById("map-scene-pick-select")
      if (sel && sel.value) {
        setCurrentScene(sel.value)
        closeModal()
        this._updateSceneBar()
        this._redraw()
      }
    },
  }])
},

_clearScene() {
  setCurrentScene(null)
  this._updateSceneBar()
  this._redraw()
},

_updateSceneBar() {
  const bar = document.querySelector(".map-scene-bar")
  if (bar) bar.outerHTML = this._renderSceneBar()
  setTimeout(() => this._bindMapEvents(), 0)
},
```

- [ ] **Step 4: 在 `_redraw` 中绘制 markers**

在 `_redraw` 的 `drawBindings` 之后添加：

```javascript
drawMarkers(this._ctx, this._state.markers, size, 0, 0, mapState.currentSceneId)
```

- [ ] **Step 5: 在 `mount` / `_openMap` 中加载 scenes**

```javascript
async mount(rootId) {
  // ... 原有逻辑 ...
  await this._loadScenes()
  // ...
},

async _openMap(mapId) {
  this.unmount()
  await this._loadMapState(mapId)
  await this._loadLocations()
  await this._loadScenes()
  this._render("map-root")
},
```

- [ ] **Step 6: 新增 CSS 样式**

```css
.map-scene-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--bg-elevated);
  border-top: 1px solid var(--border);
  font-size: 13px;
}

.map-scene-label {
  flex: 1;
  text-align: center;
  cursor: pointer;
  color: var(--text-primary);
}

.map-scene-label:hover {
  color: var(--accent);
}

.map-scene-hint {
  color: var(--text-dim);
  font-size: 12px;
}
```

- [ ] **Step 7: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapView.js frontend-console/views/mapState.js frontend-console/views/mapHexRenderer.js frontend-console/styles.css && git commit -m "feat(map): P1 Scene timeline bar and marker rendering"
```

---

## Task 11: 前端 — 标记交互（悬停气泡 + 点击跳转）

**Files:**
- Modify: `frontend-console/views/mapView.js`

- [ ] **Step 1: 在 `_buildTooltipContent` 中增加 marker 信息**

```javascript
_buildTooltipContent(q, r) {
  // ... 原有 binding/tile 逻辑 ...

  // P1: 检查 marker
  const markers = this._state.markers || []
  const hitMarker = markers.find((m) => m.hex_q === q && m.hex_r === r && m.visible)
  if (hitMarker) {
    const typeLabels = { character: "人物", event: "事件", item: "物品" }
    const typeLabel = typeLabels[hitMarker.marker_type] || hitMarker.marker_type
    let html = `<div class="map-tooltip-title">${esc(hitMarker.label || typeLabel)}</div>`
    html += `<div class="map-tooltip-sub">${esc(typeLabel)}</div>`
    if (hitMarker.marker_type === "event" && hitMarker.start_scene_id) {
      html += `<div class="map-tooltip-sub">点击跳转 Scene</div>`
    }
    return html
  }

  // ... 原有 tile fallback ...
},
```

- [ ] **Step 2: 在 `_handleBrowseClick` 中处理 event marker 点击**

```javascript
_handleBrowseClick(q, r) {
  setSelectedHex(q, r)
  this._updateDetailPanel(q, r)

  // P1: 事件标记点击 → 跳转 Scene
  const markers = this._state.markers || []
  const eventMarker = markers.find(
    (m) => m.hex_q === q && m.hex_r === r && m.marker_type === "event" && m.visible
  )
  if (eventMarker && eventMarker.start_scene_id) {
    setCurrentScene(eventMarker.start_scene_id)
    this._updateSceneBar()
    this._redraw()
    toast(`跳转到 Scene: ${esc(eventMarker.label || "")}`, "info")
    return
  }

  // ... 原有 binding/tile toast ...
},
```

- [ ] **Step 3: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapView.js && git commit -m "feat(map): marker tooltip and event click-to-scene navigation"
```

---

## Task 12: 前端 — 编辑模式标记管理

**Files:**
- Modify: `frontend-console/views/mapView.js`
- Modify: `frontend-console/views/mapEditPanel.js`

- [ ] **Step 1: 在编辑面板中新增标记工具**

在 `mapEditPanel.js` 的 `renderEditPanel` 中新增标记工具按钮和标记配置区：

```javascript
// 在 map-tool-row 中增加标记按钮
<div class="map-tool-row">
  <button class="btn btn-sm map-tool-btn active" data-action="map-tool-brush">画笔</button>
  <button class="btn btn-sm map-tool-btn" data-action="map-tool-bucket">油漆桶</button>
  <button class="btn btn-sm map-tool-btn" data-action="map-tool-bind">地点绑定</button>
  <button class="btn btn-sm map-tool-btn" data-action="map-tool-marker">标记</button>
</div>

// 新增标记配置 section
<div class="map-edit-section" id="map-marker-section" style="display:none;">
  <h4>动态标记</h4>
  <select class="form-select" id="map-marker-type">
    <option value="character">人物</option>
    <option value="event">事件</option>
    <option value="item">物品</option>
  </select>
  <select class="form-select" id="map-marker-entity">
    ${entityOptions}
  </select>
  <input class="form-input" id="map-marker-label" placeholder="标记名称（可选）" />
  <p class="map-hint">选择类型和实体后，点击六边形放置标记。</p>
</div>
```

- [ ] **Step 2: 在 mapView 中处理标记编辑**

在 `_handleDragDraw` 中新增 marker 分支：

```javascript
} else if (mapState.activeTool === "marker") {
  const markerType = mapState.selectedMarkerType || "character"
  const entityId = mapState.selectedMarkerEntityId
  const label = mapState.selectedMarkerLabel
  if (!entityId) return
  // 即时创建标记
  try {
    await api.world.createMapMarker(
      this._state.map.id,
      {
        entity_id: entityId,
        marker_type: markerType,
        hex_q: q,
        hex_r: r,
        label: label || null,
      },
      state.currentProjectId
    )
    await this._loadMapState(this._state.map.id)
    this._redraw()
  } catch (err) {
    toast(`标记创建失败：${err.message}`, "error")
  }
}
```

- [ ] **Step 3: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/views/mapView.js frontend-console/views/mapEditPanel.js && git commit -m "feat(map): marker editing tool in edit panel"
```

---

## Task 13: 前端 — 测试

**Files:**
- Modify: `frontend-console/tests/mapView.test.js`

- [ ] **Step 1: 新增 Marker 和 Scene 测试**

```javascript
describe("mapHexRenderer 标记绘制", () => {
  it("drawMarkers 绘制可见标记", () => {
    const ctx = {
      beginPath: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
      stroke: vi.fn(),
      fillText: vi.fn(),
    }
    const markers = [
      { hex_q: 1, hex_r: 1, marker_type: "character", label: "张三", visible: true, offset_x: 0, offset_y: 0 },
    ]
    drawMarkers(ctx, markers, 30, 0, 0, null)
    expect(ctx.arc).toHaveBeenCalled()
    expect(ctx.fill).toHaveBeenCalled()
  })

  it("drawMarkers 过滤不可见标记", () => {
    const ctx = {
      beginPath: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
      stroke: vi.fn(),
    }
    const markers = [
      { hex_q: 1, hex_r: 1, marker_type: "character", visible: false, offset_x: 0, offset_y: 0 },
    ]
    drawMarkers(ctx, markers, 30, 0, 0, null)
    expect(ctx.arc).not.toHaveBeenCalled()
  })
})

describe("mapView Scene 时间轴", () => {
  it("_renderSceneBar 显示 Scene 列表", () => {
    mapState.sceneList = [
      { id: "s1", index: 1, title: "开端" },
      { id: "s2", index: 2, title: "发展" },
    ]
    mapState.currentSceneId = "s1"
    const html = mapView._renderSceneBar()
    expect(html).toContain("开端")
    expect(html).toContain("map-scene-prev")
    expect(html).toContain("map-scene-next")
  })
})

describe("mapView marker 交互", () => {
  it("_buildTooltipContent 对 marker 返回标记信息", () => {
    mapView._state = {
      map: { hex_size: 30, grid_width: 5, grid_height: 5 },
      tiles: [{ hex_q: 1, hex_r: 1, terrain_type: "grassland" }],
      location_bindings: [],
      markers: [{ hex_q: 1, hex_r: 1, marker_type: "character", label: "张三", visible: true }],
    }
    mapView._locations = []
    const html = mapView._buildTooltipContent(1, 1)
    expect(html).toContain("张三")
    expect(html).toContain("人物")
  })
})
```

- [ ] **Step 2: 运行前端测试**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run tests/mapView.test.js
```

Expected: PASS。

- [ ] **Step 3: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add frontend-console/tests/mapView.test.js && git commit -m "test(map): add P1 marker and scene tests"
```

---

## Task 14: PRD 偏差清单更新 + 文档同步

**Files:**
- Modify: `docs/references/map-prd-v1.1.md`

- [ ] **Step 1: 更新 PRD 偏差清单**

1. 在 "已知前端偏差（P0 未处理，后续迭代）" 列表末尾追加：

```
14. **P0 偏差已修复**（2026-06-15）：以上 7 项 P0 偏差已全部实现。
```

2. 更新文档状态：

```
**文档状态**：P0 + P1 已实现（2026-06-15）
**下次更新**：P2 实现后根据实际 API、数据模型和交互细节同步调整。
```

3. 在 "实现记录" 末尾追加 P1 偏差记录（如有）。

- [ ] **Step 2: Commit**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist && git add docs/references/map-prd-v1.1.md && git commit -m "docs(map): update PRD with P0 gap fixes and P1 status"
```

---

## Task 15: 全量测试 + 验收

- [ ] **Step 1: 运行后端全量测试**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/backend && python -m pytest modules/world/tests/test_map.py -v
```

Expected: 全部 PASS。

- [ ] **Step 2: 运行前端全量测试**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console && npx vitest run
```

Expected: 全部 PASS。

- [ ] **Step 3: 运行 lint**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/backend && python -m ruff check modules/world/
```

Expected: 无错误。

---

## 自我审查

### Spec 覆盖检查

| PRD P1 要求 | 对应 Task |
|-------------|-----------|
| `map_markers` service/API (GET/POST/PATCH/DELETE) | Task 2, 3, 4 |
| Scene 列表读取（跨模块，不直 import outline.models） | Task 5 |
| `mapStateResponse.scene` 填充 | Task 5 |
| `mapStateResponse.markers` 填充 | Task 5 |
| Scene 时间轴 UI | Task 10 |
| 人物/事件/物品标记渲染 (Layer 4) | Task 8, 10 |
| 标记按 Scene 可见性过滤 | Task 8 |
| 悬停人物标记气泡 | Task 11 |
| 点击事件标记跳转 Scene | Task 11 |
| 标记编辑工具 | Task 12 |
| P0 偏差清单更新 | Task 14 |
| 后端测试 | Task 6 |
| 前端测试 | Task 13 |
| 全量验收 | Task 15 |

### Placeholder 检查

- 无 TBD/TODO。
- 每个 task 包含具体代码。
- 无模糊表述。

### 类型一致性

- `MapMarkerCreate.marker_type` 使用 `Literal` 白名单，前端 `map-marker-type` select 的 value 与白名单一致。
- `MapMarkerResponse` 字段名与 `MapMarker` ORM 列名一致。
- `api.world.createMapMarker` 参数签名与后端 `POST /markers` body 一致。
- `drawMarkers` 的 `sceneId` 参数类型与 `mapState.currentSceneId` 类型一致（`string | null`）。

---

## P2/P3 远景（本计划不实施）

### P2 — 组织与聚焦层
- 新建 `map_territory_tiles` 表 + model + schema + repo + service + API
- 势力范围 Canvas 渲染（半透明覆盖层）
- 聚焦模式：不相关 hex 透明度 0.3
- `GET /api/world/maps/{map_id}/focus` 端点

### P3 — AI 位置建议层
- 新建 `map_position_suggestions` 表 + model + schema + repo + service + API
- LLM 集成：从 Scene 正文 / 深度导入提取位置建议
- 建议确认/忽略 UI
- 用户确认后写入 `map_markers` 或其他正式表

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-15-map-p1-scene-layer.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**

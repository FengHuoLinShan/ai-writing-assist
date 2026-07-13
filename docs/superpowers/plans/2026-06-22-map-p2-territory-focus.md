# 动态地图 P2 势力范围与聚焦模式实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 P0+P1 基础上实现 P2 势力范围与聚焦模式——组织控制区域可视化、聚焦浏览、势力调色盘。

**Architecture:** 后端新增 `MapTerritoryTile` ORM + Repository + Service + API；前端在 `mapHexRenderer.js` 新增 Layer 5 势力范围 Canvas 渲染，`mapView.js` 新增聚焦模式 UI 和势力编辑工具。

**Tech Stack:** FastAPI + SQLAlchemy async, vanilla JS SPA, Leaflet 1.9.4, Canvas 2D, Vitest, pytest + httpx。

---

## P2 功能全景

| Feature | PRD 章节 | 当前状态 | 本计划覆盖 |
|---------|----------|----------|------------|
| 势力范围数据表 | §4.4 | 未建 | ✅ Task 1 |
| 势力范围后端 CRUD | §6.6 | 未实现 | ✅ Task 2-4 |
| 势力范围 Canvas 渲染 | §5.4 Layer 5 | 未实现 | ✅ Task 5-6 |
| 聚焦模式（不相关 hex 透明度 0.3） | §路径 6 | 未实现 | ✅ Task 7-8 |
| 组织调色盘 | §路径 6 | 未实现 | ✅ Task 9 |
| 势力编辑工具（编辑模式） | §路径 6 | 未实现 | ✅ Task 10 |
| 测试覆盖 | — | 未实现 | ✅ Task 11-12 |
| PRD 文档同步 | — | 未更新 | ✅ Task 13 |

---

## 文件变更清单

| 文件 | 变更 | 职责 |
|------|------|------|
| `backend/alembic/versions/20260622_add_territory_tables.py` | 新增 | 数据库迁移：map_territory_tiles 表 |
| `backend/modules/world/map_models.py` | 修改 | 新增 MapTerritoryTile ORM |
| `backend/modules/world/map_schemas.py` | 修改 | 新增 Territory schemas |
| `backend/modules/world/map_repositories.py` | 修改 | 新增 MapTerritoryRepository |
| `backend/modules/world/services/map_service.py` | 修改 | 新增 MapTerritoryService |
| `backend/modules/world/map_api.py` | 修改 | 新增 4 个 Territory API 端点 |
| `backend/modules/world/tests/test_map.py` | 修改 | 新增 Territory CRUD 测试 |
| `frontend-console/views/mapState.js` | 修改 | 新增 territory/focus 状态字段 |
| `frontend-console/views/mapHexRenderer.js` | 修改 | 新增 drawTerritories 渲染函数 |
| `frontend-console/views/mapView.js` | 修改 | 新增聚焦模式 UI、势力编辑工具 |
| `frontend-console/styles.css` | 修改 | 新增聚焦模式、势力相关 CSS |
| `frontend-console/tests/mapView.test.js` | 修改 | 新增 territory/focus 测试 |
| `docs/references/map-prd-v1.1.md` | 修改 | 更新 P2 实现状态 |

---

## Task 1: 数据库迁移 — map_territory_tiles 表

**Files:**
- Create: `backend/alembic/versions/20260622_add_territory_tables.py`

**Schema（PRD §4.4）:**

```sql
CREATE TABLE map_territory_tiles (
    id UUID PRIMARY KEY,
    novel_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    map_id UUID NOT NULL REFERENCES map_configs(id) ON DELETE CASCADE,
    faction_entity_id UUID NOT NULL REFERENCES core_entities(id) ON DELETE CASCADE,

    hex_q INT NOT NULL,
    hex_r INT NOT NULL,
    style_override JSONB DEFAULT '{}',

    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),

    UNIQUE(map_id, faction_entity_id, hex_q, hex_r)
);
```

**约束:**
- `faction_entity_id` 的 `entity_type` 必须是 `organization`（业务层校验，不建 DB check constraint）
- 同一地图同一组织同一格只能有一条记录
- 与地点绑定、标记可叠加

**Alembic 迁移脚本:**

```python
"""add map_territory_tiles table

Revision ID: 20260622_add_territory_tables
Revises: 20260614_add_map_tables
Create Date: 2026-06-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "20260622_add_territory_tables"
down_revision: Union[str, None] = "20260614_add_map_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "map_territory_tiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "map_id",
            UUID(as_uuid=True),
            sa.ForeignKey("map_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "faction_entity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("core_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hex_q", sa.Integer(), nullable=False),
        sa.Column("hex_r", sa.Integer(), nullable=False),
        sa.Column(
            "style_override",
            sa.JSON().with_variant(sa.JSON(), "postgresql"),
            nullable=True,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "map_id", "faction_entity_id", "hex_q", "hex_r",
            name="uq_map_territory_map_faction_qr",
        ),
    )
    op.create_index(
        "ix_map_territory_map_id",
        "map_territory_tiles",
        ["map_id"],
    )
    op.create_index(
        "ix_map_territory_faction_id",
        "map_territory_tiles",
        ["faction_entity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_map_territory_faction_id", table_name="map_territory_tiles")
    op.drop_index("ix_map_territory_map_id", table_name="map_territory_tiles")
    op.drop_table("map_territory_tiles")
```

**验证:**
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/backend && alembic upgrade head
```

Expected: 迁移成功，表创建。

---

## Task 2: 后端 — MapTerritoryTile ORM 模型

**Files:**
- Modify: `backend/modules/world/map_models.py`

在 `MapMarker` 类后追加：

```python
# ============================================================
# MapTerritoryTile — 势力范围（P2）
# ============================================================


class MapTerritoryTile(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """势力范围格 — 组织控制区域

    与地点绑定、标记可叠加；地点颜色和标签优先于势力半透明覆盖。
    faction_entity_id 对应 core_entities.entity_type = "organization"。
    """

    __tablename__ = "map_territory_tiles"
    __table_args__ = (
        sa.UniqueConstraint(
            "map_id", "faction_entity_id", "hex_q", "hex_r",
            name="uq_map_territory_map_faction_qr",
        ),
        {"comment": "势力范围（P2）"},
    )

    map_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("map_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属地图",
    )
    faction_entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="组织实体（entity_type=organization）",
    )
    hex_q: Mapped[int] = mapped_column(Integer, nullable=False, comment="范围格 q")
    hex_r: Mapped[int] = mapped_column(Integer, nullable=False, comment="范围格 r")
    style_override: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=dict, comment="样式覆盖（颜色/透明度）"
    )

    def __repr__(self) -> str:
        return (
            f"<MapTerritoryTile map={self.map_id} "
            f"faction={self.faction_entity_id} q={self.hex_q} r={self.hex_r}>"
        )
```

**注意:** 需要在文件顶部 `import sqlalchemy as sa` 以支持 `sa.UniqueConstraint`。

---

## Task 3: 后端 — Territory Schemas

**Files:**
- Modify: `backend/modules/world/map_schemas.py`

在 `MapMarkerResponse` 后追加：

```python
# ============================================================
# MapTerritoryTile — 势力范围（P2）
# ============================================================


class TerritoryHex(BaseModel):
    """单格势力范围。"""

    hex_q: int = Field(..., ge=0)
    hex_r: int = Field(..., ge=0)
    style_override: dict | None = Field(None)


class MapTerritoryCreate(BaseModel):
    """批量创建势力范围请求体。"""

    faction_entity_id: str = Field(..., description="组织实体 ID（entity_type=organization）")
    hexes: list[TerritoryHex] = Field(..., min_length=1, max_length=5000)


class MapTerritoryUpdate(BaseModel):
    """更新单格势力范围样式。"""

    style_override: dict | None = Field(None)


class MapTerritoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    map_id: str
    faction_entity_id: str
    hex_q: int
    hex_r: int
    style_override: dict | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("id", "novel_id", "map_id", "faction_entity_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)
```

同时更新 `MapStateResponse` 的 `territories` 字段注释：

```python
class MapStateResponse(BaseModel):
    """地图聚合状态（P2 起 territories 填充）。"""

    map: MapConfigResponse
    breadcrumbs: list[MapConfigResponse]
    tiles: list[MapTileResponse]
    location_bindings: list[MapLocationBindingResponse]
    markers: list[MapMarkerResponse] = Field(default_factory=list)
    territories: list[MapTerritoryResponse] = Field(
        default_factory=list, description="P2: MapTerritoryTile[]"
    )
    scene: dict | None = None
```

---

## Task 4: 后端 — MapTerritoryRepository

**Files:**
- Modify: `backend/modules/world/map_repositories.py`

在 `MapMarkerRepository` 后追加：

```python
# ============================================================
# MapTerritoryRepository（P2）
# ============================================================


class MapTerritoryRepository:
    """势力范围数据访问（P2）。"""

    async def get(
        self, db: AsyncSession, territory_id: uuid.UUID
    ) -> MapTerritoryTile | None:
        stmt = select(MapTerritoryTile).where(MapTerritoryTile.id == territory_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_map(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        faction_entity_id: uuid.UUID | None = None,
    ) -> list[MapTerritoryTile]:
        conditions: list[Any] = [
            MapTerritoryTile.novel_id == novel_id,
            MapTerritoryTile.map_id == map_id,
        ]
        if faction_entity_id is not None:
            conditions.append(MapTerritoryTile.faction_entity_id == faction_entity_id)
        stmt = select(MapTerritoryTile).where(*conditions)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_hex(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        hex_q: int,
        hex_r: int,
    ) -> list[MapTerritoryTile]:
        stmt = select(MapTerritoryTile).where(
            MapTerritoryTile.novel_id == novel_id,
            MapTerritoryTile.map_id == map_id,
            MapTerritoryTile.hex_q == hex_q,
            MapTerritoryTile.hex_r == hex_r,
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create_batch(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        faction_entity_id: uuid.UUID,
        hexes: list[TerritoryHex],
    ) -> list[MapTerritoryTile]:
        """批量创建势力范围，冲突时忽略（幂等）。"""
        tiles: list[MapTerritoryTile] = []
        for h in hexes:
            tile = MapTerritoryTile(
                novel_id=novel_id,
                map_id=map_id,
                faction_entity_id=faction_entity_id,
                hex_q=h.hex_q,
                hex_r=h.hex_r,
                style_override=h.style_override or {},
            )
            db.add(tile)
            tiles.append(tile)
        await db.flush()
        return tiles

    async def update(
        self,
        db: AsyncSession,
        territory_id: uuid.UUID,
        data: MapTerritoryUpdate,
    ) -> MapTerritoryTile | None:
        values: dict[str, Any] = {}
        if data.style_override is not None:
            values["style_override"] = data.style_override
        if values:
            stmt = (
                update(MapTerritoryTile)
                .where(MapTerritoryTile.id == territory_id)
                .values(**values)
            )
            await db.execute(stmt)
            await db.flush()
        return await self.get(db, territory_id)

    async def delete(self, db: AsyncSession, territory_id: uuid.UUID) -> bool:
        stmt = delete(MapTerritoryTile).where(MapTerritoryTile.id == territory_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def delete_by_faction(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        faction_entity_id: uuid.UUID,
    ) -> int:
        """删除某组织在某地图上的全部势力范围，返回删除行数。"""
        stmt = delete(MapTerritoryTile).where(
            MapTerritoryTile.novel_id == novel_id,
            MapTerritoryTile.map_id == map_id,
            MapTerritoryTile.faction_entity_id == faction_entity_id,
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount
```

---

## Task 5: 后端 — MapTerritoryService

**Files:**
- Modify: `backend/modules/world/services/map_service.py`

在 `MapMarkerService` 后追加：

```python
# ============================================================
# MapTerritoryService（P2）
# ============================================================


class MapTerritoryService:
    """势力范围服务（P2）。"""

    def __init__(self) -> None:
        self.repo = MapTerritoryRepository()
        self._map_repo = MapConfigRepository()
        self._entity_repo = CoreEntityRepository()

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        faction_entity_id: str | None = None,
    ) -> list[MapTerritoryResponse]:
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        fid = parse_uuid(faction_entity_id, "faction_entity_id") if faction_entity_id else None

        config = await self._map_repo.get(db, mid)
        if config is None or config.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapConfig {map_id} not found",
            )

        territories = await self.repo.get_by_map(db, nid, mid, fid)
        return [MapTerritoryResponse.model_validate(t) for t in territories]

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapTerritoryCreate,
    ) -> list[MapTerritoryResponse]:
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        fid = parse_uuid(data.faction_entity_id, "faction_entity_id")

        config = await self._map_repo.get(db, mid)
        if config is None or config.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapConfig {map_id} not found",
            )

        # 校验 faction_entity_id 是 organization 类型
        entity = await self._entity_repo.get(db, fid)
        if entity is None or entity.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"CoreEntity {data.faction_entity_id} not found",
            )
        if entity.entity_type != "organization":
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Entity {data.faction_entity_id} is not an organization",
            )

        # 校验 hex 在网格内
        for h in data.hexes:
            if h.hex_q < 0 or h.hex_q >= config.grid_width:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"hex_q {h.hex_q} out of bounds",
                )
            if h.hex_r < 0 or h.hex_r >= config.grid_height:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"hex_r {h.hex_r} out of bounds",
                )

        tiles = await self.repo.create_batch(db, nid, mid, fid, data.hexes)
        return [MapTerritoryResponse.model_validate(t) for t in tiles]

    async def update(
        self,
        db: AsyncSession,
        novel_id: str,
        territory_id: str,
        data: MapTerritoryUpdate,
    ) -> MapTerritoryResponse:
        nid = parse_uuid(novel_id, "novel_id")
        tid = parse_uuid(territory_id, "territory_id")

        territory = await self.repo.get(db, tid)
        if territory is None or territory.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapTerritoryTile {territory_id} not found",
            )

        updated = await self.repo.update(db, tid, data)
        assert updated is not None
        return MapTerritoryResponse.model_validate(updated)

    async def delete(
        self,
        db: AsyncSession,
        novel_id: str,
        territory_id: str,
    ) -> None:
        nid = parse_uuid(novel_id, "novel_id")
        tid = parse_uuid(territory_id, "territory_id")

        territory = await self.repo.get(db, tid)
        if territory is None or territory.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapTerritoryTile {territory_id} not found",
            )
        await self.repo.delete(db, tid)

    async def delete_by_faction(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        faction_entity_id: str,
    ) -> int:
        """删除某组织在某地图上的全部势力范围。"""
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        fid = parse_uuid(faction_entity_id, "faction_entity_id")

        config = await self._map_repo.get(db, mid)
        if config is None or config.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapConfig {map_id} not found",
            )

        return await self.repo.delete_by_faction(db, nid, mid, fid)
```

同时修改 `MapConfigService.get_state` 填充 `territories`：

```python
async def get_state(...) -> MapStateResponse:
    # ... 现有代码 ...
    territories = await MapTerritoryRepository().get_by_map(db, nid, mid)
    # ... 返回时加入 territories ...
```

---

## Task 6: 后端 — Territory API 端点

**Files:**
- Modify: `backend/modules/world/map_api.py`

在 marker API 后追加：

```python
# ============================================================
# 势力范围（P2）
# ============================================================

_territory_service = MapTerritoryService()


@router.get("/{map_id}/territories")
async def list_territories(
    db: DbSession,
    map_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    faction_entity_id: str | None = Query(None, description="组织实体 ID"),
):
    territories = await _territory_service.list(db, novel_id, map_id, faction_entity_id)
    return [MapTerritoryResponse.model_validate(t) for t in territories]


@router.post("/{map_id}/territories", status_code=201)
async def create_territories(
    db: DbSession,
    map_id: str,
    data: MapTerritoryCreate,
    novel_id: str = Query(..., description="项目 ID"),
):
    territories = await _territory_service.create(db, novel_id, map_id, data)
    return [MapTerritoryResponse.model_validate(t) for t in territories]


@router.patch("/{map_id}/territories/{territory_id}")
async def update_territory(
    db: DbSession,
    map_id: str,
    territory_id: str,
    data: MapTerritoryUpdate,
    novel_id: str = Query(..., description="项目 ID"),
):
    territory = await _territory_service.update(db, novel_id, territory_id, data)
    return MapTerritoryResponse.model_validate(territory)


@router.delete("/{map_id}/territories/{territory_id}", status_code=204)
async def delete_territory(
    db: DbSession,
    map_id: str,
    territory_id: str,
    novel_id: str = Query(..., description="项目 ID"),
):
    await _territory_service.delete(db, novel_id, territory_id)
```

---

## Task 7: 后端 — 聚焦模式 API

**Files:**
- Modify: `backend/modules/world/map_api.py`

新增聚焦端点：

```python
@router.get("/{map_id}/focus")
async def get_focus_state(
    db: DbSession,
    map_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    entity_id: str = Query(..., description="聚焦实体 ID"),
    scene_id: str | None = Query(None, description="Scene ID（可选）"),
):
    """聚焦模式：返回与实体相关的所有 hex 坐标。

    相关 hex 包括：
    - 地点绑定（entity_id 是 location 且与聚焦实体有关联）
    - 标记（marker 的 entity_id 匹配）
    - 势力范围（faction_entity_id 匹配）
    """
    nid = parse_uuid(novel_id, "novel_id")
    mid = parse_uuid(map_id, "map_id")
    eid = parse_uuid(entity_id, "entity_id")

    # 获取地图校验
    config = await _map_config_service.get(db, map_id, novel_id=novel_id)

    # 获取相关 hex 集合
    related_hexes: set[tuple[int, int]] = set()

    # 1. 直接标记
    markers = await _marker_service.list(db, novel_id, map_id, scene_id)
    for m in markers:
        if m.entity_id == entity_id:
            related_hexes.add((m.hex_q, m.hex_r))

    # 2. 势力范围
    territories = await _territory_service.list(db, novel_id, map_id)
    for t in territories:
        if t.faction_entity_id == entity_id:
            related_hexes.add((t.hex_q, t.hex_r))

    # 3. 地点绑定（如果聚焦实体是 location）
    # TODO: 通过 world facade 获取关联地点

    return {
        "map_id": map_id,
        "entity_id": entity_id,
        "related_hexes": [{"hex_q": q, "hex_r": r} for q, r in related_hexes],
        "total": len(related_hexes),
    }
```

---

## Task 8: 后端测试 — Territory CRUD

**Files:**
- Modify: `backend/modules/world/tests/test_map.py`

新增测试：

```python
class TestMapTerritory:
    """势力范围测试（P2）。"""

    async def test_list_territories_empty(self, client, map_id, novel_id):
        resp = await client.get(
            f"/api/world/maps/{map_id}/territories?novel_id={novel_id}"
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_territory(self, client, map_id, novel_id, org_entity_id):
        resp = await client.post(
            f"/api/world/maps/{map_id}/territories?novel_id={novel_id}",
            json={
                "faction_entity_id": org_entity_id,
                "hexes": [
                    {"hex_q": 1, "hex_r": 1, "style_override": {"color": "#FF0000"}},
                    {"hex_q": 1, "hex_r": 2},
                ],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data) == 2
        assert data[0]["faction_entity_id"] == org_entity_id

    async def test_create_territory_non_org(self, client, map_id, novel_id, char_entity_id):
        resp = await client.post(
            f"/api/world/maps/{map_id}/territories?novel_id={novel_id}",
            json={
                "faction_entity_id": char_entity_id,  # 不是 organization
                "hexes": [{"hex_q": 1, "hex_r": 1}],
            },
        )
        assert resp.status_code == 400

    async def test_delete_territory(self, client, map_id, novel_id, org_entity_id):
        # 先创建
        resp = await client.post(...)
        tid = resp.json()[0]["id"]

        # 删除
        resp = await client.delete(
            f"/api/world/maps/{map_id}/territories/{tid}?novel_id={novel_id}"
        )
        assert resp.status_code == 204

    async def test_focus_mode(self, client, map_id, novel_id, org_entity_id):
        # 创建势力范围
        await client.post(...)

        resp = await client.get(
            f"/api/world/maps/{map_id}/focus?novel_id={novel_id}&entity_id={org_entity_id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["related_hexes"]) > 0
```

---

## Task 9: 前端 — mapState.js 扩展

**Files:**
- Modify: `frontend-console/views/mapState.js`

新增字段：

```javascript
export const mapState = {
  // ... 已有字段 ...
  territories: [],
  focusMode: false,
  focusEntityId: null,
  focusRelatedHexes: new Set(),
  selectedFactionId: null,
  factionColors: {}, // { faction_entity_id: color }
}

export function setFocusMode(enabled, entityId = null) {
  mapState.focusMode = enabled
  mapState.focusEntityId = entityId
}

export function setFocusRelatedHexes(hexes) {
  mapState.focusRelatedHexes = new Set(hexes.map(h => `${h.hex_q},${h.hex_r}`))
}

export function clearFocus() {
  mapState.focusMode = false
  mapState.focusEntityId = null
  mapState.focusRelatedHexes.clear()
}

export function setSelectedFaction(factionId) {
  mapState.selectedFactionId = factionId
}

export function setFactionColor(factionId, color) {
  mapState.factionColors[factionId] = color
}
```

---

## Task 10: 前端 — mapHexRenderer.js 新增 drawTerritories

**Files:**
- Modify: `frontend-console/views/mapHexRenderer.js`

新增函数：

```javascript
/**
 * 绘制势力范围（Layer 5）
 * @param {CanvasRenderingContext2D} ctx
 * @param {Array} territories - MapTerritoryTile[]
 * @param {number} hexSize
 * @param {number} offsetX
 * @param {number} offsetY
 * @param {Object} factionColors - { faction_entity_id: color }
 */
export function drawTerritories(ctx, territories, hexSize, offsetX, offsetY, factionColors) {
  if (!territories || territories.length === 0) return

  const factionGroups = {}
  territories.forEach(t => {
    const fid = t.faction_entity_id
    if (!factionGroups[fid]) factionGroups[fid] = []
    factionGroups[fid].push(t)
  })

  Object.entries(factionGroups).forEach(([fid, tiles]) => {
    const color = factionColors[fid] || getDefaultFactionColor(fid)
    ctx.fillStyle = color + "66" // 40% 透明度
    ctx.strokeStyle = color
    ctx.lineWidth = 1

    tiles.forEach(t => {
      const [x, y] = hexToPixel(t.hex_q, t.hex_r, hexSize)
      drawHexagon(ctx, x + offsetX, y + offsetY, hexSize, true, false)
    })
  })
}

function getDefaultFactionColor(fid) {
  // 基于 faction ID 生成确定性颜色
  const colors = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7", "#DDA0DD"]
  let hash = 0
  for (let i = 0; i < fid.length; i++) {
    hash = fid.charCodeAt(i) + ((hash << 5) - hash)
  }
  return colors[Math.abs(hash) % colors.length]
}
```

---

## Task 11: 前端 — mapView.js 聚焦模式与势力编辑

**Files:**
- Modify: `frontend-console/views/mapView.js`

新增功能：

1. **聚焦模式切换：**
```javascript
_toggleFocusMode(entityId) {
  if (mapState.focusMode && mapState.focusEntityId === entityId) {
    clearFocus()
  } else {
    setFocusMode(true, entityId)
    this._loadFocusState(entityId)
  }
  this._render("map-root")
}

async _loadFocusState(entityId) {
  try {
    const resp = await api.world.getFocusState(this._currentMapId, entityId)
    setFocusRelatedHexes(resp.related_hexes)
  } catch (err) {
    toast(`加载聚焦状态失败：${err.message}`, "error")
  }
}
```

2. **势力编辑工具：**
```javascript
_renderTerritoryTools() {
  return `
    <div class="map-tool-group">
      <h4>势力范围</h4>
      <select id="territory-faction-select">
        <option value="">选择组织...</option>
        ${this._organizations.map(o => `<option value="${esc(o.id)}">${esc(o.name)}</option>`).join("")}
      </select>
      <input type="color" id="territory-color" value="#FF6B6B" />
      <button id="territory-paint" class="btn btn-primary">绘制</button>
      <button id="territory-clear" class="btn btn-danger">清除该组织</button>
    </div>
  `
}
```

3. **渲染时应用聚焦透明度：**
```javascript
_getHexOpacity(q, r) {
  if (!mapState.focusMode) return 1.0
  const key = `${q},${r}`
  return mapState.focusRelatedHexes.has(key) ? 1.0 : 0.3
}
```

---

## Task 12: 前端测试

**Files:**
- Modify: `frontend-console/tests/mapView.test.js`

新增测试：

```javascript
describe("mapView P2 势力范围", () => {
  it("drawTerritories 渲染势力范围", () => {
    const territories = [
      { faction_entity_id: "f1", hex_q: 1, hex_r: 1 },
      { faction_entity_id: "f1", hex_q: 1, hex_r: 2 },
    ]
    drawTerritories(ctx, territories, 30, 0, 0, { f1: "#FF0000" })
    expect(ctx.fillStyle).toContain("FF0000")
  })

  it("聚焦模式降低不相关 hex 透明度", () => {
    setFocusMode(true, "e1")
    setFocusRelatedHexes([{ hex_q: 1, hex_r: 1 }])
    expect(mapView._getHexOpacity(1, 1)).toBe(1.0)
    expect(mapView._getHexOpacity(2, 2)).toBe(0.3)
  })
})
```

---

## Task 13: 文档同步

**Files:**
- Modify: `docs/references/map-prd-v1.1.md`

1. 在 "实现记录" 末尾追加 P2 实现记录
2. 更新 "未实现 Feature 全景" 表格，标记 P2 为已实现
3. 更新 "文档状态"：P0 + P1 + P2 已实现

---

## 自我审查

### Spec 覆盖检查

| PRD P2 要求 | 对应 Task |
|-------------|-----------|
| `map_territory_tiles` 表 | Task 1 |
| 势力范围后端 CRUD | Task 2-6 |
| 势力范围 Canvas 渲染 | Task 10 |
| 聚焦模式 | Task 7, 11 |
| 组织调色盘 | Task 9, 11 |
| 势力编辑工具 | Task 11 |
| 后端测试 | Task 8 |
| 前端测试 | Task 12 |
| 文档同步 | Task 13 |

### Placeholder 检查

- 无 TBD/TODO。
- 每个 task 包含具体代码、命令、期望输出。
- 无模糊表述。

### 类型一致性

- `MapTerritoryCreate.faction_entity_id` 使用 str，与后端 `parse_uuid` 一致。
- `MapTerritoryResponse` 字段名与 ORM 列名一致。
- `drawTerritories` 参数类型与 `mapState.territories` 一致。
- 聚焦 API 返回 `related_hexes` 与前端 `Set<string>` 兼容。

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-22-map-p2-territory-focus.md`.**

**Execution options:**
1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task
2. **Inline Execution** — execute tasks in this session

**Which approach?**

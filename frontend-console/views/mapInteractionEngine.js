/**
 * 地图交互会话工具。
 *
 * 不访问 DOM 和 API，方便在 mapView/mapQuickCreateView 之间复用。
 */

const LAYER_PRIORITY = {
  conflict: 90,
  marker: 80,
  location: 70,
  terrain_region: 40,
  terrain_patch: 30,
  tile: 10,
}

export function createMapInteractionSession(initial = {}) {
  return {
    mode: initial.mode || "browse",
    selected: null,
    dragging: null,
    layoutUndo: [],
    terrainUndo: [],
    preview: initial.preview || null,
  }
}

export function beginDrag(session, object) {
  return {
    ...session,
    dragging: {
      object,
      start: object ? { ...object } : null,
    },
  }
}

export function dragToHex(session, q, r) {
  if (!session.dragging?.object) return session
  return {
    ...session,
    dragging: {
      ...session.dragging,
      object: {
        ...session.dragging.object,
        center_hex_q: Math.max(0, Math.round(q)),
        center_hex_r: Math.max(0, Math.round(r)),
      },
    },
  }
}

export function commitDrag(session, layouts) {
  if (!session.dragging?.object) return { session, layouts }
  const changed = session.dragging.object
  const nextLayouts = layouts.map((layout) => (
    layout.location_entity_id === changed.location_entity_id
      ? { ...layout, ...changed, locked: true, layout_source: "user_drag" }
      : layout
  ))
  return {
    session: {
      ...session,
      dragging: null,
      layoutUndo: [...session.layoutUndo, layouts],
    },
    layouts: nextLayouts,
  }
}

export function undoLayout(session, currentLayouts) {
  if (!session.layoutUndo.length) return { session, layouts: currentLayouts }
  const previous = session.layoutUndo[session.layoutUndo.length - 1]
  return {
    session: {
      ...session,
      layoutUndo: session.layoutUndo.slice(0, -1),
    },
    layouts: previous,
  }
}

export function pushTerrainUndo(session, terrainSnapshot) {
  return {
    ...session,
    terrainUndo: [...session.terrainUndo, terrainSnapshot],
  }
}

export function undoTerrain(session, currentTerrain) {
  if (!session.terrainUndo.length) return { session, terrain: currentTerrain }
  const previous = session.terrainUndo[session.terrainUndo.length - 1]
  return {
    session: {
      ...session,
      terrainUndo: session.terrainUndo.slice(0, -1),
    },
    terrain: previous,
  }
}

export function queryMapObjectsAt(point, { layers = [] } = {}) {
  const x = Number(point?.x)
  const y = Number(point?.y)
  if (!Number.isFinite(x) || !Number.isFinite(y)) return []
  return layers
    .flatMap((layer, layerIndex) => (layer.objects || []).map((object, objectIndex) => ({
      ...object,
      layer: layer.type,
      zIndex: Number(layer.zIndex ?? LAYER_PRIORITY[layer.type] ?? 0),
      _layerIndex: layerIndex,
      _objectIndex: objectIndex,
    })))
    .filter((object) => hitObject(x, y, object))
    .sort((a, b) => (
      b.zIndex - a.zIndex
      || (Number(b.priority) || 0) - (Number(a.priority) || 0)
      || b._layerIndex - a._layerIndex
      || b._objectIndex - a._objectIndex
    ))
    .map(({ _layerIndex, _objectIndex, ...object }) => object)
}

function hitObject(x, y, object) {
  if (typeof object.hitTest === "function") return object.hitTest(x, y)
  if (object.hitArea) {
    const { x: hx = 0, y: hy = 0, width = 0, height = 0 } = object.hitArea
    return x >= hx && y >= hy && x <= hx + width && y <= hy + height
  }
  if (object.hex_q != null && object.hex_r != null && object.point) {
    const radius = Number(object.radius) || 18
    const dx = x - object.point.x
    const dy = y - object.point.y
    return Math.sqrt(dx * dx + dy * dy) <= radius
  }
  return false
}

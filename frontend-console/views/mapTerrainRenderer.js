/**
 * 手绘地形 Canvas 渲染器。
 */

import { hexToPixel, hexCorners } from "./mapHexRenderer.js"
import { getTerrainAsset } from "./mapTerrainAssets.js"

const TERRAIN_STYLES = {
  mountain: "#6f7b8a",
  forest: "#2f8f5b",
  water: "#3d8fd1",
  ruin: "#8b8172",
  abyss: "#22152f",
  barrier: "#5a9cff",
  magic_field: "#6f63ff",
  corruption: "#7c315f",
  danger_zone: "#c23b3b",
}

export function drawTerrainLayers(ctx, terrainState = {}, { hexSize = 30, editMode = false } = {}) {
  const layers = terrainState.layers || []
  const patches = terrainState.patches || []
  const layerById = new Map(layers.map((layer) => [layer.id, layer]))
  for (const patch of patches) {
    const layer = layerById.get(patch.layer_id)
    if (!layer || layer.visible === false) continue
    drawPatch(ctx, patch, layer, hexSize, editMode)
  }
}

export function buildTerrainHitObjects(terrainState = {}, toPoint) {
  return (terrainState.patches || []).map((patch) => {
    const point = typeof toPoint === "function"
      ? toPoint(patch.hex_q, patch.hex_r)
      : { x: patch.hex_q, y: patch.hex_r }
    return {
      id: patch.id || `${patch.region_id}:${patch.hex_q},${patch.hex_r}`,
      type: "terrain_patch",
      region_id: patch.region_id,
      layer_id: patch.layer_id,
      hex_q: patch.hex_q,
      hex_r: patch.hex_r,
      point,
      radius: 18,
      priority: 10,
    }
  })
}

function drawPatch(ctx, patch, layer, hexSize, editMode) {
  const [x, y] = hexToPixel(patch.hex_q, patch.hex_r, hexSize)
  const corners = hexCorners(hexSize)
  const asset = getTerrainAsset(layer.terrain_asset_key)
  ctx.save()
  ctx.globalAlpha = Number(layer.opacity ?? asset.default_opacity ?? 0.4)
  ctx.fillStyle = TERRAIN_STYLES[layer.terrain_asset_key] || "#64748b"
  ctx.strokeStyle = editMode ? "#ffffff" : ctx.fillStyle
  ctx.lineWidth = editMode ? 1 : 0.25
  ctx.beginPath()
  corners.forEach(([cx, cy], index) => {
    if (index === 0) ctx.moveTo(x + cx, y + cy)
    else ctx.lineTo(x + cx, y + cy)
  })
  ctx.closePath()
  ctx.fill()
  if (editMode) ctx.stroke()
  ctx.restore()
}

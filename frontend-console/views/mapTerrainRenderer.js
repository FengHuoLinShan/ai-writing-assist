/**
 * 手绘地形 Canvas 渲染器。
 */

import { hexToPixel, hexCorners } from "./mapHexRenderer.js"
import { getTerrainAsset, TERRAIN_PRESETS } from "./mapTerrainAssets.js"

export function drawTerrainLayers(ctx, terrainState = {}, { hexSize = 30, editMode = false } = {}) {
  const layers = [...(terrainState.layers || [])].sort((a, b) => (
    Number(a.z_index || 0) - Number(b.z_index || 0)
    || String(a.created_at || "").localeCompare(String(b.created_at || ""))
    || String(a.id || "").localeCompare(String(b.id || ""))
  ))
  const patches = terrainState.patches || []
  for (const layer of layers) {
    if (layer.visible === false) continue
    for (const patch of patches) {
      if (patch.layer_id !== layer.id) continue
      drawPatch(ctx, patch, layer, hexSize, editMode)
    }
  }
}

function drawPatch(ctx, patch, layer, hexSize, editMode) {
  const [x, y] = hexToPixel(patch.hex_q, patch.hex_r, hexSize)
  const corners = hexCorners(hexSize)
  const asset = getTerrainAsset(layer.terrain_asset_key)
  const preset = TERRAIN_PRESETS[layer.meta?.preset_key] || TERRAIN_PRESETS.standard
  ctx.save()
  ctx.filter = `saturate(${preset.saturation}) contrast(${preset.contrast})`
  ctx.globalAlpha = Math.min(1, Number(layer.opacity ?? asset.default_opacity ?? 0.4) * preset.opacity_scale)
  ctx.fillStyle = asset.color || "#64748b"
  ctx.strokeStyle = asset.unknown ? "#f59e0b" : editMode ? "#ffffff" : ctx.fillStyle
  ctx.lineWidth = editMode ? 1 : 0.25
  ctx.beginPath()
  corners.forEach(([cx, cy], index) => {
    if (index === 0) ctx.moveTo(x + cx, y + cy)
    else ctx.lineTo(x + cx, y + cy)
  })
  ctx.closePath()
  ctx.fill()
  ctx.clip()
  drawAssetPattern(ctx, asset.pattern, x, y, hexSize, asset.unknown)
  if (editMode) ctx.stroke()
  ctx.restore()
}

function drawAssetPattern(ctx, pattern, x, y, size, unknown) {
  ctx.globalAlpha *= 0.72
  ctx.strokeStyle = unknown ? "#fbbf24" : "rgba(255,255,255,.72)"
  ctx.fillStyle = ctx.strokeStyle
  ctx.lineWidth = Math.max(1, size / 18)
  if (pattern === "dots") {
    for (let dx = -size / 2; dx <= size / 2; dx += size / 3) {
      ctx.beginPath()
      ctx.arc(x + dx, y + Math.sin(dx) * 3, Math.max(1.5, size / 14), 0, Math.PI * 2)
      ctx.fill()
    }
    return
  }
  if (pattern === "rings" || pattern === "spiral") {
    ctx.beginPath()
    ctx.arc(x, y, size * 0.42, 0, pattern === "spiral" ? Math.PI * 1.6 : Math.PI * 2)
    ctx.stroke()
    ctx.beginPath()
    ctx.arc(x, y, size * 0.2, 0, Math.PI * 2)
    ctx.stroke()
    return
  }
  if (pattern === "waves") {
    for (let dy = -size / 3; dy <= size / 3; dy += size / 3) {
      ctx.beginPath()
      ctx.moveTo(x - size * 0.6, y + dy)
      ctx.quadraticCurveTo(x, y + dy - size / 5, x + size * 0.6, y + dy)
      ctx.stroke()
    }
    return
  }
  if (["line", "ridge", "veins"].includes(pattern)) {
    ctx.beginPath()
    ctx.moveTo(x - size * 0.65, y + size * 0.25)
    ctx.lineTo(x - size * 0.15, y - size * 0.3)
    ctx.lineTo(x + size * 0.15, y + size * 0.12)
    ctx.lineTo(x + size * 0.65, y - size * 0.25)
    ctx.stroke()
    return
  }
  if (["grid", "blocks", "cross", "arch", "broken"].includes(pattern) || unknown) {
    ctx.beginPath()
    ctx.moveTo(x - size * 0.5, y)
    ctx.lineTo(x + size * 0.5, y)
    ctx.moveTo(x, y - size * 0.5)
    ctx.lineTo(x, y + size * 0.5)
    if (unknown) {
      ctx.moveTo(x - size * 0.45, y - size * 0.45)
      ctx.lineTo(x + size * 0.45, y + size * 0.45)
    }
    ctx.stroke()
    return
  }
  ctx.beginPath()
  for (let i = 0; i < 8; i += 1) {
    const angle = (Math.PI * 2 * i) / 8
    ctx.moveTo(x, y)
    ctx.lineTo(x + Math.cos(angle) * size * 0.55, y + Math.sin(angle) * size * 0.55)
  }
  ctx.stroke()
}

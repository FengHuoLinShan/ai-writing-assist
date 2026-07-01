/**
 * 手绘地形编辑会话。
 */

import { getTerrainAsset } from "./mapTerrainAssets.js"

export function createTerrainSession({ assetKey = "barrier", layerId = null, regionId = null } = {}) {
  const asset = getTerrainAsset(assetKey)
  return {
    activeAssetKey: asset.asset_key,
    layerId,
    regionId,
    brushSize: asset.default_brush_size,
    opacity: asset.default_opacity,
    tool: "brush",
    patches: new Map(),
    undoStack: [],
    drawing: false,
    lastHex: null,
  }
}

export function beginTerrainStroke(session) {
  return {
    ...session,
    drawing: true,
    lastHex: null,
    undoStack: [...session.undoStack, snapshotPatches(session.patches)],
  }
}

export function paintTerrainHex(session, q, r) {
  if (!session.drawing) return session
  const key = `${q},${r}`
  if (session.lastHex === key) return session
  const patches = new Map(session.patches)
  for (const cell of brushCells(q, r, session.brushSize)) {
    const cellKey = `${cell.hex_q},${cell.hex_r}`
    if (session.tool === "eraser") {
      patches.delete(cellKey)
    } else {
      patches.set(cellKey, {
        region_id: session.regionId,
        hex_q: cell.hex_q,
        hex_r: cell.hex_r,
        strength: 1,
        brush_source: "brush",
      })
    }
  }
  return { ...session, patches, lastHex: key }
}

export function endTerrainStroke(session) {
  return { ...session, drawing: false, lastHex: null }
}

export function undoTerrainStroke(session) {
  if (!session.undoStack.length) return session
  const previous = session.undoStack[session.undoStack.length - 1]
  return {
    ...session,
    patches: restorePatches(previous),
    undoStack: session.undoStack.slice(0, -1),
    drawing: false,
    lastHex: null,
  }
}

export function terrainSessionToPayload(session, { layerName = null, regionName = null } = {}) {
  return {
    layer: {
      name: layerName || `${getTerrainAsset(session.activeAssetKey).label}层`,
      terrain_asset_key: session.activeAssetKey,
      opacity: session.opacity,
      visible: true,
      locked: false,
    },
    regions: [{
      id: session.regionId,
      layer_id: session.layerId,
      name: regionName || `${getTerrainAsset(session.activeAssetKey).label} 1`,
      region_status: "active",
    }],
    patches: [...session.patches.values()],
  }
}

export function brushCells(q, r, size = 1) {
  const radius = Math.max(1, Number(size) || 1) - 1
  const cells = []
  for (let dq = -radius; dq <= radius; dq++) {
    for (let dr = -radius; dr <= radius; dr++) {
      if (Math.max(Math.abs(dq), Math.abs(dr), Math.abs(-dq - dr)) <= radius) {
        cells.push({ hex_q: q + dq, hex_r: r + dr })
      }
    }
  }
  return cells
}

function snapshotPatches(patches) {
  return [...patches.entries()]
}

function restorePatches(snapshot) {
  return new Map(snapshot)
}

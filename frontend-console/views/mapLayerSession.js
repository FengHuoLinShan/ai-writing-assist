/**
 * 图层树的会话选择投影。
 *
 * `visible/locked/opacity/zoom` 仍由后端图层树作为权威；本模块只处理
 * exclusive/floor 组当前子层和临时 isolate，不产生编辑 revision。
 */

const STORAGE_PREFIX = "novel_map_active_layer_children:"

export function layerNodeId(node) {
  return node?.id || node?.client_id || null
}

function parentId(node) {
  return node?.parent_id || node?.parent_client_id || null
}

export function layerSessionStorageKey(novelId, mapId) {
  return `${STORAGE_PREFIX}${novelId || "none"}:${mapId || "none"}`
}

export function indexLayerTree(nodes = []) {
  const byId = new Map()
  const children = new Map()
  for (const node of nodes || []) {
    const id = layerNodeId(node)
    if (!id) continue
    byId.set(id, node)
    const parent = parentId(node)
    if (!children.has(parent)) children.set(parent, [])
    children.get(parent).push(node)
  }
  for (const siblings of children.values()) {
    siblings.sort((a, b) => (
      Number(a.sort_order || 0) - Number(b.sort_order || 0)
      || String(layerNodeId(a)).localeCompare(String(layerNodeId(b)))
    ))
  }
  return { byId, children }
}

function defaultChild(group, children = []) {
  if (!children.length) return null
  if (group?.selection_mode === "floor") {
    return children.find((node) => Number(node.floor_level) === 0)
      || [...children].sort((a, b) => (
        Number(a.floor_level ?? Number.MAX_SAFE_INTEGER)
          - Number(b.floor_level ?? Number.MAX_SAFE_INTEGER)
        || Number(a.sort_order || 0) - Number(b.sort_order || 0)
        || String(layerNodeId(a)).localeCompare(String(layerNodeId(b)))
      ))[0]
  }
  return children[0]
}

function readStoredSelections(novelId, mapId, storage) {
  if (!storage?.getItem) return {}
  try {
    const parsed = JSON.parse(storage.getItem(layerSessionStorageKey(novelId, mapId)) || "{}")
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

export function persistLayerSelections(novelId, mapId, selections, storage = globalThis.localStorage) {
  if (!storage?.setItem || !novelId || !mapId) return
  try {
    storage.setItem(layerSessionStorageKey(novelId, mapId), JSON.stringify(selections || {}))
  } catch {
    // localStorage 容量/隐私模式错误不应阻断地图使用。
  }
}

/**
 * 恢复并校正所有 exclusive/floor group 的直接子层。
 * focusNodeId 在存在时优先选中其祖先链上的分支。
 */
export function resolveLayerSelections({
  nodes = [],
  novelId = null,
  mapId = null,
  focusNodeId = null,
  storage = globalThis.localStorage,
  previous = null,
} = {}) {
  const { byId, children } = indexLayerTree(nodes)
  const stored = { ...readStoredSelections(novelId, mapId, storage), ...(previous || {}) }
  const next = {}
  for (const group of nodes) {
    if (!["exclusive", "floor"].includes(group.selection_mode)) continue
    const id = layerNodeId(group)
    const directChildren = children.get(id) || []
    const storedChild = directChildren.find((node) => layerNodeId(node) === stored[id])
    const selected = storedChild || defaultChild(group, directChildren)
    if (selected) next[id] = layerNodeId(selected)
  }

  if (focusNodeId && byId.has(focusNodeId)) {
    let child = byId.get(focusNodeId)
    let parent = byId.get(parentId(child))
    while (parent) {
      if (["exclusive", "floor"].includes(parent.selection_mode)) {
        next[layerNodeId(parent)] = layerNodeId(child)
      }
      child = parent
      parent = byId.get(parentId(parent))
    }
  }
  persistLayerSelections(novelId, mapId, next, storage)
  return next
}

export function setLayerSelection({
  nodes = [],
  selections = {},
  groupId,
  childId,
  novelId,
  mapId,
  storage = globalThis.localStorage,
} = {}) {
  const { byId } = indexLayerTree(nodes)
  const group = byId.get(groupId)
  const child = byId.get(childId)
  if (!group || !child || parentId(child) !== groupId) return selections
  if (!["exclusive", "floor"].includes(group.selection_mode)) return selections
  const next = { ...(selections || {}), [groupId]: childId }
  persistLayerSelections(novelId, mapId, next, storage)
  return next
}

function isDescendantOrSelf(nodeId, ancestorId, byId) {
  let current = byId.get(nodeId)
  while (current) {
    const id = layerNodeId(current)
    if (id === ancestorId) return true
    current = byId.get(parentId(current))
  }
  return false
}

/** 计算会话选择后的可见性，不改变后端 effective_visible。 */
export function sessionLayerVisible(node, nodes = [], selections = {}, isolateNodeId = null) {
  const id = layerNodeId(node)
  if (!id) return true
  if ((node.effective_visible ?? node.visible) === false) return false
  const { byId } = indexLayerTree(nodes)
  let child = node
  let parent = byId.get(parentId(child))
  while (parent) {
    const groupId = layerNodeId(parent)
    if (["exclusive", "floor"].includes(parent.selection_mode)) {
      const activeChild = selections[groupId]
      if (activeChild && layerNodeId(child) !== activeChild) return false
    }
    child = parent
    parent = byId.get(parentId(parent))
  }
  if (isolateNodeId && !isDescendantOrSelf(id, isolateNodeId, byId)) return false
  return true
}

export function activeSelectionReason(node, nodes = [], selections = {}) {
  if ((node?.effective_visible ?? node?.visible) === false) return "结构隐藏"
  const { byId } = indexLayerTree(nodes)
  let child = node
  let parent = byId.get(parentId(child))
  while (parent) {
    const groupId = layerNodeId(parent)
    if (["exclusive", "floor"].includes(parent.selection_mode)) {
      const activeChild = selections[groupId]
      if (activeChild && layerNodeId(child) !== activeChild) {
        return parent.selection_mode === "floor" ? "非当前楼层" : "非当前独占图层"
      }
    }
    child = parent
    parent = byId.get(parentId(parent))
  }
  return null
}


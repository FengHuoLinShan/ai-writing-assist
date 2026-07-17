/**
 * 地图编辑侧边栏渲染 — PRD docs/PRD-动态地图功能.md §路径1 / §路径2
 *
 * 返回 HTML 字符串（由 mapView 注入 .map-edit-panel 容器）。
 * 事件绑定在 mapView._bindMapEvents 中通过 data-action 委托。
 */
import { TERRAIN_OPTIONS } from "./mapHexRenderer.js"
import { mapState } from "./mapState.js"
import { TERRAIN_ASSETS, TERRAIN_PACKS, TERRAIN_PRESETS } from "./mapTerrainAssets.js"

function renderLayerTree(nodes) {
  if (!nodes?.length) return `<p class="map-hint">图层树尚未加载</p>`
  const children = new Map()
  for (const node of nodes) {
    const parent = node.parent_id || node.parent_client_id || null
    if (!children.has(parent)) children.set(parent, [])
    children.get(parent).push(node)
  }
  let collapsedDepth = null
  return nodes.map((node) => {
    const nodeId = node.id || node.client_id || ""
    const depth = Math.max(1, Number(node.depth || 1))
    if (collapsedDepth != null && depth > collapsedDepth) return ""
    if (collapsedDepth != null && depth <= collapsedDepth) collapsedDepth = null
    const effectiveLocked = node.effective_locked ?? node.locked
    const effectiveVisible = node.effective_visible ?? node.visible
    const effectiveOpacity = Number(node.effective_opacity ?? node.opacity ?? 1)
    const effectiveMinZoom = node.effective_min_zoom ?? node.min_zoom
    const effectiveMaxZoom = node.effective_max_zoom ?? node.max_zoom
    const systemNode = Boolean(node.layer_key)
    const collapsed = mapState.collapsedLayerNodeIds.has(nodeId)
    const sessionReason = node.session_reason || null
    const isolated = mapState.isolateLayerNodeId === nodeId
    const groupChildren = (children.get(nodeId) || []).sort((a, b) => a.sort_order - b.sort_order)
    const activeChild = mapState.activeLayerChildIds[nodeId]
    if (collapsed && node.node_type === "group") collapsedDepth = depth
    return `
      <div class="map-layer-tree-row ${node.node_type === "group" ? "is-group" : "is-leaf"} ${sessionReason ? "is-session-hidden" : ""} ${isolated ? "is-isolated" : ""}" style="--layer-depth:${depth}" data-layer-node-id="${esc(nodeId)}">
        ${node.node_type === "group"
          ? `<button class="map-layer-tree-name link-button" data-action="map-layer-collapse" data-id="${esc(nodeId)}">${collapsed ? "▸" : "▾"} ${esc(node.name)}</button>`
          : `<span class="map-layer-tree-name">• ${esc(node.name)}</span>`}
        <span class="map-layer-tree-effective">${sessionReason || (effectiveVisible ? "可见" : "隐藏")}${effectiveLocked ? " · 继承锁定" : ""} · ${Math.round(effectiveOpacity * 100)}% · ${effectiveMinZoom ?? "-3"}~${effectiveMaxZoom ?? "3"}${node.selection_mode && node.selection_mode !== "normal" ? ` · ${node.selection_mode === "floor" ? "楼层" : "独占"}` : ""}</span>
        ${node.node_type === "group" && ["exclusive", "floor"].includes(node.selection_mode) && groupChildren.length
          ? `<select class="form-select map-layer-active-child" data-layer-active-group="${esc(nodeId)}" aria-label="选择${node.selection_mode === "floor" ? "当前楼层" : "当前子层"}">
              ${groupChildren.map((child) => `<option value="${esc(child.id || child.client_id)}" ${(child.id || child.client_id) === activeChild ? "selected" : ""}>${child.floor_level != null ? `${esc(child.floor_level)}F · ` : ""}${esc(child.name)}</option>`).join("")}
            </select>`
          : ""}
        <span class="map-layer-tree-actions">
          <button class="btn btn-xs" data-action="map-layer-toggle-visible" data-id="${esc(nodeId)}" title="显示/隐藏">${node.visible ? "◉" : "○"}</button>
          <button class="btn btn-xs" data-action="map-layer-toggle-lock" data-id="${esc(nodeId)}" title="锁定/解锁">${node.locked ? "🔒" : "🔓"}</button>
          <button class="btn btn-xs" data-action="map-layer-move-up" data-id="${esc(nodeId)}" title="上移">↑</button>
          <button class="btn btn-xs" data-action="map-layer-move-down" data-id="${esc(nodeId)}" title="下移">↓</button>
          <button class="btn btn-xs" data-action="map-layer-settings" data-id="${esc(nodeId)}" title="图层设置">设置</button>
          <button class="btn btn-xs ${isolated ? "active" : ""}" data-action="map-layer-isolate" data-id="${esc(nodeId)}" title="临时隔离显示">${isolated ? "退出隔离" : "隔离"}</button>
          ${!systemNode && node.node_type === "group" ? `<button class="btn btn-xs btn-danger" data-action="map-layer-delete-group" data-id="${esc(nodeId)}">删组</button>` : ""}
        </span>
      </div>
    `
  }).join("")
}

/**
 * 渲染编辑侧边栏 HTML。
 * @param {{locations:Array<{id:string,name:string}>}} ctx 可绑定的 location 实体列表
 * @returns {string}
 */
export function renderEditPanel(ctx) {
  const locations = ctx.locations || []
  const locOptions = locations.length
    ? locations.map((l) => `<option value="${esc(l.id)}">${esc(l.name)}</option>`).join("")
    : `<option value="">（无可用地点）</option>`

  const allEntities = ctx.allEntities || []
  const entityOptions = allEntities.length
    ? allEntities.map((e) => `<option value="${esc(e.id)}">${esc(e.name)}</option>`).join("")
    : `<option value="">（无可用实体）</option>`

  const scenes = ctx.scenes || []
  const sceneOptions = scenes.length
    ? scenes.map((s) => `<option value="${esc(s.id)}">${esc(s.title)}</option>`).join("")
    : ""

  const terrainLayers = ctx.terrainLayers || []
  const layerTree = ctx.layerTree || []
  const pathLayers = ctx.pathLayers || []
  const paths = ctx.paths || []
  const selectedLayerId = mapState.selectedTerrainLayerId || terrainLayers[0]?.id || ""
  const editorNode = mapState.editorLayer === "terrainOverlay"
    ? layerTree.find((node) => (
      node.terrain_layer_id === selectedLayerId
      || node.terrain_layer_client_id === selectedLayerId
    )) || layerTree.find((node) => node.layer_key === "terrainOverlay")
    : mapState.editorLayer === "path"
      ? layerTree.find((node) => (
        node.path_layer_id === mapState.selectedPathLayerId
        || node.path_layer_client_id === mapState.selectedPathLayerId
      )) || layerTree.find((node) => node.layer_key === "path")
      : layerTree.find((node) => node.layer_key === ({
      location: "location",
      baseTerrain: "baseTerrain",
      marker: `marker.${mapState.selectedMarkerType || "character"}`,
      territory: "territory",
    }[mapState.editorLayer]))
  const editorLayerLocked = Boolean(editorNode?.effective_locked ?? editorNode?.locked)
  const layerOptions = terrainLayers.length
    ? terrainLayers.map((layer) => `<option value="${esc(layer.id)}" ${selectedLayerId === layer.id ? "selected" : ""}>${esc(layer.name)}${layer.locked ? " 🔒" : ""}</option>`).join("")
    : `<option value="">（暂无覆盖图层）</option>`
  const assetGroups = TERRAIN_PACKS.map((pack) => `
    <optgroup label="${esc(pack.label)}">
      ${TERRAIN_ASSETS.filter((item) => item.pack_key === pack.pack_key).map((item) => `<option value="${esc(item.asset_key)}" ${mapState.selectedTerrainAssetKey === item.asset_key ? "selected" : ""}>${esc(item.label)}</option>`).join("")}
    </optgroup>
  `).join("")
  const selectedAssetKnown = TERRAIN_ASSETS.some(
    (item) => item.asset_key === mapState.selectedTerrainAssetKey,
  )
  const unknownAssetOption = selectedAssetKnown
    ? ""
    : `<option value="${esc(mapState.selectedTerrainAssetKey)}" selected>未知素材（${esc(mapState.selectedTerrainAssetKey)}）</option>`
  const presetOptions = Object.values(TERRAIN_PRESETS).map((preset) => (
    `<option value="${esc(preset.key)}" ${mapState.selectedTerrainPreset === preset.key ? "selected" : ""}>${esc(preset.label)}</option>`
  )).join("")
  const selectedPathLayerId = mapState.selectedPathLayerId || pathLayers[0]?.id || ""
  const selectedPathLayer = pathLayers.find((layer) => layer.id === selectedPathLayerId)
  const pathLayerOptions = pathLayers.length
    ? pathLayers.map((layer) => `<option value="${esc(layer.id)}" ${selectedPathLayerId === layer.id ? "selected" : ""}>${esc(layer.name || layer.display_name || "线路图层")}</option>`).join("")
    : `<option value="">（暂无线路图层）</option>`
  const compatiblePathProfiles = Object.entries(ctx.pathProfiles || {}).filter(([, profile]) => (
    !selectedPathLayer?.category || profile.category === selectedPathLayer.category
  ))
  const pathTypeOptions = compatiblePathProfiles.map(([key, profile]) => (
    `<option value="${esc(key)}" ${mapState.selectedPathType === key ? "selected" : ""}>${esc(profile.label)}</option>`
  )).join("")
  const selectedPath = paths.find((path) => (path.id || path.client_id) === mapState.selectedPathId)
  const endpointOptions = (selectedEntityId) => [
    `<option value="">（未绑定地点）</option>`,
    ...locations.map((location) => (
      `<option value="${esc(location.id)}" ${location.id === selectedEntityId ? "selected" : ""}>${esc(location.name)}</option>`
    )),
  ].join("")
  const selectedPathNodes = selectedPath?.nodes || []
  const selectedPathNode = selectedPathNodes[mapState.selectedPathNodeIndex]
  const segmentTypeOptions = [
    `<option value="">跟随线路类型</option>`,
    ...compatiblePathProfiles.map(([key, profile]) => (
      `<option value="${esc(key)}" ${selectedPathNode?.segment_type === key ? "selected" : ""}>${esc(profile.label)}</option>`
    )),
  ].join("")

  return `
    <div class="map-edit-tools" data-editor-layer="${esc(mapState.editorLayer)}" data-editor-locked="${editorLayerLocked ? "true" : "false"}">
      <div class="map-edit-section map-layer-tree-section">
        <div class="map-layer-tree-heading"><h4>图层树</h4><button class="btn btn-xs" data-action="map-layer-add-group">+ 分组</button></div>
        <div class="map-layer-tree">${renderLayerTree(layerTree)}</div>
        <p class="map-hint">父组的显隐、锁定、透明度和缩放范围会递归作用于子层。</p>
        <div class="map-tool-row map-layer-tree-actions-global">
          <button class="btn btn-xs" data-action="map-layer-undo">撤销结构</button>
          <button class="btn btn-xs" data-action="map-layer-redo">重做结构</button>
          <button class="btn btn-xs btn-primary" data-action="map-layer-apply">应用图层结构</button>
        </div>
        ${mapState.layerTreeBaselineStale ? `<p class="map-hint map-layer-stale-hint">服务端图层树已更新，本地结构草稿已保留，请检查后重新应用。</p>` : ""}
      </div>
      <div class="map-edit-section map-editor-layer-nav">
        <h4>编辑图层</h4>
        <div class="map-tool-row">
          ${[
            ["location", "地点"],
            ["baseTerrain", "底图地貌"],
            ["terrainOverlay", "覆盖素材"],
            ["path", "线路"],
            ["marker", "标记"],
            ["territory", "领地"],
          ].map(([value, label]) => `<button class="btn btn-sm map-editor-layer-btn ${mapState.editorLayer === value ? "active" : ""}" data-action="map-editor-layer" data-layer="${value}">${label}</button>`).join("")}
        </div>
      </div>
      ${editorLayerLocked ? `<p class="map-hint map-layer-locked-hint">当前编辑图层受自身或父组锁定；画布工具已停用，请先在图层树中解锁。</p>` : ""}

      <div class="map-edit-section" id="map-location-section" style="display:${mapState.editorLayer === "location" ? "" : "none"};">
        <h4>地点位置</h4>
        <div class="map-tool-row"><button class="btn btn-sm map-tool-btn ${mapState.activeTool === "locationMove" ? "active" : ""}" data-action="map-tool-locationMove">移动地点</button><button class="btn btn-sm map-tool-btn ${mapState.activeTool === "bind" ? "active" : ""}" data-action="map-tool-bind">编辑范围</button></div>
        <select class="form-select" id="map-bind-select">${locOptions}</select>
        <button class="btn btn-sm" data-action="map-location-lock">锁定/解锁所选地点</button>
        <label class="map-checkbox"><input type="checkbox" id="map-bind-center" /> 设为中心点</label>
        <p class="map-hint">移动地点会整体平移它的全部范围格；锁定地点需要先解锁。</p>
        <span class="map-pending-count" id="map-binding-pending-count">0 个待绑定</span>
      </div>

      <div class="map-edit-section" id="map-terrain-section" style="display:${mapState.editorLayer === "baseTerrain" ? "" : "none"};">
        <h4>底图地貌</h4>
        <div class="map-tool-row"><button class="btn btn-sm map-tool-btn ${mapState.activeTool === "brush" ? "active" : ""}" data-action="map-tool-brush">画笔</button><button class="btn btn-sm map-tool-btn ${mapState.activeTool === "bucket" ? "active" : ""}" data-action="map-tool-bucket">填充桶</button></div>
        <select class="form-select" id="map-terrain-select">
          ${TERRAIN_OPTIONS.map((t) => `<option value="${esc(t.value)}">${esc(t.label)}</option>`).join("")}
        </select>
        <p class="map-hint">底图地貌写入 map_tiles，不使用覆盖素材。</p>
      </div>

      <div class="map-edit-section" id="map-overlay-section" style="display:${mapState.editorLayer === "terrainOverlay" ? "" : "none"};">
        <h4>覆盖素材图层</h4>
        <select class="form-select" id="map-overlay-layer">${layerOptions}</select>
        <div class="map-tool-row"><button class="btn btn-sm" data-action="map-overlay-layer-add">新建</button><button class="btn btn-sm" data-action="map-overlay-layer-edit" ${selectedLayerId ? "" : "disabled"}>设置</button><button class="btn btn-sm btn-danger" data-action="map-overlay-layer-delete" ${selectedLayerId ? "" : "disabled"}>删除</button></div>
        <label>素材</label><select class="form-select" id="map-overlay-asset">${unknownAssetOption}${assetGroups}</select>
        <label>样式</label><select class="form-select" id="map-overlay-preset">${presetOptions}</select>
        <label>笔刷尺寸</label><input class="form-input" id="map-overlay-brush-size" type="range" min="1" max="5" value="${mapState.overlayBrushSize}" />
        <div class="map-tool-row"><button class="btn btn-sm map-overlay-tool ${mapState.overlayTool === "brush" ? "active" : ""}" data-action="map-overlay-tool" data-tool="brush">画笔</button><button class="btn btn-sm map-overlay-tool ${mapState.overlayTool === "eraser" ? "active" : ""}" data-action="map-overlay-tool" data-tool="eraser">橡皮</button><button class="btn btn-sm map-overlay-tool ${mapState.overlayTool === "bucket" ? "active" : ""}" data-action="map-overlay-tool" data-tool="bucket">填充桶</button></div>
        <p class="map-hint">覆盖素材独立于底图，可锁定、排序和调节透明度。</p>
      </div>

      <div class="map-edit-section" id="map-marker-section" style="display:${mapState.editorLayer === "marker" ? "" : "none"};">
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
        <select class="form-select" id="map-marker-scene-start">
          <option value="">不限定起始 Scene</option>
          ${sceneOptions}
        </select>
        <select class="form-select" id="map-marker-scene-end">
          <option value="">不限定结束 Scene</option>
          ${sceneOptions}
        </select>
        <p class="map-hint">选择类型和实体后，点击六边形放置标记。可选择 Scene 范围限定标记可见时段。</p>
      </div>

      <div class="map-edit-section map-path-section" id="map-path-section" style="display:${mapState.editorLayer === "path" ? "" : "none"};">
        <div class="map-layer-tree-heading"><h4>道路与水系</h4><button class="btn btn-xs" data-action="map-path-layer-add">+ 线路图层</button></div>
        <div class="map-tool-row">
          <select class="form-select" id="map-path-layer">${pathLayerOptions}</select>
          <button class="btn btn-xs btn-danger" data-action="map-path-layer-delete" ${selectedPathLayerId ? "" : "disabled"}>删除图层</button>
        </div>
        <select class="form-select" id="map-path-type">${pathTypeOptions}</select>
        <div class="map-tool-row">
          <button class="btn btn-sm map-path-tool ${mapState.pathTool === "draw" ? "active" : ""}" data-action="map-path-tool" data-tool="draw">手绘</button>
          <button class="btn btn-sm map-path-tool ${mapState.pathTool === "select" ? "active" : ""}" data-action="map-path-tool" data-tool="select">选择</button>
          <button class="btn btn-sm map-path-tool ${mapState.pathTool === "nodes" ? "active" : ""}" data-action="map-path-tool" data-tool="nodes">节点精修</button>
        </div>
        <p class="map-hint">按住并拖动绘制连续线路；每隔约 0.2 格采样，松手后自动简化。</p>
        <div class="map-path-list">
          ${paths.length ? paths.map((path) => `<button class="map-path-list-row ${(path.id || path.client_id) === mapState.selectedPathId ? "active" : ""}" data-action="map-path-select" data-id="${esc(path.id || path.client_id)}"><span>${esc(path.name || "未命名线路")}</span><small>${esc((ctx.pathProfiles || {})[path.path_type]?.label || path.path_type || "线路")}${path.status === "archived" ? " · 已归档" : ""}</small></button>`).join("") : `<p class="map-hint">手绘第一条道路或水系。</p>`}
        </div>
        ${selectedPath ? `
          <div class="map-path-selection-summary"><strong>${esc(selectedPath.name || "未命名线路")}</strong><span>${(selectedPath.nodes || []).length || 0} 个节点</span><button class="btn btn-xs" data-action="map-path-archive" data-id="${esc(selectedPath.id || selectedPath.client_id)}">${selectedPath.status === "archived" ? "恢复" : "归档"}</button></div>
          <div class="map-path-endpoints">
            <label><span>起点地点</span><select class="form-select" id="map-path-start-location" ${selectedPath.status === "archived" ? "disabled" : ""}>${endpointOptions(selectedPath.start_location_entity_id)}</select></label>
            <button class="btn btn-xs" data-action="map-path-endpoint-snap" data-side="start" ${selectedPath.start_location_entity_id && selectedPath.status !== "archived" ? "" : "disabled"}>重新吸附</button>
            <label><span>终点地点</span><select class="form-select" id="map-path-end-location" ${selectedPath.status === "archived" ? "disabled" : ""}>${endpointOptions(selectedPath.end_location_entity_id)}</select></label>
            <button class="btn btn-xs" data-action="map-path-endpoint-snap" data-side="end" ${selectedPath.end_location_entity_id && selectedPath.status !== "archived" ? "" : "disabled"}>重新吸附</button>
          </div>
          ${mapState.pathTool === "nodes" ? `
            <div class="map-path-node-editor">
              <div class="map-path-node-heading">
                <span>${selectedPathNode ? `节点 ${mapState.selectedPathNodeIndex + 1} / ${selectedPathNodes.length}` : "请在画布上点选节点"}</span>
                <span class="map-tool-row">
                  <button class="btn btn-xs" data-action="map-path-node-action" data-node-action="insert" ${selectedPathNode && selectedPath.status !== "archived" ? "" : "disabled"}>插入节点</button>
                  <button class="btn btn-xs btn-danger" data-action="map-path-node-action" data-node-action="delete" ${selectedPathNode && selectedPathNodes.length > 2 && selectedPath.status !== "archived" ? "" : "disabled"}>删除节点</button>
                </span>
              </div>
              <label><span>宽度 ${Number(selectedPathNode?.width_scale ?? 1).toFixed(2)}×</span><input id="map-path-node-width" type="range" min="0.25" max="4" step="0.05" value="${Number(selectedPathNode?.width_scale ?? 1)}" ${selectedPathNode ? "" : "disabled"} /></label>
              <label><span>张力 ${Number(selectedPathNode?.tension ?? 0.5).toFixed(2)}</span><input id="map-path-node-tension" type="range" min="0" max="1" step="0.05" value="${Number(selectedPathNode?.tension ?? 0.5)}" ${selectedPathNode ? "" : "disabled"} /></label>
              <select class="form-select" id="map-path-node-segment" ${selectedPathNode ? "" : "disabled"}>${segmentTypeOptions}</select>
            </div>
          ` : ""}
        ` : ""}
      </div>

      <div class="map-edit-section" id="map-territory-section" style="display:${mapState.editorLayer === "territory" ? "" : "none"};">
        ${ctx.territoryTools || ""}
        <div class="map-tool-row"><button class="btn btn-sm ${!mapState.territoryEraseMode ? "active" : ""}" data-action="map-territory-mode" data-mode="paint">绘制</button><button class="btn btn-sm ${mapState.territoryEraseMode ? "active" : ""}" data-action="map-territory-mode" data-mode="erase">擦除</button></div>
      </div>

      <div class="map-edit-section">
        <button class="btn btn-sm" data-action="map-undo">↶ 撤销 (Ctrl+Z)</button>
        <button class="btn btn-sm" data-action="map-redo">↷ 重做</button>
        <span class="map-pending-count" id="map-pending-count">${Number(ctx.pendingCount || 0)} 个待应用变更</span>
      </div>

      <div class="map-edit-actions">
        <button class="btn btn-primary btn-sm" data-action="map-apply">应用当前图层</button>
        <button class="btn btn-sm" data-action="map-save">保存全部并退出</button>
      </div>
    </div>
  `
}

/**
 * 更新待应用变更计数显示。
 * @param {number} count
 */
export function updatePendingCount(count) {
  const el = document.getElementById("map-pending-count")
  if (el) el.textContent = `${count} 个待应用变更`
}

/**
 * 更新待绑定地点计数显示。
 * @param {number} count
 */
export function updateBindingPendingCount(count) {
  const el = document.getElementById("map-binding-pending-count")
  if (el) el.textContent = `${count} 个待绑定`
}

/**
 * 切换工具时显示/隐藏对应 section。
 * @param {string} tool brush / bucket / bind
 */
export function toggleToolSections(tool) {
  document.querySelectorAll(".map-tool-btn").forEach((btn) => btn.classList.remove("active"))
  const active = document.querySelector(`[data-action="map-tool-${tool}"]`)
  if (active) active.classList.add("active")
}

export default renderEditPanel

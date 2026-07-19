import {
  getApi,
  getAppState,
  getCloseModal,
  getEsc,
  getShowModalHtml,
  getToast,
} from "../../bridge/index.js"
import { formatMapDiagnosticInfo } from "../../../views/mapDiagnosticInfo.js"
import { mapAssetDisplay } from "../../../shared/assetDisplayState.js"
import { mapDynamicNormalizationLabel } from "../../../views/mapTimelineProjection.js"

export function createMapModalController({
  projectId,
  getMaps,
  getArchivedMaps,
  getActiveMapId,
  onCreated,
  onAssigned,
  onRestored,
  onFactStatus,
  onConfirmObservation,
  onIgnoreObservation,
  onConflictObservation,
  onUnassignObservation,
  onFocusInspector,
  onEditItem,
}) {
  const api = getApi()
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()
  let disposed = false
  let generation = 0

  const owns = (token = generation) => !disposed
    && token === generation
    && getAppState()?.currentProjectId === projectId
    && getAppState()?.currentView === "map"

  function dispose() {
    disposed = true
    generation += 1
  }

  function showCreateWorld() {
    showModalHtml("创建世界地图", `
      <div class="form-group"><label>名称 *</label><input class="form-input" id="map-create-name" maxlength="255" placeholder="如：九州世界" /></div>
      <div class="form-group"><label>尺寸</label><select class="form-select" id="map-create-size"><option value="30,20">30×20（世界地图，600 格）</option></select></div>
      <div class="form-group"><label>模板</label><select class="form-select" id="map-create-template"><option value="blank">空白</option><option value="continent">大陆型</option><option value="islands">群岛型</option></select></div>
    `, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const name = document.getElementById("map-create-name")?.value?.trim()
        if (!name) { toast("请输入地图名称", "warning"); return false }
        const [gridWidth, gridHeight] = (document.getElementById("map-create-size")?.value || "30,20").split(",").map(Number)
        const template = document.getElementById("map-create-template")?.value || "blank"
        const token = generation
        try {
          const created = await api.world.createMap({ name, map_type: "world", grid_width: gridWidth, grid_height: gridHeight, template }, projectId)
          if (!owns(token)) return false
          closeModal()
          toast("世界地图已创建", "success")
          await onCreated?.(created)
          return true
        } catch (error) {
          if (owns(token)) toast(`创建失败：${error.message || "未知错误"}`, "error")
          return false
        }
      },
    }])
  }

  function showAssign(item) {
    const maps = getMaps?.() || []
    if (!maps.length) { toast("请先创建一张地图，再分配待处理项", "warning"); return false }
    showModalHtml("分配地图待处理项", `<p>分配后将打开目标地图，并继续补全「${esc(item.target_name || item.dynamic_type || "地图建议")}」。</p><div class="form-group"><label>目标地图</label><select class="form-select" id="map-inbox-assignment-map">${maps.map((map) => `<option value="${esc(map.id)}" ${map.id === (item.map_id || getActiveMapId?.()) ? "selected" : ""}>${esc(map.name)}</option>`).join("")}</select></div>`, [{
      text: "分配并继续", class: "btn-primary", handler: async () => {
        const mapId = document.getElementById("map-inbox-assignment-map")?.value
        if (!mapId) return false
        const success = await onAssigned?.(item, mapId)
        if (success) closeModal()
        return success
      },
    }])
    return true
  }

  function showRestore(mapId) {
    const map = (getArchivedMaps?.() || []).find((item) => item.id === mapId)
    if (!map) return false
    showModalHtml("恢复归档地图", `<p>将恢复「${esc(map.name)}」及其完整子树。</p><div class="form-group"><label>恢复根名称</label><input class="form-input" id="map-restore-root-name" maxlength="255" value="${esc(map.name)}" /></div>`, [{
      text: "恢复子树", class: "btn-primary", handler: async () => {
        const rootName = document.getElementById("map-restore-root-name")?.value?.trim() || map.name
        const success = await onRestored?.(map, rootName)
        if (success) closeModal()
        return success
      },
    }])
    return true
  }

  async function copyDiagnostic(item) {
    try {
      await navigator.clipboard.writeText(formatMapDiagnosticInfo(item, { mapId: getActiveMapId?.() }))
      toast("诊断信息已复制", "success")
      return true
    } catch {
      toast("无法访问剪贴板，请检查浏览器权限", "warning")
      return false
    }
  }

  function showDynamicItem(item) {
    if (!item) return false
    const display = mapAssetDisplay(item)
    const detail = [item.type_label, item.location_label, item.spatial_anchor_label].filter(Boolean).join(" · ")
    const body = `<div class="map-object-info">
      ${detail ? `<div class="map-detail-section"><div class="map-detail-label">对象</div><div class="map-detail-value">${esc(detail)}</div></div>` : ""}
      <div class="map-detail-section"><div class="map-detail-label">时间</div><div class="map-detail-value">${esc(item.time_label || "时间未确定")}</div></div>
      <div class="map-detail-section"><div class="map-detail-label">状态</div><div class="map-detail-value">${esc(display.label)}${item.normalization_state ? ` · ${esc(mapDynamicNormalizationLabel(item.normalization_state))}` : ""}</div></div>
      <div class="map-detail-section"><div class="map-detail-label">来源</div><div class="map-detail-value">${esc(item.change_summary || item.source_summary || "暂无来源摘要")}</div></div>
      <div class="map-detail-section"><div class="map-detail-label">证据</div><div class="map-detail-value">${esc(item.evidence_text || "未提供正文证据")}</div></div>
    </div>`
    const buttons = [{ text: "修改", class: "btn-primary", handler: () => { closeModal(); return onEditItem?.(item) ?? false } }]
    if (item.item_kind === "observation") buttons.push(
      { text: "采用", class: "btn-primary", handler: () => { closeModal(); onConfirmObservation?.(item) } },
      { text: "忽略", class: "", handler: () => { closeModal(); onIgnoreObservation?.(item) } },
      { text: "标记冲突", class: "", handler: () => { closeModal(); onConflictObservation?.(item) } },
      { text: "更换地图", class: "", handler: () => { closeModal(); showAssign(item) } },
      { text: "取消分配", class: "", handler: () => { closeModal(); onUnassignObservation?.(item) } },
    )
    if (item.item_kind === "fact") buttons.push(
      { text: "回滚", class: "", handler: () => { closeModal(); onFactStatus?.(item, "rolled_back") } },
      { text: "废弃", class: "", handler: () => { closeModal(); onFactStatus?.(item, "deprecated") } },
      { text: "恢复采用", class: "btn-primary", handler: () => { closeModal(); onFactStatus?.(item, "confirmed") } },
    )
    buttons.push(
      { text: "复制诊断信息", class: "", handler: () => copyDiagnostic(item) },
      { text: "打开检查器", class: "", handler: () => { closeModal(); onFocusInspector?.(item) } },
    )
    showModalHtml(esc(item.title || item.target_name || "地图对象"), body, buttons, { size: "large" })
    return true
  }

  return { copyDiagnostic, dispose, showAssign, showCreateWorld, showDynamicItem, showRestore }
}

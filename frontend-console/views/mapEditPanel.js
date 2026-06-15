/**
 * 地图编辑侧边栏渲染 — PRD docs/PRD-动态地图功能.md §路径1 / §路径2
 *
 * 返回 HTML 字符串（由 mapView 注入 .map-edit-panel 容器）。
 * 事件绑定在 mapView._bindMapEvents 中通过 data-action 委托。
 */
import { TERRAIN_OPTIONS } from "./mapHexRenderer.js"

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

  return `
    <div class="map-edit-tools">
      <div class="map-edit-section">
        <h4>模式</h4>
        <div class="map-tool-row">
          <button class="btn btn-sm map-tool-btn active" data-action="map-tool-brush">画笔</button>
          <button class="btn btn-sm map-tool-btn" data-action="map-tool-bucket">油漆桶</button>
          <button class="btn btn-sm map-tool-btn" data-action="map-tool-bind">地点绑定</button>
          <button class="btn btn-sm map-tool-btn" data-action="map-tool-marker">标记</button>
        </div>
      </div>

      <div class="map-edit-section" id="map-terrain-section">
        <h4>地形</h4>
        <select class="form-select" id="map-terrain-select">
          ${TERRAIN_OPTIONS.map((t) => `<option value="${esc(t.value)}">${esc(t.label)}</option>`).join("")}
        </select>
      </div>

      <div class="map-edit-section" id="map-bind-section" style="display:none;">
        <h4>绑定地点</h4>
        <select class="form-select" id="map-bind-select">
          ${locOptions}
        </select>
        <label class="map-checkbox">
          <input type="checkbox" id="map-bind-center" /> 设为中心点
        </label>
        <p class="map-hint">选择地点后，点击或拖拽六边形绑定。</p>
        <span class="map-pending-count" id="map-binding-pending-count">0 个待绑定</span>
      </div>

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

      <div class="map-edit-section">
        <button class="btn btn-sm" data-action="map-undo">↶ 撤销 (Ctrl+Z)</button>
        <span class="map-pending-count" id="map-pending-count">0 个待应用变更</span>
      </div>

      <div class="map-edit-actions">
        <button class="btn btn-primary btn-sm" data-action="map-apply">应用</button>
        <button class="btn btn-sm" data-action="map-save">保存并退出编辑</button>
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
  const terrainSection = document.getElementById("map-terrain-section")
  const bindSection = document.getElementById("map-bind-section")
  const markerSection = document.getElementById("map-marker-section")
  if (terrainSection) terrainSection.style.display = (tool === "bind" || tool === "marker") ? "none" : ""
  if (bindSection) bindSection.style.display = (tool === "bind") ? "" : "none"
  if (markerSection) markerSection.style.display = (tool === "marker") ? "" : "none"

  document.querySelectorAll(".map-tool-btn").forEach((btn) => btn.classList.remove("active"))
  const active = document.querySelector(`[data-action="map-tool-${tool}"]`)
  if (active) active.classList.add("active")
}

export default renderEditPanel

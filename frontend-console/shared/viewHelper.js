/**
 * View 工具函数
 *
 * 提取所有 view 共通的 DOM 事件委托模式。
 */

/**
 * 在指定元素上绑定事件委托（data-action 模式）
 *
 * 自动处理 removeEventListener + addEventListener 循环，防止重复监听。
 *
 * @param {object} view - View 对象（用于保存 handler 引用和 this 绑定）
 * @param {Element} element - 绑定元素
 * @param {string} eventType - 事件类型（默认 "click"）
 * @param {object<string, Function>} handlerMap - action 名到 handler 的映射
 */
export function bindDelegation(view, element, eventType, handlerMap) {
  const key = `__delegation_${eventType}`
  if (element[key]) element.removeEventListener(eventType, element[key])
  element[key] = async (e) => {
    const t = e.target.closest?.("[data-action]")
    if (!t) return
    const a = t.getAttribute("data-action")
    const ctx = {
      id: t.getAttribute("data-id"),
      chapter: t.getAttribute("data-chapter"),
    }
    const handler = handlerMap[a]
    if (!handler) return
    try {
      await Promise.resolve(handler.call(view, e, t, ctx))
    } catch (err) {
      _toastDelegationError(err)
    }
  }
  element.addEventListener(eventType, element[key])
}

function _toastDelegationError(err) {
  const message = err?.message || "未知错误"
  if (typeof toast === "function") toast(`操作失败：${message}`, "error")
}

/**
 * 在 #workspace-content 上绑定 click 事件委托
 * @param {object} view
 * @param {object<string, Function>} handlerMap
 */
export function bindWorkspaceClick(view, handlerMap) {
  const el = document.getElementById("workspace-content")
  if (!el) return
  bindDelegation(view, el, "click", handlerMap)
}

function _escapeHtml(str) {
  if (str === null || str === undefined) return ""
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
}

/**
 * 渲染行内操作下拉菜单
 *
 * @param {string} menuId - 菜单唯一标识（用于 data-menu-id）
 * @param {Array<{action:string, label:string, class?:string, data?:Object}>} items - 菜单项
 * @returns {string} HTML
 */
export function renderActionMenu(menuId, items) {
  const itemHtml = items.map((item) => {
    const cls = ["action-menu-item", item.class || ""].filter(Boolean).join(" ")
    const dataAttrs = Object.entries(item.data || {})
      .map(([k, v]) => `data-${k}="${_escapeHtml(v)}"`)
      .join(" ")
    return `<button class="${_escapeHtml(cls)}" data-action="${_escapeHtml(item.action)}" ${dataAttrs}>${_escapeHtml(item.label)}</button>`
  }).join("")
  return `
    <div class="action-menu" data-menu-id="${_escapeHtml(menuId)}">
      <button class="action-menu-btn" type="button" title="更多操作">&#183;&#183;&#183;</button>
      <div class="action-menu-list">${itemHtml}</div>
    </div>
  `
}

/**
 * 绑定行内操作下拉菜单
 *
 * 为 .action-menu-btn 添加 toggle，点击外部自动关闭。
 * @param {Element} [container] - 容器，默认 #workspace-content
 */
export function bindActionMenus(container = document.getElementById("workspace-content")) {
  if (!container || typeof container.querySelectorAll !== "function") return

  container.querySelectorAll(".action-menu-btn").forEach((btn) => {
    if (btn.dataset.actionMenuBound === "true") return
    btn.dataset.actionMenuBound = "true"
    btn.addEventListener("click", (e) => {
      e.stopPropagation()
      const menu = btn.closest(".action-menu")
      const wasOpen = menu?.classList.contains("open")
      // 关闭同容器内其他菜单
      container.querySelectorAll(".action-menu.open").forEach((m) => m.classList.remove("open"))
      if (!wasOpen) menu?.classList.add("open")
    })
  })

  const closeAll = () => container.querySelectorAll(".action-menu.open").forEach((m) => m.classList.remove("open"))
  document.removeEventListener("click", closeAll)
  document.addEventListener("click", closeAll)
}

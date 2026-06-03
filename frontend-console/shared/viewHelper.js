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
  const key = `_${eventType}Delegation`
  if (view[key]) element.removeEventListener(eventType, view[key])
  view[key] = (e) => {
    const t = e.target.closest("[data-action]")
    if (!t) return
    const a = t.getAttribute("data-action")
    const ctx = {
      id: t.getAttribute("data-id"),
      chapter: t.getAttribute("data-chapter"),
    }
    const handler = handlerMap[a]
    if (handler) handler.call(view, e, t, ctx)
  }
  element.addEventListener(eventType, view[key])
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

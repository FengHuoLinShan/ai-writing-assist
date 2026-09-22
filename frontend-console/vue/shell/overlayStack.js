/**
 * overlayStack — AppShell 的唯一 overlay 根与返回栈权威（V4 U01）。
 *
 * 计划 04-FRONTEND-HIFI §4：「只有一个 overlay root……Escape 关闭当前
 * 模态，关闭后返回触发控件。」本模块以登记顺序（后开者在上）提供：
 *
 * - ``registerOverlay({ id, requestClose })``：打开时登记，返回句柄；
 *   关闭时 ``unregister()``。焦点回触发控件仍由各 overlay 自身的
 *   useModalDialog/origin 恢复逻辑负责（返回栈的"返回"语义）。
 * - ``installOverlayEscapeRouter()``：AppShell 安装一次的 document 兜底
 *   Escape 路由（bubble 层）——overlay 内部的嵌套浮层与各 overlay 自身的
 *   Escape 处理先在元素层消费；未被消费的 Escape 才关最上层已登记
 *   overlay。无登记时不干预（保留页面内非模态 Escape 的既有行为）。
 * - 旧命令式全局模态（#modal-overlay）保持既有嵌套语义：它可见时
 *   本路由不接管（useModalDialog 的 syncNestedModal 已把它当作更高层）。
 */

const overlays = []
let idSequence = 0
let tokenSequence = 0
let routerInstalled = false

function legacyGlobalModalVisible() {
  const globalOverlay = document.getElementById("modal-overlay")
  return Boolean(globalOverlay && !globalOverlay.classList.contains("hidden"))
}

export function registerOverlay({ id, requestClose }) {
  // 身份用栈管理器生成的唯一 token，展示 id 不兼任唯一身份：不同模态
  // 组件的局部 generation 完全可能拼出相同 id（modal:2），按 id 比较栈顶
  // 会认错实例（PR160-162 审查 F6）。
  const token = ++tokenSequence
  const entry = { token, id: id || `overlay-${++idSequence}`, requestClose }
  overlays.push(entry)
  return {
    get id() { return entry.id },
    token,
    unregister() {
      const index = overlays.indexOf(entry)
      if (index !== -1) overlays.splice(index, 1)
    },
    requestClose() { entry.requestClose() },
  }
}

export function overlayCount() {
  return overlays.length
}

export function topOverlay() {
  return overlays.length ? overlays[overlays.length - 1] : null
}

export function isTopOverlay(handle) {
  if (!handle) return overlays.length === 0
  return topOverlay()?.token === handle.token
}

export function closeTopOverlay() {
  const top = topOverlay()
  if (!top) return false
  top.requestClose()
  return true
}

export function installOverlayEscapeRouter() {
  if (routerInstalled || typeof document === "undefined") return
  routerInstalled = true
  // bubble 兜底而非 capture 权威：overlay 内部的嵌套浮层（菜单/弹层）与
  // 各 overlay 自身的 Escape 处理先在元素层消费并 stopPropagation——
  // 只有未被任何层消费的 Escape 才落到栈路由，关闭最上层已登记 overlay。
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented) return
    if (legacyGlobalModalVisible()) return
    if (!closeTopOverlay()) return
    // 终结消费：本路由先于旧 document 快捷键处理器注册；preventDefault
    // 标记已消费，stopImmediatePropagation 阻止同节点上后注册的
    // useShellShortcuts 把同一次 Escape 再解释成第二个动作（返回父视图）。
    event.preventDefault()
    event.stopImmediatePropagation()
  })
}

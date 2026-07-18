/**
 * Vue bridge — Vue 组件访问既有 vanilla 基建的唯一入口。
 *
 * 既有基建以 window 全局存在：
 * - window.api（api.js）、window.appState + window.onStateChange（state.js）
 * - window.router（router.js）、window.toast（ui/toast.js）
 * - window.tryMigrateLocalAuthorPreferences（state.js）
 *
 * Vue 组件只允许经本模块取用，禁止引用裸全局；单测通过
 * setBridgeOverrides() 注入替身（生产代码不 import/检测 Mock）。
 */
import { getCurrentScope, onScopeDispose, readonly, ref } from "vue"

const _overrides = {}

/** 测试专用：注入 bridge 替身，键为 api/router/state/toast/confirm/onStateChange 等。 */
export function setBridgeOverrides(overrides = {}) {
  Object.assign(_overrides, overrides)
}

export function resetBridgeOverrides() {
  for (const key of Object.keys(_overrides)) delete _overrides[key]
}

export function getApi() {
  return _overrides.api ?? globalThis.api
}

export function getRouter() {
  return _overrides.router ?? globalThis.router
}

export function getAppState() {
  return _overrides.state ?? globalThis.appState
}

/** toast(message, type) — 全局不可用时降级为空操作，避免阻塞交互。 */
export function getToast() {
  const toast = _overrides.toast ?? globalThis.toast
  return typeof toast === "function" ? toast : () => {}
}

/** confirm(message) — 与 vanilla 行为一致走原生确认框；测试可注入替身。 */
export function getConfirm() {
  const confirmFn = _overrides.confirm ?? globalThis.confirm
  return typeof confirmFn === "function" ? (message) => confirmFn(message) : () => true
}

/**
 * showModalHtml(title, htmlString, buttons, options) — 外壳全局模态框。
 * 内容 HTML 必须先用 esc() 处理动态片段（README「安全与契约」既有豁免模式，
 * 不属于 Vue 模板 v-html 场景）；外壳 modal 的 Vue 化留待 Phase 6。
 */
export function getShowModalHtml() {
  const fn = _overrides.showModalHtml ?? globalThis.showModalHtml
  return typeof fn === "function" ? fn : () => {}
}

/** confirmAction(message, onConfirm, confirmText) — 外壳全局二次确认。 */
export function getConfirmAction() {
  const fn = _overrides.confirmAction ?? globalThis.confirmAction
  return typeof fn === "function" ? fn : () => {}
}

export function getCloseModal() {
  const fn = _overrides.closeModal ?? globalThis.closeModal
  return typeof fn === "function" ? fn : () => {}
}

/** esc(value) — HTML 转义（仅供 modal 内容等字符串拼装场景；Vue 模板用 {{ }} 自动转义）。 */
export function getEsc() {
  const fn = _overrides.esc ?? globalThis.esc
  return typeof fn === "function" ? fn : (value) => String(value ?? "")
}

/** window.errorLog — 前端错误日志（bible 投影 409 冲突处理读 _lastApiError）。 */
export function getErrorLog() {
  return _overrides.errorLog ?? globalThis.errorLog ?? null
}

/** D20-D22: localStorage 旧作者偏好一次性迁移，失败仅告警不阻断页面加载。 */
export async function tryMigrateLocalAuthorPreferences(projectId) {
  const migrate = _overrides.tryMigrateLocalAuthorPreferences
    ?? globalThis.tryMigrateLocalAuthorPreferences
  if (typeof migrate !== "function") return
  try {
    await migrate(projectId)
  } catch (err) {
    console.warn("本地偏好迁移失败:", err)
  }
}

/**
 * 把 appState 的单个键桥接为随 onStateChange 同步的只读 ref。
 * 组件作用域内自动退订；无订阅机制时退化为一次性快照。
 */
export function useStateKey(key) {
  const source = getAppState()
  const value = ref(source ? source[key] : null)
  const subscribe = _overrides.onStateChange ?? globalThis.onStateChange
  if (typeof subscribe === "function") {
    const off = subscribe((changedKey, newValue) => {
      if (changedKey === key) value.value = newValue
    })
    if (getCurrentScope()) onScopeDispose(off)
  }
  return readonly(value)
}

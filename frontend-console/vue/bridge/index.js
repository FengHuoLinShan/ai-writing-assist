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

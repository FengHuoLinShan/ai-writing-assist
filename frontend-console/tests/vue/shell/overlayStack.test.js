import { afterEach, beforeEach, expect, it, vi } from "vitest"

/**
 * U01 overlay 栈：唯一 overlay 根与返回栈权威。
 * 计划 04-FRONTEND-HIFI §4——Escape 只关最上层已登记 overlay；旧命令式
 * 全局模态可见时不接管；无登记时不干预既有行为。
 *
 * overlayStack 是模块级单例、Escape 路由整个文档只装一次（生产语义）。
 * 测试共用该单例：每个用例登记的句柄在 afterEach 全部退栈。
 */

import {
  closeTopOverlay,
  installOverlayEscapeRouter,
  isTopOverlay,
  overlayCount,
  registerOverlay,
  topOverlay,
} from "../../../vue/shell/overlayStack.js"

let handles = []

function track(entry) {
  handles.push(entry)
  return entry
}

function pressEscape() {
  const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })
  document.dispatchEvent(event)
  return event
}

beforeEach(() => {
  installOverlayEscapeRouter()
})

afterEach(() => {
  for (const handle of handles.splice(0)) handle.unregister()
  document.body.innerHTML = ""
})

it("closes only the top-most registered overlay on Escape", () => {
  const first = vi.fn()
  const second = vi.fn()
  track(registerOverlay({ id: "a", requestClose: first }))
  track(registerOverlay({ id: "b", requestClose: second }))

  const event = pressEscape()
  expect(second).toHaveBeenCalledTimes(1)
  expect(first).not.toHaveBeenCalled()
  expect(event.defaultPrevented).toBe(true)
})

it("closing the top keeps the lower overlay open; next Escape closes it", () => {
  const lower = vi.fn()
  const upper = vi.fn()
  track(registerOverlay({ id: "lower", requestClose: lower }))
  const upperHandle = track(registerOverlay({ id: "upper", requestClose: upper }))

  pressEscape()
  expect(upper).toHaveBeenCalledTimes(1)
  expect(lower).not.toHaveBeenCalled()

  upperHandle.unregister()
  pressEscape()
  expect(lower).toHaveBeenCalledTimes(1)
})

it("does not intercept Escape when nothing is registered", () => {
  const event = pressEscape()
  expect(event.defaultPrevented).toBe(false)
})

it("yields to the legacy imperative global modal when visible", () => {
  const overlay = document.createElement("div")
  overlay.id = "modal-overlay"
  document.body.appendChild(overlay)

  const close = vi.fn()
  track(registerOverlay({ id: "a", requestClose: close }))

  overlay.classList.add("hidden")
  const hiddenEvent = pressEscape()
  expect(close).toHaveBeenCalledTimes(1)
  expect(hiddenEvent.defaultPrevented).toBe(true)

  overlay.classList.remove("hidden")
  const visibleEvent = pressEscape()
  expect(close).toHaveBeenCalledTimes(1) // 全局模态可见：本路由不接管
  expect(visibleEvent.defaultPrevented).toBe(false)
})

it("unregister removes the entry and isTopOverlay reflects stack order", () => {
  const handle = track(registerOverlay({ id: "solo", requestClose: () => {} }))
  expect(overlayCount()).toBeGreaterThanOrEqual(1)
  expect(isTopOverlay(handle)).toBe(true)
  expect(topOverlay().id).toBe("solo")

  const upper = track(registerOverlay({ id: "upper", requestClose: () => {} }))
  expect(isTopOverlay(handle)).toBe(false)
  expect(isTopOverlay(upper)).toBe(true)

  handle.unregister()
  upper.unregister()
  expect(isTopOverlay(null)).toBe(true)
})

it("identifies registered instances by unique token, not display id (PR160-162 F6)", () => {
  // 不同模态组件的局部 generation 可能拼出相同展示 id（两个 modal:2）；
  // 栈顶身份必须按注册实例判定，只有后注册者为栈顶。
  const lowerClose = vi.fn()
  const lower = track(registerOverlay({ id: "modal:2", requestClose: lowerClose }))
  const upper = track(registerOverlay({ id: "modal:2", requestClose: () => {} }))
  expect(isTopOverlay(lower)).toBe(false)
  expect(isTopOverlay(upper)).toBe(true)
  expect(lower.token).not.toBe(upper.token)

  upper.unregister()
  expect(isTopOverlay(lower)).toBe(true)
  // 相同 id 的两个实例只有一个在栈内时，栈顶关闭仍指向正确实例。
  pressEscape()
  expect(lowerClose).toHaveBeenCalledTimes(1)
})

it("terminal consumption blocks later document listeners for the same Escape (PR160-162 F8)", () => {
  const close = vi.fn()
  const entry = track(registerOverlay({ id: "cmd", requestClose: close }))
  // 旧 useShellShortcuts 在 mounted 后注册——晚于栈路由；同一次按键不得
  // 再被解释为第二个动作（如返回父视图）。
  const legacy = vi.fn()
  document.addEventListener("keydown", legacy)
  pressEscape()
  expect(close).toHaveBeenCalledTimes(1)
  expect(legacy).not.toHaveBeenCalled()
  document.removeEventListener("keydown", legacy)
  entry.unregister()

  // 栈内无登记（未消费）时事件照常到达后续 document 监听器。
  const idle = vi.fn()
  document.addEventListener("keydown", idle)
  const event = pressEscape()
  expect(idle).toHaveBeenCalledTimes(1)
  expect(event.defaultPrevented).toBe(false)
  document.removeEventListener("keydown", idle)
})

it("closeTopOverlay reports whether anything closed", () => {
  // 栈内可能残留其他用例句柄的防御不存在——closeTop 只关当前最上层。
  const close = vi.fn()
  track(registerOverlay({ id: "mine", requestClose: close }))
  expect(closeTopOverlay()).toBe(true)
  expect(close).toHaveBeenCalledTimes(1)
})

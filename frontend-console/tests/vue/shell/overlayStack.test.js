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

it("closeTopOverlay reports whether anything closed", () => {
  // 栈内可能残留其他用例句柄的防御不存在——closeTop 只关当前最上层。
  const close = vi.fn()
  track(registerOverlay({ id: "mine", requestClose: close }))
  expect(closeTopOverlay()).toBe(true)
  expect(close).toHaveBeenCalledTimes(1)
})

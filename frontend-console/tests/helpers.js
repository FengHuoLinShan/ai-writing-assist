import { vi } from "vitest"

/**
 * 将全局 state 的公共字段重置为默认值。
 * 可在 beforeEach 中统一调用，避免各测试文件重复赋值。
 */
export function resetState(overrides = {}) {
  const defaults = {
    currentProjectId: null,
    currentProject: null,
    currentSubView: null,
    selectedItem: null,
    selectedItems: [],
    mode: "NORMAL",
    projects: [],
    loading: false,
    error: null,
    toast: null,
    backendConnected: true,
    cache: {},
    viewStates: {},
  }
  if (!globalThis.state) {
    globalThis.state = {}
  }
  Object.assign(globalThis.state, defaults, overrides)
}

/** 清空 document.body，避免测试间 DOM 互相污染。 */
export function clearDocument() {
  if (typeof document !== "undefined") {
    document.body.innerHTML = ""
  }
}

/** clearDocument 的别名，兼容不同命名习惯。 */
export const resetDocument = clearDocument

/**
 * 创建一个可复用的 Canvas 2D mock context。
 *
 * Options:
 * - captureAlpha: 是否记录 globalAlpha 变更（默认 true）
 * - recordCalls: 是否记录常用绘图调用次数与参数（默认 false）
 * - methods: 额外需要 mock 的方法名数组
 */
export function createCanvasMock(options = {}) {
  const { captureAlpha = true, recordCalls = false, methods = [] } = options

  const ctx = {
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    closePath: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    arc: vi.fn(),
    fillText: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    setLineDash: vi.fn(),
  }

  for (const method of methods) {
    if (!(method in ctx)) {
      ctx[method] = vi.fn()
    }
  }

  if (recordCalls) {
    const calls = {
      beginPath: 0,
      moveTo: [],
      lineTo: [],
      closePath: 0,
      fill: 0,
      stroke: 0,
      arc: 0,
      fillText: [],
      save: 0,
      restore: 0,
      setLineDash: [],
      alphaLog: [],
      fillStyle: "",
      strokeStyle: "",
      lineWidth: 0,
    }
    ctx._calls = calls
    ctx.beginPath = () => { calls.beginPath++ }
    ctx.moveTo = (x, y) => { calls.moveTo.push([x, y]) }
    ctx.lineTo = (x, y) => { calls.lineTo.push([x, y]) }
    ctx.closePath = () => { calls.closePath++ }
    ctx.fill = () => { calls.fill++ }
    ctx.stroke = () => { calls.stroke++ }
    ctx.arc = () => { calls.arc++ }
    ctx.fillText = (text, ...rest) => { calls.fillText.push([text, ...rest]) }
    ctx.save = () => { calls.save++ }
    ctx.restore = () => { calls.restore++ }
    ctx.setLineDash = (dash) => { calls.setLineDash.push(dash) }
    Object.defineProperty(ctx, "fillStyle", {
      get() { return calls.fillStyle },
      set(v) { calls.fillStyle = v },
    })
    Object.defineProperty(ctx, "strokeStyle", {
      get() { return calls.strokeStyle },
      set(v) { calls.strokeStyle = v },
    })
    Object.defineProperty(ctx, "lineWidth", {
      get() { return calls.lineWidth },
      set(v) { calls.lineWidth = v },
    })
    Object.defineProperty(ctx, "globalAlpha", {
      get() { return calls.globalAlpha },
      set(v) { calls.alphaLog.push(v); calls.globalAlpha = v },
    })
  } else if (captureAlpha) {
    const alphaLog = []
    Object.defineProperty(ctx, "globalAlpha", {
      get() { return alphaLog[alphaLog.length - 1] },
      set(v) { alphaLog.push(v) },
    })
    ctx.alphaLog = alphaLog
  } else {
    Object.defineProperty(ctx, "globalAlpha", {
      get() { return 1 },
      set() {},
    })
  }

  return ctx
}

/**
 * 让 confirmAction 的 mock 立即执行确认回调，
 * 常用于测试删除、强制创建等需要二次确认的流程。
 */
export function autoConfirm() {
  confirmAction.mockImplementation((_message, onConfirm) => onConfirm())
}

/**
 * 从最近一次 showModal 调用中提取按钮 handler。
 * 默认取第 0 次调用、第 0 个按钮。
 */
export function captureModalHandler({ callIndex = 0, buttonIndex = 0 } = {}) {
  const call = showModal.mock.calls[callIndex]
  if (!call) return null
  const buttons = call[2]
  return buttons?.[buttonIndex]?.handler ?? null
}

/**
 * 将对象方法 stub 为空实现，测试结束后需自行 restore。
 */
export function stubMethod(obj, name) {
  return vi.spyOn(obj, name).mockImplementation(() => {})
}

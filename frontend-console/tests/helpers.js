import { vi } from "vitest"

export const defaultTestState = Object.freeze({
  currentProjectId: null,
  currentProject: null,
  currentView: "project",
  currentSubView: null,
  selectedItem: null,
  selectedItems: [],
  mode: "NORMAL",
  projects: [],
  viewStates: {},
  loading: false,
  error: null,
  toast: null,
  backendConnected: true,
  cache: {},
})

/**
 * 将全局 state 的公共字段重置为默认值。
 * 可在 beforeEach 中统一调用，避免各测试文件重复赋值。
 */
export function resetState(overrides = {}) {
  if (!globalThis.state) {
    globalThis.state = {}
  }
  for (const key of Object.keys(globalThis.state)) {
    delete globalThis.state[key]
  }
  Object.assign(globalThis.state, structuredClone(defaultTestState), overrides)
}

/** 清空 document.body，避免测试间 DOM 互相污染。 */
export function clearDocument() {
  if (typeof document !== "undefined") {
    document.body.innerHTML = ""
  }
}

/**
 * 恢复每个 Vitest 用例共享的完整浏览器环境。
 *
 * `clearAllMocks()` 只清理调用历史，保留 setup.js 中 API/router mock 的默认
 * implementation。这样测试可以在自己的 beforeEach 中覆盖行为，又不会把前一个
 * 用例的调用、DOM、storage、route 或临时 state 带到下一个用例。
 */
export function resetTestEnvironment(stateOverrides = {}) {
  vi.useRealTimers()
  vi.clearAllMocks()
  if (!globalThis.__vitestDefaultState || globalThis.state === globalThis.__vitestDefaultState) {
    resetState(stateOverrides)
  }
  clearDocument()

  if (typeof localStorage !== "undefined") localStorage.clear()
  if (typeof sessionStorage !== "undefined") sessionStorage.clear()

  globalThis.router?._resetTestState?.()
  if (typeof window !== "undefined") {
    try {
      window.history.replaceState(null, "", "/")
    } catch {
      window.location.hash = ""
    }
  }
}

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

/** 将 HTML 字符串渲染到脱离页面的容器，便于区域化断言。 */
export function renderHtml(html) {
  const container = document.createElement("div")
  container.innerHTML = html
  return container
}

/** 读取最近一次 showModal 调用，返回具名字段而不是 mock 调用下标。 */
export function latestModal() {
  const call = showModal.mock.calls.at(-1)
  if (!call) return null
  const [title, body, buttons = []] = call
  return { title, body, buttons }
}

/**
 * 从 showModal mock 调用中提取 body 的 HTML 字符串。
 * 兼容字符串、{ html: string } 以及 HTMLElement。
 */
export function modalHtmlFromCall(call) {
  const body = call?.[1]
  if (body && typeof body === "object" && typeof body.html === "string") return body.html
  return body
}

/** 读取最近一次 showModal 调用的 HTML body。 */
export function latestModalHtml() {
  return modalHtmlFromCall(showModal.mock.calls.at(-1))
}

/** 按用户可见按钮文案触发最近一次 modal action。 */
export async function clickModalButtonByText(text) {
  const modal = latestModal()
  const action = modal?.buttons.find((button) => button.text === text)
  if (!action) {
    const labels = modal?.buttons.map((button) => button.text).join(", ") || "无按钮"
    throw new Error(`未找到 modal 按钮 "${text}"。可用按钮：${labels}`)
  }
  return action.handler?.()
}

/** 断言默认可见 UI 没有泄露技术 ID，并在失败时列出具体 ID。 */
export function expectNoTechnicalIds(container, ids) {
  const text = container?.textContent || ""
  const leaked = ids.filter((id) => id && text.includes(id))
  if (leaked.length > 0) {
    throw new Error(`用户可见文本泄露技术 ID：${leaked.join(", ")}`)
  }
}

function overlap(a, b) {
  return !(
    a.x + a.width <= b.x
    || b.x + b.width <= a.x
    || a.y + a.height <= b.y
    || b.y + b.height <= a.y
  )
}

function describeBox(item) {
  const box = item.box
  return `${item.label || item.text || item.itemId || "未命名"} `
    + `(${box.x},${box.y},${box.width}x${box.height})`
}

/** 断言布局项不重叠，失败时输出两个冲突项的标签和 box。 */
export function expectNoOverlaps(items) {
  for (let i = 0; i < items.length; i += 1) {
    for (let j = i + 1; j < items.length; j += 1) {
      if (overlap(items[i].box, items[j].box)) {
        throw new Error(`布局项重叠：${describeBox(items[i])} overlaps ${describeBox(items[j])}`)
      }
    }
  }
}

/**
 * 将对象方法 stub 为空实现，测试结束后需自行 restore。
 */
export function stubMethod(obj, name) {
  return vi.spyOn(obj, name).mockImplementation(() => {})
}

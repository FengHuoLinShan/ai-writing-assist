import { afterEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import RpAdaptiveConfirmPopover from "../../../vue/views/interaction/RpAdaptiveConfirmPopover.vue"
import {
  calculateAdaptivePopoverPlacement,
  readVisualViewportRect,
} from "../../../vue/views/interaction/adaptivePopoverPlacement.js"

const originalVisualViewport = Object.getOwnPropertyDescriptor(
  globalThis,
  "visualViewport",
)

function rect(left, top, width, height) {
  return {
    bottom: top + height,
    height,
    left,
    right: left + width,
    top,
    width,
    x: left,
    y: top,
  }
}

async function settlePosition() {
  await flushPromises()
  const requestFrame = globalThis.requestAnimationFrame
    || ((callback) => setTimeout(callback, 0))
  await new Promise((resolve) => requestFrame(() => resolve()))
  await flushPromises()
}

afterEach(() => {
  if (originalVisualViewport) {
    Object.defineProperty(globalThis, "visualViewport", originalVisualViewport)
  } else {
    delete globalThis.visualViewport
  }
  document.body.innerHTML = ""
  vi.restoreAllMocks()
})

describe("RP 自适应确认框定位", () => {
  it("底部空间不足时弹到触发按钮上方", () => {
    const result = calculateAdaptivePopoverPlacement({
      anchorRect: rect(12, 780, 100, 44),
      popoverRect: rect(0, 0, 360, 120),
      viewportRect: rect(0, 0, 390, 844),
    })

    expect(result.placement).toBe("top")
    expect(result.top).toBe(652)
    expect(result.top + 120).toBeLessThanOrEqual(832)
  })

  it("上方靠近粘性标题时选择下方，并在窄屏内水平夹紧", () => {
    const result = calculateAdaptivePopoverPlacement({
      anchorRect: rect(300, 60, 60, 40),
      popoverRect: rect(0, 0, 240, 100),
      viewportRect: rect(0, 40, 390, 500),
    })

    expect(result.placement).toBe("bottom")
    expect(result.top).toBe(108)
    expect(result.left).toBe(138)
    expect(result.left + result.width).toBeLessThanOrEqual(378)
  })

  it("按 Safari visual viewport 避开地址栏、软键盘和移出可视区的锚点", () => {
    const viewport = readVisualViewportRect({
      height: 360,
      offsetLeft: 0,
      offsetTop: 120,
      width: 390,
    })
    const result = calculateAdaptivePopoverPlacement({
      anchorRect: rect(120, 700, 100, 44),
      popoverRect: rect(0, 0, 320, 160),
      viewportRect: viewport,
    })

    expect(viewport).toEqual({
      bottom: 480,
      height: 360,
      left: 0,
      right: 390,
      top: 120,
      width: 390,
    })
    expect(result.placement).toBe("top")
    expect(result.top).toBeGreaterThanOrEqual(132)
    expect(result.top + 160).toBeLessThanOrEqual(468)
  })

  it("两边都放不下时选择空间较大的一侧并限制内部最大高度", () => {
    const result = calculateAdaptivePopoverPlacement({
      anchorRect: rect(100, 150, 100, 30),
      popoverRect: rect(0, 0, 360, 400),
      viewportRect: rect(0, 0, 320, 300),
    })

    expect(result.placement).toBe("top")
    expect(result.maxHeight).toBe(130)
    expect(result.width).toBe(296)
    expect(result.left).toBe(12)
  })

  it("监听 visualViewport 变化重新选向，并在关闭后恢复触发点焦点", async () => {
    const visualViewport = new EventTarget()
    Object.assign(visualViewport, {
      height: 500,
      offsetLeft: 0,
      offsetTop: 0,
      width: 390,
    })
    Object.defineProperty(globalThis, "visualViewport", {
      configurable: true,
      value: visualViewport,
    })

    const anchor = document.createElement("button")
    anchor.textContent = "看海模式"
    document.body.append(anchor)
    let anchorRect = rect(120, 430, 100, 44)
    anchor.getBoundingClientRect = () => anchorRect
    const nativeRect = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockImplementation(function getBoundingClientRect() {
        if (this.classList.contains("rp-adaptive-confirm")) {
          return rect(0, 0, 320, 128)
        }
        return nativeRect.call(this)
      })

    const host = document.createElement("div")
    document.body.append(host)
    const wrapper = mount(RpAdaptiveConfirmPopover, {
      attachTo: host,
      props: {
        anchor,
        confirmText: "开始看海",
        id: "placement-test",
        message: "会持续使用模型额度。",
        open: true,
      },
    })
    await settlePosition()

    const layer = document.querySelector(".rp-adaptive-confirm")
    expect(layer.dataset.placement).toBe("top")
    expect(layer.parentElement).toBe(document.body)
    expect(document.activeElement.textContent).toBe("开始看海")

    anchorRect = rect(120, 30, 100, 44)
    visualViewport.dispatchEvent(new Event("resize"))
    await settlePosition()
    expect(layer.dataset.placement).toBe("bottom")

    document.querySelector(".rp-adaptive-confirm__actions button").click()
    expect(wrapper.emitted("close")).toHaveLength(1)
    await wrapper.setProps({ open: false })
    await flushPromises()
    expect(document.activeElement).toBe(anchor)
    wrapper.unmount()
  })
})

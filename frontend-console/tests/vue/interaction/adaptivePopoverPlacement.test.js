import { afterEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import RpAdaptiveConfirmPopover from "../../../vue/views/interaction/RpAdaptiveConfirmPopover.vue"
import { calculateAdaptivePopoverPlacement } from "../../../vue/views/interaction/adaptivePopoverPlacement.js"

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

  it("视口变化不丢失确认焦点，关闭后恢复触发点焦点", async () => {
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

    expect(document.querySelector("[role=alertdialog]").textContent).toContain("会持续使用模型额度")


    expect(document.activeElement.textContent).toBe("开始看海")

    anchorRect = rect(120, 30, 100, 44)
    visualViewport.dispatchEvent(new Event("resize"))
    await settlePosition()

    document.querySelector(".rp-adaptive-confirm__actions button").click()
    expect(wrapper.emitted("close")).toHaveLength(1)
    await wrapper.setProps({ open: false })
    await flushPromises()
    expect(document.activeElement).toBe(anchor)
    wrapper.unmount()
  })

  it("两侧空间都极小时保留最小可交互高度", () => {
    const result = calculateAdaptivePopoverPlacement({
      anchorRect: rect(120, 80, 100, 44),
      popoverRect: rect(0, 0, 320, 128),
      viewportRect: { left: 0, top: 0, right: 390, bottom: 200, width: 390, height: 200 },
    })

    // 视口 200px 高、锚点居中：上下可用空间都远小于弹窗高度。
    expect(result.spaceAbove).toBeLessThan(128)
    expect(result.spaceBelow).toBeLessThan(128)
    expect(result.maxHeight).toBe(Math.min(160, 200 - 24))
    expect(result.top + Math.min(128, result.maxHeight)).toBeLessThanOrEqual(200 - 12)
  })
})

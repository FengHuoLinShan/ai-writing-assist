import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import OutlineHeader from "../../../vue/views/outline/components/OutlineHeader.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

describe("OutlineHeader", () => {
  beforeEach(() => {
    setBridgeOverrides({
      state: { currentProject: { id: "p1", title: "测试作品" } },
      router: { navigate() {} },
    })
  })

  afterEach(() => resetBridgeOverrides())

  it.each([
    ["threads", "剧情线操作", "create-thread", "ai-create-plot-thread", "从正文提取剧情线"],
    ["arcs", "篇章操作", "create-arc", "ai-create-outline-arc", "从正文整理篇章"],
  ])("keeps %s creation visible and puts maintenance tools in one disclosure", (subView, label, createAction, aiAction, extractLabel) => {
    const wrapper = mount(OutlineHeader, { props: { subView } })
    const actions = wrapper.get(`[aria-label="${label}"]`)
    const directButtons = Array.from(actions.element.children).filter((element) => element.matches("button"))

    expect(directButtons).toHaveLength(2)
    expect(actions.get(`[data-action="${createAction}"]`).classes()).toContain("btn-primary")
    expect(actions.get(`[data-action="${aiAction}"]`).classes()).not.toContain("btn-primary")
    expect(actions.get(".outline-structure-tools > summary").text()).toBe("分析与整理")
    expect(actions.get('[data-action="analyze-outline"]').text()).toBe("AI 分析大纲")
    expect(actions.get('[data-action="plot-structure-auto-extract"]').text()).toBe(extractLabel)
    expect(actions.find('[data-role="smart-dedup-action"]').exists()).toBe(true)
  })

  it("closes the maintenance disclosure after an injected action runs", () => {
    const wrapper = mount(OutlineHeader, { props: { subView: "threads" } })
    const details = wrapper.get(".outline-structure-tools")
    const injectedButton = document.createElement("button")
    details.get('[data-role="smart-dedup-action"]').element.append(injectedButton)
    details.element.open = true

    injectedButton.click()

    expect(details.element.open).toBe(false)
  })

  it("篇章审阅页只保留返回篇章入口", async () => {
    const replace = vi.fn()
    setBridgeOverrides({
      state: { currentProject: { id: "p1", title: "测试作品" } },
      router: { replace, getCurrentQuery: () => new URLSearchParams("review=ai&status=draft") },
    })
    const wrapper = mount(OutlineHeader, { props: { subView: "arcs", reviewMode: true } })

    expect(wrapper.text()).toContain("篇章")
    expect(wrapper.find('[data-action="create-arc"]').exists()).toBe(false)
    await wrapper.get('[data-action="close-outline-generate-preview"]').trigger("click")
    expect(replace).toHaveBeenCalledWith("outline", "arcs", expect.any(URLSearchParams))
    expect(replace.mock.calls[0][2].get("review")).toBeNull()
  })

  it("场景审阅页只保留返回场景入口", async () => {
    const replace = vi.fn()
    setBridgeOverrides({
      state: { currentProject: { id: "p1", title: "测试作品" } },
      router: { replace, getCurrentQuery: () => new URLSearchParams("review=ai&scene_id=s1") },
    })
    const wrapper = mount(OutlineHeader, { props: { subView: "scenes", reviewMode: true } })

    expect(wrapper.get('[data-action="close-outline-generate-preview"]').text()).toBe("返回场景")
    expect(wrapper.find('[data-action="ai-create-planned-scene"]').exists()).toBe(false)
    await wrapper.get('[data-action="close-outline-generate-preview"]').trigger("click")
    expect(replace).toHaveBeenCalledWith("outline", "scenes", expect.any(URLSearchParams))
    expect(replace.mock.calls[0][2].get("review")).toBeNull()
    expect(replace.mock.calls[0][2].get("scene_id")).toBe("s1")
  })
})

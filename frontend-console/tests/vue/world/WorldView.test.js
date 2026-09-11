import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { worldSession } from "../../../vue/views/world/worldSession.js"
import WorldView from "../../../vue/views/world/WorldView.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

let navigate

beforeEach(() => {
  document.body.innerHTML = '<div id="sidebar-context-slot"></div>'
  navigate = vi.fn()
  setBridgeOverrides({ state: { currentProjectId: "p1", currentProject: { title: "雾港" } }, router: { navigate, commitCurrentQuery: vi.fn() } })
})

afterEach(async () => {
  await vi.dynamicImportSettled()
  resetBridgeOverrides()
})

describe("WorldView 动态工具卡", () => {
  it("列表页整理进度入口就地展开而不跳到写作", async () => {
    worldSession.autoExtractOpen = false
    const wrapper = mount(WorldView, { props: { projectId: "p1", subView: "objects" }, global: { stubs: { WorldObjectsTab: true, OwnerAiDrawer: true } } })
    await wrapper.get('[data-action="toggle-extract"]').trigger('click')
    expect(worldSession.autoExtractOpen).toBe(true)
    expect(navigate).not.toHaveBeenCalled()
    worldSession.autoExtractOpen = false
    wrapper.unmount()
  })

  it("关系页提供关系上下文动作", async () => {
    const wrapper = mount(WorldView, {
      props: { projectId: "p1", subView: "relations", reviewCounts: { objects: 2, aliases: 3, relations: 4 } },
      global: { stubs: { WorldRelationsTab: true, OwnerAiDrawer: true } },
    })
    const tools = document.querySelector("#sidebar-context-slot")
    expect(tools.textContent).toContain("新建关系")
    expect(tools.textContent).toContain("待决定关系")
    expect(tools.textContent).toContain("AI 工具")

    tools.querySelector("[data-action='world-tool-review-relations']").click()
    expect(navigate).toHaveBeenCalledWith("world", "review", true, expect.any(URLSearchParams))
    wrapper.unmount()
  })

  it("需要决定页将分类计数交给页内队列，不重复侧栏导航", () => {
    const wrapper = mount(WorldView, {
      props: { projectId: "p1", subView: "review", reviewSubView: "review", reviewCounts: { objects: 2, aliases: 3, relations: 4 } },
      global: { stubs: { WorldReviewTab: { name: "WorldReviewTab", props: ["reviewCounts"], template: "<div />" }, OwnerAiDrawer: true } },
    })
    const tools = document.querySelector("#sidebar-context-slot")
    expect(wrapper.findComponent({ name: "WorldReviewTab" }).props("reviewCounts")).toEqual({ objects: 2, aliases: 3, relations: 4 })
    expect(tools.textContent).toContain("返回资料库")
    expect(tools.querySelector('[data-action="world-tool-review-objects"]')).toBeNull()
    wrapper.unmount()
  })
})

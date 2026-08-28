import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import WorldView from "../../../vue/views/world/WorldView.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

let navigate

beforeEach(() => {
  document.body.innerHTML = '<div id="sidebar-context-slot"></div>'
  navigate = vi.fn()
  setBridgeOverrides({ state: { currentProjectId: "p1", currentProject: { title: "雾港" } }, router: { navigate, commitCurrentQuery: vi.fn() } })
})

afterEach(() => resetBridgeOverrides())

describe("WorldView 动态工具卡", () => {
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

  it("需要决定页按对象、别名和关系展示准确计数", () => {
    const wrapper = mount(WorldView, {
      props: { projectId: "p1", subView: "review", reviewSubView: "review", reviewCounts: { objects: 2, aliases: 3, relations: 4 } },
      global: { stubs: { WorldReviewTab: true, OwnerAiDrawer: true } },
    })
    const tools = document.querySelector("#sidebar-context-slot")
    expect(tools.textContent).toContain("对象2")
    expect(tools.textContent).toContain("别名3")
    expect(tools.textContent).toContain("关系4")
    wrapper.unmount()
  })
})

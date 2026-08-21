import { afterEach, describe, expect, it, vi, beforeEach } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const loadGenerate = vi.hoisted(() => vi.fn())
vi.mock("../../../vue/generateIsland.js", () => ({ loadGenerate }))
vi.mock("../../../vue/views/generate/GenerateView.vue", () => ({
  default: { template: '<div data-embedded-generate>生成工作台</div>' },
}))
vi.mock("../../../vue/views/rag/RagSearchView.vue", () => ({
  default: { template: '<div data-embedded-search>查找资料</div>' },
}))

import OwnerAiDrawer from "../../../vue/components/OwnerAiDrawer.vue"

describe("OwnerAiDrawer", () => {
  let router

  beforeEach(() => {
    router = { navigate: vi.fn(), getCurrentQuery: vi.fn(() => new URLSearchParams()) }
    setBridgeOverrides({ state: { currentProjectId: "p1" }, router, toast: vi.fn() })
    loadGenerate.mockReset()
    loadGenerate.mockResolvedValue({ projectId: "p1", tab: "world", preset: "world_core", sessionKey: "owner-session", initialSession: {} })
  })

  it("embeds the existing world and task generation workbench without routing away", async () => {
    const wrapper = mount(OwnerAiDrawer, { props: { open: true, owner: "world", projectId: "p1" } })
    await flushPromises()

    expect(loadGenerate).toHaveBeenCalledWith(expect.objectContaining({ tab: "world" }))
    expect(wrapper.find("[data-embedded-generate]").exists()).toBe(true)
    expect(router.navigate).not.toHaveBeenCalled()

    await wrapper.get('[data-action="owner-task-context"]').trigger("click")
    await flushPromises()
    expect(loadGenerate).toHaveBeenLastCalledWith(expect.objectContaining({ tab: "task" }))
    expect(wrapper.find("[data-embedded-generate]").exists()).toBe(true)
    expect(router.navigate).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("calls the writing controller directly and embeds Search for evidence", async () => {
    const generateDraft = vi.fn()
    const wrapper = mount(OwnerAiDrawer, {
      props: {
        open: true,
        owner: "writing",
        projectId: "p1",
        sceneId: "scene-1",
        writingActions: { generateDraft },
      },
    })
    await wrapper.get('[data-action="owner-writing-draft"]').trigger("click")
    expect(generateDraft).toHaveBeenCalledOnce()

    await wrapper.get('[data-action="owner-evidence"]').trigger("click")
    expect(wrapper.find("[data-embedded-search]").exists()).toBe(true)
    expect(router.navigate).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("keeps legacy Generate preview and POV tabs when opened from a compatibility hash", async () => {
    const wrapper = mount(OwnerAiDrawer, {
      props: { open: true, owner: "writing", initialMode: "preview", projectId: "p1" },
    })
    await flushPromises()
    expect(loadGenerate).toHaveBeenCalledWith(expect.objectContaining({ tab: "preview" }))
    wrapper.unmount()
  })

  it("does not keep a late Generate load after the drawer closes", async () => {
    let resolveLoad
    loadGenerate.mockReturnValue(new Promise((resolve) => { resolveLoad = resolve }))
    const wrapper = mount(OwnerAiDrawer, { props: { open: true, owner: "world", projectId: "p1" } })
    await wrapper.setProps({ open: false })
    resolveLoad({ projectId: "p1", tab: "world", sessionKey: "late", initialSession: {} })
    await flushPromises()
    expect(wrapper.find("[data-embedded-generate]").exists()).toBe(false)
    wrapper.unmount()
  })

  afterEach(() => resetBridgeOverrides())
})

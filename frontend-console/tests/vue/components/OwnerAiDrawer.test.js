import { afterEach, describe, expect, it, vi, beforeEach } from "vitest"
import { DOMWrapper, flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const loadGenerate = vi.hoisted(() => vi.fn())
vi.mock("../../../vue/generateIsland.js", () => ({ loadGenerate }))
vi.mock("../../../vue/views/generate/GenerateView.vue", () => ({
  default: { props: ["embedded", "tab", "handoffSessionKey"], emits: ["select-mode"], template: '<div data-embedded-generate :data-embedded-mode="embedded" :data-generate-tab="tab" :data-handoff-session-key="handoffSessionKey">生成工作台<button type="button" data-request-world @click="$emit(\'select-mode\', \'world\')">带到设定共创</button></div>' },
}))
vi.mock("../../../vue/views/rag/RagSearchView.vue", () => ({
  default: { props: ["embedded"], template: '<div data-embedded-search :data-embedded-mode="embedded">查找资料</div>' },
}))

import OwnerAiDrawer from "../../../vue/components/OwnerAiDrawer.vue"

describe("OwnerAiDrawer", () => {
  let router
  let currentQuery
  const rendered = new DOMWrapper(document.body)

  beforeEach(() => {
    currentQuery = new URLSearchParams()
    router = {
      navigate: vi.fn(),
      getCurrentQuery: vi.fn(() => new URLSearchParams(currentQuery)),
      commitCurrentQuery: vi.fn((query) => {
        currentQuery = new URLSearchParams(query)
        return true
      }),
    }
    setBridgeOverrides({ state: { currentProjectId: "p1" }, router, toast: vi.fn() })
    loadGenerate.mockReset()
    loadGenerate.mockImplementation(async (options) => ({ projectId: "p1", tab: options.tab, preset: options.preset, sessionKey: "owner-session", initialSession: {} }))
  })

  it("embeds the existing world and task generation workbench without routing away", async () => {
    const wrapper = mount(OwnerAiDrawer, { props: { open: true, owner: "world", projectId: "p1" }, attachTo: document.body })
    await flushPromises()

    expect(loadGenerate).toHaveBeenCalledWith(expect.objectContaining({ tab: "world" }))
    expect(rendered.find("[data-embedded-generate]").exists()).toBe(true)
    expect(router.navigate).not.toHaveBeenCalled()

    const worldTab = rendered.get('[data-action="owner-world-generation"]')
    const taskTab = rendered.get('[data-action="owner-task-context"]')
    expect(worldTab.attributes()).toMatchObject({ role: "tab", "aria-selected": "true", tabindex: "0", "aria-controls": "owner-ai-panel-world" })
    expect(taskTab.attributes("tabindex")).toBe("-1")
    expect(rendered.get("#owner-ai-panel-world").attributes()).toMatchObject({ role: "tabpanel", "aria-labelledby": "owner-ai-tab-world" })
    await worldTab.trigger("keydown", { key: "ArrowRight" })
    expect(document.activeElement).toBe(taskTab.element)
    expect(worldTab.attributes("aria-selected")).toBe("true")

    await taskTab.trigger("click")
    await flushPromises()
    expect(loadGenerate).toHaveBeenLastCalledWith(expect.objectContaining({ tab: "task" }))
    expect(rendered.find("[data-embedded-generate]").exists()).toBe(true)
    expect(rendered.get("[data-embedded-generate]").attributes()).toHaveProperty("data-embedded-mode")
    expect(rendered.get("[data-embedded-generate]").attributes("data-generate-tab")).toBe("task")
    expect(rendered.get("[data-embedded-generate]").attributes("data-handoff-session-key")).toContain("_project_core_entity")
    const taskQuery = router.commitCurrentQuery.mock.calls.at(-1)[0]
    expect(taskQuery.get("owner_ai")).toBe("1")
    expect(taskQuery.get("owner_ai_mode")).toBe("task")
    expect(router.navigate).not.toHaveBeenCalled()
    expect(taskTab.attributes()).toMatchObject({ "aria-selected": "true", tabindex: "0" })
    expect(rendered.get("#owner-ai-panel-task").attributes()).toMatchObject({ role: "tabpanel", "aria-labelledby": "owner-ai-tab-task" })

    await rendered.get("[data-request-world]").trigger("click")
    await flushPromises()
    expect(worldTab.attributes()).toMatchObject({ "aria-selected": "true", tabindex: "0" })
    expect(rendered.get("[data-embedded-generate]").attributes("data-generate-tab")).toBe("world")
    expect(router.commitCurrentQuery.mock.calls.at(-1)[0].get("owner_ai_mode")).toBe("world")

    await rendered.get('[data-action="collapse-owner-ai-drawer"]').trigger("click")
    expect(wrapper.emitted("close")).toHaveLength(1)
    wrapper.unmount()
  })

  it("calls the writing controller directly and embeds Search for evidence", async () => {
    const generateDraft = vi.fn()
    const wrapper = mount(OwnerAiDrawer, {
      props: {
        open: true,
        owner: "writing",
        projectId: "p1",
        chapter: 1,
        sceneId: "scene-1",
        writingContext: { chapterTitle: "潮门初启", hasContent: false, hasPovCharacter: false },
        writingActions: { generateDraft },
      },
    })
    await rendered.get('[data-action="owner-writing-draft"]').trigger("click")
    expect(generateDraft).toHaveBeenCalledOnce()

    await rendered.get('[data-action="owner-writing-pov-workbench"]').trigger("click")
    await flushPromises()
    expect(loadGenerate).toHaveBeenCalledWith(expect.objectContaining({ tab: "pov_prose" }))
    expect(rendered.get('[data-action="owner-writing-generation"]').attributes("aria-selected")).toBe("true")
    await rendered.get('[data-action="return-owner-writing-tools"]').trigger("click")
    expect(rendered.find('[data-action="owner-writing-draft"]').exists()).toBe(true)

    await rendered.get('[data-action="owner-evidence"]').trigger("click")
    expect(rendered.find("[data-embedded-search]").exists()).toBe(true)
    expect(rendered.get("[data-embedded-search]").attributes()).toHaveProperty("data-embedded-mode")
    expect(rendered.get(".owner-ai-drawer__hint").text()).toContain("打开来源不会修改正文或设定")
    expect(router.commitCurrentQuery.mock.calls.at(-1)[0].get("owner_ai_mode")).toBe("evidence")
    expect(router.navigate).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("makes saved continuation primary and closes only after a generated result", async () => {
    const generateContinuation = vi.fn(async () => ({ draft_id: "candidate-1" }))
    const wrapper = mount(OwnerAiDrawer, {
      props: {
        open: true,
        owner: "writing",
        projectId: "p1",
        chapter: 2,
        sceneId: "scene-2",
        writingContext: {
          chapterTitle: "雾港来信",
          sceneTitle: "钟楼换岗",
          hasContent: true,
          hasUnsavedContent: false,
          hasPovCharacter: false,
        },
        writingActions: { generateContinuation },
      },
    })

    expect(rendered.get(".owner-ai-writing__context").text()).toContain("第 2 章 · 雾港来信")
    expect(rendered.get(".owner-ai-writing__context").text()).toContain("当前场景：钟楼换岗")
    expect(rendered.get('[data-action="owner-writing-continuation"]').classes()).toContain("btn-primary")
    expect(rendered.get('[data-action="owner-writing-pov"]').attributes()).toHaveProperty("disabled")
    expect(rendered.get(".owner-ai-writing__more").text()).toContain("当前场景还没有设置视角人物")

    await rendered.get('[data-action="owner-writing-continuation"]').trigger("click")
    await flushPromises()
    expect(generateContinuation).toHaveBeenCalledOnce()
    expect(wrapper.emitted("close")).toHaveLength(1)
    wrapper.unmount()
  })

  it("explains unsaved continuation, reuses save, and shows an in-drawer running state", async () => {
    const saveDraft = vi.fn(async () => true)
    const wrapper = mount(OwnerAiDrawer, {
      props: {
        open: true,
        owner: "writing",
        projectId: "p1",
        chapter: 1,
        writingContext: { chapterTitle: "潮门初启", hasContent: true, hasUnsavedContent: true },
        writingActions: { generateContinuation: vi.fn(), saveDraft },
      },
    })

    expect(rendered.get('[data-action="owner-writing-continuation"]').attributes()).toHaveProperty("disabled")
    expect(rendered.get(".owner-ai-writing__primary").text()).toContain("先保存工作稿")
    await rendered.get('[data-action="owner-writing-save"]').trigger("click")
    expect(saveDraft).toHaveBeenCalledOnce()

    await wrapper.setProps({
      writingContext: { chapterTitle: "潮门初启", hasContent: true, hasUnsavedContent: false },
      writingBusy: true,
    })
    expect(rendered.get(".owner-ai-writing__progress").text()).toContain("可以收起 AI 工具继续写作")
    expect(rendered.find('[data-action="owner-writing-continuation"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it("syncs the open route and closes with Escape back to its trigger", async () => {
    const trigger = document.createElement("button")
    document.body.append(trigger)
    trigger.focus()
    const wrapper = mount(OwnerAiDrawer, {
      props: { open: false, owner: "writing", projectId: "p1" },
      attachTo: document.body,
    })

    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(rendered.get('[data-action="close-owner-ai-drawer"]').element).toBe(document.activeElement)
    const openedQuery = router.commitCurrentQuery.mock.calls.at(-1)[0]
    expect(openedQuery.get("owner_ai")).toBe("1")
    expect(openedQuery.get("owner_ai_mode")).toBe("writing")

    await rendered.get('[data-action="close-owner-ai-drawer"]').trigger("keydown", { key: "Escape" })
    await flushPromises()
    expect(wrapper.emitted("close")).toHaveLength(1)
    expect(router.commitCurrentQuery.mock.calls.at(-1)[0].has("owner_ai")).toBe(false)
    expect(document.activeElement).toBe(trigger)
    wrapper.unmount()
    trigger.remove()
  })

  it("reloads the saved generation session after returning from evidence", async () => {
    const wrapper = mount(OwnerAiDrawer, { props: { open: true, owner: "writing", initialMode: "task", projectId: "p1" } })
    await flushPromises()
    expect(loadGenerate).toHaveBeenCalledTimes(1)

    await rendered.get('[data-action="owner-evidence"]').trigger("click")
    await rendered.get('[data-action="owner-task-context"]').trigger("click")
    await flushPromises()

    expect(loadGenerate).toHaveBeenCalledTimes(2)
    expect(loadGenerate).toHaveBeenLastCalledWith(expect.objectContaining({ projectId: "p1", tab: "task" }))
    wrapper.unmount()
  })

  it("keeps legacy Generate preview and POV tabs under their visible owner category", async () => {
    const wrapper = mount(OwnerAiDrawer, {
      props: { open: true, owner: "writing", initialMode: "preview", projectId: "p1" },
    })
    await flushPromises()
    expect(loadGenerate).toHaveBeenCalledWith(expect.objectContaining({ tab: "preview" }))
    expect(rendered.get('[data-action="owner-task-context"]').attributes("aria-selected")).toBe("true")
    wrapper.unmount()

    const pov = mount(OwnerAiDrawer, {
      props: { open: true, owner: "writing", initialMode: "pov_prose", projectId: "p1" },
    })
    await flushPromises()
    expect(rendered.get('[data-action="owner-writing-generation"]').attributes("aria-selected")).toBe("true")
    expect(loadGenerate).toHaveBeenLastCalledWith(expect.objectContaining({ tab: "pov_prose" }))
    pov.unmount()
  })

  it("does not keep a late Generate load after the drawer closes", async () => {
    let resolveLoad
    loadGenerate.mockReturnValue(new Promise((resolve) => { resolveLoad = resolve }))
    const wrapper = mount(OwnerAiDrawer, { props: { open: true, owner: "world", projectId: "p1" } })
    await wrapper.setProps({ open: false })
    resolveLoad({ projectId: "p1", tab: "world", sessionKey: "late", initialSession: {} })
    await flushPromises()
    expect(rendered.find("[data-embedded-generate]").exists()).toBe(false)
    wrapper.unmount()
  })

  afterEach(() => resetBridgeOverrides())
})

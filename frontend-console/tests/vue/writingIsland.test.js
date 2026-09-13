import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../vue/bridge/index.js"
import { createWritingIsland } from "../../vue/writingIsland.js"
import { clearWritingSession } from "../../vue/views/writing/writingSession.js"

describe("writingIsland", () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="workspace-content"></div>'
    clearWritingSession()
    localStorage.clear()
  })
  afterEach(() => resetBridgeOverrides())

  it("挂载真实 Vue shell 并通过 island leave guard 保护未保存正文", async () => {
    const state = { currentProjectId: "p1", viewStates: {} }
    const api = globalThis.api
    api.writing.listChapters.mockResolvedValue({ chapters: [{ chapter_index: 1, title: "第一章", word_count: 2, status: "draft" }] })
    api.outline.listScenesOrdered.mockResolvedValue([])
    api.settings.getEffectiveAuthorPrefs.mockResolvedValue(null)
    api.writing.get.mockResolvedValue({ id: "d1", novel_id: "p1", title: "第一章", content: "正文", version_number: 1, status: "draft" })
    api.writing.getVersionHistory.mockResolvedValue({ versions: [{ id: "d1", version_number: 1, status: "draft" }] })
    const confirm = vi.fn(() => false)
    setBridgeOverrides({
      state,
      api,
      confirm,
      router: { getCurrentQuery: () => new URLSearchParams("chapter_index=1&draft_id=d1") },
    })
    const island = createWritingIsland()
    await island.onEnter()
    const content = document.getElementById("workspace-content")
    content.innerHTML = island.render()
    await island.onRendered()
    await vi.waitFor(() => expect(content.querySelector("#writing-editor")).toBeTruthy())
    const viewMenu = content.querySelector(".writing-page-menu")
    viewMenu.open = true
    viewMenu.querySelector("button").click()
    expect(viewMenu.open).toBe(false)
    const editor = content.querySelector("#writing-editor")
    editor.value = "未保存正文"
    editor.dispatchEvent(new Event("input"))

    expect(island.canLeave()).toBe(false)
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("未保存修改"))
    island.onLeave()
    expect(island.canLeave()).toBe(true)
  })

  it("onLeave 使 load 晚到结果失效，后续挂载重新加载", async () => {
    const state = { currentProjectId: "p1", viewStates: {} }
    let resolveChapters
    const api = globalThis.api
    api.writing.listChapters.mockClear()
    api.writing.listChapters.mockReturnValue(new Promise((resolve) => { resolveChapters = resolve }))
    api.outline.listScenesOrdered.mockResolvedValue([])
    api.settings.getEffectiveAuthorPrefs.mockResolvedValue(null)
    setBridgeOverrides({ state, api, router: { getCurrentQuery: () => new URLSearchParams() } })
    const island = createWritingIsland()
    const entering = island.onEnter()
    island.onLeave()
    resolveChapters({ chapter_indices: [1] })
    await entering
    document.getElementById("workspace-content").innerHTML = island.render()
    await island.onRendered()
    expect(api.writing.listChapters).toHaveBeenCalledTimes(2)
    expect(document.querySelector(".view-header__count")?.textContent).toContain("1")
    island.onLeave()
  })

  it("Writing Home 只加载今日继续数据", async () => {
    const state = {
      currentProjectId: "p1",
      currentProject: { id: "p1", title: "测试小说" },
      viewStates: {},
    }
    const api = globalThis.api
    api.writing.listChapters.mockClear()
    api.writing.getVersionHistory.mockClear()
    api.outline.listScenesOrdered.mockClear()
    api.settings.getEffectiveAuthorPrefs.mockClear()
    api.projects.getWorkspaceSummary.mockResolvedValue({
      project_id: "p1",
      writing: {},
      attention: { items: [] },
    })
    api.world.listBibleDrafts.mockResolvedValue({ items: [] })
    api.world.listSuggestions.mockResolvedValue({ items: [] })
    setBridgeOverrides({
      state,
      api,
      router: { getCurrentQuery: () => new URLSearchParams("home=1") },
    })

    const island = createWritingIsland()
    await island.onEnter()

    expect(api.writing.listChapters).not.toHaveBeenCalled()
    expect(api.outline.listScenesOrdered).not.toHaveBeenCalled()
    expect(api.settings.getEffectiveAuthorPrefs).not.toHaveBeenCalled()
    document.getElementById("workspace-content").innerHTML = island.render()
    await island.onRendered()
    expect(document.querySelector('[data-writing-home="true"]')).toBeTruthy()
    expect(api.writing.getVersionHistory).not.toHaveBeenCalled()
    island.onLeave()
  })

  it("公开演示只加载正式正文阅读投影", async () => {
    globalThis.publicDemoMode = true
    globalThis.publicDemoRpMode = false
    const state = { currentProjectId: "demo", viewStates: {} }
    const api = globalThis.api
    api.writing.listChapters.mockClear()
    api.writing.getDraft.mockClear()
    api.writing.getVersionHistory.mockClear()
    api.writing.listConflictChecks.mockClear()
    api.outline.listScenesOrdered.mockClear()
    api.settings.getEffectiveAuthorPrefs.mockClear()
    api.writing.listChapters.mockResolvedValue({
      chapters: [{ id: "published-1", chapter_index: 1, title: "第一章", word_count: 4, status: "published" }],
    })
    api.writing.getDraft.mockResolvedValue({
      id: "published-1",
      novel_id: "demo",
      chapter_index: 1,
      title: "第一章",
      content: "公开正文",
      version_number: 1,
      status: "published",
    })
    setBridgeOverrides({
      state,
      api,
      router: { getCurrentQuery: () => new URLSearchParams("demo=1&chapter_index=99&readonly=1") },
    })
    const island = createWritingIsland()
    try {
      await island.onEnter()
      document.getElementById("workspace-content").innerHTML = island.render()
      await island.onRendered()
      await vi.waitFor(() => expect(document.querySelector(".public-demo-reader__content")?.textContent).toBe("公开正文"))

      expect(document.querySelector("#writing-editor")).toBeNull()
      expect(document.body.textContent).not.toContain("保存工作稿")
      expect(api.writing.getDraft).toHaveBeenCalledWith(1, "demo")
      expect(api.writing.getVersionHistory).not.toHaveBeenCalled()
      expect(api.writing.listConflictChecks).not.toHaveBeenCalled()
      expect(api.outline.listScenesOrdered).not.toHaveBeenCalled()
      expect(api.settings.getEffectiveAuthorPrefs).not.toHaveBeenCalled()
    } finally {
      island.onLeave()
      globalThis.publicDemoMode = false
      globalThis.publicDemoRpMode = false
    }
  })
})

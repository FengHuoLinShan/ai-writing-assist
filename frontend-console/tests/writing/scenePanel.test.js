/**
 * scenePanel 子模块最小测试
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createScenePanel } from "../../views/writing/scenePanel.js"
import { resetState, clearDocument } from "../helpers.js"

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

function createTestPanel(overrides = {}) {
  return createScenePanel({
    state: globalThis.state,
    api: globalThis.api,
    toast: globalThis.toast,
    esc: globalThis.esc,
    onOpenMap: vi.fn(),
    onSwitchTab: vi.fn(),
    ...overrides,
  })
}

beforeEach(() => {
  resetState()
  clearDocument()
  localStorage.clear()
  vi.clearAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("createScenePanel", () => {
  it("returns the public API", () => {
    const panel = createTestPanel()
    expect(panel.update).toBeTypeOf("function")
    expect(panel.render).toBeTypeOf("function")
    expect(panel.bindEvents).toBeTypeOf("function")
    expect(panel.setScenes).toBeTypeOf("function")
    expect(panel.setCursorOffset).toBeTypeOf("function")
    expect(panel.getCurrentScene).toBeTypeOf("function")
    expect(panel.getMapSummary).toBeTypeOf("function")
    expect(panel.dispose).toBeTypeOf("function")
  })

  it("finds current scene by cursor offset", () => {
    state.currentProjectId = "p1"
    const panel = createTestPanel()
    panel.setScenes([{
      id: "s1",
      title: "Scene 1",
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 10 }],
    }])
    panel.setCursorOffset(5)
    panel.update(null, 1)
    expect(panel.getCurrentScene()?.id).toBe("s1")
  })

  it("falls back to chapter_ids when offset missing", () => {
    state.currentProjectId = "p1"
    const panel = createTestPanel()
    panel.setScenes([{
      id: "s2",
      title: "Scene 2",
      chapter_ids: ["1"],
    }])
    panel.setCursorOffset(100)
    panel.update(null, 1)
    expect(panel.getCurrentScene()?.id).toBe("s2")
  })

  it("renders scene cockpit panel", async () => {
    state.currentProjectId = "p1"
    const panel = createTestPanel()
    panel.setScenes([{
      id: "s1",
      title: "Scene 1",
      scene_index: 1,
      chapter_ids: ["1"],
    }])
    panel.update("s1", 1)
    await flushPromises()

    const html = panel.render()
    expect(html).toContain("scene-cockpit")
    expect(html).toContain("Scene 1")
    expect(html).toContain('data-action="switch-cockpit-tab"')
    expect(html).toContain('data-action="toggle-cockpit-module"')
  })

  it("loads and renders map summary", async () => {
    state.currentProjectId = "p1"
    api.world.getMapSceneSummary.mockResolvedValue({
      primary_location: { name: "北港" },
      characters: [{ name: "沈澜" }],
      events: [{ name: "镜修" }],
      warnings: [],
      open_target: { map_id: "m1", scene_id: "s1" },
    })

    const panel = createTestPanel()
    panel.setScenes([{
      id: "s1",
      title: "Scene 1",
      chapter_ids: ["1"],
    }])
    panel.update("s1", 1)
    await flushPromises()

    const html = panel.render()
    expect(html).toContain("地图摘要")
    expect(html).toContain("北港")
    expect(html).toContain("沈澜")
    expect(html).toContain('data-action="open-map"')
  })

  it("shows error state when map summary fails", async () => {
    state.currentProjectId = "p1"
    api.world.getMapSceneSummary.mockRejectedValue(new Error("fail"))

    const panel = createTestPanel()
    panel.setScenes([{
      id: "s1",
      title: "Scene 1",
      chapter_ids: ["1"],
    }])
    panel.update("s1", 1)
    await flushPromises()

    const html = panel.render()
    expect(html).toContain("地图摘要暂不可用")
  })

  it("opens map via callback", async () => {
    state.currentProjectId = "p1"
    const openTarget = { mode: "map", map_id: "m1", scene_id: "s1" }
    api.world.getMapSceneSummary.mockResolvedValue({
      primary_location: { name: "北港" },
      open_target: openTarget,
    })
    const onOpenMap = vi.fn()
    const panel = createTestPanel({ onOpenMap })
    panel.setScenes([{
      id: "s1",
      title: "Scene 1",
      chapter_ids: ["1"],
    }])
    panel.update("s1", 1)
    await flushPromises()

    document.body.innerHTML = panel.render()
    panel.bindEvents(document.body)

    document.querySelector('[data-action="open-map"]').click()
    expect(onOpenMap).toHaveBeenCalledWith(openTarget)
  })

  it("switches cockpit tab via callback", async () => {
    state.currentProjectId = "p1"
    const onSwitchTab = vi.fn()
    const panel = createTestPanel({ onSwitchTab })
    panel.setScenes([{
      id: "s1",
      title: "Scene 1",
      chapter_ids: ["1"],
    }])
    panel.update("s1", 1)
    await flushPromises()

    document.body.innerHTML = panel.render()
    panel.bindEvents(document.body)

    document.querySelector('[data-action="switch-cockpit-tab"][data-tab="place"]').click()
    expect(onSwitchTab).toHaveBeenCalledWith("place")
  })

  it("disposes internal state", async () => {
    state.currentProjectId = "p1"
    api.world.getMapSceneSummary.mockResolvedValue({ primary_location: { name: "北港" } })
    const panel = createTestPanel()
    panel.setScenes([{ id: "s1", chapter_ids: ["1"] }])
    panel.update("s1", 1)
    await flushPromises()

    panel.dispose()
    expect(panel.getMapSummary()).toBeNull()
  })
})

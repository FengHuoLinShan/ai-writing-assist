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
  api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })
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
    expect(panel.setWritingContext).toBeTypeOf("function")
    expect(panel.refreshAlerts).toBeTypeOf("function")
    expect(panel.getCurrentScene).toBeTypeOf("function")
    expect(panel.getMapSummary).toBeTypeOf("function")
    expect(panel.getAlerts).toBeTypeOf("function")
    expect(panel.dispose).toBeTypeOf("function")
  })

  it("未选章节时显示中性参考空态，不误报未关联 Scene", () => {
    const panel = createTestPanel()

    const html = panel.render()

    expect(html).toContain("请先从左侧选择章节")
    expect(html).not.toContain("当前章节未关联地图 Scene")
    expect(html).not.toContain("scene-cockpit")
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

  it("routes map summary people and primary location into their cockpit tabs", async () => {
    state.currentProjectId = "p1"
    api.world.getMapSceneSummary.mockResolvedValue({
      primary_location: { id: "l1", name: "北港", summary: "旧码头区" },
      characters: [{ id: "c1", name: "沈澜", summary: "巡夜人" }],
      warnings: [],
    })
    api.world.listEntities.mockResolvedValue({ items: [], total: 0 })

    const panel = createTestPanel()
    panel.setScenes([{ id: "s1", title: "Scene 1", chapter_ids: ["1"] }])
    panel.update("s1", 1)
    await flushPromises()

    const html = panel.render()
    expect(html).toContain("沈澜")
    expect(html).toContain("巡夜人")
    expect(html).toContain("北港")
    expect(html).toContain("旧码头区")
  })

  it("falls back to active world references sourced from the current Scene", async () => {
    state.currentProjectId = "p1"
    api.world.getMapSceneSummary.mockResolvedValue({ warnings: [] })
    api.world.listEntities.mockImplementation(async (params) => {
      if (params.entity_type === "character") {
        return { items: [{ id: "c1", name: "罗塞尔", summary: "日记中的人物" }], total: 1 }
      }
      return { items: [{ id: "l1", name: "占卜帐篷", summary: "马戏团帐篷" }], total: 1 }
    })

    const panel = createTestPanel()
    panel.setScenes([{ id: "s1", title: "Scene 1", chapter_ids: ["1"] }])
    panel.update("s1", 1)
    await flushPromises()

    const html = panel.render()
    expect(html).toContain("罗塞尔")
    expect(html).toContain("日记中的人物")
    expect(html).toContain("占卜帐篷")
    expect(html).toContain("马戏团帐篷")
    expect(api.world.listEntities).toHaveBeenCalledWith({
      novel_id: "p1",
      scene_id: "s1",
      entity_type: "character",
      display_state: "active",
      skip: 0,
      limit: 12,
    })
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
    panel.bindEvents(document.body)

    document.querySelector('[data-action="open-map"]').click()
    expect(onOpenMap).toHaveBeenCalledTimes(1)
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

    document.body.innerHTML = panel.render()
    expect(document.querySelector('[data-tab="place"]')?.classList.contains("active")).toBe(true)
    expect(document.querySelector('[data-panel="place"]')?.classList.contains("hidden")).toBe(false)
    expect(document.querySelector('[data-panel="lore"]')?.classList.contains("hidden")).toBe(true)
  })

  it("loads the latest check for the exact project, chapter and Scene", async () => {
    state.currentProjectId = "p1"
    api.writing.listConflictChecks.mockResolvedValue({
      items: [{ id: "check-1", draft_id: "d1", version_number: 3, items: [] }],
      total: 1,
    })
    const panel = createTestPanel()
    panel.setScenes([{ id: "s1", title: "Scene 1", chapter_ids: ["1"] }])
    panel.setWritingContext({ content: "正文", draftId: "d1", versionNumber: 3 })
    panel.update("s1", 1)
    await flushPromises()

    expect(api.writing.listConflictChecks).toHaveBeenCalledWith({
      novel_id: "p1",
      chapter_index: 1,
      scene_id: "s1",
      limit: 1,
    })
    expect(panel.getLatestConflictCheck()?.id).toBe("check-1")
  })

  it("marks a loaded check stale as soon as the editor becomes dirty", async () => {
    state.currentProjectId = "p1"
    api.writing.listConflictChecks.mockResolvedValue({
      items: [{ id: "check-1", draft_id: "d1", version_number: 3, items: [] }],
    })
    const panel = createTestPanel()
    panel.setScenes([{
      id: "s1",
      title: "Scene 1",
      goal: "目标",
      core_conflict: "冲突",
      emotional_beat: "节拍",
      pov_character_id: "c1",
      chapter_ids: ["1"],
    }])
    panel.setWritingContext({ content: "正文", draftId: "d1", versionNumber: 3 })
    panel.update("s1", 1)
    await flushPromises()

    panel.setWritingContext({ content: "正文已修改", draftId: "d1", versionNumber: 3, isDirty: true })

    expect(panel.getAlerts()).toContainEqual(expect.objectContaining({
      stale: true,
      message: "正文已有未保存修改，最近校验已过期",
    }))
  })

  it("discards an old check response after switching Scene", async () => {
    state.currentProjectId = "p1"
    let resolveFirst
    api.writing.listConflictChecks
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce({ items: [{ id: "check-s2", draft_id: "d1", version_number: 1 }] })
    const panel = createTestPanel()
    panel.setScenes([
      { id: "s1", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 5 }] },
      { id: "s2", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 1, start_pos: 5, end_pos: 10 }] },
    ])
    panel.setWritingContext({ content: "0123456789", draftId: "d1", versionNumber: 1 })
    panel.setCursorOffset(1)
    panel.update("s1", 1)
    await flushPromises()
    panel.setCursorOffset(7)
    panel.update("s2", 1)
    await flushPromises()
    resolveFirst({ items: [{ id: "check-s1", draft_id: "d1", version_number: 1 }] })
    await flushPromises()

    expect(panel.getLatestConflictCheck()?.id).toBe("check-s2")
  })

  it("严格丢弃 A→B→A 中晚于新 A 返回的旧地图请求", async () => {
    state.currentProjectId = "p1"
    let resolveA1
    let resolveB
    let resolveA2
    api.world.getMapSceneSummary
      .mockImplementationOnce(() => new Promise((resolve) => { resolveA1 = resolve }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveB = resolve }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveA2 = resolve }))

    const panel = createTestPanel()
    panel.setScenes([
      { id: "scene-a", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 5 }] },
      { id: "scene-b", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 1, start_pos: 5, end_pos: 10 }] },
    ])

    panel.setCursorOffset(1)
    panel.update("scene-a", 1)
    await flushPromises()
    panel.setCursorOffset(7)
    panel.update("scene-b", 1)
    await flushPromises()
    panel.setCursorOffset(1)
    panel.update("scene-a", 1)
    await flushPromises()

    resolveA2({ primary_location: { name: "A 新摘要" }, warnings: [] })
    await flushPromises()
    expect(panel.getMapSummary()?.primary_location?.name).toBe("A 新摘要")

    resolveA1({ primary_location: { name: "A 旧摘要" }, warnings: [] })
    await flushPromises()
    expect(panel.getMapSummary()?.primary_location?.name).toBe("A 新摘要")

    resolveB({ primary_location: { name: "B 过期摘要" }, warnings: [] })
    await flushPromises()
    expect(panel.getMapSummary()?.primary_location?.name).toBe("A 新摘要")
  })

  it("never combines map or check data from another project with the same Scene id", async () => {
    state.currentProjectId = "p1"
    api.world.getMapSceneSummary.mockResolvedValue({
      primary_location: { name: "项目一旧港" },
      warnings: [{ message: "项目一风险" }],
    })
    api.writing.listConflictChecks.mockResolvedValue({
      items: [{ id: "project-one-check", draft_id: "d1", version_number: 1 }],
    })
    const panel = createTestPanel()
    panel.setScenes([{ id: "shared-scene", title: "Scene", chapter_ids: ["1"] }])
    panel.setWritingContext({ content: "正文", draftId: "d1", versionNumber: 1 })
    panel.update("shared-scene", 1)
    await flushPromises()
    expect(panel.render()).toContain("项目一旧港")

    state.currentProjectId = "p2"
    api.world.getMapSceneSummary.mockImplementation(() => new Promise(() => {}))
    api.writing.listConflictChecks.mockImplementation(() => new Promise(() => {}))
    panel.update("shared-scene", 1)
    const html = panel.render()

    expect(html).not.toContain("项目一旧港")
    expect(html).not.toContain("项目一风险")
    expect(panel.getLatestConflictCheck()).toBeNull()
  })

  it("丢弃 API 返回的跨项目或跨 Scene 校验记录", async () => {
    state.currentProjectId = "p1"
    api.writing.listConflictChecks.mockResolvedValue({
      items: [{
        id: '<script>alert("leak")</script>',
        novel_id: "p2",
        chapter_index: 1,
        scene_id: "s1",
        items: [],
      }],
    })
    const panel = createTestPanel()
    panel.setScenes([{ id: "s1", title: "Scene 1", chapter_ids: ["1"] }])
    panel.update("s1", 1)
    await flushPromises()

    expect(panel.getLatestConflictCheck()).toBeNull()
    expect(panel.getAlerts()).toContainEqual(expect.objectContaining({
      source: "最近校验",
      message: "最近校验身份不匹配，已安全忽略",
    }))
    expect(panel.render()).not.toContain("<script>")
  })

  it("切换项目时不把上一项目的校验错误带入新范围", async () => {
    state.currentProjectId = "p1"
    api.writing.listConflictChecks.mockRejectedValueOnce(new Error("p1 failed"))
    const panel = createTestPanel()
    panel.setScenes([{ id: "shared-scene", title: "Scene", chapter_ids: ["1"] }])
    panel.update("shared-scene", 1)
    await flushPromises()
    expect(panel.getAlerts()).toContainEqual(expect.objectContaining({ id: "check-unavailable" }))

    state.currentProjectId = "p2"
    api.writing.listConflictChecks.mockImplementationOnce(() => new Promise(() => {}))
    panel.update("shared-scene", 1)

    expect(panel.getAlerts().some((item) => item.id === "check-unavailable")).toBe(false)
    expect(panel.render()).not.toContain("最近校验暂不可用")
  })

  it("routes cockpit check actions through callbacks", async () => {
    state.currentProjectId = "p1"
    api.writing.listConflictChecks.mockResolvedValue({ items: [{ id: "check-1" }] })
    const onRunConflictCheck = vi.fn()
    const onOpenConflictCheck = vi.fn()
    const panel = createTestPanel({ onRunConflictCheck, onOpenConflictCheck })
    panel.setScenes([{ id: "s1", title: "Scene 1", chapter_ids: ["1"] }])
    panel.update("s1", 1)
    await flushPromises()
    panel.switchTab("alerts")
    document.body.innerHTML = panel.render()
    panel.bindEvents(document.body)

    document.querySelector('[data-action="run-cockpit-conflict-check"]').click()
    document.querySelector('[data-action="open-cockpit-conflict-check"]').click()

    expect(onRunConflictCheck).toHaveBeenCalledTimes(1)
    expect(onOpenConflictCheck).toHaveBeenCalledWith(expect.objectContaining({ id: "check-1" }))
  })

  it("切换驾驶舱标签时不会改动页面上的其他同名组件", async () => {
    state.currentProjectId = "p1"
    const panel = createTestPanel()
    panel.setScenes([{ id: "s1", title: "Scene 1", chapter_ids: ["1"] }])
    panel.update("s1", 1)
    await flushPromises()

    document.body.innerHTML = `
      <div id="outside"><button class="cockpit-tab active" data-tab="lore"></button></div>
      <div id="writing-panel-container">${panel.render()}</div>
    `
    const container = document.getElementById("writing-panel-container")
    panel.bindEvents(container)
    container.querySelector('[data-tab="place"]').click()

    expect(document.querySelector("#outside .cockpit-tab").classList.contains("active")).toBe(true)
    expect(container.querySelector('[data-tab="place"]').classList.contains("active")).toBe(true)
  })

  it("销毁后忽略已在途中的地图请求，不回写新页面 DOM", async () => {
    state.currentProjectId = "p1"
    let resolveMap
    api.world.getMapSceneSummary.mockImplementation(() => new Promise((resolve) => {
      resolveMap = resolve
    }))
    const panel = createTestPanel()
    panel.setScenes([{ id: "s1", title: "Scene 1", chapter_ids: ["1"] }])
    panel.update("s1", 1)
    await flushPromises()
    document.body.innerHTML = '<div id="writing-panel-container">新页面内容</div>'

    panel.dispose()
    resolveMap({ primary_location: { name: "旧项目地点" } })
    await flushPromises()

    expect(document.getElementById("writing-panel-container").textContent).toBe("新页面内容")
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

import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("../../../shared/workflowProgress.js", async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    clearActiveWorkflow: vi.fn(),
    persistActiveWorkflow: vi.fn(),
    pollTaskProgress: vi.fn(() => ({ stop: vi.fn() })),
    recoverActiveWorkflows: vi.fn(() => []),
  }
})

import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { useMapEnrichment } from "../../../vue/views/map/useMapEnrichment.js"
import { persistActiveWorkflow, pollTaskProgress, recoverActiveWorkflows } from "../../../shared/workflowProgress.js"

describe("useMapEnrichment", () => {
  let appState
  let startMapObservationEnrichment

  beforeEach(() => {
    vi.clearAllMocks()
    resetBridgeOverrides()
    appState = { currentProjectId: "p1", currentView: "map" }
    startMapObservationEnrichment = vi.fn(async () => ({ task_id: "task-map-1", status: "queued" }))
    setBridgeOverrides({
      state: appState,
      api: { imports: { startMapObservationEnrichment }, tasks: { get: vi.fn() } },
      toast: vi.fn(),
    })
  })

  it("携带显式授权和章节范围提交，并绑定项目恢复记录", async () => {
    const enrichment = useMapEnrichment({ projectId: "p1" })
    enrichment.state.startChapter = 3
    enrichment.state.endChapter = 8

    await expect(enrichment.submit()).resolves.toBe(true)

    expect(startMapObservationEnrichment).toHaveBeenCalledWith("p1", 3, 8, true, {
      adoption_policy: "user_authorized_pipeline",
      authorization_confirmed: true,
    })
    expect(persistActiveWorkflow).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "task-map-1", workflowType: "map_observation_enrichment", projectId: "p1", view: "map",
    }))
    expect(pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "task-map-1", workflowType: "map_observation_enrichment", novelId: "p1",
    }))
    enrichment.dispose()
  })

  it("项目切换发生在提交返回前时，不在新项目启动轮询", async () => {
    let resolveSubmit
    startMapObservationEnrichment.mockImplementation(() => new Promise((resolve) => { resolveSubmit = resolve }))
    const enrichment = useMapEnrichment({ projectId: "p1" })
    const pending = enrichment.submit()
    appState.currentProjectId = "p2"
    resolveSubmit({ task_id: "task-old-project", status: "queued" })

    await expect(pending).resolves.toBe(false)
    expect(persistActiveWorkflow).toHaveBeenCalledWith(expect.objectContaining({ projectId: "p1" }))
    expect(pollTaskProgress).not.toHaveBeenCalled()
    expect(enrichment.state.submitting).toBe(false)
    enrichment.dispose()
  })

  it("只恢复当前项目的地图补充任务", () => {
    recoverActiveWorkflows.mockReturnValue([{ taskId: "task-recover", workflowType: "map_observation_enrichment", projectId: "p1", meta: { start_chapter: 2, end_chapter: 5, high_quality: false } }])
    const enrichment = useMapEnrichment({ projectId: "p1" })

    expect(enrichment.recover()).toBe(true)
    expect(recoverActiveWorkflows).toHaveBeenCalledWith("p1")
    expect(enrichment.state).toMatchObject({ taskId: "task-recover", startChapter: 2, endChapter: 5, highQuality: false })
    expect(pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({ taskId: "task-recover", novelId: "p1" }))
    enrichment.dispose()
  })
})

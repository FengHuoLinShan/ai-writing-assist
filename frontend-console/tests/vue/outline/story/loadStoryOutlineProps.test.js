/**
 * loadStoryOutlineProps 测试 — island 预取函数的 props 形状与错误处理。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"

const workflowMocks = vi.hoisted(() => ({
  recoverActiveWorkflows: vi.fn(() => []),
}))

vi.mock("../../../../shared/workflowProgress.js", async () => ({
  ...await vi.importActual("../../../../shared/workflowProgress.js"),
  recoverActiveWorkflows: workflowMocks.recoverActiveWorkflows,
}))

function revisionFixture() {
  return {
    id: "rev-1",
    novel_id: "p1",
    version_number: 1,
    source: "manual",
    title: "霜城纪事",
    creative_core: { premise: "x", tone_and_reader_promise: "y", story_engine: "z", ending_direction: null },
    outline_markdown: "# 正文",
    major_storylines: [],
    macro_movements: [],
    open_decisions: [],
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  workflowMocks.recoverActiveWorkflows.mockReturnValue([])
  localStorage.clear()
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("loadStoryOutlineProps", () => {
  it("返回 props 包含预期的 key 集合", async () => {
    setBridgeOverrides({ state: { currentProjectId: "p1" } })

    globalThis.api.outline.getStoryOutline.mockResolvedValue({ current_revision_id: "rev-1", revision: revisionFixture() })
    globalThis.api.outline.listStoryOutlineRevisions.mockResolvedValue({ items: [revisionFixture()], total: 1, skip: 0, limit: 20 })
    globalThis.api.world.listCharacters.mockResolvedValue({ items: [{ entity_id: "c1", name: "顾沉" }], total: 1 })
    globalThis.api.world.listEntities.mockResolvedValue({ items: [{ id: "e1", name: "霜城" }], total: 1 })

    const { loadStoryOutlineProps } = await import("../../../../vue/views/outline/story/storyOutlineData.js")
    const props = await loadStoryOutlineProps("p1")

    expect(props).toHaveProperty("projectId")
    expect(props).toHaveProperty("current")
    expect(props).toHaveProperty("history")
    expect(props).toHaveProperty("historyTotal")
    expect(props).toHaveProperty("characters")
    expect(props).toHaveProperty("entities")
    expect(props).toHaveProperty("loadError")
    expect(props).toHaveProperty("assetLoadError")

    expect(props.projectId).toBe("p1")
    expect(props.current).toEqual({ current_revision_id: "rev-1", revision: expect.objectContaining({ title: "霜城纪事" }) })
    expect(props.history).toHaveLength(1)
    expect(props.historyTotal).toBe(1)
    expect(props.characters).toHaveLength(1)
    expect(props.entities).toHaveLength(1)
    expect(props.loadError).toBeNull()
    expect(props.assetLoadError).toBeNull()
  })

  it("无 projectId 时返回空 props", async () => {
    const { loadStoryOutlineProps } = await import("../../../../vue/views/outline/story/storyOutlineData.js")
    const props = await loadStoryOutlineProps(null)
    expect(props.projectId).toBeNull()
    expect(props.current).toBeNull()
    expect(props.history).toEqual([])
    expect(props.historyTotal).toBe(0)
  })

  it("加载失败时设置 loadError", async () => {
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    globalThis.api.outline.getStoryOutline.mockRejectedValue(new Error("连接超时"))
    globalThis.api.outline.listStoryOutlineRevisions.mockResolvedValue({ items: [], total: 0 })
    globalThis.api.world.listCharacters.mockResolvedValue({ items: [] })
    globalThis.api.world.listEntities.mockResolvedValue({ items: [] })

    const { loadStoryOutlineProps } = await import("../../../../vue/views/outline/story/storyOutlineData.js")
    const props = await loadStoryOutlineProps("p1")

    expect(props.loadError).toBe("连接超时")
    expect(props.current).toBeNull()
    expect(props.history).toEqual([])
    expect(props.historyTotal).toBe(0)
  })

  it("资产加载失败时设置 assetLoadError 但不阻断主数据", async () => {
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    globalThis.api.outline.getStoryOutline.mockResolvedValue({ current_revision_id: null, revision: null })
    globalThis.api.outline.listStoryOutlineRevisions.mockResolvedValue({ items: [], total: 0 })
    globalThis.api.world.listCharacters.mockRejectedValue(new Error("人物加载失败"))
    globalThis.api.world.listEntities.mockRejectedValue(new Error("实体加载失败"))

    const { loadStoryOutlineProps } = await import("../../../../vue/views/outline/story/storyOutlineData.js")
    const props = await loadStoryOutlineProps("p1")

    expect(props.current).toBeDefined()
    expect(props.loadError).toBeNull()
    expect(props.assetLoadError).toBe("可选人物或世界对象未完全加载，仍可不选资产直接生成。")
    expect(props.characters).toEqual([])
    expect(props.entities).toEqual([])
  })

  it("工作流恢复由 recover 启动", async () => {
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    globalThis.api.outline.getStoryOutline.mockResolvedValue({ current_revision_id: null, revision: null })
    globalThis.api.outline.listStoryOutlineRevisions.mockResolvedValue({ items: [], total: 0 })
    globalThis.api.world.listCharacters.mockResolvedValue({ items: [] })
    globalThis.api.world.listEntities.mockResolvedValue({ items: [] })

    const { loadStoryOutlineProps: loadProps } = await import("../../../../vue/views/outline/story/storyOutlineData.js")
    await loadProps("p1")

    expect(workflowMocks.recoverActiveWorkflows).toHaveBeenCalledOnce()
    expect(workflowMocks.recoverActiveWorkflows).toHaveBeenCalledWith("p1")
  })
})

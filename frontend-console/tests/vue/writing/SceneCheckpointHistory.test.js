import { mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import SceneCheckpointHistory from "../../../vue/views/writing/components/SceneCheckpointHistory.vue"

function historyPayload() {
  return {
    novel_id: "p1",
    scene_id: "scene-1",
    total: 3,
    items: [
      { checkpoint_id: "cp-2", dimension: "entities", chapter_index: 2, version: 2, scene_sequence: 3, is_current: true, has_field_provenance: true, created_at: "2026-10-07T12:00:00Z", label: "当前版本" },
      { checkpoint_id: "cp-3", dimension: "locations", chapter_index: 2, version: 2, scene_sequence: 3, is_current: true, has_field_provenance: true, created_at: "2026-10-07T12:00:01Z", label: "当前版本" },
      { checkpoint_id: "cp-1", dimension: "entities", chapter_index: 2, version: 1, scene_sequence: 3, is_current: false, has_field_provenance: false, created_at: "2026-10-06T09:00:00Z", label: "历史版本" },
    ],
  }
}

function mountHistory() {
  return mount(SceneCheckpointHistory, {
    props: { projectId: "p1", sceneId: "scene-1" },
  })
}

describe("SceneCheckpointHistory", () => {
  beforeEach(() => {
    setBridgeOverrides({})
  })
  afterEach(() => {
    resetBridgeOverrides()
    vi.restoreAllMocks()
  })

  it("stays collapsed until the author asks for history", () => {
    const sceneCheckpointHistory = vi.fn()
    setBridgeOverrides({ api: { story: { sceneCheckpointHistory } } })
    const wrapper = mountHistory()

    expect(wrapper.get("details").attributes("open")).toBeUndefined()
    expect(sceneCheckpointHistory).not.toHaveBeenCalled()
  })

  it("lists version batches with current/history semantics kept apart", async () => {
    const sceneCheckpointHistory = vi.fn().mockResolvedValue(historyPayload())
    setBridgeOverrides({ api: { story: { sceneCheckpointHistory } } })
    const wrapper = mountHistory()

    await wrapper.get(".scene-checkpoint-history__load button").trigger("click")

    expect(sceneCheckpointHistory).toHaveBeenCalledWith("p1", "scene-1")
    const items = wrapper.findAll(".scene-checkpoint-history__list li")
    expect(items).toHaveLength(2)
    expect(items[0].classes()).toContain("is-current")
    expect(items[0].text()).toContain("当前版本")
    expect(items[0].text()).toContain("第 2 章")
    expect(items[0].text()).toContain("第 2 次整理")
    expect(items[0].text()).toContain("人物与对象、空间与位置")
    expect(items[1].text()).toContain("历史版本")
  })

  it("explains old records without field tracking instead of faking sources", async () => {
    const sceneCheckpointHistory = vi.fn().mockResolvedValue(historyPayload())
    setBridgeOverrides({ api: { story: { sceneCheckpointHistory } } })
    const wrapper = mountHistory()

    await wrapper.get(".scene-checkpoint-history__load button").trigger("click")
    const historyItem = wrapper.findAll(".scene-checkpoint-history__list li")[1]

    expect(historyItem.text()).toContain("这个版本早于逐字段来源功能上线，没有每个字段的依据记录；可回看当时的整体依据。")
  })

  it("reopens a record through the existing checkpoint source path", async () => {
    const sceneCheckpointHistory = vi.fn().mockResolvedValue(historyPayload())
    setBridgeOverrides({ api: { story: { sceneCheckpointHistory } } })
    const wrapper = mountHistory()

    await wrapper.get(".scene-checkpoint-history__load button").trigger("click")
    await wrapper.findAll(".scene-checkpoint-history__actions button")[2].trigger("click")

    expect(wrapper.emitted("source")).toEqual([[{ checkpoint_id: "cp-1" }]])
  })

  it("shows the empty state after loading an empty list", async () => {
    const sceneCheckpointHistory = vi.fn().mockResolvedValue({ items: [], total: 0 })
    setBridgeOverrides({ api: { story: { sceneCheckpointHistory } } })
    const wrapper = mountHistory()

    await wrapper.get(".scene-checkpoint-history__load button").trigger("click")

    expect(wrapper.text()).toContain("本场还没有历史版本记录；状态整理后会产生可回看的版本。")
  })

  it("keeps errors actionable without dropping the retry entry", async () => {
    const sceneCheckpointHistory = vi.fn().mockRejectedValue(new Error("网络暂时不可用"))
    setBridgeOverrides({ api: { story: { sceneCheckpointHistory } } })
    const wrapper = mountHistory()

    await wrapper.get(".scene-checkpoint-history__load button").trigger("click")

    expect(wrapper.text()).toContain("网络暂时不可用")
    expect(wrapper.get(".scene-checkpoint-history__load button").text()).toContain("查看历史版本")
  })
})

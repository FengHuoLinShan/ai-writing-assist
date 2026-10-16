import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"
import StoryFactTimelinePanel from "../../../../vue/views/outline/components/StoryFactTimelinePanel.vue"

let wrapper

function resultFor(projectId) {
  return {
    items: [{
      id: `${projectId}-event-1`,
      event_type: "entity_updated",
      time_status: "current",
      current_scene_index: 2,
      current_chapter_index: 1,
      entity_label: "阿蘅",
      entity_type: "character",
      source: "author",
      created_at: "2026-10-16T00:00:00Z",
      snapshot_before: { state: "在桥边" },
      snapshot_after: { state: "拿到钥匙" },
    }],
    total: 51,
    unknown_time_count: 1,
    pending_revalidation_count: 0,
    pending_revalidations: [],
    source_options: ["author"],
    entity_options: [{ entity_id: `${projectId}-entity-1`, entity_type: "character", label: "阿蘅" }],
    scene_options: [{ scene_id: `${projectId}-scene-2`, scene_index: 2, title: "桥边相遇" }],
  }
}

describe("StoryFactTimelinePanel", () => {
  let api

  beforeEach(() => {
    api = {
      storyTimeline: {
        listFacts: vi.fn()
          .mockRejectedValueOnce(new Error("网络暂时不可用"))
          .mockImplementation(async (projectId) => resultFor(projectId)),
      },
    }
    setBridgeOverrides({ api })
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    resetBridgeOverrides()
    document.body.replaceChildren()
  })

  it("读取已发生事实，失败可重试，支持截止、对象、来源、状态和分页并隔离项目切换", async () => {
    wrapper = mount(StoryFactTimelinePanel, {
      attachTo: document.body,
      props: { projectId: "project-1" },
    })
    const details = wrapper.get("details").element
    details.open = true
    await wrapper.get("details").trigger("toggle")
    await flushPromises()

    expect(api.storyTimeline.listFacts).toHaveBeenCalledWith("project-1", {
      entityId: null,
      cutoffSceneId: null,
      source: null,
      status: null,
      skip: 0,
      limit: 50,
    })
    expect(wrapper.get('[role="alert"]').text()).toContain("网络暂时不可用")

    await wrapper.get(".story-fact-timeline__filters").trigger("submit")
    await flushPromises()
    expect(wrapper.text()).toContain("拿到钥匙")
    expect(wrapper.text()).toContain("1 条事件没有可确认的 Scene 时间")
    expect(wrapper.text()).not.toContain("project-1-entity-1")

    const filters = wrapper.findAll(".story-fact-timeline__filters select")
    await filters[0].setValue("project-1-scene-2")
    await filters[1].setValue("project-1-entity-1")
    await filters[2].setValue("author")
    await filters[3].setValue("current")
    await wrapper.get(".story-fact-timeline__filters").trigger("submit")
    await flushPromises()
    expect(api.storyTimeline.listFacts).toHaveBeenLastCalledWith("project-1", {
      entityId: "project-1-entity-1",
      cutoffSceneId: "project-1-scene-2",
      source: "author",
      status: "current",
      skip: 0,
      limit: 50,
    })

    await wrapper.findAll("button").find((button) => button.text() === "下一页").trigger("click")
    await flushPromises()
    expect(api.storyTimeline.listFacts).toHaveBeenLastCalledWith("project-1", {
      entityId: "project-1-entity-1",
      cutoffSceneId: "project-1-scene-2",
      source: "author",
      status: "current",
      skip: 50,
      limit: 50,
    })

    await wrapper.setProps({ projectId: "project-2" })
    await flushPromises()
    expect(api.storyTimeline.listFacts).toHaveBeenLastCalledWith("project-2", {
      entityId: null,
      cutoffSceneId: null,
      source: null,
      status: null,
      skip: 0,
      limit: 50,
    })
    expect(wrapper.text()).toContain("拿到钥匙")
    expect(wrapper.text()).not.toContain("project-1-scene-2")
  })
})

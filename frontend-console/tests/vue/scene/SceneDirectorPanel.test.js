import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import SceneDirectorPanel from "../../../vue/views/scene/SceneDirectorPanel.vue"

const history = (name) => ({
  roots: [],
  branches: [],
  rounds: [],
  references: [{
    id: `ref-${name}`,
    name,
    annotation: "",
    content_copy: { materials: [] },
    source_deleted: false,
    source_changed: false,
  }],
  recoverable_branches: [],
  recoverable_references: [],
})

describe("SceneDirectorPanel", () => {
  let api
  let wrappers

  beforeEach(() => {
    sessionStorage.clear()
    wrappers = []
    api = {
      world: { listEntities: vi.fn(async () => ({ items: [], total: 0 })) },
      story: {
        sceneDirectorHistory: vi.fn(async (_projectId, sceneId) => history(sceneId)),
        previewSceneDirectorBudget: vi.fn(),
      },
    }
    setBridgeOverrides({ api })
  })

  afterEach(() => {
    for (const wrapper of wrappers) wrapper.unmount()
    resetBridgeOverrides()
  })

  function mountPanel(sceneId, overrides = {}) {
    const wrapper = mount(SceneDirectorPanel, {
      props: {
        projectId: "project-a",
        scene: { id: sceneId, title: `Scene ${sceneId}` },
        characters: [{ id: "actor-a", name: "阿澄" }],
        visible: true,
        ...overrides,
      },
    })
    wrappers.push(wrapper)
    return wrapper
  }

  it("ignores late history responses after switching the current Scene", async () => {
    let resolveOld
    api.story.sceneDirectorHistory.mockImplementation((_projectId, sceneId) => (
      sceneId === "scene-a"
        ? new Promise((resolve) => { resolveOld = resolve })
        : Promise.resolve(history("new-scene-reference"))
    ))
    const wrapper = mountPanel("scene-a")
    await flushPromises()
    expect(api.story.sceneDirectorHistory).toHaveBeenCalledWith("project-a", "scene-a")

    await wrapper.setProps({ scene: { id: "scene-b", title: "Scene scene-b" } })
    await flushPromises()
    expect(wrapper.text()).toContain("new-scene-reference")

    resolveOld(history("stale-scene-reference"))
    await flushPromises()
    expect(wrapper.text()).toContain("new-scene-reference")
    expect(wrapper.text()).not.toContain("stale-scene-reference")
    expect(wrapper.attributes("data-director-scene")).toBe("scene-b")
  })

  it("pages the real 50-item character API without imposing a participant cap", async () => {
    const people = Array.from({ length: 51 }, (_, index) => ({
      id: `actor-${index}`, name: `人物 ${index}`,
    }))
    api.world.listEntities.mockImplementation(async ({ skip, limit }) => {
      if (limit > 50) throw new Error("query.limit must be less than or equal to 50")
      return { items: people.slice(skip, skip + limit), total: people.length }
    })
    const wrapper = mountPanel("scene-a", { characters: [] })
    await flushPromises()
    expect(api.world.listEntities).toHaveBeenCalledTimes(2)
    expect(api.world.listEntities).toHaveBeenLastCalledWith(expect.objectContaining({ skip: 50, limit: 50 }))
    expect(wrapper.findAll('.scene-director__person')).toHaveLength(51)
  })

  it("keeps inputs after a preview conflict and allows an explicit retry", async () => {
    api.story.previewSceneDirectorBudget
      .mockRejectedValueOnce(Object.assign(new Error("资料已经变化"), { status: 409 }))
      .mockResolvedValueOnce({
        preview_hash: "a".repeat(64),
        request_count: { minimum: 4, maximum: 4 },
        token_count: { minimum: 100, maximum: 300 },
        time_seconds: { minimum: 8, maximum: 100 },
        possible_charge: "开始模型请求后可能产生计费请求；不估算或显示金额",
        rounds: 1,
        participants: 1,
        omitted: [],
        warnings: [],
      })
    const wrapper = mountPanel("scene-a")
    await flushPromises()
    const panel = wrapper.find(".scene-director__setup")
    await panel.find('.scene-director__participants input[type="checkbox"]').setValue(true)
    await panel.findAll("textarea")[1].setValue("只供导演留意的节奏")
    const numbers = panel.findAll('input[type="number"]')
    await numbers[1].setValue("12")
    await numbers[2].setValue("5000")
    await numbers[3].setValue("30")

    const preview = () => panel.findAll("button").find((button) => button.text() === "预览请求与用量")
    await preview().trigger("click")
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain("资料已经变化")
    expect(numbers[1].element.value).toBe("12")
    expect(panel.findAll("textarea")[1].element.value).toBe("只供导演留意的节奏")

    await preview().trigger("click")
    await flushPromises()
    expect(api.story.previewSceneDirectorBudget).toHaveBeenCalledTimes(2)
    expect(api.story.previewSceneDirectorBudget).toHaveBeenLastCalledWith("project-a", expect.objectContaining({
      scene_id: "scene-a",
      character_ids: ["actor-a"],
      instructions: "只供导演留意的节奏",
    }))
    expect(wrapper.text()).toContain("预算按当前场景与人物资料指纹计算")
  })

  it("retains per-project, per-Scene inputs after the panel is remounted", async () => {
    const first = mountPanel("scene-a")
    const panel = first.find(".scene-director__setup")
    await panel.findAll("textarea")[0].setValue("共同听见的钟声")
    await panel.findAll("textarea")[1].setValue("仅导演可见的停顿")

    first.unmount()
    wrappers = wrappers.filter((item) => item !== first)
    const second = mountPanel("scene-a", { visible: false })
    expect(second.findAll("textarea")[0].element.value).toBe("共同听见的钟声")
    expect(second.findAll("textarea")[1].element.value).toBe("仅导演可见的停顿")
    expect(api.story.sceneDirectorHistory).toHaveBeenCalledTimes(1)
  })

  it("opens a mobile full-screen workspace and closes it with Escape", async () => {
    const originalMatchMedia = window.matchMedia
    window.matchMedia = vi.fn(() => ({ matches: true }))
    try {
      const wrapper = mountPanel("scene-a", { visible: false })
      await wrapper.setProps({ visible: true })
      expect(wrapper.classes()).toContain("is-fullscreen")
      expect(
        wrapper
          .find(".scene-director__header-actions button")
          .attributes("aria-pressed"),
      ).toBe("true")

      await wrapper.trigger("keydown", { key: "Escape" })
      expect(wrapper.classes()).not.toContain("is-fullscreen")
    } finally {
      window.matchMedia = originalMatchMedia
    }
  })
})

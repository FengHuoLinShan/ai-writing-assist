import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"

const referencePicker = vi.hoisted(() => ({
  create: vi.fn(() => ({ destroy: vi.fn(), resolve: vi.fn(), setItems: vi.fn() })),
}))
vi.mock("../../../shared/referencePicker.js", () => ({ createReferencePicker: referencePicker.create }))

import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import TaskContextTab from "../../../vue/views/generate/components/TaskContextTab.vue"

describe("task context reference search", () => {
  let api
  let wrapper

  beforeEach(() => {
    referencePicker.create.mockClear()
    api = {
      world: { listEntities: vi.fn(), getEntity: vi.fn() },
      outline: { getSceneWorkbench: vi.fn(), listScenesByChapter: vi.fn(), getScene: vi.fn() },
    }
    setBridgeOverrides({ api })
    wrapper = mount(TaskContextTab, {
      props: {
        projectId: "p1",
        preset: "custom",
        form: {
          task: "核对线索", scope: "chapter", entity_ids: [], character_ids: [], chapter_index: 3,
          scene_id: "", budget_tokens: 0, reveal_mode: "author_safe", include_world_synopsis: true,
          viewpoint_character_id: "",
        },
        bundle: null, markdown: "", pending: false, error: "",
      },
    })
  })

  afterEach(() => {
    wrapper?.unmount()
    resetBridgeOverrides()
  })

  it("scopes entity and character searches to the requested project", async () => {
    const configs = referencePicker.create.mock.calls.map(([config]) => config)
    const entitySource = configs.find((config) => config.sources[0].kind === "entity").sources[0]
    const characterSource = configs.find((config) => config.sources[0].kind === "character").sources[0]
    api.world.listEntities
      .mockResolvedValueOnce({ items: [
        { id: "e1", name: "雾港", entity_type: "location", display_state: "active" },
        { id: "c1", name: "秦岚", entity_type: "character", display_state: "active" },
      ] })
      .mockResolvedValueOnce({ items: [{ id: "c1", name: "秦岚", entity_type: "character", display_state: "active" }] })

    const entities = await entitySource.search("雾", { projectId: "p1", limit: 8 })
    const characters = await characterSource.search("秦", { projectId: "p1", limit: 6 })

    expect(entities.map((item) => item.id)).toEqual(["e1"])
    expect(characters.map((item) => item.id)).toEqual(["c1"])
    expect(api.world.listEntities).toHaveBeenNthCalledWith(1, {
      novel_id: "p1", display_state: "active", q: "雾", skip: 0, limit: 8,
    })
    expect(api.world.listEntities).toHaveBeenNthCalledWith(2, {
      novel_id: "p1", display_state: "active", entity_type: "character", q: "秦", skip: 0, limit: 6,
    })
  })

  it("prioritizes matching scenes from the selected chapter and excludes history", async () => {
    const sceneSource = referencePicker.create.mock.calls
      .map(([config]) => config)
      .find((config) => config.sources[0].kind === "scene").sources[0]
    api.outline.getSceneWorkbench.mockResolvedValue({ items: [
      { scene: { id: "project", title: "门外支援", status: "draft", chapter_ids: [4] } },
      { scene: { id: "history", title: "旧门", status: "deprecated", chapter_ids: [3] } },
    ] })
    api.outline.listScenesByChapter.mockResolvedValue([
      { id: "chapter", title: "石门内", status: "draft", chapter_ids: [3] },
      { id: "noise", title: "无关", status: "draft", chapter_ids: [3] },
    ])

    const results = await sceneSource.search("门", { projectId: "p1", limit: 5 })

    expect(results.map((item) => item.id)).toEqual(["chapter", "project"])
    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", null, {
      q: "门", view_mode: "normal", skip: 0, limit: 5,
    })
    expect(api.outline.listScenesByChapter).toHaveBeenCalledWith("p1", 3)
  })
})

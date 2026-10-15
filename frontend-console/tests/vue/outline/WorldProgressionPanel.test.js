import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import WorldProgressionPanel from "../../../vue/views/outline/components/WorldProgressionPanel.vue"

function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

function makeApi({ preview = vi.fn(async () => ({})), charactersByProject = {} } = {}) {
  return {
    world: {
      listCharacters: vi.fn(async (params) => {
        const rows = charactersByProject[params.novel_id] || []
        return { items: rows.slice(params.skip, params.skip + 50), total: rows.length }
      }),
      listEntities: vi.fn(async () => ({ items: [], total: 0 })),
    },
    outline: {
      listArcs: vi.fn(async () => ({ items: [], total: 0 })),
      listThreads: vi.fn(async () => ({ items: [], total: 0 })),
      listScenes: vi.fn(async () => ({ items: [], total: 0 })),
    },
    story: {
      previewWorldProgressionBudget: preview,
      worldProgressionHistory: vi.fn(async () => ({ roots: [] })),
    },
    assistant: {
      capabilities: vi.fn(async () => ({ guided_flows: { available: false } })),
    },
  }
}

const actor = (name, index) => ({
  id: "character-" + index,
  name,
  entity_type: "character",
})

let wrappers

beforeEach(() => {
  wrappers = []
  setBridgeOverrides({
    state: { currentProjectId: "project-a" },
    confirm: () => true,
  })
})

afterEach(() => {
  for (const wrapper of wrappers) wrapper.unmount()
  resetBridgeOverrides()
})

function mountPanel(api, projectId = "project-a") {
  setBridgeOverrides({ api })
  const wrapper = mount(WorldProgressionPanel, { props: { projectId } })
  wrappers.push(wrapper)
  return wrapper
}

async function openPanel(wrapper) {
  await wrapper.get(".world-progression__toggle").trigger("click")
  await flushPromises()
}

describe("WorldProgressionPanel", () => {
  it("先显示加载态，默认选十二位且允许作者继续增加参与者", async () => {
    const pending = deferred()
    const api = makeApi()
    api.world.listCharacters.mockImplementationOnce(() => pending.promise)
    const wrapper = mountPanel(api)
    await wrapper.get(".world-progression__toggle").trigger("click")
    expect(wrapper.get('[role="status"]').text()).toContain("正在读取")
    pending.resolve({ items: Array.from({ length: 13 }, (_, index) => actor("人物" + (index + 1), index)), total: 13 })
    await flushPromises()
    expect(wrapper.text()).toContain("已选择 12 位")
    const checkboxes = wrapper.findAll('.world-progression__participant input[type="checkbox"]')
    expect(checkboxes).toHaveLength(13)
    await checkboxes[12].setValue(true)
    expect(wrapper.text()).toContain("已选择 13 位")
  })

  it("参与者为空时提供明确空态", async () => {
    const wrapper = mountPanel(makeApi())
    await openPanel(wrapper)
    expect(wrapper.text()).toContain("还没有可证明的人物或群体身份")
    expect(wrapper.findAll('.world-progression__participant input[type="checkbox"]')).toHaveLength(0)
  })

  it("预算预览返回 409 时保留作者草稿并提示重新预览", async () => {
    const preview = vi.fn(async () => {
      throw Object.assign(new Error("basis changed"), { status: 409 })
    })
    const api = makeApi({ preview, charactersByProject: { "project-a": [actor("林澈", 1)] } })
    const wrapper = mountPanel(api)
    await openPanel(wrapper)
    const constraint = wrapper.findAll("textarea").find((item) => item.attributes("placeholder")?.includes("不要让"))
    await constraint.setValue("保留这条作者约束")
    const previewButton = wrapper.findAll("button").find((button) => button.text().includes("预算与资料"))
    await previewButton.trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("重新预览")
    expect(constraint.element.value).toBe("保留这条作者约束")
    expect(api.story.previewWorldProgressionBudget).toHaveBeenCalledTimes(1)
  })

  it("作品切换后丢弃旧预算响应，保留新作品数据", async () => {
    const oldPreview = deferred()
    const preview = vi.fn((projectId) => (
      projectId === "project-a"
        ? oldPreview.promise
        : Promise.resolve({ preview_hash: "new", scene_id: "scene-b" })
    ))
    const api = makeApi({
      preview,
      charactersByProject: {
        "project-a": [actor("旧作品人物", 1)],
        "project-b": [actor("新作品人物", 2)],
      },
    })
    const wrapper = mountPanel(api)
    await openPanel(wrapper)
    const previewButton = wrapper.findAll("button").find((button) => button.text().includes("预算与资料"))
    await previewButton.trigger("click")
    expect(preview).toHaveBeenCalledTimes(1)

    setBridgeOverrides({ state: { currentProjectId: "project-b" } })
    await wrapper.setProps({ projectId: "project-b" })
    await flushPromises()
    oldPreview.resolve({ preview_hash: "old", scene_id: "scene-a" })
    await flushPromises()

    expect(wrapper.text()).toContain("新作品人物")
    expect(wrapper.text()).not.toContain("旧作品人物")
    expect(wrapper.find("#progression-preview-title").exists()).toBe(false)
  })

  it("交汇可以准备带候选假设的导演起点并先预览独立预算", async () => {
    const api = makeApi({
      charactersByProject: {
        "project-a": [actor("林澈", 1), actor("沈闻", 2)],
      },
    })
    api.story.worldProgressionHistory = vi.fn(async () => ({
      roots: [
        {
          id: "root-1",
          scene_id: "scene-1",
          created_at: "2026-10-16T00:00:00Z",
          status: "complete",
          request: {
            mode: "free",
            participants: [
              { id: "character-1", kind: "character" },
              { id: "character-2", kind: "character" },
            ],
          },
          budget: {},
          branches: [
            {
              id: "branch-1",
              branch_kind: "start",
              status: "complete",
              steps: [
                {
                  id: "step-1",
                  step_number: 1,
                  created_at: "2026-10-16T00:00:00Z",
                  result: {
                    narrative_summary: "两人在渡口停下交涉。",
                    actor_intents: [],
                    intent_outcomes: [],
                    intersections: {
                      items: [
                        {
                          intersection_id: "intersection-1",
                          actor_ids: ["character-1", "character-2"],
                          kinds: ["same_location_target"],
                          route_ids: [],
                        },
                      ],
                      route_note: "没有可用地图路线",
                    },
                    intersection_outcomes: [
                      {
                        intersection_id: "intersection-1",
                        description: "交涉结果仍为候选假设。",
                      },
                    ],
                    state_delta: [],
                  },
                  metrics: {},
                },
              ],
            },
          ],
        },
      ],
    }))
    api.story.readWorldProgressionContinuousAuthorization = vi.fn(async () => ({
      root_id: "root-1",
      branch_id: "branch-1",
      enabled: false,
      revision: 0,
    }))
    api.story.previewSceneDirectorBudget = vi.fn(async () => ({
      preview_hash: "d".repeat(64),
      token_budget: { estimate_minimum: 100, estimate_maximum: 200 },
      fee_status: "可能计费",
    }))
    const wrapper = mountPanel(api)
    await openPanel(wrapper)
    expect(wrapper.text()).toContain("交涉结果仍为候选假设")
    await wrapper.findAll("button").find((button) => button.text().includes("准备导演起点")).trigger("click")
    const panel = wrapper.get(".world-progression__director-draft")
    expect(panel.find("textarea").element.value).toContain("作者选择的世界推进交汇起点")
    expect(panel.text()).toContain("未被当作已发生事实")
    const previewButton = panel.findAll("button").find((button) => button.text().includes("预算"))
    await previewButton.trigger("click")
    await flushPromises()
    expect(api.story.previewSceneDirectorBudget).toHaveBeenCalledTimes(1)
    expect(panel.text()).toContain("100–200 Token")
    expect(panel.text()).toContain("确认并开始导演候选")
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import WorldProgressionPanel from "../../../vue/views/outline/components/WorldProgressionPanel.vue"

vi.mock("../../../shared/aiReferenceModal.js", () => ({
  confirmAiReference: vi.fn(async () => ({ id: "confirmation-hook" })),
}))
import { confirmAiReference } from "../../../shared/aiReferenceModal.js"

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
      startWorldProgression: vi.fn(async () => ({ task_id: "task-1", root_id: "root-1" })),
      worldProgressionHistory: vi.fn(async () => ({ roots: [] })),
    },
    tasks: { get: vi.fn(async () => ({ status: "running" })) },
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
  confirmAiReference.mockReset()
  confirmAiReference.mockResolvedValue({ id: "confirmation-hook" })
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
      return { requires_context_confirmation: true, scene_id: "scene-1" }
    }).mockResolvedValueOnce({ requires_context_confirmation: true, scene_id: "scene-1" })
      .mockRejectedValueOnce(Object.assign(new Error("basis changed"), { status: 409 }))
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
    expect(api.story.previewWorldProgressionBudget).toHaveBeenCalledTimes(2)
  })

  it("先确认预算预览的资料范围，并在启动时复用同一确认", async () => {
    const preview = vi.fn()
      .mockResolvedValueOnce({ requires_context_confirmation: true, scene_id: "scene-1" })
      .mockResolvedValueOnce({ preview_hash: "preview-hash", scene_id: "scene-1" })
    const api = makeApi({ preview, charactersByProject: { "project-a": [actor("林澈", 1)] } })
    const wrapper = mountPanel(api)
    await openPanel(wrapper)

    await wrapper.findAll("button").find((button) => button.text().includes("预算与资料")).trigger("click")
    await flushPromises()

    expect(confirmAiReference).toHaveBeenCalledOnce()
    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({ scene_id: "scene-1" }))
    expect(preview.mock.calls[1][1]).toMatchObject({
      scene_id: "scene-1",
      context_confirmation_id: "confirmation-hook",
    })
    await wrapper.findAll("button").find((button) => button.text().includes("按已确认资料推进")).trigger("click")
    await flushPromises()

    expect(api.story.startWorldProgression).toHaveBeenCalledWith("project-a", expect.objectContaining({
      context_confirmation_id: "confirmation-hook",
      budget_preview_hash: "preview-hash",
    }))
    expect(confirmAiReference).toHaveBeenCalledOnce()
  })

  it("页头提供在助手中探索入口并携带大纲上下文", async () => {
    const opener = vi.fn(async () => ({}))
    setBridgeOverrides({ state: { currentProjectId: "project-a" }, assistantOpener: opener })
    const wrapper = mountPanel(makeApi())
    const assist = wrapper.findAll("button").find((button) => button.text() === "在助手中探索")
    expect(assist).toBeTruthy()
    await assist.trigger("click")
    await flushPromises()
    expect(opener).toHaveBeenCalledTimes(1)
    expect(opener.mock.calls[0][0]).toMatchObject({
      projectId: "project-a",
      context: { page: "outline", scope: "current", task_hint: "design" },
    })
  })

  it("助手未就绪时提示错误且不影响推进面板", async () => {
    const toast = vi.fn()
    setBridgeOverrides({
      state: { currentProjectId: "project-a" },
      assistantOpener: vi.fn(async () => {
        throw new Error("项目助手正在准备，请稍后从顶部打开。")
      }),
      toast,
    })
    const wrapper = mountPanel(makeApi())
    await wrapper.findAll("button").find((button) => button.text() === "在助手中探索").trigger("click")
    await flushPromises()
    expect(toast).toHaveBeenCalledWith("项目助手正在准备，请稍后从顶部打开。", "error")
    expect(wrapper.text()).toContain("世界推进")
    await openPanel(wrapper)
    expect(wrapper.text()).toContain("选择参与者")
  })

  it("原资料截止 Scene 变化后展示停止原因和恢复入口提示", async () => {
    const api = makeApi({
      charactersByProject: { "project-a": [actor("林澈", 1)] },
    })
    api.story.worldProgressionHistory = vi.fn(async () => ({
      roots: [{
        id: "root-1",
        scene_id: "scene-old",
        status: "complete",
        request: { participants: [{ id: "character-1", kind: "character" }] },
        branches: [{ id: "branch-1", branch_kind: "start", status: "complete", steps: [] }],
      }],
    }))
    api.story.readWorldProgressionContinuousAuthorization = vi.fn(async () => ({
      root_id: "root-1",
      branch_id: "branch-1",
      enabled: false,
      stop_reason: "confirmation_scope_changed",
      revision: 2,
    }))
    const wrapper = mountPanel(api)

    await openPanel(wrapper)

    expect(wrapper.text()).toContain(
      "资料截止点已变化，请从最新 Scene 新建推进并重新开启持续提醒。",
    )
    expect(wrapper.findAll("button").some((button) => button.text().includes("确认持续授权"))).toBe(false)
    expect(wrapper.findAll("button").some((button) => button.text().includes("预览预算与资料"))).toBe(true)
  })

  it("无持续授权时可首次授权，关闭后仍可重新开启", async () => {
    const api = makeApi({
      charactersByProject: { "project-a": [actor("林澈", 1)] },
    })
    api.story.worldProgressionHistory = vi.fn(async () => ({
      roots: [{
        id: "root-1",
        scene_id: "scene-1",
        request: { participants: [{ id: "character-1", kind: "character" }] },
        branches: [{ id: "branch-1", branch_kind: "start", status: "complete", steps: [] }],
      }],
    }))
    api.story.readWorldProgressionContinuousAuthorization = vi.fn(async () => ({
      root_id: null,
      branch_id: null,
      enabled: false,
      revision: 0,
    }))
    api.story.setWorldProgressionContinuousAuthorization = vi.fn()
      .mockResolvedValueOnce({
        root_id: "root-1", branch_id: "branch-1", enabled: true,
        revision: 1, participant_ids: ["character-1"], every_new_chapters: 3,
      })
      .mockResolvedValueOnce({
        root_id: null, branch_id: null, enabled: false,
        revision: 2, participant_ids: [], every_new_chapters: 3,
      })
    const wrapper = mountPanel(api)

    await openPanel(wrapper)
    let section = wrapper.get(".world-progression__continuous")
    await section.find('input[type="checkbox"]').setValue(true)
    await section.findAll("button").find((button) => button.text().includes("确认持续授权")).trigger("click")
    await flushPromises()
    expect(api.story.setWorldProgressionContinuousAuthorization).toHaveBeenNthCalledWith(
      1,
      "root-1",
      "branch-1",
      expect.objectContaining({ enabled: true, participant_ids: ["character-1"] }),
    )

    section = wrapper.get(".world-progression__continuous")
    await section.findAll("button").find((button) => button.text().includes("关闭持续授权")).trigger("click")
    await flushPromises()
    expect(api.story.setWorldProgressionContinuousAuthorization).toHaveBeenNthCalledWith(
      2,
      "root-1",
      "branch-1",
      expect.objectContaining({ enabled: false, participant_ids: [] }),
    )
    expect(wrapper.findAll(".world-progression__continuous")).toHaveLength(1)
    expect(wrapper.get(".world-progression__continuous").text()).toContain("确认持续授权")
  })

  it("授权绑定旧根时仍能找到并关闭，关闭后新根显示授权入口", async () => {
    const api = makeApi({
      charactersByProject: { "project-a": [actor("林澈", 1)] },
    })
    const branch = (id) => ({ id, branch_kind: "start", status: "complete", steps: [] })
    api.story.worldProgressionHistory = vi.fn(async () => ({
      roots: [
        { id: "root-b", scene_id: "scene-b", request: { participants: [{ id: "character-1" }] }, branches: [branch("branch-b")] },
        { id: "root-a", scene_id: "scene-a", request: { participants: [{ id: "character-1" }] }, branches: [branch("branch-a")] },
      ],
    }))
    api.story.readWorldProgressionContinuousAuthorization = vi.fn(async () => ({
      root_id: "root-a", branch_id: "branch-a", enabled: true,
      revision: 3, participant_ids: ["character-1"], every_new_chapters: 2,
    }))
    api.story.setWorldProgressionContinuousAuthorization = vi.fn(async () => ({
      root_id: null, branch_id: null, enabled: false, revision: 4,
      participant_ids: [], every_new_chapters: 2,
    }))
    const wrapper = mountPanel(api)

    await openPanel(wrapper)
    expect(api.story.readWorldProgressionContinuousAuthorization).toHaveBeenCalledWith(
      "project-a", "root-b", "branch-b",
    )
    expect(wrapper.findAll(".world-progression__continuous")).toHaveLength(1)
    await wrapper.get(".world-progression__continuous").findAll("button")
      .find((button) => button.text().includes("关闭持续授权")).trigger("click")
    await flushPromises()

    expect(api.story.setWorldProgressionContinuousAuthorization).toHaveBeenCalledWith(
      "root-a", "branch-a", expect.objectContaining({ enabled: false, expected_revision: 3 }),
    )
    expect(wrapper.findAll(".world-progression__continuous")).toHaveLength(1)
    expect(wrapper.get(".world-progression__continuous").text()).toContain("确认持续授权")
  })

  it("自动停止后在新根显式重新授权，并使用当前授权版本", async () => {
    const api = makeApi({
      charactersByProject: {
        "project-a": [actor("旧根人物", 1), actor("新根人物", 2)],
      },
    })
    const branch = (id) => ({ id, branch_kind: "start", status: "complete", steps: [] })
    api.story.worldProgressionHistory = vi.fn(async () => ({
      roots: [
        {
          id: "root-b",
          scene_id: "scene-b",
          request: { participants: [{ id: "character-2", kind: "character" }] },
          branches: [branch("branch-b")],
        },
        {
          id: "root-a",
          scene_id: "scene-a",
          request: { participants: [{ id: "character-1", kind: "character" }] },
          branches: [branch("branch-a")],
        },
      ],
    }))
    api.story.readWorldProgressionContinuousAuthorization = vi.fn(async () => ({
      root_id: "root-a",
      branch_id: "branch-a",
      enabled: false,
      stop_reason: "confirmation_scope_changed",
      revision: 5,
      participant_ids: ["character-1"],
      every_new_chapters: 2,
    }))
    api.story.setWorldProgressionContinuousAuthorization = vi.fn(async () => ({
      root_id: "root-b",
      branch_id: "branch-b",
      enabled: true,
      revision: 6,
      participant_ids: ["character-2"],
      every_new_chapters: 2,
    }))
    const wrapper = mountPanel(api)

    await openPanel(wrapper)
    const sections = wrapper.findAll(".world-progression__continuous")
    expect(sections).toHaveLength(2)
    expect(sections[1].text()).toContain("资料截止点已变化")
    expect(sections[0].text()).toContain("确认后，新授权将绑定到当前推进根")
    expect(sections[0].text()).toContain("已停止")
    expect(api.story.setWorldProgressionContinuousAuthorization).not.toHaveBeenCalled()

    await sections[0].find('input[type="checkbox"][value="character-2"]').setValue(true)
    await sections[0].findAll("button")
      .find((button) => button.text().includes("确认持续授权"))
      .trigger("click")
    await flushPromises()

    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({
      scene_id: "scene-b",
      visible_until_scene_id: "scene-b",
      character_ids: ["character-2"],
    }))
    expect(api.story.setWorldProgressionContinuousAuthorization).toHaveBeenCalledWith(
      "root-b",
      "branch-b",
      expect.objectContaining({
        enabled: true,
        participant_ids: ["character-2"],
        expected_revision: 5,
      }),
    )
  })

  it("作品切换后丢弃旧预算响应，保留新作品数据", async () => {
    const oldPreview = deferred()
    const preview = vi.fn((projectId) => (
      projectId === "project-a"
        ? oldPreview.promise
        : Promise.resolve({ requires_context_confirmation: true, scene_id: "scene-b" })
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
    oldPreview.resolve({ requires_context_confirmation: true, scene_id: "scene-a" })
    await flushPromises()

    expect(wrapper.text()).toContain("新作品人物")
    expect(wrapper.text()).not.toContain("旧作品人物")
    expect(wrapper.find("#progression-preview-title").exists()).toBe(false)
  })

  it.each([true, false])("钩子预览成功=%s 后保留已编辑的导演起点与预算", async (success) => {
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
                    plot_hooks: [{ hook_id: "hook-1", title: "渡口争端", summary: "交涉尚未完成", start_chapter: 1, end_chapter: 2 }],
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
    api.story.startSceneDirector = vi.fn(async () => ({ task_id: "director-task" }))
    api.tasks.get = vi.fn(async () => ({ status: "done", terminal: true }))
    api.story.previewWorldProgressionHook = vi.fn(async () => {
      if (!success) throw new Error("钩子读取失败")
      return { window: { start_chapter: 1, end_chapter: 2 }, effect: "只读预览" }
    })
    const wrapper = mountPanel(api)
    await openPanel(wrapper)
    expect(wrapper.text()).toContain("交涉结果仍为候选假设")
    await wrapper.findAll("button").find((button) => button.text().includes("准备导演起点")).trigger("click")
    const panel = wrapper.get(".world-progression__director-draft")
    expect(panel.find("textarea").element.value).toContain("作者选择的世界推进交汇起点")
    expect(panel.text()).toContain("未被当作已发生事实")
    await panel.find("textarea").setValue("保留作者手输的起点假设")
    const previewButton = panel.findAll("button").find((button) => button.text().includes("预算"))
    await previewButton.trigger("click")
    await flushPromises()
    expect(api.story.previewSceneDirectorBudget).toHaveBeenCalledTimes(1)
    expect(panel.text()).toContain("100–200 Token")
    expect(panel.text()).toContain("确认并开始导演候选")
    await wrapper.findAll("button").find((button) => button.text().includes("预览滚动规划窗口")).trigger("click")
    await flushPromises()
    expect(api.story.previewWorldProgressionHook).toHaveBeenCalledTimes(1)
    expect(wrapper.get(".world-progression__director-draft textarea").element.value).toBe("保留作者手输的起点假设")
    expect(wrapper.get(".world-progression__director-draft").text()).toContain("100–200 Token")
    await wrapper.findAll("button").find((button) => button.text().includes("确认并开始导演候选")).trigger("click")
    await flushPromises()
    expect(api.story.startSceneDirector).toHaveBeenCalledOnce()
    expect(api.story.startSceneDirector.mock.calls[0][2].instructions).toBe(
      api.story.previewSceneDirectorBudget.mock.calls[0][1].instructions,
    )
  })

  it("带 output_kind 的探索步骤只渲染占位并指回助手，不影响普通步骤", async () => {
    const api = makeApi({
      charactersByProject: { "project-a": [actor("林澈", 1)] },
    })
    api.story.worldProgressionHistory = vi.fn(async () => ({
      roots: [{
        id: "root-1",
        scene_id: "scene-1",
        status: "complete",
        request: { participants: [{ id: "character-1", kind: "character" }] },
        branches: [{
          id: "branch-1",
          branch_kind: "start",
          status: "complete",
          steps: [
            {
              id: "step-exp",
              step_number: 1,
              created_at: "2026-10-17T00:00:00Z",
              output_kind: "story.exploration.sandbox",
              result: { output_kind: "story.exploration.sandbox", schema_version: 1, payload: { influence_chain: [] } },
              metrics: {},
            },
            {
              id: "step-1",
              step_number: 2,
              created_at: "2026-10-16T00:00:00Z",
              result: { narrative_summary: "两人在渡口停下交涉。", actor_intents: [], state_delta: [] },
              metrics: {},
            },
          ],
        }],
      }],
    }))
    api.story.readWorldProgressionContinuousAuthorization = vi.fn(async () => ({
      root_id: "root-1", branch_id: "branch-1", enabled: false, revision: 0,
    }))
    const wrapper = mountPanel(api)
    await openPanel(wrapper)

    const note = wrapper.get(".world-progression__exploration-note")
    expect(note.text()).toContain("紧凑探索结果")
    expect(note.text()).toContain("沙盘推演")
    expect(note.text()).toContain("项目助手")
    expect(note.element.closest("details").textContent).not.toContain("从这一步继续")
    expect(wrapper.text()).toContain("两人在渡口停下交涉。")
    expect(wrapper.findAll("button").some((button) => button.text().includes("从这一步继续"))).toBe(true)
  })

  it("完整排演与锁定记录探索步骤按 kind 显示占位标签", async () => {
    const api = makeApi({
      charactersByProject: { "project-a": [actor("林澈", 1)] },
    })
    api.story.worldProgressionHistory = vi.fn(async () => ({
      roots: [{
        id: "root-1",
        scene_id: "scene-1",
        status: "complete",
        request: { participants: [{ id: "character-1", kind: "character" }] },
        branches: [{
          id: "branch-1",
          branch_kind: "start",
          status: "complete",
          steps: [
            {
              id: "step-rehearsal",
              step_number: 1,
              created_at: "2026-10-17T00:00:00Z",
              output_kind: "story.exploration.full_rehearsal",
              result: { output_kind: "story.exploration.full_rehearsal", schema_version: 1, payload: { rounds: [] } },
              metrics: {},
            },
            {
              id: "step-lock",
              step_number: 2,
              created_at: "2026-10-16T00:00:00Z",
              output_kind: "story.exploration.lock_set",
              result: { output_kind: "story.exploration.lock_set", schema_version: 1, payload: { locks: [] } },
              metrics: {},
            },
          ],
        }],
      }],
    }))
    api.story.readWorldProgressionContinuousAuthorization = vi.fn(async () => ({
      root_id: "root-1", branch_id: "branch-1", enabled: false, revision: 0,
    }))
    const wrapper = mountPanel(api)
    await openPanel(wrapper)

    const notes = wrapper.findAll(".world-progression__exploration-note")
    expect(notes).toHaveLength(2)
    expect(notes[0].text()).toContain("完整排演")
    expect(notes[1].text()).toContain("锁定记录")
    for (const note of notes) {
      expect(note.text()).toContain("紧凑探索结果")
      expect(note.text()).toContain("项目助手")
      expect(note.element.closest("details").textContent).not.toContain("从这一步继续")
    }
  })
})

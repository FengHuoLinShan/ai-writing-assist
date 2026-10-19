import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import SceneDirectorPanel from "../../../vue/views/scene/SceneDirectorPanel.vue"

vi.mock("../../../shared/aiReferenceModal.js", () => ({
  confirmAiReference: vi.fn(async () => ({ id: "confirmation-a" })),
}))
vi.mock("../../../shared/workflowProgress.js", async (importOriginal) => ({
  ...await importOriginal(),
  pollTaskProgress: vi.fn(() => ({ stop: vi.fn() })),
}))

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
        transferDirectorCandidate: vi.fn(),
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

  it("shows the closed feature state without exposing start controls and can refresh after enabling", async () => {
    api.story.sceneDirectorHistory.mockRejectedValueOnce(Object.assign(new Error("场景导演尚未开启"), { status: 503 }))
    const wrapper = mountPanel("scene-a")
    await flushPromises()
    expect(wrapper.text()).toContain("场景导演尚未开启")
    expect(wrapper.find(".scene-director__setup").exists()).toBe(false)
    const refresh = wrapper.findAll("button").find((button) => button.text().includes("刷新历史"))
    await refresh.trigger("click")
    await flushPromises()
    expect(wrapper.find(".scene-director__setup").exists()).toBe(true)
  })

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

  it.each([
    [0, 0, "advanceSceneDirector"],
    [0, 100, "continueSceneDirector"],
    [2, 0, "continueSceneDirector"],
  ])("routes %s added requests and %s added tokens through %s", async (requests, tokens, method) => {
    api.story.sceneDirectorHistory.mockResolvedValue({
      ...history("scene-a"),
      roots: [{ id: "root-a", character_ids: ["actor-a"] }],
      branches: [{ id: "branch-a", root_id: "root-a", round_ids: ["round-a"] }],
      rounds: [{ id: "round-a", branch_id: "branch-a", round_number: 1, basis_status: "current" }],
    })
    api.story.previewSceneDirectorContinuation = vi.fn(async () => ({
      preview_hash: "a".repeat(64), current_budget: { unknown_requests: 0 },
      request_count: { minimum: 4, maximum: 4 },
      token_count: { minimum: 10, maximum: 100 },
      time_seconds: { minimum: 1, maximum: 10 },
    }))
    api.story.advanceSceneDirector = vi.fn(async () => ({ task_id: "task-a" }))
    api.story.continueSceneDirector = vi.fn(async () => ({ task_id: "task-a" }))
    const wrapper = mountPanel("scene-a")
    await flushPromises()
    await wrapper.findAll("button").find((b) => b.text() === "从此回合继续").trigger("click")
    const section = wrapper.get(".scene-director__continue")
    const labels = section.findAll("label")
    await labels.find((l) => l.text().includes("新增请求额度")).get("input").setValue(requests)
    await labels.find((l) => l.text().includes("新增 Token 额度")).get("input").setValue(tokens)
    await section.findAll("button").find((b) => b.text() === "预览同一累计根预算").trigger("click")
    await flushPromises()
    const submit = section.get("button.btn-primary")
    expect(submit.text()).toBe(requests || tokens ? "确认续算并创建分支" : "用原预算推进一轮")
    await submit.trigger("click")
    await flushPromises()
    expect(api.story[method]).toHaveBeenCalledWith("root-a", expect.objectContaining({
      additional_requests: requests, additional_tokens: tokens,
      context_confirmation_id: "confirmation-a",
    }))
    const other = method === "advanceSceneDirector" ? "continueSceneDirector" : "advanceSceneDirector"
    expect(api.story[other]).not.toHaveBeenCalled()
  })

  it("resumes a paused first-round branch with its preview identity and explicit allowance", async () => {
    api.story.sceneDirectorHistory.mockResolvedValue({
      ...history("scene-a"),
      roots: [{ id: "root-a", character_ids: ["actor-a"] }],
      branches: [{ id: "branch-a", root_id: "root-a", branch_kind: "start", status: "paused_budget", round_ids: [] }],
      rounds: [],
    })
    api.story.previewSceneDirectorResume = vi.fn(async () => ({
      preview_hash: "b".repeat(64),
      current_budget: { requests_used: 2, requests_authorized: 2, tokens_used: 20, tokens_authorized: 1000, unknown_requests: 0 },
      possible_charge: "复用检查点",
    }))
    api.story.resumeSceneDirector = vi.fn(async () => ({ task_id: "task-resume" }))
    const wrapper = mountPanel("scene-a")
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "恢复暂停回合").trigger("click")
    const resumePanel = wrapper.get('section[aria-labelledby="director-resume-title"]')
    await resumePanel.findAll("label").find((label) => label.text().includes("新增请求额度")).get("input").setValue(2)
    await resumePanel.findAll("button").find((button) => button.text() === "预览恢复与累计预算").trigger("click")
    await flushPromises()
    expect(resumePanel.find("button.btn-primary").element.disabled).toBe(false)
    await resumePanel.find("button.btn-primary").trigger("click")
    await flushPromises()
    expect(api.story.previewSceneDirectorResume).toHaveBeenCalledWith("root-a", {
      operation_id: expect.any(String),
      novel_id: "project-a",
      parent_round_id: null,
      resume_branch_id: "branch-a",
      rounds: 1,
      basis_choice: "current",
    })
    expect(api.story.resumeSceneDirector).toHaveBeenCalledWith("root-a", expect.objectContaining({
      resume_branch_id: "branch-a",
      parent_round_id: null,
      additional_requests: 2,
      additional_tokens: 0,
      context_confirmation_id: "confirmation-a",
      budget_preview_hash: "b".repeat(64),
    }))
  })

  it("keeps continuation input when refreshed history no longer contains its parent", async () => {
    api.story.sceneDirectorHistory.mockResolvedValueOnce({
      ...history("scene-a"),
      roots: [{ id: "root-a", character_ids: ["actor-a"] }],
      branches: [{ id: "branch-a", root_id: "root-a", round_ids: ["round-a"] }],
      rounds: [{ id: "round-a", branch_id: "branch-a", round_number: 1, basis_status: "current" }],
    })
    api.story.previewSceneDirectorContinuation = vi.fn()
    const wrapper = mountPanel("scene-a")
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "从此回合继续").trigger("click")
    const draft = wrapper.get(".scene-director__continue textarea")
    await draft.setValue("保留续算假设")
    await wrapper.findAll("button").find((button) => button.text() === "刷新历史").trigger("click")
    await flushPromises()
    await wrapper.get(".scene-director__continue").findAll("button").find((button) => button.text() === "预览同一累计根预算").trigger("click")
    await flushPromises()
    expect(api.story.previewSceneDirectorContinuation).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("导演历史尚未载入")
    expect(draft.element.value).toBe("保留续算假设")
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

  it("keeps the chosen World candidate type on 409 and restores saved transfer status", async () => {
    const round = {
      id: "round-a", branch_id: "branch-a", round_number: 1,
      source_hash: "a".repeat(64), output_hash: "c".repeat(64),
      basis_status: "current", candidate_events: [],
      candidate_transfer_choices: [{
        candidate_id: "visitor", source_kind: "reference", source_id: "visitor",
        label: "陌生访客", description: "", conflict: false,
      }],
    }
    api.story.sceneDirectorHistory.mockResolvedValue({
      ...history("scene-a"), rounds: [round], candidate_transfers: [],
    })
    api.story.transferDirectorCandidate
      .mockRejectedValueOnce(Object.assign(new Error("changed"), { status: 409 }))
      .mockResolvedValueOnce({ world_candidate_id: "world-candidate-a", entity_type: "character" })
    const wrapper = mountPanel("scene-a")
    await flushPromises()
    const candidate = wrapper.get(".scene-director__candidate-events article")
    await candidate.get("select").setValue("character")
    await candidate.get("button").trigger("click")
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain("原选择已保留")
    expect(candidate.get("select").element.value).toBe("character")
    expect(api.story.transferDirectorCandidate).toHaveBeenCalledWith("round-a", expect.objectContaining({
      novel_id: "project-a", scene_id: "scene-a", confirmed: true,
      candidate_id: "visitor", entity_type: "character",
      expected_source_hash: "a".repeat(64), expected_output_hash: "c".repeat(64),
    }))
    await candidate.get("button").trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("已转入 World 候选，仍待审核采用")
    expect(candidate.find("button").exists()).toBe(false)
  })

  it("renders compact exploration rounds as placeholders pointing back to the assistant", async () => {
    api.story.sceneDirectorHistory.mockResolvedValue({
      ...history("scene-a"),
      roots: [{ id: "root-a", character_ids: ["actor-a"] }],
      branches: [{ id: "branch-a", root_id: "root-a", round_ids: ["round-exp", "round-a"] }],
      rounds: [
        {
          id: "round-exp", branch_id: "branch-a", round_number: 1, basis_status: "current",
          output_kind: "story.exploration.scene_line",
          output_json: { output_kind: "story.exploration.scene_line", schema_version: 1, payload: { line: "紧凑结果" } },
          performances: [], materials: [],
        },
        { id: "round-a", branch_id: "branch-a", round_number: 2, basis_status: "current", performances: [], materials: [] },
      ],
    })
    const wrapper = mountPanel("scene-a")
    await flushPromises()
    const note = wrapper.get(".scene-director__exploration-note")
    expect(note.text()).toContain("紧凑探索结果")
    expect(note.text()).toContain("场景一句对白")
    expect(note.text()).toContain("项目助手")
    // 探索回合内不渲染旧操作入口与表演卡区块；普通回合保持原样。
    const explorationArticle = note.element.closest("article")
    expect(explorationArticle.textContent).not.toContain("从此回合继续")
    expect(explorationArticle.textContent).not.toContain("保存为参考剧本")
    expect(explorationArticle.querySelector(".scene-director__cards")).toBeNull()
    expect(wrapper.findAll("button").some((button) => button.text() === "从此回合继续")).toBe(true)
  })

  it("labels full rehearsal and sandbox exploration rounds with their kind names", async () => {
    api.story.sceneDirectorHistory.mockResolvedValue({
      ...history("scene-a"),
      roots: [{ id: "root-a", character_ids: ["actor-a"] }],
      branches: [{ id: "branch-a", root_id: "root-a", round_ids: ["round-rehearsal", "round-sandbox"] }],
      rounds: [
        {
          id: "round-rehearsal", branch_id: "branch-a", round_number: 1, basis_status: "current",
          output_kind: "story.exploration.full_rehearsal",
          output_json: { output_kind: "story.exploration.full_rehearsal", schema_version: 1, payload: { rounds: [] } },
          performances: [], materials: [],
        },
        {
          id: "round-sandbox", branch_id: "branch-a", round_number: 2, basis_status: "current",
          output_kind: "story.exploration.sandbox",
          output_json: { output_kind: "story.exploration.sandbox", schema_version: 1, payload: { influence_chain: [] } },
          performances: [], materials: [],
        },
      ],
    })
    const wrapper = mountPanel("scene-a")
    await flushPromises()
    const notes = wrapper.findAll(".scene-director__exploration-note")
    expect(notes).toHaveLength(2)
    expect(notes[0].text()).toContain("完整排演")
    expect(notes[1].text()).toContain("沙盘推演")
    for (const note of notes) {
      expect(note.text()).toContain("紧凑探索结果")
      expect(note.text()).toContain("项目助手")
      expect(note.element.closest("article").querySelector(".scene-director__cards")).toBeNull()
    }
  })

  it("drops a late candidate transfer response after switching Scene", async () => {
    const round = {
      id: "round-old", branch_id: "branch-old", round_number: 1,
      source_hash: "a".repeat(64), output_hash: "c".repeat(64), basis_status: "current",
      candidate_events: [{ candidate_id: "arrival", label: "旧访客", description: "旧候选" }],
      candidate_transfer_choices: [{
        candidate_id: "arrival", source_kind: "event", source_id: "arrival",
        label: "旧访客", description: "旧候选", conflict: false,
      }],
    }
    api.story.sceneDirectorHistory.mockImplementation(async (_projectId, sceneId) => (
      sceneId === "scene-a"
        ? { ...history(sceneId), rounds: [round], candidate_transfers: [] }
        : { ...history(sceneId), rounds: [], candidate_transfers: [] }
    ))
    let resolveTransfer
    api.story.transferDirectorCandidate.mockImplementation(() => new Promise((resolve) => {
      resolveTransfer = resolve
    }))
    const wrapper = mountPanel("scene-a")
    await flushPromises()
    await wrapper.get(".scene-director__candidate-events button").trigger("click")
    await wrapper.setProps({ scene: { id: "scene-b", title: "新场景" } })
    await flushPromises()
    resolveTransfer({ world_candidate_id: "old-world", entity_type: "event" })
    await flushPromises()
    expect(wrapper.text()).not.toContain("旧访客")
    expect(wrapper.text()).not.toContain("已转入 World 候选")
    expect(wrapper.attributes("data-director-scene")).toBe("scene-b")
  })
})

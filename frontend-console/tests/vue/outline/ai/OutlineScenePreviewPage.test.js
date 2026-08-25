import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import OutlineScenePreviewPage from "../../../../vue/views/outline/ai/OutlineScenePreviewPage.vue"
import {
  outlineGenerateManager,
  resetOutlineGenerateState,
} from "../../../../vue/views/outline/ai/outlineWorkflowManagers.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)

const projectId = "project-scene-preview"
const taskId = "task-scene-preview"

function previewDraft(title = "潮门初启") {
  return {
    result: "proposed",
    scenes: [{
      proposal_ref: "scene-proposal-1",
      target_scene_ref: null,
      parent_arc_ref: "arc-first",
      title,
      planned_start_chapter: 1,
      planned_end_chapter: 2,
      goal: "让主角第一次看见退潮遗迹。",
      core_conflict: "救人会错过唯一入口。",
      core_conflict_status: "present",
      emotional_beat: "惊异转为决断。",
      must_happen: "主角选择先救人。",
      must_not_happen: "不要提前揭示遗迹真相。",
      narrative_tag: "hook",
      narrative_function: "建立退潮规则并留下第一次代价。",
      pov_character_ref: "character-lead",
      related_thread_refs: ["thread-main"],
      related_character_refs: ["character-lead"],
      related_entity_refs: [],
      basis: "承接故事总览中的共同代价。",
      uncertain_fields: [],
      confidence: 0.9,
    }],
    story_outline_conflict: null,
    author_decisions: [],
  }
}

function setup({ apply } = {}) {
  const applyStructurePreview = apply || vi.fn(async () => ({ target: "planned_scene", total_scenes: 1 }))
  const router = {
    replace: vi.fn(async () => true),
    getCurrentQuery: vi.fn(() => new URLSearchParams("review=ai&scene_id=s1")),
  }
  setBridgeOverrides({
    api: { outline: { applyStructurePreview } },
    state: { currentProjectId: projectId, currentView: "outline", currentSubView: "scenes" },
    router,
    toast: vi.fn(),
    closeModal: vi.fn(),
    confirmAction: vi.fn((_message, handler) => handler()),
  })
  outlineGenerateManager.state.ownerProjectId = projectId
  outlineGenerateManager.state.taskId = taskId
  outlineGenerateManager.state.meta = { target: "planned_scene", mode: "create", label: "细纲" }
  outlineGenerateManager.state.progress = { taskId, done: true, terminal: true }
  outlineGenerateManager.state.preview = {
    sourceTaskId: taskId,
    contextConfirmationId: "confirmation-scene-preview",
    draftStructure: previewDraft(),
    warnings: [],
    target: "planned_scene",
    mode: "create",
    overlap: {},
  }
  return { applyStructurePreview, router }
}

beforeEach(() => {
  localStorage.clear()
  resetOutlineGenerateState()
})

afterEach(() => {
  resetOutlineGenerateState()
  resetBridgeOverrides()
})

describe("场景 AI 建议结构化审阅", () => {
  it("不暴露 JSON，并按既有 wire 提交可读表单与隐藏引用", async () => {
    const { applyStructurePreview, router } = setup()
    const wrapper = mount(OutlineScenePreviewPage, { props: { projectId } })
    await flushPromises()

    expect(wrapper.text()).toContain("检查场景细纲")
    expect(wrapper.find("#outline-layer-preview-json").exists()).toBe(false)
    await wrapper.get("#outline-scene-preview-0-title").setValue("作者修订后的潮门开场")
    await wrapper.get("#outline-scene-preview-0-status").setValue("not_applicable")
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(applyStructurePreview).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: projectId,
      context_confirmation_id: "confirmation-scene-preview",
      source_task_id: taskId,
      confirmed: true,
      draft_structure: expect.objectContaining({
        scenes: [expect.objectContaining({
          title: "作者修订后的潮门开场",
          core_conflict: null,
          core_conflict_status: "not_applicable",
          parent_arc_ref: "arc-first",
          pov_character_ref: "character-lead",
          related_thread_refs: ["thread-main"],
        })],
      }),
    }))
    expect(router.replace).toHaveBeenCalledWith("outline", "scenes", expect.any(URLSearchParams))
    expect(router.replace.mock.calls[0][2].get("review")).toBeNull()
  })

  it("刷新恢复同项目同任务的本机修改，并在切换项目时隔离", async () => {
    setup()
    const key = `novel_outline_scene_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(taskId)}`
    localStorage.setItem(key, JSON.stringify({
      version: 1,
      project_id: projectId,
      source_task_id: taskId,
      target: "planned_scene",
      saved_at: "2026-08-23T10:00:00Z",
      draft_structure: previewDraft("本机恢复的场景"),
    }))
    const wrapper = mount(OutlineScenePreviewPage, { props: { projectId } })
    await flushPromises()

    expect(wrapper.get("#outline-scene-preview-0-title").element.value).toBe("本机恢复的场景")
    expect(wrapper.text()).toContain("已恢复本机修改")
    await wrapper.get("#outline-scene-preview-0-title").setValue("只属于原项目")
    await wrapper.setProps({ projectId: "project-next" })
    await flushPromises()

    expect(JSON.parse(localStorage.getItem(key)).draft_structure.scenes[0].title).toBe("只属于原项目")
    expect(localStorage.getItem(`novel_outline_scene_preview:${encodeURIComponent("project-next")}:${encodeURIComponent(taskId)}`)).toBeNull()
    expect(wrapper.text()).toContain("这份建议暂时无法打开")
  })

  it("校验章节范围和明确冲突，并聚焦错误摘要", async () => {
    const { applyStructurePreview } = setup()
    const wrapper = mount(OutlineScenePreviewPage, { props: { projectId }, attachTo: document.body })
    await flushPromises()
    await wrapper.get("#outline-scene-preview-0-start").setValue("12")
    await wrapper.get("#outline-scene-preview-0-end").setValue("3")
    await wrapper.get("#outline-scene-preview-0-conflict").setValue("")
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(applyStructurePreview).not.toHaveBeenCalled()
    expect(wrapper.get(".story-outline-generate__error-summary").element).toBe(document.activeElement)
    expect(wrapper.get("#outline-scene-preview-0-end-error").text()).toContain("不能早于")
    expect(wrapper.get("#outline-scene-preview-0-conflict-error").text()).toContain("核心冲突")
  })

  it("409 后保留草稿并阻止重复采用", async () => {
    const conflict = new Error("结构版本冲突")
    conflict.status = 409
    setup({ apply: vi.fn(async () => { throw conflict }) })
    const wrapper = mount(OutlineScenePreviewPage, { props: { projectId } })
    await flushPromises()
    await wrapper.get("#outline-scene-preview-0-title").setValue("冲突时仍保留")
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(wrapper.text()).toContain("作品结构已变化")
    expect(wrapper.get('[data-action="apply-outline-generate-preview"]').attributes("disabled")).toBeDefined()
    const key = `novel_outline_scene_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(taskId)}`
    expect(JSON.parse(localStorage.getItem(key)).draft_structure.scenes[0].title).toBe("冲突时仍保留")
    expect(JSON.parse(localStorage.getItem(key)).conflict).toBe(true)
  })
})

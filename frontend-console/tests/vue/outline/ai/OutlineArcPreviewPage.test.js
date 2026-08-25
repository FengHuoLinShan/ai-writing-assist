import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import OutlineArcPreviewPage from "../../../../vue/views/outline/ai/OutlineArcPreviewPage.vue"
import {
  outlineGenerateManager,
  resetOutlineGenerateState,
} from "../../../../vue/views/outline/ai/outlineWorkflowManagers.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)

const projectId = "project-arc-preview"
const taskId = "task-arc-preview"

function previewDraft(title = "雾港失忆篇") {
  return {
    result: "proposed",
    arcs: [{
      proposal_ref: "arc-proposal-1",
      target_arc_ref: null,
      title,
      arc_index: 1,
      start_chapter: 1,
      end_chapter: 12,
      arc_goal: "让主角发现整座城市都在遗忘同一段历史。",
      core_conflict: "保存真相会让同伴陷入危险。",
      main_opposition: "负责抹除档案的城市议会。",
      entry_hook: "一份空白档案写着主角的名字。",
      midpoint_turn: "同伴承认自己参与过第一次删改。",
      climax: "主角必须公开档案或烧毁唯一证据。",
      result_state: "城市开始质疑官方历史。",
      next_hook: "议会地下库仍藏着更早的记录。",
      related_thread_refs: ["thread-main"],
      related_character_refs: [],
      related_entity_refs: [],
      basis: "承接故事总览中的记忆与控制主题。",
      uncertain_fields: [],
      confidence: 0.9,
    }],
    story_outline_conflict: null,
    author_decisions: [],
  }
}

function setup({ apply } = {}) {
  const applyStructurePreview = apply || vi.fn(async () => ({ target: "outline_arc", total_arcs: 1 }))
  const router = {
    replace: vi.fn(async () => true),
    refresh: vi.fn(),
    getCurrentQuery: vi.fn(() => new URLSearchParams("review=ai&status=draft")),
  }
  setBridgeOverrides({
    api: { outline: { applyStructurePreview } },
    state: { currentProjectId: projectId, currentView: "outline", currentSubView: "arcs" },
    router,
    toast: vi.fn(),
    closeModal: vi.fn(),
    confirmAction: vi.fn((_message, handler) => handler()),
  })
  outlineGenerateManager.state.ownerProjectId = projectId
  outlineGenerateManager.state.taskId = taskId
  outlineGenerateManager.state.meta = { target: "outline_arc", mode: "create", label: "篇章" }
  outlineGenerateManager.state.progress = { taskId, done: true, terminal: true }
  outlineGenerateManager.state.preview = {
    sourceTaskId: taskId,
    contextConfirmationId: "confirmation-arc-preview",
    draftStructure: previewDraft(),
    warnings: [],
    target: "outline_arc",
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

describe("篇章 AI 建议结构化审阅", () => {
  it("不暴露 JSON，并把作者修改按既有 apply wire 提交", async () => {
    const { applyStructurePreview, router } = setup()
    const wrapper = mount(OutlineArcPreviewPage, { props: { projectId } })
    await flushPromises()

    expect(wrapper.text()).toContain("检查篇章建议")
    expect(wrapper.find("#outline-layer-preview-json").exists()).toBe(false)
    await wrapper.get("#outline-arc-preview-0-title").setValue("作者修订后的失忆篇")
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(applyStructurePreview).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: projectId,
      context_confirmation_id: "confirmation-arc-preview",
      source_task_id: taskId,
      confirmed: true,
      draft_structure: expect.objectContaining({
        arcs: [expect.objectContaining({
          title: "作者修订后的失忆篇",
          related_thread_refs: ["thread-main"],
        })],
      }),
    }))
    expect(router.replace).toHaveBeenCalledWith("outline", "arcs", expect.any(URLSearchParams))
    expect(router.replace.mock.calls[0][2].get("review")).toBeNull()
  })

  it("刷新恢复同项目同任务的本机修改", async () => {
    setup()
    const key = `novel_outline_arc_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(taskId)}`
    localStorage.setItem(key, JSON.stringify({
      version: 1,
      project_id: projectId,
      source_task_id: taskId,
      target: "outline_arc",
      saved_at: "2026-08-23T10:00:00Z",
      draft_structure: previewDraft("本机恢复的篇章"),
    }))

    const wrapper = mount(OutlineArcPreviewPage, { props: { projectId } })
    await flushPromises()

    expect(wrapper.get("#outline-arc-preview-0-title").element.value).toBe("本机恢复的篇章")
    expect(wrapper.text()).toContain("已恢复本机修改")
    await wrapper.get("#outline-arc-preview-0-title").setValue("离开前自动保存")
    wrapper.unmount()
    expect(JSON.parse(localStorage.getItem(key)).draft_structure.arcs[0].title).toBe("离开前自动保存")
  })

  it("项目切换时只把修改写回原项目", async () => {
    setup()
    const wrapper = mount(OutlineArcPreviewPage, { props: { projectId } })
    await flushPromises()
    await wrapper.get("#outline-arc-preview-0-title").setValue("只属于原项目")

    await wrapper.setProps({ projectId: "project-next" })
    await flushPromises()

    const oldKey = `novel_outline_arc_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(taskId)}`
    const nextKey = `novel_outline_arc_preview:${encodeURIComponent("project-next")}:${encodeURIComponent(taskId)}`
    expect(JSON.parse(localStorage.getItem(oldKey)).draft_structure.arcs[0].title).toBe("只属于原项目")
    expect(localStorage.getItem(nextKey)).toBeNull()
    expect(wrapper.text()).toContain("这份建议暂时无法打开")
  })

  it("校验章节范围并聚焦错误摘要", async () => {
    const { applyStructurePreview } = setup()
    const wrapper = mount(OutlineArcPreviewPage, { props: { projectId }, attachTo: document.body })
    await flushPromises()
    await wrapper.get("#outline-arc-preview-0-start").setValue("12")
    await wrapper.get("#outline-arc-preview-0-end").setValue("3")
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(applyStructurePreview).not.toHaveBeenCalled()
    expect(wrapper.get(".story-outline-generate__error-summary").element).toBe(document.activeElement)
    expect(wrapper.get("#outline-arc-preview-0-end-error").text()).toContain("不能早于")
  })

  it("409 后保留草稿并阻止重复采用", async () => {
    const conflict = new Error("结构版本冲突")
    conflict.status = 409
    setup({ apply: vi.fn(async () => { throw conflict }) })
    const wrapper = mount(OutlineArcPreviewPage, { props: { projectId } })
    await flushPromises()
    await wrapper.get("#outline-arc-preview-0-title").setValue("冲突时仍保留")
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(wrapper.text()).toContain("作品结构已变化")
    expect(wrapper.get('[data-action="apply-outline-generate-preview"]').attributes("disabled")).toBeDefined()
    const key = `novel_outline_arc_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(taskId)}`
    expect(JSON.parse(localStorage.getItem(key)).draft_structure.arcs[0].title).toBe("冲突时仍保留")
    expect(JSON.parse(localStorage.getItem(key)).conflict).toBe(true)
  })

  it("明确放弃后不会被卸载自动保存重新写回", async () => {
    const { router } = setup()
    const wrapper = mount(OutlineArcPreviewPage, { props: { projectId } })
    await flushPromises()
    await wrapper.get("#outline-arc-preview-0-title").setValue("即将放弃")
    await wrapper.get('[data-action="discard-outline-generate-preview"]').trigger("click")
    wrapper.unmount()

    const key = `novel_outline_arc_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(taskId)}`
    expect(localStorage.getItem(key)).toBeNull()
    expect(router.replace).toHaveBeenCalledWith("outline", "arcs", expect.any(URLSearchParams))
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import OutlineThreadPreviewPage from "../../../../vue/views/outline/ai/OutlineThreadPreviewPage.vue"
import {
  outlineGenerateManager,
  resetOutlineGenerateState,
} from "../../../../vue/views/outline/ai/outlineWorkflowManagers.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)

const projectId = "project-thread-preview"
const taskId = "task-thread-preview"

function previewDraft(name = "失落档案主线") {
  return {
    result: "proposed",
    reuse_judgments: [],
    threads: [{
      proposal_ref: "thread-proposal-1",
      target_thread_ref: null,
      name,
      thread_type: "main",
      summary: "档案员追查被删除的城市记忆。",
      visible_goal: "找到失踪档案",
      hidden_truth: "档案馆主动删去了历史",
      start_chapter: 1,
      planned_payoff_chapter: 12,
      current_stage: "埋下",
      related_character_refs: [],
      related_entity_refs: [],
      reader_known_state: "读者只知道档案失踪",
      author_known_state: "作者知道馆长参与删改",
      information_movements: [{
        movement_ref: "movement-1",
        information_subject: "被删除的城市历史",
        surface_understanding: "事故导致资料缺失",
        hidden_content: "人为抹除",
        target_ref: null,
        nodes: [{ kind: "seed", content: "发现空白目录", chapter_hint: 2, scene_ref: null, trigger: null, effect: null }],
        basis: "总纲要求通过档案逐步揭露真相。",
        uncertain_fields: [],
        confidence: 0.9,
      }],
      basis: "承接故事总览的记忆主题。",
      uncertain_fields: [],
      confidence: 0.9,
    }],
    story_outline_conflict: null,
    author_decisions: [],
  }
}

function setup({ apply } = {}) {
  const applyStructurePreview = apply || vi.fn(async () => ({ target: "plot_thread", total_threads: 1 }))
  const router = {
    replace: vi.fn(async () => true),
    refresh: vi.fn(),
    getCurrentQuery: vi.fn(() => new URLSearchParams("review=ai&status=draft")),
  }
  setBridgeOverrides({
    api: { outline: { applyStructurePreview } },
    state: { currentProjectId: projectId, currentView: "outline", currentSubView: "threads" },
    router,
    toast: vi.fn(),
    closeModal: vi.fn(),
    confirmAction: vi.fn((_message, handler) => handler()),
  })
  outlineGenerateManager.state.ownerProjectId = projectId
  outlineGenerateManager.state.taskId = taskId
  outlineGenerateManager.state.meta = { target: "plot_thread", mode: "create", label: "剧情线" }
  outlineGenerateManager.state.progress = { taskId, done: true, terminal: true }
  outlineGenerateManager.state.preview = {
    sourceTaskId: taskId,
    contextConfirmationId: "confirmation-thread-preview",
    draftStructure: previewDraft(),
    warnings: [],
    target: "plot_thread",
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

describe("剧情线 AI 建议结构化审阅", () => {
  it("不暴露 JSON，并把作者修改原样提交到既有 apply wire", async () => {
    const { applyStructurePreview, router } = setup()
    const wrapper = mount(OutlineThreadPreviewPage, { props: { projectId } })
    await flushPromises()

    expect(wrapper.text()).toContain("检查剧情线建议")
    expect(wrapper.find(".outline-preview-json").exists()).toBe(false)
    expect(wrapper.find("#outline-layer-preview-json").exists()).toBe(false)
    await wrapper.get("#outline-thread-preview-0-name").setValue("作者修订后的主线")
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(applyStructurePreview).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: projectId,
      context_confirmation_id: "confirmation-thread-preview",
      source_task_id: taskId,
      confirmed: true,
      draft_structure: expect.objectContaining({
        threads: [expect.objectContaining({ name: "作者修订后的主线", information_movements: expect.any(Array) })],
      }),
    }))
    expect(router.replace).toHaveBeenCalledWith("outline", "threads", expect.any(URLSearchParams))
    expect(router.replace.mock.calls[0][2].get("review")).toBeNull()
  })

  it("刷新恢复同项目同任务的本机修改，不读取其他项目草稿", async () => {
    setup()
    const key = `novel_outline_thread_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(taskId)}`
    localStorage.setItem(key, JSON.stringify({
      version: 1,
      project_id: projectId,
      source_task_id: taskId,
      target: "plot_thread",
      saved_at: "2026-08-23T10:00:00Z",
      draft_structure: previewDraft("本机恢复的剧情线"),
    }))
    localStorage.setItem(`novel_outline_thread_preview:other:${taskId}`, JSON.stringify({
      project_id: "other",
      source_task_id: taskId,
      target: "plot_thread",
      draft_structure: previewDraft("不应出现"),
    }))

    const wrapper = mount(OutlineThreadPreviewPage, { props: { projectId } })
    await flushPromises()

    expect(wrapper.get("#outline-thread-preview-0-name").element.value).toBe("本机恢复的剧情线")
    expect(wrapper.text()).toContain("已恢复本机修改")
    await wrapper.get("#outline-thread-preview-0-name").setValue("离开前自动保存")
    wrapper.unmount()
    expect(JSON.parse(localStorage.getItem(key)).draft_structure.threads[0].name).toBe("离开前自动保存")
  })

  it("项目切换时只把离开前修改写回原项目", async () => {
    setup()
    const wrapper = mount(OutlineThreadPreviewPage, { props: { projectId } })
    await flushPromises()
    await wrapper.get("#outline-thread-preview-0-name").setValue("只属于原项目")

    await wrapper.setProps({ projectId: "project-next" })
    await flushPromises()

    const oldKey = `novel_outline_thread_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(taskId)}`
    const nextKey = `novel_outline_thread_preview:${encodeURIComponent("project-next")}:${encodeURIComponent(taskId)}`
    expect(JSON.parse(localStorage.getItem(oldKey)).draft_structure.threads[0].name).toBe("只属于原项目")
    expect(localStorage.getItem(nextKey)).toBeNull()
    expect(wrapper.text()).toContain("这份建议暂时无法打开")
  })

  it("校验失败同时聚焦错误摘要并保留字段级错误", async () => {
    const { applyStructurePreview } = setup()
    const wrapper = mount(OutlineThreadPreviewPage, { props: { projectId }, attachTo: document.body })
    await flushPromises()
    await wrapper.get("#outline-thread-preview-0-name").setValue("")
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(applyStructurePreview).not.toHaveBeenCalled()
    expect(wrapper.get(".story-outline-generate__error-summary").element).toBe(document.activeElement)
    expect(wrapper.get("#outline-thread-preview-0-name-error").text()).toContain("名称")
  })

  it("409 后保留草稿并阻止重复采用", async () => {
    const conflict = new Error("结构版本冲突")
    conflict.status = 409
    setup({ apply: vi.fn(async () => { throw conflict }) })
    const wrapper = mount(OutlineThreadPreviewPage, { props: { projectId } })
    await flushPromises()
    await wrapper.get("#outline-thread-preview-0-name").setValue("冲突时仍保留")
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(wrapper.text()).toContain("作品结构已变化")
    expect(wrapper.get('[data-action="apply-outline-generate-preview"]').attributes("disabled")).toBeDefined()
    const key = `novel_outline_thread_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(taskId)}`
    expect(JSON.parse(localStorage.getItem(key)).draft_structure.threads[0].name).toBe("冲突时仍保留")
    expect(JSON.parse(localStorage.getItem(key)).conflict).toBe(true)

    wrapper.unmount()
    outlineGenerateManager.state.applyError = null
    const restored = mount(OutlineThreadPreviewPage, { props: { projectId } })
    await flushPromises()
    expect(restored.text()).toContain("作品结构已变化")
    expect(restored.get('[data-action="apply-outline-generate-preview"]').attributes("disabled")).toBeDefined()
    expect(restored.get("#outline-thread-preview-0-name").element.value).toBe("冲突时仍保留")
  })

  it("明确放弃后不会被卸载自动保存重新写回", async () => {
    const { router } = setup()
    const wrapper = mount(OutlineThreadPreviewPage, { props: { projectId } })
    await flushPromises()
    await wrapper.get("#outline-thread-preview-0-name").setValue("即将放弃")
    await wrapper.get('[data-action="discard-outline-generate-preview"]').trigger("click")
    wrapper.unmount()

    const key = `novel_outline_thread_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(taskId)}`
    expect(localStorage.getItem(key)).toBeNull()
    expect(router.replace).toHaveBeenCalledWith("outline", "threads", expect.any(URLSearchParams))
  })
})

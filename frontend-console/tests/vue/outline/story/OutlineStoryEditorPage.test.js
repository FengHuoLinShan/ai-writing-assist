import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import OutlineStoryEditorPage from "../../../../vue/views/outline/story/OutlineStoryEditorPage.vue"
import { ISLAND_LEAVE_GUARD } from "../../../../vue/mountIsland.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"

function revision(overrides = {}) {
  return {
    id: "rev-1",
    version_number: 1,
    title: "霜城纪事",
    creative_core: {
      premise: "档案员追查被篡改的历史。",
      tone_and_reader_promise: "冷峻谜题与温暖关系并行。",
      story_engine: "每找回一份档案，就打开更大的谎言。",
      ending_direction: "让真相可被共同记录。",
    },
    outline_markdown: "主角进入霜城档案馆。",
    major_storylines: [{ name: "失真档案", narrative_function: "驱动主谜题", trajectory: "从私人到公共", intersections: ["城防家族"], resolution_direction: "建立公开档案" }],
    macro_movements: [{ name: "走向公共", story_state_change: "从自证转为守护城市", advanced_storylines: ["失真档案"] }],
    open_decisions: [{ question: "是否公布谎言？", why_it_matters: "决定伦理代价", options: ["公布", "保留"] }],
    ...overrides,
  }
}

function props(overrides = {}) {
  return {
    projectId: "p1",
    current: { current_revision_id: "rev-1", revision: revision() },
    loadError: null,
    ...overrides,
  }
}

let api
let router
let toast
let confirm
let guard

function mountEditor(overrides = {}) {
  return mount(OutlineStoryEditorPage, {
    props: props(overrides),
    global: {
      provide: {
        [ISLAND_LEAVE_GUARD]: (fn) => { guard = fn },
      },
    },
  })
}

beforeEach(() => {
  localStorage.clear()
  guard = null
  api = {
    outline: {
      createStoryOutlineRevision: vi.fn(),
      getStoryOutline: vi.fn(),
    },
  }
  router = { replace: vi.fn(async () => true), refresh: vi.fn(async () => true) }
  toast = vi.fn()
  confirm = vi.fn(() => true)
  setBridgeOverrides({ api, router, toast, confirm, state: { currentProjectId: "p1" } })
})

afterEach(() => resetBridgeOverrides())

describe("故事总览编辑页", () => {
  it("使用作者可读的结构化表单，不暴露 Markdown 或 JSON 编辑区", () => {
    const wrapper = mountEditor()
    expect(wrapper.get("h2").text()).toBe("编辑故事总览")
    expect(wrapper.text()).toContain("总览正文")
    expect(wrapper.text()).not.toContain("Markdown")
    expect(wrapper.text()).not.toContain("JSON")
    expect(wrapper.findAll(".story-outline-list-item")).toHaveLength(3)
    expect(wrapper.findAll(".story-outline-list-item.card")).toHaveLength(0)
    expect(wrapper.get('[data-action="save-story-outline-revision"]').attributes("disabled")).toBeDefined()
  })

  it("按项目暂存并在重新进入时恢复未完成内容", async () => {
    const first = mountEditor()
    await first.get("#story-outline-manual-title-input").setValue("霜城纪事新方向")
    expect(guard).toBeTypeOf("function")
    expect(guard()).toBe(true)
    const stored = JSON.parse(localStorage.getItem("story-outline-editor-draft:p1"))
    expect(stored.project_id).toBe("p1")
    expect(stored.content.title).toBe("霜城纪事新方向")
    expect(confirm).toHaveBeenCalledWith("本地草稿已保留。确定离开故事总览编辑页吗？")
    first.unmount()

    const restored = mountEditor()
    expect(restored.get("#story-outline-manual-title-input").element.value).toBe("霜城纪事新方向")
    expect(restored.text()).toContain("已恢复本地草稿")
    restored.unmount()

    setBridgeOverrides({ state: { currentProjectId: "p2" } })
    const otherProject = mountEditor({ projectId: "p2", current: { current_revision_id: null, revision: null } })
    expect(otherProject.get("#story-outline-manual-title-input").element.value).toBe("")
  })

  it("保存为新版本后清理本地草稿并返回总览", async () => {
    api.outline.createStoryOutlineRevision.mockResolvedValue({ version_number: 2 })
    const wrapper = mountEditor()
    await wrapper.get("#story-outline-manual-title-input").setValue("霜城纪事第二版")
    await wrapper.get('[data-action="save-story-outline-revision"]').trigger("submit")
    await flushPromises()

    expect(api.outline.createStoryOutlineRevision).toHaveBeenCalledTimes(1)
    const [projectId, payload] = api.outline.createStoryOutlineRevision.mock.calls[0]
    expect(projectId).toBe("p1")
    expect(payload).toMatchObject({
      title: "霜城纪事第二版",
      base_revision_id: "rev-1",
      source: "manual",
      provenance: { actor: "author", note: "前端手工保存" },
    })
    expect(payload.idempotency_key).toMatch(/^story-outline-/)
    expect(localStorage.getItem("story-outline-editor-draft:p1")).toBeNull()
    expect(router.replace).toHaveBeenCalledWith("outline", "story-outline")
    expect(toast).toHaveBeenCalledWith("故事总览已保存为新版本 v2", "success")
  })

  it("版本冲突时保留草稿，同步最新基准后可重试", async () => {
    const conflictError = Object.assign(new Error("conflict"), { status: 409 })
    api.outline.createStoryOutlineRevision
      .mockRejectedValueOnce(conflictError)
      .mockResolvedValueOnce({ version_number: 3 })
    api.outline.getStoryOutline.mockResolvedValue({ current_revision_id: "rev-2", revision: revision({ id: "rev-2", version_number: 2 }) })
    const wrapper = mountEditor()
    await wrapper.get("#story-outline-manual-title-input").setValue("保留的本地草稿")
    await wrapper.get('[data-action="save-story-outline-revision"]').trigger("submit")
    await flushPromises()

    expect(wrapper.text()).toContain("本地草稿仍在")
    expect(localStorage.getItem("story-outline-editor-draft:p1")).not.toBeNull()
    await wrapper.get("#story-outline-manual-title-input").setValue("冲突后继续修改的草稿")
    expect(wrapper.text()).toContain("本地草稿仍在")
    expect(wrapper.get('[data-action="save-story-outline-revision"]').attributes("disabled")).toBeDefined()
    await wrapper.get(".story-outline-editor-notice--warning .btn").trigger("click")
    await flushPromises()
    expect(api.outline.getStoryOutline).toHaveBeenCalledWith("p1")
    expect(wrapper.text()).toContain("基于当前版本 v2")
    expect(wrapper.get('[data-action="save-story-outline-revision"]').attributes("disabled")).toBeUndefined()

    await wrapper.get('[data-action="save-story-outline-revision"]').trigger("submit")
    await flushPromises()
    expect(api.outline.createStoryOutlineRevision.mock.calls[1][1].base_revision_id).toBe("rev-2")
    expect(router.replace).toHaveBeenCalledWith("outline", "story-outline")
  })

  it("保存请求未完成时阻止导航，避免迟到响应切错作品", async () => {
    let finishSave
    api.outline.createStoryOutlineRevision.mockImplementation(() => new Promise((resolve) => { finishSave = resolve }))
    const wrapper = mountEditor()
    await wrapper.get("#story-outline-manual-title-input").setValue("保存中的新版本")
    await wrapper.get('[data-action="save-story-outline-revision"]').trigger("submit")

    expect(guard()).toBe(false)
    expect(toast).toHaveBeenCalledWith("正在保存故事总览，请稍候", "info")
    expect(confirm).not.toHaveBeenCalled()

    finishSave({ version_number: 2 })
    await flushPromises()
    expect(router.replace).toHaveBeenCalledWith("outline", "story-outline")
  })

  it("字段不完整时就地提示且不发起保存请求", async () => {
    const wrapper = mountEditor({ current: { current_revision_id: null, revision: null } })
    document.body.appendChild(wrapper.element)
    await wrapper.get("#story-outline-manual-title-input").setValue("只有标题")
    await wrapper.get('[data-action="save-story-outline-revision"]').trigger("submit")
    await flushPromises()
    expect(wrapper.get("#story-outline-manual-error").text()).toContain("核心前提不能为空")
    expect(document.activeElement?.id).toBe("story-outline-manual-error")
    expect(api.outline.createStoryOutlineRevision).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

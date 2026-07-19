/**
 * storyOutline 预览与验证路径测试。
 * 测试 task done → preview 创建、校验失败、apply/discard 行为。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import OutlineStoryTab from "../../../../vue/views/outline/story/OutlineStoryTab.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"
import { storyOutlineTaskManager } from "../../../../vue/views/outline/story/storyOutlineData.js"

vi.mock("../../../../shared/workflowProgress.js", async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    pollTaskProgress: vi.fn(() => ({ stop: vi.fn() })),
    persistActiveWorkflow: vi.fn(),
    recoverActiveWorkflows: vi.fn(() => []),
    clearActiveWorkflow: vi.fn(),
  }
})

import { pollTaskProgress } from "../../../../shared/workflowProgress.js"

function contentFixture(overrides = {}) {
  return {
    title: "霜城纪事",
    creative_core: {
      premise: "一名记忆残缺的档案员追查城市被篡改的历史。",
      tone_and_reader_promise: "冷峻谜题与温暖的人物关系并行。",
      story_engine: "每找回一份档案，就打开更大的谎言。",
      ending_direction: "主角选择让真相可被共同记录。",
    },
    outline_markdown: "# 第一部\n\n主角进入霜城档案馆。",
    major_storylines: [],
    macro_movements: [],
    open_decisions: [],
    ...overrides,
  }
}

function makeProps(overrides = {}) {
  return {
    projectId: "p1",
    current: null,
    history: [],
    historyTotal: 0,
    characters: [],
    entities: [],
    loadError: null,
    assetLoadError: null,
    ...overrides,
  }
}

function taskFixture(result) {
  return {
    task_type: "story_outline_generate",
    meta: { action: "outline.story_outline.generate", novel_id: "p1" },
    result: {
      ...result,
      managed_llm_steps: [{ provider: "test-provider", model: "test-model" }],
      apply_status: result.apply_status ?? null,
      applied_revision_id: result.applied_revision_id ?? null,
    },
  }
}

function revisionFixture(id, version, title) {
  return {
    id,
    version_number: version,
    source: "manual",
    created_at: "2026-07-19T00:00:00Z",
    is_current: true,
    ...contentFixture({ title }),
  }
}

function mockReloadTo(revision) {
  globalThis.api.outline.getStoryOutline.mockResolvedValue({ current_revision_id: revision.id, revision })
  globalThis.api.outline.listStoryOutlineRevisions.mockResolvedValue({ items: [revision], total: 1 })
  globalThis.api.world.listCharacters.mockResolvedValue({ items: [] })
  globalThis.api.world.listEntities.mockResolvedValue({ items: [] })
}

function resetManager() {
  storyOutlineTaskManager.stop()
  storyOutlineTaskManager.state.taskId = null
  storyOutlineTaskManager.state.meta = null
  storyOutlineTaskManager.state.progress = null
  storyOutlineTaskManager.state.taskNotice = null
  storyOutlineTaskManager.state.cancelPending = false
  storyOutlineTaskManager.setOnTerminal(null)
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ""
  resetManager()
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("预览 · 任务完成创建 preview", () => {
  it("任务成功完成时创建可编辑预览", async () => {
    const toast = vi.fn()
    setBridgeOverrides({ toast, state: { currentProjectId: "p1" } })
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })

    // 通过 adopt 发起任务，模拟 onDone 回调
    storyOutlineTaskManager.adopt(
      { task_id: "task-done-1", status: "running" },
      { action: "outline.story_outline.generate", apply_base_revision_id: "rev-1", apply_idempotency_key: "k1" },
      "p1",
    )

    const callArgs = vi.mocked(pollTaskProgress).mock.calls[0]?.[0]
    expect(callArgs).toBeDefined()
    const content = contentFixture()
    callArgs.onDone(
      { taskId: "task-done-1", done: true, terminal: true },
      taskFixture(content),
    )

    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    expect(wrapper.find("#story-outline-preview-title").exists()).toBe(true)
    expect(wrapper.text()).toContain("AI 总纲完整预览")
    expect(wrapper.find("#story-outline-preview-title-input").element.value).toBe("霜城纪事")
    expect(wrapper.find('[data-action="apply-story-outline-preview"]').exists()).toBe(true)
    expect(wrapper.find('[data-action="discard-story-outline-preview"]').exists()).toBe(true)
    expect(toast).toHaveBeenCalledWith("小说总纲建议已生成，请编辑后明确采用", "success")
  })

  it("任务返回的 apply_status=applied 时显示已采用提示", async () => {
    const toast = vi.fn()
    setBridgeOverrides({ toast, state: { currentProjectId: "p1" } })
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })

    storyOutlineTaskManager.adopt(
      { task_id: "task-applied", status: "running" },
      { action: "outline.story_outline.generate" },
      "p1",
    )

    const callArgs = vi.mocked(pollTaskProgress).mock.calls[0]?.[0]
    callArgs.onDone(
      { taskId: "task-applied", done: true, terminal: true },
      taskFixture({ title: "x", apply_status: "applied" }),
    )

    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain("已经采用")
    expect(wrapper.find("#story-outline-preview-title").exists()).toBe(false)
  })

  it("任务返回内容不符合 schema 时显示错误提示而非 preview", async () => {
    const toast = vi.fn()
    setBridgeOverrides({ toast, state: { currentProjectId: "p1" } })
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })

    storyOutlineTaskManager.adopt(
      { task_id: "task-invalid", status: "running" },
      { action: "outline.story_outline.generate" },
      "p1",
    )

    const callArgs = vi.mocked(pollTaskProgress).mock.calls[0]?.[0]
    // 缺少必须字段 title
    callArgs.onDone(
      { taskId: "task-invalid", done: true, terminal: true },
      taskFixture({ creative_core: { premise: "x" } }),
    )

    await wrapper.vm.$nextTick()
    expect(wrapper.find("#story-outline-preview-title").exists()).toBe(false)
    expect(storyOutlineTaskManager.state.taskNotice).toContain("总纲格式")
    expect(storyOutlineTaskManager.state.taskId).toBeNull()
  })

  it("任务失败时显示错误通知", async () => {
    const toast = vi.fn()
    setBridgeOverrides({ toast, state: { currentProjectId: "p1" } })
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })

    storyOutlineTaskManager.adopt(
      { task_id: "task-failed", status: "running" },
      { action: "outline.story_outline.generate" },
      "p1",
    )

    const callArgs = vi.mocked(pollTaskProgress).mock.calls[0]?.[0]
    callArgs.onFailed({ taskId: "task-failed", failed: true, terminal: true, cancelled: false, errorMessage: "生成失败" })

    await wrapper.vm.$nextTick()
    expect(storyOutlineTaskManager.state.taskNotice).toContain("小说总纲生成失败")
    expect(wrapper.text()).toContain("小说总纲生成失败")
  })

  it("任务取消时显示取消提示", async () => {
    const toast = vi.fn()
    setBridgeOverrides({ toast, state: { currentProjectId: "p1" } })
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })

    storyOutlineTaskManager.adopt(
      { task_id: "task-cancelled", status: "running" },
      { action: "outline.story_outline.generate" },
      "p1",
    )

    const callArgs = vi.mocked(pollTaskProgress).mock.calls[0]?.[0]
    callArgs.onFailed({ taskId: "task-cancelled", failed: false, cancelled: true, terminal: true })

    await wrapper.vm.$nextTick()
    expect(storyOutlineTaskManager.state.taskNotice).toContain("已取消")
    expect(storyOutlineTaskManager.state.taskNotice).toContain("没有创建 revision")
  })

  it("重新加载保留未采用编辑并将 apply base 更新到最新 revision", async () => {
    setBridgeOverrides({ toast: vi.fn(), state: { currentProjectId: "p1" } })
    const current = revisionFixture("rev-1", 1, "旧总纲")
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({ current: { current_revision_id: "rev-1", revision: current } }),
      attachTo: document.body,
    })
    storyOutlineTaskManager.adopt(
      { task_id: "task-rebase", status: "running" },
      {
        action: "outline.story_outline.generate",
        novel_id: "p1",
        apply_base_revision_id: "rev-1",
        apply_idempotency_key: "key-before-rebase",
      },
      "p1",
    )
    const callbacks = vi.mocked(pollTaskProgress).mock.calls[0][0]
    callbacks.onDone(
      { taskId: "task-rebase", done: true, terminal: true },
      taskFixture(contentFixture({ title: "AI 初稿" })),
    )
    await wrapper.vm.$nextTick()
    await wrapper.find("#story-outline-preview-title-input").setValue("作者编辑稿")

    mockReloadTo(revisionFixture("rev-2", 2, "最新总纲"))
    await wrapper.find('[data-action="reload-story-outline"]').trigger("click")
    await flushPromises()

    expect(wrapper.find("#story-outline-preview-title-input").element.value).toBe("作者编辑稿")
    globalThis.api.outline.applyStoryOutlinePreview.mockResolvedValue({ version_number: 3 })
    mockReloadTo(revisionFixture("rev-3", 3, "已采用总纲"))
    await wrapper.find('[data-action="apply-story-outline-preview"]').trigger("click")
    await flushPromises()

    expect(globalThis.api.outline.applyStoryOutlinePreview).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      source_task_id: "task-rebase",
      title: "作者编辑稿",
      base_revision_id: "rev-2",
      confirmed: true,
    }))
    expect(globalThis.api.outline.applyStoryOutlinePreview.mock.calls[0][0].idempotency_key).not.toBe("key-before-rebase")
    expect(wrapper.text()).toContain("当前总纲 · v3")
    wrapper.unmount()
  })
})

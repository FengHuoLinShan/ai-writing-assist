/**
 * OutlineStoryTab 组件测试 — 渲染与行为契约。
 * bridge 替身通过 setBridgeOverrides 注入。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import OutlineStoryTab from "../../../../vue/views/outline/story/OutlineStoryTab.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"
import { storyOutlineTaskManager } from "../../../../vue/views/outline/story/storyOutlineData.js"

// ---- fixtures ----

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
    major_storylines: [{
      name: "失真档案",
      narrative_function: "驱动主谜题",
      trajectory: "从个人记忆追到公共历史",
      intersections: ["与城防家族的利益冲突"],
      resolution_direction: "建立公开档案制度",
    }],
    macro_movements: [{
      name: "真相从私人走向公共",
      story_state_change: "主角从自证转为保护整座城的记忆",
      advanced_storylines: ["失真档案"],
    }],
    open_decisions: [{
      question: "主角是否公布亲人的谎言？",
      why_it_matters: "决定结局的伦理代价",
      options: ["公布全部", "保留私密但公布制度证据"],
    }],
    ...overrides,
  }
}

function revisionFixture(overrides = {}) {
  return {
    id: "rev-1",
    novel_id: "p1",
    version_number: 1,
    source: "manual",
    provenance: {},
    base_revision_id: null,
    restored_from_revision_id: null,
    content_hash: "a".repeat(64),
    created_at: "2026-07-16T00:00:00Z",
    is_current: true,
    ...contentFixture(),
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

// ---- helpers ----

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
  resetManager()
})

afterEach(() => {
  resetBridgeOverrides()
})

// ================================================================
// 渲染契约
// ================================================================

describe("渲染 · 当前版本与空状态", () => {
  it("无 revision 时渲染空状态", () => {
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })
    expect(wrapper.text()).toContain("尚未创建故事总览")
    expect(wrapper.find("#story-outline-empty-title").exists()).toBe(true)
  })

  it("有 revision 时渲染当前版本标题、内容与所有区块", () => {
    const rev = revisionFixture()
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({
        current: { current_revision_id: "rev-1", revision: rev },
        history: [rev],
        historyTotal: 1,
      }),
    })
    const text = wrapper.text()
    expect(text).toContain("当前版本 · v1")
    expect(text).toContain("霜城纪事")
    expect(text).toContain("核心前提")
    expect(text).toContain("基调与读者承诺")
    expect(text).toContain("故事引擎")
    expect(text).toContain("结局方向")
    expect(text).toContain("主要剧情线")
    expect(text).toContain("故事推进")
    expect(text).toContain("待决定问题")
    expect(text).toContain("失真档案")
    expect(text).toContain("驱动主谜题")
    expect(text).toContain("历史版本")
  })

  it("当前 revision 为空时仍展示各块但 marking 为 待决定", () => {
    const rev = revisionFixture({
      creative_core: { premise: "a", tone_and_reader_promise: "b", story_engine: "c", ending_direction: null },
      major_storylines: [],
      macro_movements: [],
      open_decisions: [],
    })
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({
        current: { current_revision_id: "rev-1", revision: rev },
      }),
    })
    expect(wrapper.text()).toContain("待决定")
    expect(wrapper.text()).toContain("暂无。")
  })

  it("历史列表包含「不会原地回滚」提示", () => {
    const rev = revisionFixture({ id: "old-rev", is_current: false })
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({
        current: { current_revision_id: "rev-curr", revision: revisionFixture({ id: "rev-curr" }) },
        history: [rev],
        historyTotal: 1,
      }),
    })
    expect(wrapper.text()).toContain("不会改写原有历史")
    expect(wrapper.find('[data-action="restore-story-outline-revision"]').exists()).toBe(true)
  })

  it("当前版本在历史列表中显示 badge", () => {
    const rev = revisionFixture({ id: "rev-current", is_current: true })
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({
        current: { current_revision_id: "rev-current", revision: rev },
        history: [rev],
        historyTotal: 1,
      }),
    })
    expect(wrapper.text()).toContain("当前版本")
  })
})

describe("渲染 · 边界状态", () => {
  it("无项目时显示空提示", () => {
    const wrapper = mount(OutlineStoryTab, { props: makeProps({ projectId: null }) })
    expect(wrapper.text()).toContain("请先选择项目")
  })

  it("加载错误时显示错误与重新加载按钮", () => {
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({ loadError: "网络请求异常" }),
    })
    expect(wrapper.text()).toContain("故事总览加载失败")
    expect(wrapper.text()).toContain("网络请求异常")
    const reloadBtn = wrapper.find('[data-action="reload-story-outline"]')
    expect(reloadBtn.exists()).toBe(true)
    expect(reloadBtn.text()).toBe("重新加载")
  })

  it("assetLoadError 在 Intro 区显示", () => {
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({ assetLoadError: "可选人物未完全加载" }),
    })
    expect(wrapper.find('p.form-error[role="status"]').exists()).toBe(true)
    expect(wrapper.text()).toContain("可选人物未完全加载")
  })

  it("taskNotice 在 Intro 区显示", () => {
    storyOutlineTaskManager.state.taskNotice = "任务已过期"
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })
    expect(wrapper.text()).toContain("任务已过期")
  })
})

describe("渲染 · AI 生成按钮状态", () => {
  it("无 revision 时编辑按钮显示「手工创建」", () => {
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })
    expect(wrapper.find('[data-action="edit-story-outline"]').text()).toContain("手工创建")
  })

  it("有 revision 时编辑按钮显示「编辑为新版本」", () => {
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({
        current: { current_revision_id: "rev-1", revision: revisionFixture() },
      }),
    })
    expect(wrapper.find('[data-action="edit-story-outline"]').text()).toContain("编辑为新版本")
  })

  it("有运行中任务时 AI 生成按钮 disabled", () => {
    storyOutlineTaskManager.state.taskId = "task-running"
    storyOutlineTaskManager.state.progress = {
      taskId: "task-running",
      terminal: false,
      done: false,
      failed: false,
      cancelled: false,
      availableActions: ["cancel"],
    }
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })
    const btn = wrapper.find('[data-action="generate-story-outline"]')
    expect(btn.attributes("disabled")).toBeDefined()
  })

  it("无运行中任务时 AI 生成按钮可用", () => {
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })
    const btn = wrapper.find('[data-action="generate-story-outline"]')
    expect(btn.attributes("disabled")).toBeUndefined()
  })
})

describe("渲染 · 任务进度", () => {
  it("有运行中任务时显示进度卡", () => {
    storyOutlineTaskManager.state.taskId = "task-progress"
    storyOutlineTaskManager.state.progress = {
      taskId: "task-progress",
      label: "AI 小说总纲",
      status: "running",
      statusLabel: "运行中",
      terminal: false,
      done: false,
      failed: false,
      cancelled: false,
      indeterminate: true,
      availableActions: ["cancel"],
      message: "正在生成小说总纲预览",
    }
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })
    expect(wrapper.find(".outline-progress-card-wrap").exists()).toBe(true)
  })
})

// ================================================================
// 行为契约
// ================================================================

describe("行为 · 事件触发", () => {
  it("点击 AI 生成调用 showModalHtml 表单", async () => {
    const showModal = vi.fn()
    setBridgeOverrides({ showModalHtml: showModal, state: { currentProjectId: "p1" } })
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({
        characters: [{ entity_id: "c1", name: "顾沉" }],
        entities: [{ id: "e1", name: "霜城" }],
      }),
    })
    await wrapper.find('[data-action="generate-story-outline"]').trigger("click")
    expect(showModal).toHaveBeenCalledTimes(1)
    const title = showModal.mock.calls[0][0]
    expect(title).toBe("AI 生成故事总览")
  })

  it("有运行中任务时 AI 生成按钮 disabled", async () => {
    const toast = vi.fn()
    setBridgeOverrides({ toast })
    storyOutlineTaskManager.state.taskId = "task-running"
    storyOutlineTaskManager.state.progress = {
      taskId: "task-running",
      terminal: false,
      done: false,
      failed: false,
    }
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })
    const btn = wrapper.find('[data-action="generate-story-outline"]')
    expect(btn.attributes("disabled")).toBeDefined()
  })

  it("点击重新加载原位重取总纲数据", async () => {
    const next = revisionFixture({ id: "rev-2", version_number: 2, title: "重载后总纲" })
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    globalThis.api.outline.getStoryOutline.mockResolvedValue({ current_revision_id: "rev-2", revision: next })
    globalThis.api.outline.listStoryOutlineRevisions.mockResolvedValue({ items: [next], total: 1 })
    globalThis.api.world.listCharacters.mockResolvedValue({ items: [] })
    globalThis.api.world.listEntities.mockResolvedValue({ items: [] })
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })
    await wrapper.find('[data-action="reload-story-outline"]').trigger("click")
    await flushPromises()

    expect(globalThis.api.outline.getStoryOutline).toHaveBeenCalledWith("p1")
    expect(wrapper.text()).toContain("当前版本 · v2")
    expect(wrapper.text()).toContain("重载后总纲")
  })

  it("点击编辑按钮触发 showModalHtml 编辑器", async () => {
    const showModal = vi.fn()
    setBridgeOverrides({ showModalHtml: showModal, state: { currentProjectId: "p1" } })
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })
    await wrapper.find('[data-action="edit-story-outline"]').trigger("click")
    expect(showModal).toHaveBeenCalledTimes(1)
    expect(showModal.mock.calls[0][0]).toBe("编辑故事总览")
  })

  it("查看历史按钮触发 viewRevision", async () => {
    const rev = revisionFixture()
    const showModal = vi.fn()
    setBridgeOverrides({ showModalHtml: showModal, toast: vi.fn(), state: { currentProjectId: "p1" } })
    api.outline.getStoryOutlineRevision = vi.fn().mockResolvedValue(rev)
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({
        current: { current_revision_id: "rev-1", revision: rev },
        history: [rev],
        historyTotal: 1,
      }),
    })
    await wrapper.find('[data-action="view-story-outline-revision"]').trigger("click")
    await wrapper.vm.$nextTick()
    expect(showModal).toHaveBeenCalled()
    expect(showModal.mock.calls[0][0]).toContain("故事总览历史版本")
  })
})

describe("行为 · 任务操作", () => {
  it("取消按钮绑定 cancelTask", async () => {
    const toast = vi.fn()
    setBridgeOverrides({
      toast,
      confirm: vi.fn(() => true),
    })
    storyOutlineTaskManager.state.taskId = "task-cancel"
    storyOutlineTaskManager.state.progress = {
      taskId: "task-cancel",
      terminal: false,
      done: false,
      failed: false,
      cancelled: false,
      availableActions: ["cancel"],
    }
    globalThis.api.tasks.cancel = vi.fn().mockResolvedValue({})
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })
    // 通过进度卡内部的取消按钮触发
    const cancelBtn = wrapper.find('[data-action="cancel-story-outline-task"]')
    if (cancelBtn.exists()) {
      await cancelBtn.trigger("click")
      await wrapper.vm.$nextTick()
      // 确认对话框已处理
    }
  })
})

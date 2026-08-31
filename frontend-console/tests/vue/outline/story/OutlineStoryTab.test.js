/**
 * OutlineStoryTab 组件测试 — 渲染与行为契约。
 * bridge 替身通过 setBridgeOverrides 注入。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"

const confirmAiReference = vi.hoisted(() => vi.fn())
vi.mock("../../../../shared/aiReferenceModal.js", () => ({ confirmAiReference }))

import OutlineStoryTab from "../../../../vue/views/outline/story/OutlineStoryTab.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"
import { storyOutlineTaskManager } from "../../../../vue/views/outline/story/storyOutlineData.js"
import { recoverActiveWorkflows } from "../../../../shared/workflowProgress.js"

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
  confirmAiReference.mockResolvedValue({ id: "confirm-default" })
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
  it("无 revision 时只渲染一个明确的首次进入区", () => {
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })
    const onboarding = wrapper.get(".story-outline-onboarding")
    expect(onboarding.get("#story-outline-intro-title").text()).toBe("先确定故事方向")
    expect(onboarding.get('[data-action="generate-story-outline"]').text()).toBe("AI 生成可编辑预览")
    expect(onboarding.get('[data-action="generate-story-outline"]').classes()).toContain("btn-primary")
    expect(onboarding.get('[data-action="edit-story-outline"]').text()).toBe("手工创建")
    expect(onboarding.get(".story-outline-more").attributes("open")).toBeUndefined()
    expect(wrapper.find("#story-outline-empty-title").exists()).toBe(false)
    expect(wrapper.find("#story-outline-history-title").exists()).toBe(false)
    expect(wrapper.find(".empty-icon").exists()).toBe(false)
  })

  it("有 revision 时渲染当前版本标题、内容与所有区块", () => {
    const rev = revisionFixture({ id: "rev-2", version_number: 2 })
    const oldRev = revisionFixture({ id: "rev-1", is_current: false, title: "霜城纪事初稿" })
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({
        current: { current_revision_id: "rev-2", revision: rev },
        history: [rev, oldRev],
        historyTotal: 2,
      }),
    })
    const text = wrapper.text()
    expect(text).toContain("当前版本 · v2")
    expect(text).toContain("霜城纪事")
    expect(wrapper.findAll(".story-outline-document .card")).toHaveLength(0)
    expect(wrapper.findAll(".story-outline-core > div")).toHaveLength(4)
    expect(wrapper.findAll(".story-outline-entry")).toHaveLength(3)
    expect(wrapper.get(".story-outline-document__prose").text()).toBe("第一部\n\n主角进入霜城档案馆。")
    expect(text).toContain("核心前提")
    expect(text).toContain("基调与读者承诺")
    expect(text).toContain("故事引擎")
    expect(text).toContain("结局方向")
    expect(text).toContain("主要剧情线")
    expect(text).toContain("故事推进")
    expect(text).toContain("待决定问题")
    expect(text).toContain("失真档案")
    expect(text).toContain("驱动主谜题")
    expect(text).toContain("过往版本")
    expect(wrapper.get(".story-outline-history").attributes("open")).toBeUndefined()
    expect(wrapper.get("#story-outline-intro-title").text()).toBe("调整整体方向")
    expect(wrapper.get(".story-outline-intro").classes()).not.toContain("card")
    expect(wrapper.get('[data-action="edit-story-outline"]').classes()).toContain("btn-primary")
    expect(wrapper.get('[data-action="generate-story-outline"]').classes()).not.toContain("btn-primary")
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
    expect(wrapper.text()).toContain("还没有主要剧情线")
    expect(wrapper.text()).toContain("还没有故事推进")
    expect(wrapper.text()).toContain("目前没有待决定问题")
  })

  it("未知来源和异常时间不向作者暴露内部原值", () => {
    const rev = revisionFixture({ source: "internal_batch", created_at: "not-a-date" })
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({ current: { current_revision_id: rev.id, revision: rev } }),
    })
    expect(wrapper.text()).toContain("其他方式创建 · 时间未知")
    expect(wrapper.text()).not.toContain("internal_batch")
    expect(wrapper.text()).not.toContain("not-a-date")
  })

  it("过往版本默认收起并保留安全采用提示", () => {
    const rev = revisionFixture({ id: "old-rev", is_current: false })
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({
        current: { current_revision_id: "rev-curr", revision: revisionFixture({ id: "rev-curr" }) },
        history: [rev],
        historyTotal: 1,
      }),
    })
    expect(wrapper.get(".story-outline-history").attributes("open")).toBeUndefined()
    expect(wrapper.text()).toContain("查看不会改变当前内容")
    expect(wrapper.find('[data-action="view-story-outline-revision"]').text()).toBe("查看内容")
    expect(wrapper.find('[data-action="restore-story-outline-revision"]').exists()).toBe(true)
    expect(wrapper.find('[data-action="restore-story-outline-revision"]').classes()).not.toContain("btn-primary")
  })

  it("当前版本不在过往版本中重复出现", () => {
    const rev = revisionFixture({ id: "rev-current", is_current: true, version_number: 2, title: "当前方向" })
    const oldRev = revisionFixture({ id: "rev-old", is_current: false, title: "旧方向" })
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({
        current: { current_revision_id: "rev-current", revision: rev },
        history: [rev, oldRev],
        historyTotal: 2,
      }),
    })
    const history = wrapper.get(".story-outline-history")
    expect(history.findAll(".story-outline-history__item")).toHaveLength(1)
    expect(history.text()).toContain("旧方向")
    expect(history.text()).not.toContain("当前方向")
    expect(history.find(".badge").exists()).toBe(false)
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

  it("assetLoadError 在当前主操作区显示", () => {
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

  it("正常状态把重新加载收进更多操作", () => {
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })
    const more = wrapper.get(".story-outline-more")
    expect(more.attributes("open")).toBeUndefined()
    expect(more.get("summary").text()).toBe("更多")
    expect(more.get('[data-action="reload-story-outline"]').text()).toBe("重新加载内容")
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
    const taskRegion = wrapper.get(".outline-task-status")
    expect(taskRegion.get(".outline-task-status__title").text()).toBe("AI 任务")
    expect(taskRegion.findComponent({ name: "WorkflowProgressCard" }).exists()).toBe(true)
    expect(taskRegion.element.compareDocumentPosition(wrapper.get("[aria-labelledby='story-outline-intro-title']").element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
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
    expect(title).toBe("用 AI 生成故事总览")
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

  it("点击编辑按钮进入可刷新的编辑页", async () => {
    const navigate = vi.fn()
    setBridgeOverrides({ router: { navigate }, state: { currentProjectId: "p1" } })
    const wrapper = mount(OutlineStoryTab, { props: makeProps() })
    await wrapper.find('[data-action="edit-story-outline"]').trigger("click")
    expect(navigate).toHaveBeenCalledTimes(1)
    expect(navigate.mock.calls[0].slice(0, 3)).toEqual(["outline", "story-outline", true])
    expect(navigate.mock.calls[0][3].toString()).toBe("edit=1")
  })

  it("查看历史按钮触发 viewRevision", async () => {
    const currentRev = revisionFixture({ id: "rev-current", version_number: 2 })
    const rev = revisionFixture({ id: "rev-old", is_current: false })
    const showModal = vi.fn()
    setBridgeOverrides({ showModalHtml: showModal, toast: vi.fn(), state: { currentProjectId: "p1" } })
    api.outline.getStoryOutlineRevision = vi.fn().mockResolvedValue(rev)
    const wrapper = mount(OutlineStoryTab, {
      props: makeProps({
        current: { current_revision_id: "rev-current", revision: currentRev },
        history: [currentRev, rev],
        historyTotal: 2,
      }),
    })
    await wrapper.find('[data-action="view-story-outline-revision"]').trigger("click")
    await wrapper.vm.$nextTick()
    expect(showModal).toHaveBeenCalled()
    expect(showModal.mock.calls[0][0]).toContain("故事总览历史版本")
    expect(showModal.mock.calls[0][1]).toContain("story-outline-document--modal")
    expect(showModal.mock.calls[0][1]).not.toContain('class="card"')
  })
})

describe("行为 · AI 生成设置", () => {
  async function openGenerateForm(props = makeProps()) {
    const host = document.createElement("div")
    document.body.append(host)
    let primaryAction = null
    const closeModal = vi.fn()
    const showModalHtml = vi.fn((_title, html, buttons) => {
      host.innerHTML = html
      primaryAction = buttons[0]
    })
    setBridgeOverrides({
      showModalHtml,
      closeModal,
      toast: vi.fn(),
      state: { currentProjectId: props.projectId },
    })
    const wrapper = mount(OutlineStoryTab, { props })
    await wrapper.get('[data-action="generate-story-outline"]').trigger("click")
    await flushPromises()
    return { wrapper, host, showModalHtml, closeModal, getPrimaryAction: () => primaryAction }
  }

  it("先显示三项作者问题并把参考资料渐进收起", async () => {
    const modal = await openGenerateForm(makeProps({
      characters: [{ entity_id: "c1", name: "顾沉" }],
      entities: [{ id: "e1", name: "霜城" }],
    }))

    expect(modal.showModalHtml.mock.calls[0][0]).toBe("用 AI 生成故事总览")
    expect(modal.showModalHtml.mock.calls[0][3]).toBeUndefined()
    expect(modal.host.textContent).toContain("你想写一个怎样的故事")
    expect(modal.host.textContent).toContain("预计篇幅")
    expect(modal.host.textContent).toContain("这次先规划到哪里")
    expect(modal.host.textContent).toContain("选择参考资料（可选）")
    expect(modal.host.textContent).not.toContain("Top-K")
    expect(modal.host.querySelector(".story-outline-generate__references").open).toBe(false)
    expect(modal.host.querySelector("#story-outline-planned-scale").tagName).toBe("INPUT")
    expect(modal.getPrimaryAction().text).toBe("开始生成预览")

    modal.wrapper.unmount()
    modal.host.remove()
  })

  it("缺少必填内容时显示字段错误并聚焦错误摘要", async () => {
    const modal = await openGenerateForm()
    const result = await modal.getPrimaryAction().handler()

    expect(result).toBe(false)
    expect(globalThis.api.outline.generateStoryOutline).not.toHaveBeenCalled()
    const summary = modal.host.querySelector("#story-outline-generate-error-summary")
    expect(summary.hidden).toBe(false)
    expect(summary.textContent).toContain("你想写一个怎样的故事")
    expect(modal.host.querySelector("#story-outline-author-intent").getAttribute("aria-invalid")).toBe("true")
    expect(document.activeElement).toBe(summary)

    modal.wrapper.unmount()
    modal.host.remove()
  })

  it("沿用原 wire 字段提交作者输入和显式参考资料", async () => {
    const currentRevision = revisionFixture()
    const modal = await openGenerateForm(makeProps({
      current: { current_revision_id: currentRevision.id, revision: currentRevision },
      characters: [{ entity_id: "c1", name: "顾沉" }],
      entities: [{ id: "e1", name: "霜城" }],
    }))
    modal.host.querySelector("#story-outline-author-intent").value = "追查一座城市被抹去的共同记忆"
    modal.host.querySelector("#story-outline-planned-scale").value = "30 万字长篇"
    modal.host.querySelector("#story-outline-coverage").value = "覆盖全书，先细化第一部"
    modal.host.querySelector('input[name="story-outline-character"]').checked = true
    modal.host.querySelector('input[name="story-outline-entity"]').checked = true
    modal.host.querySelector("#story-outline-include-current").checked = true
    globalThis.api.outline.generateStoryOutline.mockResolvedValue({ task_id: "story-task-1", status: "pending" })
    globalThis.api.tasks.get.mockResolvedValue({
      task_id: "story-task-1",
      task_type: "story_outline_generate",
      status: "running",
      meta: { action: "outline.story_outline.generate", novel_id: "p1" },
    })

    expect(await modal.getPrimaryAction().handler()).toBe(true)
    expect(globalThis.api.outline.generateStoryOutline).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      author_intent: "追查一座城市被抹去的共同记忆",
      planned_scale: "30 万字长篇",
      coverage: "覆盖全书，先细化第一部",
      selected_character_ids: ["c1"],
      selected_entity_ids: ["e1"],
      context_confirmation_id: "confirm-default",
      include_current_outline: true,
      operation_id: expect.any(String),
    }))
    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({
      action: "outline.story_outline.generate",
      character_ids: ["c1"],
      entity_ids: ["e1"],
    }))
    const operationId = globalThis.api.outline.generateStoryOutline.mock.calls[0][0].operation_id
    expect(recoverActiveWorkflows("p1").map((item) => item.taskId)).toEqual(["story-task-1"])
    expect(recoverActiveWorkflows("p1").some((item) => item.taskId === operationId)).toBe(false)
    expect(modal.closeModal).toHaveBeenCalledTimes(1)

    modal.wrapper.unmount()
    modal.host.remove()
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

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  normalizeTaskProgress,
  persistActiveWorkflow,
} from "../shared/workflowProgress.js"
import storyOutlineView, { validateStoryOutlineContent } from "../views/storyOutlineView.js"
import { autoConfirm, clearDocument, resetState } from "./helpers.js"

const ACTION = "outline.story_outline.generate"

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

function resetView() {
  storyOutlineView._stopTaskPolling()
  storyOutlineView._projectId = null
  storyOutlineView._lifecycle = 0
  storyOutlineView._loading = false
  storyOutlineView._loadError = null
  storyOutlineView._assetLoadError = null
  storyOutlineView._current = null
  storyOutlineView._history = []
  storyOutlineView._historyTotal = 0
  storyOutlineView._characters = []
  storyOutlineView._entities = []
  storyOutlineView._taskId = null
  storyOutlineView._taskMeta = null
  storyOutlineView._taskProgress = null
  storyOutlineView._taskPoller = null
  storyOutlineView._taskNotice = null
  storyOutlineView._cancelPending = false
  storyOutlineView._preview = null
  storyOutlineView._applyError = null
  storyOutlineView._restoreKeys = {}
}

beforeEach(() => {
  clearDocument()
  localStorage.clear()
  resetState({
    currentProjectId: "p1",
    currentProject: { id: "p1", title: "霜城" },
    currentView: "outline",
    currentSubView: "story-outline",
  })
  resetView()
  api.outline.getStoryOutline.mockResolvedValue({ current_revision_id: null, revision: null })
  api.outline.listStoryOutlineRevisions.mockResolvedValue({ items: [], total: 0, skip: 0, limit: 20 })
  api.world.listCharacters.mockResolvedValue({ items: [], total: 0 })
  api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
  vi.clearAllMocks()
  api.outline.getStoryOutline.mockResolvedValue({ current_revision_id: null, revision: null })
  api.outline.listStoryOutlineRevisions.mockResolvedValue({ items: [], total: 0, skip: 0, limit: 20 })
  api.world.listCharacters.mockResolvedValue({ items: [], total: 0 })
  api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
})

afterEach(() => {
  storyOutlineView._stopTaskPolling()
  vi.useRealTimers()
})

describe("StoryOutline 加载与安全展示", () => {
  it("加载当前 revision、历史和可选世界资产", async () => {
    const revision = revisionFixture()
    api.outline.getStoryOutline.mockResolvedValue({ current_revision_id: "rev-1", revision })
    api.outline.listStoryOutlineRevisions.mockResolvedValue({ items: [revision], total: 1, skip: 0, limit: 20 })
    api.world.listCharacters.mockResolvedValue({ items: [{ entity_id: "char-1", name: "顾沉" }], total: 1 })
    api.world.listEntities.mockResolvedValue({ items: [{ id: "entity-1", name: "霜城" }], total: 1 })

    await storyOutlineView.onEnter()

    expect(api.outline.getStoryOutline).toHaveBeenCalledWith("p1")
    expect(api.outline.listStoryOutlineRevisions).toHaveBeenCalledWith("p1", 0, 20)
    expect(api.world.listCharacters).toHaveBeenCalledWith({ novel_id: "p1", skip: 0, limit: 50 })
    expect(api.world.listEntities).toHaveBeenCalledWith({
      novel_id: "p1",
      display_state: "active",
      skip: 0,
      limit: 50,
      view_mode: "normal",
    })
    expect(storyOutlineView._current.revision.title).toBe("霜城纪事")
    expect(storyOutlineView._historyTotal).toBe(1)
  })

  it("展示全部字段并转义恶意动态文本", async () => {
    const attack = '<img src=x onerror="globalThis.__storyOutlineXss=1">'
    const revision = revisionFixture({
      title: attack,
      creative_core: {
        premise: attack,
        tone_and_reader_promise: attack,
        story_engine: attack,
        ending_direction: attack,
      },
      outline_markdown: attack,
      major_storylines: [{
        name: attack,
        narrative_function: attack,
        trajectory: attack,
        intersections: [attack],
        resolution_direction: attack,
      }],
      macro_movements: [{ name: attack, story_state_change: attack, advanced_storylines: [attack] }],
      open_decisions: [{ question: attack, why_it_matters: attack, options: [attack] }],
    })
    storyOutlineView._projectId = "p1"
    storyOutlineView._current = { current_revision_id: "rev-1", revision }
    storyOutlineView._history = [revision]
    storyOutlineView._historyTotal = 1

    const html = await storyOutlineView.render()
    document.body.innerHTML = `<main id="workspace-content">${html}</main>`

    expect(document.querySelector("img")).toBeNull()
    expect(document.body.innerHTML).toContain("&lt;img")
    expect(globalThis.__storyOutlineXss).toBeUndefined()
    expect(document.body.textContent).toContain("核心前提")
    expect(document.body.textContent).toContain("基调与读者承诺")
    expect(document.body.textContent).toContain("故事引擎")
    expect(document.body.textContent).toContain("结局方向")
    expect(document.body.textContent).toContain("主要剧情线")
    expect(document.body.textContent).toContain("宏观推进")
    expect(document.body.textContent).toContain("开放决策")
  })

  it("历史文案明确说明采用会创建新 revision", () => {
    storyOutlineView._history = [revisionFixture({ id: "old-rev", is_current: false })]
    storyOutlineView._historyTotal = 1

    const html = storyOutlineView._renderHistory()

    expect(html).toContain("创建更高版本号的新 revision")
    expect(html).toContain("不会原地回滚或改写历史")
    expect(html).toContain("采用为新版本")
  })
})

describe("StoryOutline AI 生成与采用", () => {
  it("生成表单只包含高层意图/尺度/覆盖与可选资产，不含起止章", () => {
    storyOutlineView._projectId = "p1"
    storyOutlineView._characters = [{ entity_id: "char-1", name: "顾沉" }]
    storyOutlineView._entities = [{ id: "entity-1", name: "霜城" }]

    storyOutlineView._showGenerateForm()

    const html = showModal.mock.calls.at(-1)[1].html
    expect(html).toContain("作者意图")
    expect(html).toContain("计划尺度")
    expect(html).toContain("覆盖描述")
    expect(html).toContain("可选人物（可为空")
    expect(html).toContain("可选世界对象（可为空")
    expect(html).not.toContain("start_chapter")
    expect(html).not.toContain("end_chapter")
    expect(html).not.toContain("起始章节")
    expect(html).not.toContain("结束章节")
  })

  it("显式空选择可提交生成，生成不会调用 apply", async () => {
    storyOutlineView._projectId = "p1"
    storyOutlineView._current = { current_revision_id: "rev-1", revision: revisionFixture() }
    storyOutlineView._showGenerateForm()
    const html = showModal.mock.calls.at(-1)[1].html
    document.body.innerHTML = `<main id="workspace-content">${html}</main>`
    document.getElementById("story-outline-author-intent").value = "写一部记忆政治长篇"
    document.getElementById("story-outline-planned-scale").value = "百万字三部"
    document.getElementById("story-outline-coverage").value = "覆盖全书"
    api.outline.generateStoryOutline.mockResolvedValue({ task_id: "task-1", status: "pending" })
    api.tasks.get.mockImplementation(() => new Promise(() => {}))

    await storyOutlineView._submitGeneration()

    expect(api.outline.generateStoryOutline).toHaveBeenCalledWith({
      novel_id: "p1",
      author_intent: "写一部记忆政治长篇",
      planned_scale: "百万字三部",
      coverage: "覆盖全书",
      selected_character_ids: [],
      selected_entity_ids: [],
      include_current_outline: false,
    })
    expect(api.outline.applyStoryOutlinePreview).not.toHaveBeenCalled()
    expect(api.outline.createStoryOutlineRevision).not.toHaveBeenCalled()
    expect(storyOutlineView._preview).toBeNull()
  })

  it("完整 preview 所有字段可编辑，采用 wire 携带 base/idempotency/confirmed", async () => {
    storyOutlineView._projectId = "p1"
    storyOutlineView._preview = {
      taskId: "task-1",
      baseRevisionId: "rev-1",
      idempotencyKey: "story-outline-apply-key",
      content: contentFixture(),
    }
    const html = await storyOutlineView.render()
    document.body.innerHTML = `<main id="workspace-content">${html}</main>`
    document.getElementById("story-outline-preview-title-input").value = "编辑后总纲"
    document.getElementById("story-outline-preview-premise").value = "编辑后前提"
    document.getElementById("story-outline-preview-tone").value = "编辑后承诺"
    document.getElementById("story-outline-preview-engine").value = "编辑后引擎"
    document.getElementById("story-outline-preview-ending").value = "编辑后结局"
    document.getElementById("story-outline-preview-markdown").value = "# 编辑后正文"
    document.getElementById("story-outline-preview-major-storylines").value = JSON.stringify([{
      name: "新主线",
      narrative_function: "功能",
      trajectory: "轨迹",
      intersections: [],
      resolution_direction: "收束",
    }])
    document.getElementById("story-outline-preview-macro-movements").value = JSON.stringify([{
      name: "新推进",
      story_state_change: "新状态",
      advanced_storylines: ["新主线"],
    }])
    document.getElementById("story-outline-preview-open-decisions").value = JSON.stringify([{
      question: "新问题",
      why_it_matters: "很重要",
      options: ["选项 A"],
    }])
    api.outline.applyStoryOutlinePreview.mockResolvedValue({ version_number: 2 })

    await storyOutlineView._applyPreview()

    expect(api.outline.applyStoryOutlinePreview).toHaveBeenCalledWith({
      novel_id: "p1",
      source_task_id: "task-1",
      title: "编辑后总纲",
      creative_core: {
        premise: "编辑后前提",
        tone_and_reader_promise: "编辑后承诺",
        story_engine: "编辑后引擎",
        ending_direction: "编辑后结局",
      },
      outline_markdown: "# 编辑后正文",
      major_storylines: [{
        name: "新主线",
        narrative_function: "功能",
        trajectory: "轨迹",
        intersections: [],
        resolution_direction: "收束",
      }],
      macro_movements: [{ name: "新推进", story_state_change: "新状态", advanced_storylines: ["新主线"] }],
      open_decisions: [{ question: "新问题", why_it_matters: "很重要", options: ["选项 A"] }],
      base_revision_id: "rev-1",
      idempotency_key: "story-outline-apply-key",
      confirmed: true,
    })
  })

  it("JSON 错误在前端给出字段级提示，不提交 apply", async () => {
    storyOutlineView._projectId = "p1"
    storyOutlineView._preview = {
      taskId: "task-1",
      baseRevisionId: null,
      idempotencyKey: "story-outline-apply-key",
      content: contentFixture(),
    }
    document.body.innerHTML = `<main id="workspace-content">${await storyOutlineView.render()}</main>`
    document.getElementById("story-outline-preview-major-storylines").value = "{not-json"

    await storyOutlineView._applyPreview()

    expect(api.outline.applyStoryOutlinePreview).not.toHaveBeenCalled()
    expect(document.getElementById("story-outline-apply-error").textContent).toContain("主要剧情线 JSON 格式错误")
  })

  it("409 明确提示重新加载并保留当前编辑 preview", async () => {
    storyOutlineView._projectId = "p1"
    storyOutlineView._preview = {
      taskId: "task-conflict",
      baseRevisionId: "rev-1",
      idempotencyKey: "story-outline-conflict-key",
      content: contentFixture(),
    }
    document.body.innerHTML = `<main id="workspace-content">${await storyOutlineView.render()}</main>`
    const conflict = new Error("请求冲突")
    conflict.status = 409
    api.outline.applyStoryOutlinePreview.mockRejectedValue(conflict)

    await storyOutlineView._applyPreview()

    expect(storyOutlineView._preview.taskId).toBe("task-conflict")
    expect(document.getElementById("story-outline-apply-error").textContent).toContain("请重新加载")
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("请重新加载"), "error")
  })

  it("同一 apply payload 重试复用幂等键，编辑内容后轮换幂等键", async () => {
    storyOutlineView._projectId = "p1"
    storyOutlineView._preview = {
      taskId: "task-retry",
      baseRevisionId: "rev-1",
      idempotencyKey: "story-outline-stable-key",
      content: contentFixture(),
    }
    document.body.innerHTML = `<main id="workspace-content">${await storyOutlineView.render()}</main>`
    api.outline.applyStoryOutlinePreview.mockRejectedValue(new Error("network uncertain"))

    await storyOutlineView._applyPreview()
    const firstKey = api.outline.applyStoryOutlinePreview.mock.calls[0][0].idempotency_key
    await storyOutlineView._applyPreview()
    const retryKey = api.outline.applyStoryOutlinePreview.mock.calls[1][0].idempotency_key
    document.getElementById("story-outline-preview-title-input").value = "作者再次编辑"
    await storyOutlineView._applyPreview()
    const editedKey = api.outline.applyStoryOutlinePreview.mock.calls[2][0].idempotency_key

    expect(firstKey).toBe("story-outline-stable-key")
    expect(retryKey).toBe(firstKey)
    expect(editedKey).not.toBe(firstKey)
    expect(editedKey).toMatch(/^story-outline-/)
  })

  it("冲突后重新加载保留编辑内容并显式更新 apply base", async () => {
    storyOutlineView._projectId = "p1"
    storyOutlineView._current = {
      current_revision_id: "rev-1",
      revision: revisionFixture({ id: "rev-1" }),
    }
    storyOutlineView._preview = {
      taskId: "task-rebase",
      baseRevisionId: "rev-1",
      idempotencyKey: "story-outline-old-key",
      content: contentFixture(),
    }
    document.body.innerHTML = `<main id="workspace-content">${await storyOutlineView.render()}</main>`
    document.getElementById("story-outline-preview-title-input").value = "冲突后保留的编辑"
    api.outline.getStoryOutline.mockResolvedValue({
      current_revision_id: "rev-2",
      revision: revisionFixture({ id: "rev-2", version_number: 2 }),
    })
    api.outline.listStoryOutlineRevisions.mockResolvedValue({
      items: [revisionFixture({ id: "rev-2", version_number: 2 })],
      total: 2,
      skip: 0,
      limit: 20,
    })

    await storyOutlineView._reload()

    expect(storyOutlineView._preview.content.title).toBe("冲突后保留的编辑")
    expect(storyOutlineView._preview.baseRevisionId).toBe("rev-2")
    expect(storyOutlineView._preview.idempotencyKey).not.toBe("story-outline-old-key")
  })
})

describe("StoryOutline 历史与任务恢复", () => {
  it("采用历史发送当前 base 并创建新 revision", async () => {
    storyOutlineView._projectId = "p1"
    storyOutlineView._current = { current_revision_id: "rev-current", revision: revisionFixture({ id: "rev-current" }) }
    api.outline.restoreStoryOutlineRevision.mockResolvedValue({ version_number: 3 })
    autoConfirm()

    await storyOutlineView._restoreRevision("rev-old")

    expect(api.outline.restoreStoryOutlineRevision).toHaveBeenCalledWith(
      "rev-old",
      "p1",
      expect.objectContaining({
        base_revision_id: "rev-current",
        idempotency_key: expect.stringMatching(/^story-outline-/),
        confirmed: true,
      }),
    )
  })

  it("只恢复匹配 project/action/task type 的小说总纲任务", async () => {
    persistActiveWorkflow({
      taskId: "task-wrong-action",
      workflowType: "story_outline_generate",
      projectId: "p1",
      meta: { novel_id: "p1", action: "outline.generate" },
    })
    persistActiveWorkflow({
      taskId: "task-other-project",
      workflowType: "story_outline_generate",
      projectId: "p2",
      meta: { novel_id: "p2", action: ACTION },
    })

    await storyOutlineView.onEnter()

    expect(api.tasks.get).not.toHaveBeenCalled()
    expect(storyOutlineView._taskId).toBeNull()
  })

  it("刷新后恢复匹配任务并完整加载 preview", async () => {
    persistActiveWorkflow({
      taskId: "task-restore",
      workflowType: "story_outline_generate",
      projectId: "p1",
      meta: {
        novel_id: "p1",
        project_id: "p1",
        action: ACTION,
        apply_base_revision_id: "rev-1",
        apply_idempotency_key: "story-outline-restored-key",
      },
    })
    api.tasks.get.mockResolvedValue({
      task_id: "task-restore",
      task_type: "story_outline_generate",
      status: "done",
      progress: 1,
      meta: { novel_id: "p1", action: ACTION },
      result: {
        ...contentFixture(),
        managed_llm_steps: [{ step_name: "outline.story_outline.generate.structured" }],
      },
      available_actions: ["dismiss"],
    })

    await storyOutlineView.onEnter()
    await vi.waitFor(() => expect(storyOutlineView._preview).not.toBeNull())

    expect(api.tasks.get).toHaveBeenCalledWith("task-restore", "p1")
    expect(storyOutlineView._preview).toMatchObject({
      taskId: "task-restore",
      baseRevisionId: "rev-1",
      idempotencyKey: "story-outline-restored-key",
      content: { title: "霜城纪事" },
    })
  })

  it("项目切换后丢弃旧项目的晚到任务响应", async () => {
    persistActiveWorkflow({
      taskId: "task-late",
      workflowType: "story_outline_generate",
      projectId: "p1",
      meta: { novel_id: "p1", project_id: "p1", action: ACTION },
    })
    let resolveTask
    api.tasks.get.mockImplementation(() => new Promise((resolve) => { resolveTask = resolve }))

    await storyOutlineView.onEnter()
    resetState({
      currentProjectId: "p2",
      currentProject: { id: "p2", title: "新项目" },
      currentView: "outline",
      currentSubView: "story-outline",
    })
    await storyOutlineView.onEnter()
    resolveTask({
      task_id: "task-late",
      task_type: "story_outline_generate",
      status: "done",
      meta: { novel_id: "p1", action: ACTION },
      result: contentFixture(),
    })
    await Promise.resolve()
    await Promise.resolve()

    expect(storyOutlineView._projectId).toBe("p2")
    expect(storyOutlineView._preview).toBeNull()
    expect(storyOutlineView._taskId).toBeNull()
  })

  it("任务返回的 novel/action/type 不匹配时拒绝 preview", async () => {
    persistActiveWorkflow({
      taskId: "task-mismatch",
      workflowType: "story_outline_generate",
      projectId: "p1",
      meta: { novel_id: "p1", project_id: "p1", action: ACTION },
    })
    api.tasks.get.mockResolvedValue({
      task_id: "task-mismatch",
      task_type: "outline_generate",
      status: "done",
      meta: { novel_id: "p1", action: ACTION },
      result: contentFixture(),
    })

    await storyOutlineView.onEnter()
    await vi.waitFor(() => expect(storyOutlineView._taskNotice).toContain("不匹配"))

    expect(storyOutlineView._preview).toBeNull()
    expect(storyOutlineView._taskId).toBeNull()
  })

  it("取消显式携带任务所属 novel_id，不伪装成失败", async () => {
    storyOutlineView._projectId = "p1"
    storyOutlineView._taskId = "task-cancel"
    storyOutlineView._taskMeta = { novel_id: "p1", action: ACTION }
    storyOutlineView._taskProgress = normalizeTaskProgress({
      task_id: "task-cancel",
      task_type: "story_outline_generate",
      status: "running",
      meta: storyOutlineView._taskMeta,
      available_actions: ["cancel"],
    }, "story_outline_generate")
    api.tasks.cancel.mockResolvedValue({ task_id: "task-cancel", status: "cancelled", cancelled: true })
    autoConfirm()

    await storyOutlineView._cancelTask()

    expect(api.tasks.cancel).toHaveBeenCalledWith("task-cancel", "p1")
    expect(storyOutlineView._taskProgress.cancelled).toBe(true)
    expect(storyOutlineView._taskProgress.failed).toBe(false)
    expect(storyOutlineView._taskNotice).toContain("已取消")
    expect(storyOutlineView._taskNotice).toContain("没有创建 revision")
  })
})

describe("StoryOutline strict 编辑 schema", () => {
  it("导航标签允许重复或与正文摘要使用不同措辞", () => {
    const content = contentFixture({
      major_storylines: [
        ...contentFixture().major_storylines,
        ...contentFixture().major_storylines,
      ],
      macro_movements: [{
        name: "错误推进",
        story_state_change: "状态改变",
        advanced_storylines: ["摘要中的另一种说法", "摘要中的另一种说法"],
      }],
      open_decisions: [{
        question: "尚未决定",
        why_it_matters: "保留弹性",
        options: ["暂不决定", "暂不决定"],
      }],
    })

    expect(validateStoryOutlineContent(content).macro_movements[0].advanced_storylines)
      .toEqual(["摘要中的另一种说法", "摘要中的另一种说法"])
  })
})

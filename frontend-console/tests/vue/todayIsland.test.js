import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../vue/bridge/index.js"
import { persistActiveWorkflow, recoverActiveWorkflows } from "../../shared/workflowProgress.js"
import { loadTodayProps } from "../../vue/todayIsland.js"
import TodayView from "../../vue/views/today/TodayView.vue"
import {
  generateSessionKey,
  readCreativeContinuation,
  writeCreativeContinuation,
  writeGenerateSession,
} from "../../vue/views/generate/generateSession.js"
import { rememberWritingLocation } from "../../vue/views/writing/writingSession.js"
import { localAuthorDate } from "../../vue/views/writing/home/useAuthorTasks.js"

function deferred() {
  let resolve
  let reject
  const promise = new Promise((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function summaryWithTask(projectId, title) {
  return {
    project_id: projectId,
    writing: {},
    attention: {},
    author_tasks: {
      today_count: 1,
      inbox_count: 0,
      later_count: 0,
      preview: [{ id: "shared-task", title, updated_at: `${projectId}-revision` }],
    },
  }
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

afterEach(() => resetBridgeOverrides())

describe("todayIsland", () => {
  it("作者任务、需要决定和后台整理保持三种不同交互", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    const patchAuthorTask = vi.fn(async () => ({}))
    setBridgeOverrides({
      router,
      api: { projects: { patchAuthorTask } },
      toast: vi.fn(),
    })
    const wrapper = mount(TodayView, { props: {
      project: { id: "p1", title: "雾港" },
      summary: {
        project_id: "p1", writing: {},
        author_tasks: {
          today_count: 1, inbox_count: 2, later_count: 1,
          preview: [{ id: "task-1", title: "核对港口规则", updated_at: "u1", source: { kind: "world_page", id: "page-1", label: "港口制度", available: true } }],
        },
        attention: {
          items: [{ key: "decision-1", source_kind: "world_object", title: "确认别名", summary: "选择正式名称", author_action: "needs_decision", relevance: "project_general", severity: "medium", target: { kind: "world_review_aliases", item_id: "group-1" } }],
          actionable_total: 1,
        },
      },
      workflows: [{ taskId: "worker-1", workflowType: "smart_dedup_scan", percent: 30 }],
    } })

    expect(wrapper.get(".today-author-tasks").text()).toContain("核对港口规则")
    expect(wrapper.get("[aria-labelledby='today-attention-title']").text()).toContain("确认别名")
    expect(wrapper.get("[aria-labelledby='today-workflows-title']").text()).toContain("正在检查重复资料")
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(1)

    await wrapper.get(".today-author-task-row .btn").trigger("click")
    expect(router.navigate.mock.calls.at(-1)[0]).toBe("world")
    expect(router.navigate.mock.calls.at(-1)[3].get("page_id")).toBe("page-1")

    await wrapper.get('.today-author-task-row input[type="checkbox"]').trigger("change")
    await flushPromises()
    expect(patchAuthorTask).toHaveBeenCalledWith("p1", "task-1", { status: "completed", expected_updated_at: "u1" })
    expect(wrapper.find(".today-author-task-row").exists()).toBe(false)
  })

  it("首页任务冲突时恢复复选框并刷新最新摘要", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    const patchAuthorTask = vi.fn(async () => {
      throw Object.assign(new Error("任务已更新"), { status: 409 })
    })
    setBridgeOverrides({
      router,
      api: { projects: { patchAuthorTask } },
      toast: vi.fn(),
    })
    const wrapper = mount(TodayView, { props: {
      project: { id: "p1", title: "雾港" },
      summary: {
        project_id: "p1",
        writing: {},
        attention: {},
        author_tasks: {
          today_count: 1,
          inbox_count: 0,
          later_count: 0,
          preview: [{ id: "task-1", title: "核对港口规则", updated_at: "u1" }],
        },
      },
    } })
    const checkbox = wrapper.get('.today-author-task-row input[type="checkbox"]')
    checkbox.element.checked = true

    await checkbox.trigger("change")
    await flushPromises()

    expect(checkbox.element.checked).toBe(false)
    expect(router.refresh).toHaveBeenCalledTimes(1)
  })

  it("首页任务完成成功晚到时不改写新作品状态或提示刷新", async () => {
    const request = deferred()
    const patchAuthorTask = vi.fn(() => request.promise)
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    const toast = vi.fn()
    setBridgeOverrides({ api: { projects: { patchAuthorTask } }, router, toast })
    const wrapper = mount(TodayView, { props: {
      project: { id: "project-a", title: "作品 A" },
      summary: summaryWithTask("project-a", "A 的任务"),
      workflows: [],
    } })

    const pending = wrapper.get('.today-author-task-row input[type="checkbox"]').trigger("change")
    await vi.waitFor(() => expect(patchAuthorTask).toHaveBeenCalled())
    expect(patchAuthorTask).toHaveBeenCalledWith("project-a", "shared-task", {
      status: "completed",
      expected_updated_at: "project-a-revision",
    })

    await wrapper.setProps({
      project: { id: "project-b", title: "作品 B" },
      summary: summaryWithTask("project-b", "B 的任务"),
    })
    request.resolve({})
    await pending
    await flushPromises()

    expect(wrapper.get(".today-author-task-row strong").text()).toBe("B 的任务")
    expect(wrapper.get('.today-author-task-row input[type="checkbox"]').attributes("disabled")).toBeUndefined()
    expect(toast).not.toHaveBeenCalled()
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it.each([409, 500])("首页任务完成错误 %s 晚到时不改写新作品状态或提示刷新", async (status) => {
    const request = deferred()
    const patchAuthorTask = vi.fn(() => request.promise)
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    const toast = vi.fn()
    setBridgeOverrides({ api: { projects: { patchAuthorTask } }, router, toast })
    const wrapper = mount(TodayView, { props: {
      project: { id: "project-a", title: "作品 A" },
      summary: summaryWithTask("project-a", "A 的任务"),
      workflows: [],
    } })

    const pending = wrapper.get('.today-author-task-row input[type="checkbox"]').trigger("change")
    await vi.waitFor(() => expect(patchAuthorTask).toHaveBeenCalled())
    await wrapper.setProps({
      project: { id: "project-b", title: "作品 B" },
      summary: summaryWithTask("project-b", "B 的任务"),
    })
    const currentCheckbox = wrapper.get('.today-author-task-row input[type="checkbox"]')
    currentCheckbox.element.checked = true
    request.reject(Object.assign(new Error("A 的任务更新失败"), { status }))
    await pending
    await flushPromises()

    expect(patchAuthorTask.mock.calls[0][0]).toBe("project-a")
    expect(wrapper.get(".today-author-task-row strong").text()).toBe("B 的任务")
    expect(currentCheckbox.element.checked).toBe(true)
    expect(currentCheckbox.attributes("disabled")).toBeUndefined()
    expect(toast).not.toHaveBeenCalled()
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("只在服务器续写章与本机指针一致时带入 Scene", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    setBridgeOverrides({ router })
    rememberWritingLocation("p1", { currentChapter: 3, currentDraftId: "d3", currentSceneId: "s3" })
    const wrapper = mount(TodayView, { props: {
      project: { id: "p1" },
      summary: { project_id: "p1", continuation: { chapter_index: 3, title: "第三章" }, writing: {}, attention: {} },
    } })
    await wrapper.get(".today-resume__action").trigger("click")
    expect(router.navigate.mock.calls[0][3].get("scene_id")).toBe("s3")

    await wrapper.setProps({ summary: { project_id: "p1", continuation: { chapter_index: 4, title: "第四章" }, writing: {}, attention: {} } })
    await wrapper.get(".today-resume__action").trigger("click")
    expect(router.navigate.mock.calls[1][3].get("scene_id")).toBeNull()
  })

  it("把本机写作位置作为可选排序焦点传给安全摘要", async () => {
    const getWorkspaceSummary = vi.fn(async () => ({ project_id: "p1", attention: { items: [] } }))
    rememberWritingLocation("p1", { currentChapter: 3, currentDraftId: "d3", currentSceneId: "s3" })
    setBridgeOverrides({
      state: { currentProjectId: "p1", currentProject: { id: "p1" } },
      api: { projects: { getWorkspaceSummary }, tasks: { get: vi.fn() } },
    })

    await loadTodayProps()

    expect(getWorkspaceSummary).toHaveBeenCalledWith("p1", {
      focus_chapter_index: 3,
      focus_scene_id: "s3",
      on_date: localAuthorDate(),
    })
  })

  it("展示具体待决事项并深链到所属领域", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    setBridgeOverrides({ router })
    const wrapper = mount(TodayView, { props: {
      project: { id: "p1" },
      summary: {
        project_id: "p1",
        writing: {},
        attention: {
          items: [{
            key: "writing:item-1",
            source_kind: "writing_conflict",
            title: "核对港口规则",
            summary: "正文没有逐字出现约定内容",
            author_action: "can_improve",
            relevance: "exact_scene",
            severity: "low",
            target: { kind: "writing_conflict", item_id: "item-1", chapter_index: 3, scene_id: "s3" },
          }],
          actionable_total: 7,
          has_more: true,
          more_targets: [{
            source_kind: "writing_conflict",
            target: { kind: "writing_conflict", chapter_index: 3, scene_id: "s3" },
          }, {
            source_kind: "world_relation_group",
            target: { kind: "world_review_relations" },
          }],
          world_objects: 2,
        },
      },
    } })

    expect(wrapper.get(".today-attention-row").text()).toContain("当前场景")
    expect(wrapper.get(".today-attention-row").text()).toContain("可以改进")
    expect(wrapper.get(".today-attention-footer").text()).toContain("还有 6 项")
    expect(wrapper.findAll(".today-attention-footer .btn")).toHaveLength(1)
    expect(wrapper.get(".today-attention-footer .btn").text()).toBe("查看更多")
    await wrapper.get(".today-attention-row .btn").trigger("click")

    const query = router.navigate.mock.calls[0][3]
    expect(router.navigate.mock.calls[0].slice(0, 3)).toEqual(["writing", null, true])
    expect(query.get("open")).toBe("conflicts")
    expect(query.get("conflict_item_id")).toBe("item-1")
    expect(query.get("scene_id")).toBe("s3")

    await wrapper.get(".today-attention-footer .btn").trigger("click")
    expect(router.navigate.mock.calls[1][3].get("conflict_item_id")).toBeNull()
    expect(router.navigate.mock.calls[1][3].get("open")).toBe("conflicts")
  })

  it("具体待决列表为空时显示诚实空态", () => {
    setBridgeOverrides({ router: { navigate: vi.fn(), refresh: vi.fn() } })
    const wrapper = mount(TodayView, { props: {
      project: { id: "p1" },
      summary: { project_id: "p1", writing: {}, attention: { items: [], actionable_total: 0, has_more: false } },
    } })

    expect(wrapper.get(".today-attention-empty").text()).toBe("当前没有需要你决定的内容")
    expect(wrapper.find(".today-attention-card").exists()).toBe(false)
  })

  it.each([
    ["world_review_objects", "objects", "entity_id"],
    ["world_review_aliases", "aliases", "group_id"],
    ["world_review_relations", "relations", "group_id"],
  ])("World 审核深链精确携带 %s 目标", async (kind, reviewKind, targetKey) => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    setBridgeOverrides({ router })
    const wrapper = mount(TodayView, { props: {
      project: { id: "p1" },
      summary: {
        project_id: "p1",
        writing: {},
        attention: {
          items: [{
            key: `world:${kind}:target-1`,
            source_kind: "world_object",
            title: "审核世界设定",
            summary: "确认是否采用。",
            author_action: "needs_decision",
            relevance: "current_chapter",
            severity: "medium",
            target: { kind, item_id: "target-1", chapter_index: 3 },
          }],
          actionable_total: 1,
        },
      },
    } })

    await wrapper.get(".today-attention-row .btn").trigger("click")

    const query = router.navigate.mock.calls[0][3]
    expect(router.navigate.mock.calls[0].slice(0, 3)).toEqual(["world", "review", true])
    expect(query.get("kind")).toBe(reviewKind)
    expect(query.get(targetKey)).toBe("target-1")
    expect(query.get("source_chapter_index")).toBe("3")
  })

  it("loads the safe project summary and restores at most three workflows", async () => {
    const state = { currentProjectId: "p1", currentProject: { id: "p1", title: "雾港" } }
    const api = {
      projects: { getWorkspaceSummary: vi.fn(async () => ({ project_id: "p1", continuation: null, writing: {}, attention: {} })) },
      tasks: { get: vi.fn(async (taskId) => ({ id: taskId, task_id: taskId, task_type: "deep_import", status: "running", progress: 0.5 })) },
    }
    for (let index = 1; index <= 4; index += 1) {
      persistActiveWorkflow({ taskId: `t${index}`, workflowType: "deep_import", projectId: "p1" })
    }
    setBridgeOverrides({ state, api })

    const props = await loadTodayProps()

    expect(props.summary.project_id).toBe("p1")
    expect(props.workflows).toHaveLength(3)
    expect(props.workflows[0]).not.toHaveProperty("errorMessage", expect.stringContaining("t1"))
    expect(api.tasks.get).toHaveBeenCalledTimes(3)
    expect(api.tasks.get).toHaveBeenCalledWith(expect.any(String), "p1")
  })

  it("keeps an unavailable workflow visible without exposing a technical failure", async () => {
    const state = { currentProjectId: "p1", currentProject: { id: "p1", title: "雾港" } }
    persistActiveWorkflow({ taskId: "private-task-id", workflowType: "writing_generate", projectId: "p1" })
    setBridgeOverrides({
      state,
      api: {
        projects: { getWorkspaceSummary: vi.fn(async () => ({ project_id: "p1" })) },
        tasks: { get: vi.fn(async () => { throw new Error("worker offline") }) },
      },
    })

    const props = await loadTodayProps()

    expect(props.workflows).toEqual([expect.objectContaining({ stateUnknown: true, statusLabel: "状态暂不可用" })])
  })

  it("保留已完成但尚待作者审阅的故事总览收据", async () => {
    const state = { currentProjectId: "p1", currentProject: { id: "p1", title: "雾港" } }
    persistActiveWorkflow({
      taskId: "story-outline-task",
      workflowType: "story_outline_generate",
      projectId: "p1",
      view: "outline",
    })
    persistActiveWorkflow({
      taskId: "applied-story-outline-task",
      workflowType: "story_outline_generate",
      projectId: "p1",
      view: "outline",
    })
    setBridgeOverrides({
      state,
      api: {
        projects: { getWorkspaceSummary: vi.fn(async () => ({ project_id: "p1" })) },
        tasks: { get: vi.fn(async (taskId) => ({
          task_id: taskId,
          task_type: "story_outline_generate",
          status: "done",
          result: { apply_status: taskId.startsWith("applied-") ? "applied" : null },
        })) },
      },
    })

    const props = await loadTodayProps()

    expect(props.workflows).toEqual([expect.objectContaining({
      taskId: "story-outline-task",
      workflowType: "story_outline_generate",
      done: true,
    })])
    expect(recoverActiveWorkflows("p1").map((workflow) => workflow.taskId)).toEqual(["story-outline-task"])
  })

  it("does not block writing when the summary request fails", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    setBridgeOverrides({
      router,
      state: { currentProjectId: "p1", currentProject: { id: "p1", title: "雾港" } },
      api: {
        projects: { getWorkspaceSummary: vi.fn(async () => { throw new Error("暂时离线") }) },
        tasks: { get: vi.fn() },
      },
    })

    const props = await loadTodayProps()

    expect(props.summary).toBeNull()
    expect(props.loadError).toContain("暂时离线")
    const wrapper = mount(TodayView, { props })
    expect(wrapper.get("#today-resume-title").text()).toBe("继续写作")
    expect(wrapper.get(".today-resume__action").text()).toBe("进入写作")
    expect(wrapper.findAll(".today-attention-card")).toHaveLength(4)
    expect(wrapper.get(".today-attention-card strong").text()).toBe("—")
    await wrapper.get(".today-resume__action").trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("writing", null, true, expect.any(URLSearchParams))
  })

  it("uses the single hero action to continue an unfinished import before the first chapter", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    setBridgeOverrides({ router })
    const wrapper = mount(TodayView, {
      props: {
        project: { id: "p1", title: "雾港" },
        summary: { continuation: null, writing: { chapter_count: 0, word_count: 0 }, attention: {} },
        workflows: [{ taskId: "hidden-task", workflowType: "deep_import", status: "running" }],
      },
    })

    expect(wrapper.get("#today-resume-title").text()).toBe("继续整理导入内容")
    const primary = wrapper.get(".today-resume__action")
    expect(primary.text()).toBe("继续整理")
    expect(wrapper.findAll(".today-resume .btn-primary")).toHaveLength(1)
    await primary.trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("writing", null)
  })

  it("空白作品不需要模型也能先写第一章，世界观保留为次操作", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    setBridgeOverrides({ router })
    const wrapper = mount(TodayView, {
      props: {
        project: { id: "p1", title: "雾港" },
        summary: { continuation: null, writing: { chapter_count: 0, word_count: 0 }, attention: {} },
        workflows: [],
      },
    })

    expect(wrapper.get("#today-resume-title").text()).toBe("开始第一章")
    expect(wrapper.findAll(".today-resume .btn-primary")).toHaveLength(1)
    expect(wrapper.get('[data-action="continue-writing"]').text()).toBe("开始第一章")
    await wrapper.get('[data-action="continue-writing"]').trigger("click")
    expect(router.navigate).toHaveBeenNthCalledWith(1, "writing", null, true, expect.any(URLSearchParams))

    await wrapper.get('[data-action="start-world-core"]').trigger("click")
    const query = router.navigate.mock.calls[1][3]
    expect(router.navigate).toHaveBeenNthCalledWith(2, "generate", null, true, expect.any(URLSearchParams))
    expect(query.get("preset")).toBe("world_core")
    expect(query.get("target")).toBe("core_entity")
  })

  it("隐藏首页任务只更新本地卡片，不整页刷新", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    const confirmAction = vi.fn((_message, onConfirm) => onConfirm())
    const toast = vi.fn()
    persistActiveWorkflow({ taskId: "failed-task", workflowType: "writing_generate", projectId: "p1" })
    setBridgeOverrides({ router, confirmAction, toast })
    const wrapper = mount(TodayView, {
      props: {
        project: { id: "p1", title: "雾港" },
        summary: { continuation: null, writing: {}, attention: {} },
        workflows: [{ taskId: "failed-task", workflowType: "writing_generate", failed: true }],
      },
    })

    await wrapper.get(".today-workflow-card__actions .btn-ghost").trigger("click")

    expect(confirmAction).toHaveBeenCalledWith(expect.stringContaining("仍可以在对应页面找回"), expect.any(Function), "从首页隐藏")
    expect(wrapper.find(".today-workflow-card").exists()).toBe(false)
    expect(recoverActiveWorkflows("p1")).toEqual([])
    expect(toast).toHaveBeenCalledWith("已从首页隐藏", "success")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("keeps正文 primary while exposing the explicit local world track as secondary", async () => {
    const state = { currentProjectId: "p1", currentProject: { id: "p1", title: "雾港" } }
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    const generate = { worldChat: vi.fn(), generateWorldSuggestion: vi.fn() }
    const key = generateSessionKey("p1", "page-a", "world_bible_page")
    writeGenerateSession(key, { composer: "继续轨道 A", messages: [] })
    writeCreativeContinuation("p1", {
      destination: "generate",
      route: { source_page_id: "page-a", target: "world_bible_page" },
    })
    setBridgeOverrides({
      state,
      router,
      api: {
        projects: { getWorkspaceSummary: vi.fn(async () => ({ project_id: "p1", continuation: { title: "第三章", chapter_index: 3 }, writing: {}, attention: {} })) },
        world: {
          listBibleDrafts: vi.fn(async () => ({ items: [{ id: "draft-b", title: "后台更新的轨道 B" }] })),
          listSuggestions: vi.fn(async () => ({ items: [] })),
        },
        generate,
        tasks: { get: vi.fn() },
      },
    })

    const props = await loadTodayProps()
    const wrapper = mount(TodayView, { props })

    expect(wrapper.get("#today-resume-title").text()).toBe("继续第 3 章正文")
    expect(wrapper.get(".today-resume__action").text()).toBe("进入正文编辑")
    expect(wrapper.get("#today-resume-secondary-title").text()).toBe("继续完善世界书页面")
    await wrapper.get('[data-action="continue-world-secondary"]').trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("generate", null, true, expect.any(URLSearchParams))
    const query = router.navigate.mock.calls[0][3]
    expect(query.get("source_page_id")).toBe("page-a")
    expect(query.get("target")).toBe("world_bible_page")
    expect(generate.worldChat).not.toHaveBeenCalled()
    expect(generate.generateWorldSuggestion).not.toHaveBeenCalled()

    await wrapper.get(".today-resume__action").trigger("click")
    expect(router.navigate.mock.calls.at(-1).slice(0, 3)).toEqual(["writing", null, true])
    expect(router.navigate.mock.calls.at(-1)[3].get("chapter_index")).toBe("3")
  })

  it("deduplicates a world continuation shown beside正文", () => {
    const worldDraft = {
      key: "world_bible_draft:draft-1",
      destination: "world_bible_draft",
      route: { draft_id: "draft-1" },
      title: "继续《潮汐法则》工作稿",
      description: "打开服务器保存的世界书工作稿；正式页面尚未变化。",
    }
    setBridgeOverrides({ router: { navigate: vi.fn(), refresh: vi.fn() } })

    const wrapper = mount(TodayView, { props: {
      project: { id: "p1", title: "雾港" },
      summary: {
        project_id: "p1",
        continuation: { title: "第三章", chapter_index: 3 },
        writing: { chapter_count: 3, word_count: 1200 },
        attention: {},
      },
      creativeContinuation: worldDraft,
      worldContinuations: [worldDraft],
    } })

    expect(wrapper.findAll(".today-resume-secondary")).toHaveLength(1)
    expect(wrapper.find("[aria-labelledby='today-unfinished-world-title']").exists()).toBe(false)
  })

  it("clears an evicted local pointer and promotes a server draft without pretending chat is cross-device", async () => {
    const state = { currentProjectId: "p1", currentProject: { id: "p1", title: "雾港" } }
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    writeCreativeContinuation("p1", {
      destination: "generate",
      route: { source_page_id: null, target: "core_entity" },
    })
    setBridgeOverrides({
      state,
      router,
      api: {
        projects: { getWorkspaceSummary: vi.fn(async () => ({ project_id: "p1", continuation: null, writing: {}, attention: {} })) },
        world: {
          listBibleDrafts: vi.fn(async () => ({ items: [{ id: "draft-1", page_id: "page-1", title: "潮汐法则" }] })),
          listSuggestions: vi.fn(async () => ({ items: [{ id: "suggestion-1", target_type: "world_bible_page_draft", payload_json: { page: { title: "港口制度" } } }] })),
        },
        tasks: { get: vi.fn() },
      },
    })

    const props = await loadTodayProps()
    const wrapper = mount(TodayView, { props })

    expect(props.creativeContinuation).toBeNull()
    expect(props.continuationWarning).toContain("已失效")
    expect(wrapper.get("#today-resume-title").text()).toBe("继续《潮汐法则》工作稿")
    expect(wrapper.get(".today-resume").text()).toContain("本机未发送的文字和对话不会出现在其他设备")
    await wrapper.get(".today-resume__action").trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("world", "bible", true, expect.any(URLSearchParams))
    expect(readCreativeContinuation("p1")).toMatchObject({ destination: "world_bible_draft", route: { draft_id: "draft-1" } })
  })

  it("offers a saved World Core checkpoint across devices without a local chat session", async () => {
    const state = { currentProjectId: "p1", currentProject: { id: "p1", title: "雾港" } }
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    setBridgeOverrides({
      state,
      router,
      api: {
        projects: { getWorkspaceSummary: vi.fn(async () => ({ project_id: "p1", continuation: null, writing: { chapter_count: 0 }, attention: {} })) },
        world: {
          listBibleDrafts: vi.fn(async () => ({ items: [] })),
          listSuggestions: vi.fn(async ({ review_group: reviewGroup }) => ({
            items: reviewGroup === "world_adoption"
              ? [{ id: "checkpoint-1", target_type: "world_core_checkpoint", payload_json: { schema_version: "world_core_checkpoint.v1" } }]
              : [],
          })),
        },
        tasks: { get: vi.fn() },
      },
    })

    const props = await loadTodayProps()
    const wrapper = mount(TodayView, { props })

    expect(props.creativeContinuation).toBeNull()
    expect(wrapper.get("#today-resume-title").text()).toBe("继续让灵感生长")
    await wrapper.get(".today-resume__action").trigger("click")
    const query = router.navigate.mock.calls[0][3]
    expect(query.get("preset")).toBe("world_core")
    expect(query.get("checkpoint_id")).toBe("checkpoint-1")
  })

  it("prioritizes review of a Deep Import adoption package", async () => {
    const state = { currentProjectId: "p1", currentProject: { id: "p1", title: "雾港" } }
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    setBridgeOverrides({
      state,
      router,
      api: {
        projects: { getWorkspaceSummary: vi.fn(async () => ({ project_id: "p1", continuation: null, writing: { chapter_count: 0 }, attention: {} })) },
        world: {
          listBibleDrafts: vi.fn(async () => ({ items: [] })),
          listSuggestions: vi.fn(async ({ review_group: reviewGroup }) => ({
            items: reviewGroup === "world_adoption"
              ? [{ id: "package-1", target_type: "world_adoption_package", source_module: "imports" }]
              : [],
          })),
        },
        tasks: { get: vi.fn() },
      },
    })

    const wrapper = mount(TodayView, { props: await loadTodayProps() })
    expect(wrapper.get("#today-resume-title").text()).toBe("审阅深度导入设定")
    await wrapper.get(".today-resume__action").trigger("click")
    const query = router.navigate.mock.calls[0][3]
    expect(router.navigate.mock.calls[0].slice(0, 3)).toEqual(["world", "bible", true])
    expect(query.get("adoption_package_id")).toBe("package-1")
  })

  it("不在未完成创作中重复展示已进入待决投影的建议", async () => {
    const suggestion = { id: "suggestion-1", target_type: "world_bible_page_draft", payload_json: { page: { title: "港口制度" } } }
    setBridgeOverrides({
      state: { currentProjectId: "p1", currentProject: { id: "p1" } },
      api: {
        projects: { getWorkspaceSummary: vi.fn(async () => ({
          project_id: "p1",
          writing: { chapter_count: 1 },
          attention: {
            items: [{ key: "world:suggestion-1", target: { kind: "world_suggestion", suggestion_id: "suggestion-1" } }],
          },
        })) },
        world: {
          listBibleDrafts: vi.fn(async () => ({ items: [] })),
          listSuggestions: vi.fn(async ({ review_group: reviewGroup }) => ({ items: reviewGroup === "generation_center" ? [suggestion] : [] })),
        },
        tasks: { get: vi.fn() },
      },
    })

    const props = await loadTodayProps()

    expect(props.worldContinuations).toEqual([])
  })

  it("采用包待决项打开既有审阅入口", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    setBridgeOverrides({ router })
    const wrapper = mount(TodayView, { props: {
      project: { id: "p1" },
      summary: {
        project_id: "p1",
        writing: {},
        attention: {
          items: [{
            key: "world:adoption-package",
            source_kind: "world_suggestion",
            title: "确认待采用建议：世界设定采用包",
            summary: "查看建议并决定是否采用。",
            author_action: "needs_decision",
            relevance: "project_general",
            severity: "medium",
            target: { kind: "world_adoption", suggestion_id: "package-1" },
          }],
          actionable_total: 1,
        },
      },
    } })

    await wrapper.get(".today-attention-row .btn").trigger("click")

    const query = router.navigate.mock.calls[0][3]
    expect(router.navigate.mock.calls[0].slice(0, 3)).toEqual(["world", "bible", true])
    expect(query.get("adoption_package_id")).toBe("package-1")
    expect(query.get("open")).toBeNull()
  })

  it("世界书目录导入待决项回到导入向导", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    setBridgeOverrides({ router })
    const wrapper = mount(TodayView, { props: {
      project: { id: "p1" },
      summary: {
        project_id: "p1", writing: {},
        attention: { items: [{
          key: "world:worldbook-import", source_kind: "world_suggestion",
          title: "确认待采用建议：世界书目录导入", summary: "查看导入预览。",
          author_action: "needs_decision", relevance: "project_general", severity: "high",
          target: { kind: "worldbook_import", suggestion_id: "import-1" },
        }], actionable_total: 1 },
      },
    } })

    await wrapper.get(".today-attention-row .btn").trigger("click")

    const query = router.navigate.mock.calls[0][3]
    expect(router.navigate.mock.calls[0].slice(0, 3)).toEqual(["world", "bible", true])
    expect(query.get("open")).toBe("worldbook-import")
    expect(query.get("suggestion_id")).toBe("import-1")
  })

  it("keeps a pending suggestion pointer that is beyond the first result page", async () => {
    const state = { currentProjectId: "p1", currentProject: { id: "p1", title: "雾港" } }
    const firstPage = Array.from({ length: 50 }, (_, index) => ({
      id: `suggestion-${index + 1}`,
      target_type: "world_bible_page_draft",
      payload_json: { page: { title: `建议 ${index + 1}` } },
    }))
    const pointed = {
      id: "suggestion-51",
      target_type: "world_bible_page_draft",
      payload_json: { page: { title: "精确恢复的港口制度" } },
    }
    writeCreativeContinuation("p1", {
      destination: "world_suggestion_review",
      route: { suggestion_id: pointed.id },
    })
    const listSuggestions = vi.fn(async ({ skip }) => (
      skip === 0
        ? { items: firstPage, total: 51 }
        : { items: [pointed], total: 51 }
    ))
    setBridgeOverrides({
      state,
      api: {
        projects: { getWorkspaceSummary: vi.fn(async () => ({ project_id: "p1", continuation: null, writing: {}, attention: {} })) },
        world: {
          listBibleDrafts: vi.fn(async () => ({ items: [] })),
          listSuggestions,
        },
        tasks: { get: vi.fn() },
      },
    })

    const props = await loadTodayProps()

    const generationCalls = listSuggestions.mock.calls.filter(([request]) => request.review_group === "generation_center")
    expect(generationCalls[0][0]).toEqual(expect.objectContaining({ skip: 0, limit: 50 }))
    expect(generationCalls[1][0]).toEqual(expect.objectContaining({ skip: 50, limit: 50 }))
    expect(props.creativeContinuation).toMatchObject({
      destination: "world_suggestion_review",
      route: { suggestion_id: "suggestion-51" },
      title: "审查《精确恢复的港口制度》建议",
    })
    expect(props.continuationWarning).toBeNull()
    expect(readCreativeContinuation("p1")).toMatchObject({
      destination: "world_suggestion_review",
      route: { suggestion_id: "suggestion-51" },
    })
  })
})

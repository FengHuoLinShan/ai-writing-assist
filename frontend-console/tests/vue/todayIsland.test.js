import { mount } from "@vue/test-utils"
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

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

afterEach(() => resetBridgeOverrides())

describe("todayIsland", () => {
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

  it("does not block writing when the summary request fails", async () => {
    setBridgeOverrides({
      state: { currentProjectId: "p1", currentProject: { id: "p1", title: "雾港" } },
      api: {
        projects: { getWorkspaceSummary: vi.fn(async () => { throw new Error("暂时离线") }) },
        tasks: { get: vi.fn() },
      },
    })

    const props = await loadTodayProps()

    expect(props.summary).toBeNull()
    expect(props.loadError).toContain("暂时离线")
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

  it("uses one primary action to start World Core in an empty project", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    setBridgeOverrides({ router })
    const wrapper = mount(TodayView, {
      props: {
        project: { id: "p1", title: "雾港" },
        summary: { continuation: null, writing: { chapter_count: 0, word_count: 0 }, attention: {} },
        workflows: [],
      },
    })

    expect(wrapper.get("#today-resume-title").text()).toBe("从几个灵感开始")
    expect(wrapper.findAll(".today-resume .btn-primary")).toHaveLength(1)
    await wrapper.get('[data-action="start-world-core"]').trigger("click")
    const query = router.navigate.mock.calls[0][3]
    expect(router.navigate).toHaveBeenCalledWith("generate", null, true, expect.any(URLSearchParams))
    expect(query.get("preset")).toBe("world_core")
    expect(query.get("target")).toBe("core_entity")
  })

  it("隐藏首页任务只更新本地卡片，不整页刷新", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    persistActiveWorkflow({ taskId: "failed-task", workflowType: "writing_generate", projectId: "p1" })
    setBridgeOverrides({ router })
    const wrapper = mount(TodayView, {
      props: {
        project: { id: "p1", title: "雾港" },
        summary: { continuation: null, writing: {}, attention: {} },
        workflows: [{ taskId: "failed-task", workflowType: "writing_generate", failed: true }],
      },
    })

    await wrapper.get(".today-workflow-card__actions .btn-ghost").trigger("click")

    expect(wrapper.find(".today-workflow-card").exists()).toBe(false)
    expect(recoverActiveWorkflows("p1")).toEqual([])
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("keeps the author's explicit local world track ahead of writing and background refreshes", async () => {
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

    expect(wrapper.get("#today-resume-title").text()).toBe("继续完善世界书页面")
    expect(wrapper.get(".today-resume").text()).not.toContain("第 3 章")
    await wrapper.get(".today-resume__action").trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("generate", null, true, expect.any(URLSearchParams))
    const query = router.navigate.mock.calls[0][3]
    expect(query.get("source_page_id")).toBe("page-a")
    expect(query.get("target")).toBe("world_bible_page")
    expect(generate.worldChat).not.toHaveBeenCalled()
    expect(generate.generateWorldSuggestion).not.toHaveBeenCalled()
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

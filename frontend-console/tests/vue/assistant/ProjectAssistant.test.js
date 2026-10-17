import { afterEach, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { reactive } from "vue"
import ProjectAssistant from "../../../vue/components/ProjectAssistant.vue"

const ExplorationResultCardStub = {
  props: ["source", "projectId"],
  emits: ["refresh"],
  template: '<article class="exploration-stub" :data-result-id="source.result_id" :data-source="JSON.stringify(source)"></article>',
}

afterEach(() => { mocks.api = null })

const mocks = vi.hoisted(() => ({ assistant: null, opener: null, api: null }))
vi.mock("../../../vue/composables/useProjectAssistant.js", () => ({ createProjectAssistant: () => mocks.assistant }))
vi.mock("../../../vue/bridge/index.js", () => ({
  getAssistantWorkContext: () => ({}), registerProjectAssistantOpener: handler => { mocks.opener = handler; return () => { mocks.opener = null } },
  getApi: () => mocks.api || {},
  getConfirm: () => () => true,
}))
vi.mock("../../../vue/shared/assistantNavigation.js", () => ({ locateAssistantSource: vi.fn(), openAssistantDestination: vi.fn() }))
enableAutoUnmount(afterEach)

const baseState = () => reactive({ enabled: true, messages: [], sessions: [], total: 0, messageTotal: 0, input: "", run: null, loading: false, busy: false, destinations: [], selected: [], context: null, omissions: [] })

it("renders an exploration result source through the dedicated card", async () => {
  const state = baseState()
  state.run = { id: "run-1", status: "completed", result: { sources: [{ evidence_id: "ev-1", title: "探索结果", domain_reference: { type: "story_exploration_result", root_id: "root-1", branch_id: "branch-1", result_id: "result-1", scale: "scene_line", label: "B 会说什么", output_kind: "story.exploration.scene_line", payload: { line: "你是不是没睡好？", rationale: "只看到疲惫", withheld: ["A 已失业"], unknowns: [], warnings: [] } } }] } }
  mocks.assistant = { state, load: vi.fn(), dispose: vi.fn(), refreshRun: vi.fn(async () => state.run) }
  const wrapper = mount(ProjectAssistant, { props: { projectId: "p1", open: true }, global: { stubs: { ProactiveCare: true, EditorialDesk: true, ExplorationResultCard: ExplorationResultCardStub } } })
  const card = wrapper.getComponent(ExplorationResultCardStub)
  expect(card.attributes("data-result-id")).toBe("result-1")
  expect(JSON.parse(card.attributes("data-source")).output_kind).toBe("story.exploration.scene_line")

  card.vm.$emit("refresh")
  await wrapper.vm.$nextTick()
  expect(mocks.assistant.refreshRun).toHaveBeenCalledWith(state.run.id)
})

it("shows the exploration recommendation with a manual scale override and preview", async () => {
  const state = baseState()
  state.run = { status: "completed", result: { sources: [{ evidence_id: "ev-2", title: "探索推荐", domain_reference: { type: "story_exploration_recommendation", scale: "sandbox", focus: "面包师的日常", reason: "输入是一条世界规则" } }] } }
  const explorationPreview = vi.fn(async () => ({ recommendation: { scale: "sandbox" }, budget: { requests_min: 1, requests_max: 1 }, possible_charge: "开始模型请求后可能产生计费" }))
  mocks.api = { story: { explorationPreview } }
  mocks.assistant = { state, load: vi.fn(), dispose: vi.fn(), refreshRun: vi.fn() }
  const wrapper = mount(ProjectAssistant, { props: { projectId: "p1", open: true }, global: { stubs: { ProactiveCare: true, EditorialDesk: true, ExplorationResultCard: ExplorationResultCardStub } } })
  const recommendation = wrapper.get(".project-assistant-exploration-recommendation")
  expect(recommendation.text()).toContain("推荐尺度：沙盘")
  expect(recommendation.text()).toContain("输入是一条世界规则")

  const override = recommendation.findAll("select").at(-1)
  await override.setValue("event")
  expect(recommendation.text()).toContain("已手动覆盖")
  await recommendation.findAll("button").find(button => button.text().includes("按此设定查看预览")).trigger("click")
  await flushPromises()

  expect(explorationPreview).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p1", scale: "event", focus: "面包师的日常" }))
  expect(explorationPreview.mock.calls[0][0].operation_id).toBeTruthy()
  expect(recommendation.text()).toContain("预计模型请求 1 次")
})

it("only resumes within the same budget when the server permits recovery", async () => {
  const state = reactive({ enabled: true, messages: [], sessions: [], input: "", run: { status: "failed", can_resume: false } })
  mocks.assistant = { state, load: vi.fn(), dispose: vi.fn(), resume: vi.fn() }
  const wrapper = mount(ProjectAssistant, { props: { projectId: "p1", open: true }, global: { stubs: { ProactiveCare: true } } })
  const resume = () => wrapper.findAll("button").find(button => button.text() === "恢复本次查证")
  expect(resume()).toBeUndefined()
  state.run.can_resume = true
  await wrapper.vm.$nextTick()
  await resume().trigger("click")
  expect(mocks.assistant.resume).toHaveBeenCalledExactlyOnceWith(false)
  state.run.can_resume = false
  await wrapper.vm.$nextTick()
  expect(resume()).toBeUndefined()
})

it("opens the exact editorial issue selected from a notice", async () => {
  const state = reactive({ enabled: true, messages: [], sessions: [], input: "", run: null, loading: false, busy: false })
  mocks.assistant = { state, load: vi.fn().mockResolvedValue(), dispose: vi.fn(), setInput: vi.fn() }
  const wrapper = mount(ProjectAssistant, {
    props: { projectId: "p1", open: false },
    global: {
      stubs: {
        ProactiveCare: true,
        EditorialDesk: {
          props: ["projectId", "active", "focusChapter", "focusIssueId"],
          template: '<div class="editorial-stub">{{ focusIssueId }}</div>',
        },
      },
    },
  })
  await wrapper.vm.$nextTick()
  await mocks.opener({ projectId: "p1", editorial: true, chapterIndex: 3, issueId: "issue-17" })
  await wrapper.vm.$nextTick()

  expect(wrapper.get(".editorial-stub").text()).toBe("issue-17")
  expect(wrapper.findAll(".project-assistant-tabs button").find((button) => button.text() === "编辑台").attributes("aria-pressed")).toBe("true")
})

it.each([false, true])("resolves delayed capabilities in an open panel and preserves author RP choice (%s)", async (chooseRp) => {
  const state = reactive({ enabled: false, messages: [], sessions: [], input: "恢复的讨论草稿", run: null })
  let completeLoad
  mocks.assistant = { state, load: vi.fn(() => new Promise(resolve => { completeLoad = resolve })), dispose: vi.fn() }
  const wrapper = mount(ProjectAssistant, {
    props: { projectId: "p1", open: true },
    global: { stubs: { ProactiveCare: true, EditorialDesk: true, GoalRunsPanel: true, InteractionAuthorPanel: true } },
  })
  const tab = (label) => wrapper.findAll(".project-assistant-tabs button").find(button => button.text() === label)
  if (chooseRp) await tab("RP旅程").trigger("click")

  state.enabled = true
  completeLoad()
  await flushPromises()

  expect(tab(chooseRp ? "RP旅程" : "讨论").attributes("aria-pressed")).toBe("true")
  if (!chooseRp) expect(wrapper.get("#assistant-input").element.value).toBe("恢复的讨论草稿")
})

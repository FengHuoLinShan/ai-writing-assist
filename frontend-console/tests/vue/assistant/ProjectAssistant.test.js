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
  getApi: () => mocks.api || {}, getAppState: () => ({}), getCurrentWritingFingerprint: vi.fn(), notifyProjectAssistantChanged: vi.fn(),
  getConfirm: () => () => true,
}))
vi.mock("../../../vue/shared/assistantNavigation.js", () => ({ locateAssistantSource: vi.fn(), openAssistantDestination: vi.fn() }))
vi.mock("../../../vue/shared/workflowManager.js", () => ({ createWorkflowManager: () => ({ resetMemoryScope: vi.fn(), stop: vi.fn() }) }))
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
  state.run = { status: "completed", result: { sources: [{ evidence_id: "ev-2", title: "探索推荐", domain_reference: { type: "story_exploration_recommendation", question: "重力变化会怎样？", scale: "sandbox", focus_hint: "面包师的日常", reason: "输入是一条世界规则" } }] } }
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
  expect(explorationPreview.mock.calls[0][0]).not.toHaveProperty("operation_id")
  expect(state.context.exploration_intent).toEqual({ question: "重力变化会怎样？", scale: "event", focus: "面包师的日常" })
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

it("shows the exact focused asset label in the context summary", async () => {
  const state = reactive({
    enabled: true,
    messages: [],
    sessions: [],
    input: "",
    run: null,
    context: { page: "world", focus_label: "档案条目：身份 · 修订 2" },
  })
  mocks.assistant = { state, load: vi.fn(), dispose: vi.fn() }
  const wrapper = mount(ProjectAssistant, {
    props: { projectId: "p1", open: true },
    global: { stubs: { ProactiveCare: true } },
  })
  await wrapper.vm.$nextTick()

  expect(wrapper.text()).toContain("档案条目：身份 · 修订 2")
})

it('keeps the submitted target distinct from the next turn and reports actual omissions', async () => {
  const state = reactive({ enabled: true, messages: [], sessions: [], input: '',
    context: { page: 'world', focus_label: '对象：新目标' },
    run: { status: 'completed', context: { page: 'writing', chapter_index: 2, source_hash: 'a'.repeat(64), draft_id: 'original', excluded_targets: ['hidden'], selection: '甲😀' }, result: { sources: [{ title: '已读依据' }], omissions: ['没有人物知识证明'] } },
  })
  mocks.assistant = { state, load: vi.fn(), dispose: vi.fn() }
  const wrapper = mount(ProjectAssistant, { props: { projectId: 'p1', open: true }, global: { stubs: { ProactiveCare: true } } })
  const summaries = wrapper.findAll('.assistant-context-summary')
  expect(summaries[0].text()).toContain('本轮固定目标：第 2 章')
  expect(summaries[0].text()).toContain('选区共 2 字')
  expect(summaries[0].text()).toContain('已排除 1 项')
  expect(summaries[0].text()).toContain('本轮返回 1 项依据')
  expect(summaries[0].text()).toContain('没有人物知识证明')
  expect(summaries[1].text()).toContain('本次参考：对象：新目标')
  expect(summaries[0].text()).not.toContain('新目标')
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

it("preserves an unsafe exploration edit when another run is opened externally", async () => {
  const state = baseState()
  state.run = { id: "run-current", status: "completed", result: { sources: [{ domain_reference: { type: "story_exploration_result", result_id: "result-current" } }] } }
  mocks.assistant = { state, load: vi.fn(), dispose: vi.fn(), openRun: vi.fn() }
  mount(ProjectAssistant, { props: { projectId: "p1", open: true }, global: { stubs: { ProactiveCare: true, EditorialDesk: true, ExplorationResultCard: { ...ExplorationResultCardStub, methods: { canLeave: () => false } } } } })
  await flushPromises()
  await expect(mocks.opener({ projectId: "p1", runId: "run-old" })).rejects.toThrow("未保存")
  expect(mocks.assistant.openRun).not.toHaveBeenCalled()
})

it('expands the current discussion without replacing its composer or selection', async () => {
  const media = vi.spyOn(globalThis, 'matchMedia').mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })
  const state = reactive({ enabled: true, messages: [], sessions: [], input: '保留这个尚未发送的要求', run: null })
  mocks.assistant = { state, load: vi.fn(), dispose: vi.fn() }
  const wrapper = mount(ProjectAssistant, { props: { projectId: 'p1', open: true }, global: { stubs: { ProactiveCare: true } } })
  const input = wrapper.get('#assistant-input').element
  input.setSelectionRange(2, 6)
  await wrapper.findAll('button').find(button => button.text() === '扩大工作区').trigger('click')
  expect(wrapper.classes()).toContain('project-assistant--expanded')
  expect(wrapper.get('#assistant-input').element).toBe(input)
  expect([input.selectionStart, input.selectionEnd]).toEqual([2, 6])
  expect(input.value).toBe(state.input)
  await wrapper.findAll('button').find(button => button.text() === '收起工作区').trigger('click')
  expect(wrapper.classes()).not.toContain('project-assistant--expanded')
  expect(wrapper.get('#assistant-input').element).toBe(input)
  media.mockRestore()
})

it('restores approval after switching from a blueprint and still clears it on scope changes', async () => {
  const { createProjectAssistant } = await vi.importActual('../../../vue/composables/useProjectAssistant.js')
  const controller = createProjectAssistant()
  const approval = { preserve: ['保留姓名'], max_judgments: 2, timeout_seconds: 30 }
  const context = { page: 'world', focus_ref: { kind: 'entity', entity_id: 'object' } }
  localStorage.setItem('novel_assistant_v1:local:p1', JSON.stringify({ drafts: { new: { text: '整理简介', context, approvalRequest: approval, oneShotTeam: true } } }))
  controller.state.projectId = 'p1'
  controller.state.blueprint = 'research'
  controller.state.enabled = true
  mocks.assistant = { ...controller, load: vi.fn() }
  const wrapper = mount(ProjectAssistant, { props: { projectId: 'p1', open: false }, global: { stubs: { ProactiveCare: true } } })
  await controller.selectSession(null, { saveCurrent: false })
  expect(controller.state.approvalRequest).toEqual(approval)
  expect(controller.state.context).toEqual(context)
  expect(controller.state.blueprint).toBeNull()
  controller.state.context = { ...context, scope: 'project' }
  expect(controller.state.approvalRequest).toBeNull()
  wrapper.unmount()
  localStorage.removeItem('novel_assistant_v1:local:p1')
})

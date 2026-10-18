import { afterEach, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { reactive } from "vue"
import ProjectAssistant from "../../../vue/components/ProjectAssistant.vue"

const mocks = vi.hoisted(() => ({ assistant: null, opener: null }))
vi.mock("../../../vue/composables/useProjectAssistant.js", () => ({ createProjectAssistant: () => mocks.assistant }))
vi.mock("../../../vue/bridge/index.js", () => ({
  getAssistantWorkContext: () => ({}), registerProjectAssistantOpener: handler => { mocks.opener = handler; return () => { mocks.opener = null } },
  getApi: () => ({}), getAppState: () => ({}), getCurrentWritingFingerprint: vi.fn(), notifyProjectAssistantChanged: vi.fn(),
  getConfirm: () => () => true,
}))
vi.mock("../../../vue/shared/assistantNavigation.js", () => ({ locateAssistantSource: vi.fn(), openAssistantDestination: vi.fn() }))
vi.mock("../../../vue/shared/workflowManager.js", () => ({ createWorkflowManager: () => ({ resetMemoryScope: vi.fn(), stop: vi.fn() }) }))
enableAutoUnmount(afterEach)

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

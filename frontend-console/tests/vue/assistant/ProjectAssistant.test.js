import { afterEach, expect, it, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import { reactive } from "vue"
import ProjectAssistant from "../../../vue/components/ProjectAssistant.vue"

const mocks = vi.hoisted(() => ({ assistant: null }))
vi.mock("../../../vue/composables/useProjectAssistant.js", () => ({ createProjectAssistant: () => mocks.assistant }))
vi.mock("../../../vue/bridge/index.js", () => ({
  getAssistantWorkContext: () => ({}), registerProjectAssistantOpener: () => () => {},
}))
vi.mock("../../../vue/shared/assistantNavigation.js", () => ({ locateAssistantSource: vi.fn(), openAssistantDestination: vi.fn() }))
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

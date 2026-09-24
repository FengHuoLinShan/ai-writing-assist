import { afterEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { reactive } from "vue"
import CognitionPanel from "../../../vue/components/CognitionPanel.vue"
import ProjectAssistant from "../../../vue/components/ProjectAssistant.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
const mocks = vi.hoisted(() => ({ assistant: null }))
vi.mock("../../../vue/composables/useProjectAssistant.js", () => ({ createProjectAssistant: () => mocks.assistant }))

afterEach(() => { resetBridgeOverrides(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
const record = { id: "understanding-a", revision_id: "revision-a", text: "她仍保留戒心。", author_status: "derived", freshness: "current", source_count: 1 }
const button = (wrapper, label) => wrapper.findAll("button").find(value => value.text() === label)
async function open(wrapper) { wrapper.get("details").element.open = true; await wrapper.get("details").trigger("toggle"); await flushPromises() }

it("修正请求失联时保留输入，并用原操作恢复", async () => {
  const correctUnderstanding = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ outcome: "updated" })
  const understanding = vi.fn().mockResolvedValue({ items: [record], head_commit_id: "head-a" })
  setBridgeOverrides({ api: { collaboration: { understanding, correctUnderstanding } } })
  const wrapper = mount(CognitionPanel, { props: { projectId: "project-a" } })
  await open(wrapper)
  await button(wrapper, "修正").trigger("click")
  await wrapper.get("textarea").setValue("她只同意交换线索。")
  await wrapper.get("form").trigger("submit"); await flushPromises()
  expect(wrapper.get("textarea").element.value).toBe("她只同意交换线索。")
  const operation = correctUnderstanding.mock.calls[0][2].operation_id
  await wrapper.get("form").trigger("submit"); await flushPromises()
  expect(correctUnderstanding.mock.calls[1][2].operation_id).toBe(operation)
  expect(wrapper.text()).toContain("修正已保存")
  wrapper.unmount()
})

it("冲突不覆盖新理解，作者对照新版后才能重新保存", async () => {
  const correctUnderstanding = vi.fn().mockRejectedValueOnce(Object.assign(new Error("已有新版本"), { status: 409 })).mockResolvedValue({ outcome: "updated" })
  let guard
  const understanding = vi.fn().mockResolvedValueOnce({ items: [record], head_commit_id: "head-a" }).mockResolvedValue({ items: [{ ...record, revision_id: "revision-b", text: "最新的作者理解" }], head_commit_id: "head-b" })
  setBridgeOverrides({ api: { collaboration: { understanding, correctUnderstanding } }, router: { registerLeaveGuard: callback => { guard = callback; return () => {} } } })
  vi.stubGlobal("confirm", vi.fn(() => false))
  const wrapper = mount(CognitionPanel, { props: { projectId: "project-a" } })
  await open(wrapper)
  await button(wrapper, "修正").trigger("click")
  await wrapper.get("textarea").setValue("保留我的修正输入。")
  expect(guard()).toBe(false)
  await wrapper.get("form").trigger("submit"); await flushPromises()
  await button(wrapper, "读取新版并保留输入").trigger("click"); await flushPromises()
  expect(wrapper.get("textarea").element.value).toBe("保留我的修正输入。")
  expect(wrapper.text()).toContain("最新的作者理解")
  await wrapper.get("form").trigger("submit"); await flushPromises()
  expect(correctUnderstanding.mock.calls[1][2]).toEqual(expect.objectContaining({ expected_commit_id: "head-b", expected_revision_id: "revision-b", text: "保留我的修正输入。" }))
  wrapper.unmount()
})

it("切换项目后不接纳旧请求结果", async () => {
  let resolve
  const understanding = vi.fn(() => new Promise(done => { resolve = done }))
  setBridgeOverrides({ api: { collaboration: { understanding } } })
  const wrapper = mount(CognitionPanel, { props: { projectId: "project-a" } })
  await open(wrapper)
  await wrapper.setProps({ projectId: "project-b" })
  resolve({ items: [record], head_commit_id: "head-a" }); await flushPromises()
  expect(wrapper.text()).not.toContain(record.text)
  wrapper.unmount()
})

it("助手页内切换标签也保护未保存的理解修正", async () => {
  mocks.assistant = { state: reactive({ enabled: true, messages: [], sessions: [], input: "", run: null }), load: vi.fn(), dispose: vi.fn() }
  setBridgeOverrides({ api: { collaboration: {
    capabilities: vi.fn().mockResolvedValue({ enabled: true, recipes: [] }),
    cases: vi.fn().mockResolvedValue({ items: [] }),
    understanding: vi.fn().mockResolvedValue({ items: [record], head_commit_id: "head-a" }),
  } } })
  const confirm = vi.fn(() => false)
  vi.stubGlobal("confirm", confirm)
  const wrapper = mount(ProjectAssistant, { props: { projectId: "project-a", open: true }, global: { stubs: { ProactiveCare: true, ForecastDock: true } } })
  await button(wrapper, "试改").trigger("click"); await flushPromises()
  const panel = wrapper.getComponent(CognitionPanel)
  await open(panel)
  await button(panel, "修正").trigger("click")
  await panel.get("textarea").setValue("这段修正不能丢失。")
  await button(wrapper, "讨论").trigger("click")
  expect(confirm).toHaveBeenCalled()
  expect(wrapper.getComponent(CognitionPanel).get("textarea").element.value).toBe("这段修正不能丢失。")
  confirm.mockReturnValue(true)
  await button(wrapper, "讨论").trigger("click")
  expect(wrapper.findComponent(CognitionPanel).exists()).toBe(false)
  wrapper.unmount()
})

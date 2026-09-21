import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import InteractionForecast from "../../../vue/views/interaction/InteractionForecast.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
const journey = id => ({ id, selected_leaf_node_id: "leaf-" + id, selection_epoch: 1, overview_epoch: 0, source: { source_context_epoch: 0 } })
const item = title => ({ candidate_id: "candidate", assessment_hash: "a".repeat(64), issue_key: title, title, statements: [], directions: [{ direction_id: "ask", title: "追问", condition: "仍在场时", proposal: "末班车何时离开？" }], evidence: [], unknowns: [] })
beforeEach(() => localStorage.clear())
afterEach(() => { resetBridgeOverrides(); vi.restoreAllMocks() })

it("晚到的旧旅程建议不覆盖新旅程，带入只发出预填事件", async () => {
  let resolveOld
  const old = new Promise(resolve => { resolveOld = resolve })
  const feed = vi.fn(async (id, body) => id === "old" ? old : { focus_seq: body.context.focus_seq, items: [item("新的发展")] })
  const prefill = vi.fn(async () => ({ text: "末班车何时离开？", sent: false }))
  setBridgeOverrides({ api: { interactionForecasts: { capabilities: vi.fn(async () => ({ enabled: true })), feed, prefill } } })
  const wrapper = mount(InteractionForecast, { props: { journey: journey("old") } })
  await flushPromises()
  wrapper.get("details").element.open = true
  await wrapper.get("details").trigger("toggle")
  await wrapper.setProps({ journey: journey("new") })
  await flushPromises()
  resolveOld({ focus_seq: 1, items: [item("旧的发展")] })
  await flushPromises()
  expect(wrapper.text()).toContain("新的发展")
  expect(wrapper.text()).not.toContain("旧的发展")
  await wrapper.findAll("button").find(button => button.text() === "带入输入框").trigger("click")
  await flushPromises()
  expect(wrapper.emitted("prefill")[0][0]).toEqual({ text: "末班车何时离开？", sent: false })
  wrapper.unmount()
})

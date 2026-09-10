import { afterEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import TargetedCompletionPanel from "../../../vue/components/TargetedCompletionPanel.vue"

const receipt = vi.hoisted(() => ({ status: "done", result: { targeted_completion: {
  status: "done", chapter_range: { start: 2, end: 6 },
  ambiguities: [{ key: "same-name", name: "林舟", candidate_ids: ["e1", "e2"] }],
} } }))
vi.mock("../../../vue/composables/useWorkflowPolling.js", () => ({ useWorkflowPolling: () => ({
  stopAll: vi.fn(), start: ({ onUpdate }) => onUpdate({}, receipt),
}) }))
afterEach(resetBridgeOverrides)

it("同名对象须明确选择后另开原章节范围的查漏，不修改旧任务", async () => {
  const navigate = vi.fn(), targetedCompletion = vi.fn(async () => ({ task_id: "new-task" }))
  const original = JSON.stringify(receipt)
  localStorage.clear()
  setBridgeOverrides({ state: { currentProjectId: "p1" }, router: { navigate }, api: {
    imports: { targetedCompletion },
    world: { getEntity: vi.fn(async id => ({ name: "林舟", summary: id === "e1" ? "钟楼守卫" : "远行商人" })) },
  } })
  const wrapper = mount(TargetedCompletionPanel, { props: { projectId: "p1", sourceTaskId: "old-task" } })
  await flushPromises()
  const submit = wrapper.findAll("button").find(button => button.text() === "确认身份并重新查漏")
  expect(submit.attributes("disabled")).toBeDefined()
  await wrapper.get("select").trigger("focus")
  await flushPromises()
  expect(wrapper.text()).toContain("钟楼守卫")
  await wrapper.get("select").setValue("e1")
  await submit.trigger("click")
  await flushPromises()
  expect(targetedCompletion).toHaveBeenCalledWith({ novel_id: "p1", targets: [{ entity_id: "e1" }], start_chapter: 2, end_chapter: 6, authorization_confirmed: true })
  expect(navigate.mock.calls[0][3].get("import_task_id")).toBe("new-task")
  expect(JSON.stringify(receipt)).toBe(original)
  wrapper.unmount()
})

import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import ImportReviewResolutionPanel from "../../../vue/components/ImportReviewResolutionPanel.vue"

const polling = vi.hoisted(() => ({ start: vi.fn(), stopAll: vi.fn() }))
vi.mock("../../../vue/composables/useWorkflowPolling.js", () => ({ useWorkflowPolling: () => polling }))
beforeEach(() => { localStorage.clear(); polling.start.mockReset(); polling.stopAll.mockReset() })
afterEach(resetBridgeOverrides)

it("一次授权提交原范围，恢复不重复启动", async () => {
  const resolveReview = vi.fn(async () => ({ task_id: "task-1" }))
  const imports = { resolveReview, reviewSummary: vi.fn(async () => ({ unclassified: 5 })) }
  setBridgeOverrides({ api: { imports } })
  const wrapper = mount(ImportReviewResolutionPanel, { props: { projectId: "p1" } })
  await flushPromises()
  await wrapper.findAll("button").find(button => button.text() === "整理这些资料").trigger("click")
  await wrapper.get("form").trigger("submit")
  await flushPromises()
  expect(resolveReview).toHaveBeenCalledTimes(1)
  expect(resolveReview).toHaveBeenCalledWith({ novel_id: "p1", start_chapter: 1, end_chapter: 0, repair_scenes: true, authorization_confirmed: true })
  wrapper.unmount()
  const resumed = mount(ImportReviewResolutionPanel, { props: { projectId: "p1" } })
  await flushPromises()
  expect(resolveReview).toHaveBeenCalledTimes(1)
  expect(polling.start.mock.calls.at(-1)[0].taskId).toBe("task-1")
  resumed.unmount()
})

it("按问题成组采用，排除例外，不要求逐行点已核对", async () => {
  const groups = [1, 2].map(index => ({ key: `candidate-${index}`, group_key: "same-question", kind: "alias", outcome: "decision", question: "这些称呼是否属于同一人？", label: `称呼${index}`, explanation: "归属需要决定", fingerprint: `fingerprint-${index}` }))
  const receipt = { status: "done", result: { review_resolution: { groups, counts: { decision: 2 }, question_count: 1, fact_count: 2, processed_count: 2 } } }
  const decideReview = vi.fn(async () => ({ status: "accepted" }))
  polling.start.mockImplementation(({ onUpdate }) => onUpdate({}, receipt))
  setBridgeOverrides({ api: { imports: { decideReview, reviewSummary: vi.fn(async () => ({ latest: { task_id: "task-1", status: "done", result: receipt.result.review_resolution } })) } } })
  const wrapper = mount(ImportReviewResolutionPanel, { props: { projectId: "p1" } })
  await flushPromises()
  expect(wrapper.findAll("article")).toHaveLength(1)
  expect(wrapper.text()).not.toContain("已核对")
  await wrapper.findAll('input[type="checkbox"]')[1].setValue(false)
  await wrapper.findAll("button").find(button => button.text() === "确认采用本组选中资料").trigger("click")
  await flushPromises()
  expect(decideReview).toHaveBeenCalledWith("task-1", "p1", { candidate_keys: ["candidate-1"], expected_fingerprints: { "candidate-1": "fingerprint-1" }, confirmed: true })
  wrapper.unmount()
})

it("切换作品后晚到概况不能覆盖新项目", async () => {
  let finish
  const reviewSummary = vi.fn(id => id === "p1" ? new Promise(resolve => { finish = resolve }) : Promise.resolve({ unclassified: 7 }))
  setBridgeOverrides({ api: { imports: { reviewSummary } } })
  const wrapper = mount(ImportReviewResolutionPanel, { props: { projectId: "p1" } })
  await wrapper.setProps({ projectId: "p2" })
  await flushPromises()
  finish({ unclassified: 999 })
  await flushPromises()
  expect(wrapper.text()).toContain("7 项")
  expect(wrapper.text()).not.toContain("999")
  wrapper.unmount()
})

it("恢复已完成结果不会再次通知父页面刷新", async () => {
  polling.start.mockImplementation(({ onUpdate, onDone }) => { onUpdate({}, { status: "done", result: { review_resolution: { counts: {} } } }); onDone() })
  setBridgeOverrides({ api: { imports: { reviewSummary: vi.fn(async () => ({ latest: { task_id: "finished", status: "done", result: { counts: {} } } })) } } })
  const wrapper = mount(ImportReviewResolutionPanel, { props: { projectId: "p1" } })
  await flushPromises()
  expect(wrapper.emitted("updated")).toBeUndefined()
  expect(polling.start).toHaveBeenCalledTimes(1)
  wrapper.unmount()
})

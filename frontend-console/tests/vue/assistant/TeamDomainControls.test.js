import { mount, flushPromises } from "@vue/test-utils"
import { afterEach, expect, it, vi } from "vitest"
import { setBridgeOverrides, registerProjectAssistantOpener } from "../../../vue/bridge/index.js"
import WorldStressReport from "../../../vue/views/world/components/WorldStressReport.vue"
import SceneRehearsalPanel from "../../../vue/views/scene/SceneRehearsalPanel.vue"

afterEach(() => setBridgeOverrides({ api: undefined, state: undefined }))
it("keeps an intentional rule flaw when retesting only its selected scenario", async () => {
  const report = { assessment_hash: "hash", freshness: "stale", assessment: { summary: "待重测", omissions: ["没有检查后果"], scenarios: [{ key: "outside", title: "外侧推门", verdict: "invalid_counterexample", assumptions: [], actions: ["推门"], costs: [], invariant: "内侧机关", outcome: "门未开" }] }, source_scope: { page: "world", target: { target_type: "world_entity", target_id: "rule" } }, dispositions: { outside: { disposition: "intentional" } } }
  setBridgeOverrides({ state: { currentProjectId: "p1" }, api: { world: { stressReport: vi.fn(async () => report) } } })
  const opener = vi.fn()
  const unregister = registerProjectAssistantOpener(opener)
  const wrapper = mount(WorldStressReport, { props: { projectId: "p1", reportId: "report" } })
  await flushPromises()
  expect(wrapper.text()).toContain("原规则已变化")
  expect(wrapper.text()).toContain("没有检查后果")
  await wrapper.findAll("button").find(button => button.text() === "只重测这一情境").trigger("click")
  expect(opener).toHaveBeenCalledWith(expect.objectContaining({ previousReportId: "report", scenarioKeys: ["outside"], preservedConstraints: ["保留情境：外侧推门"], context: report.source_scope }))
  unregister(); wrapper.unmount()
})
it("passes exact immutable parent round into a new rehearsal fork", async () => {
  const rehearsal = { id: "run", rounds: [{ number: 1, hash: "frozen-round", events: [{ actor_id: "actor", action: "等候", outcome: "succeeded" }] }] }
  setBridgeOverrides({ api: { assistant: { capabilities: vi.fn(async () => ({ rehearsal: { available: true } })) }, story: { rehearsal: vi.fn(async () => rehearsal) } } })
  const wrapper = mount(SceneRehearsalPanel, { props: { projectId: "p1", rehearsalId: "run", characters: [{ id: "actor", name: "阿澄" }] } })
  await flushPromises()
  await wrapper.findAll("button").find(button => button.text().includes("另试一种发展")).trigger("click")
  expect(wrapper.emitted("run")[0][0]).toMatchObject({ rehearsal: true, characterIds: ["actor"], parentId: "run", forkRound: 1, parentHash: "frozen-round" })
  await wrapper.setProps({ running: true })
  expect(wrapper.findAll("button").every(button => button.attributes("disabled") !== undefined)).toBe(true)
  wrapper.unmount()
})

it("ignores late decisions after switching reports and prevents duplicate retests", async () => {
  const report = id => ({ assessment_hash: id, assessment: { summary: id, omissions: [], scenarios: [{ key: "door", title: "推门", assumptions: [], actions: [], costs: [] }] } })
  let finishDecision, finishRetest
  const decide = vi.fn(() => new Promise(resolve => { finishDecision = resolve }))
  setBridgeOverrides({ state: { currentProjectId: "p1" }, api: { world: { stressReport: vi.fn(async (_project, id) => report(id)), decideStressScenario: decide } } })
  const opener = vi.fn(() => new Promise(resolve => { finishRetest = resolve }))
  const unregister = registerProjectAssistantOpener(opener)
  const wrapper = mount(WorldStressReport, { props: { projectId: "p1", reportId: "first" } })
  await flushPromises()
  await wrapper.findAll("button").find(button => button.text() === "有意保留").trigger("click")
  await wrapper.setProps({ reportId: "second" })
  await flushPromises()
  const retest = () => wrapper.findAll("button").find(button => button.text() === "只重测这一情境")
  expect(retest().attributes("disabled")).toBeUndefined()
  await retest().trigger("click")
  finishDecision(report("first"))
  await flushPromises()
  expect(wrapper.text()).toContain("second")
  expect(wrapper.text()).not.toContain("first")
  expect(retest().attributes("disabled")).toBeDefined()
  await retest().trigger("click")
  expect(opener).toHaveBeenCalledTimes(1)
  finishRetest()
  await flushPromises()
  expect(retest().attributes("disabled")).toBeUndefined()
  unregister(); wrapper.unmount()
})

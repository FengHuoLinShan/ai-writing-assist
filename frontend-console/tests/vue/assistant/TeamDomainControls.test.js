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
  const scenarioSeed = { participants: [{ kind: "object", id: "actor" }], locations: [], positions: [], resources: [], routes: [], assumptions: [] }
  const rehearsal = { id: "run", protocol: "simulation_v3", scenario_seed: scenarioSeed, rounds: [{ number: 1, hash: "frozen-round", events: [{ actor_id: "actor", action: "等候", outcome: "succeeded" }] }] }
  setBridgeOverrides({ api: { assistant: { capabilities: vi.fn(async () => ({ rehearsal: { available: true } })) }, story: { rehearsal: vi.fn(async () => rehearsal) } } })
  const wrapper = mount(SceneRehearsalPanel, { props: { projectId: "p1", rehearsalId: "run", characters: [{ id: "actor", name: "阿澄" }] } })
  await flushPromises()
  await wrapper.findAll("button").find(button => button.text().includes("另试一种发展")).trigger("click")
  expect(wrapper.emitted("run")[0][0]).toMatchObject({ rehearsal: true, protocol: "simulation_v3", seed: scenarioSeed, rounds: 1, characterIds: ["actor"], parentId: "run", forkRound: 1, parentHash: "frozen-round" })
  await wrapper.setProps({ running: true })
  expect(wrapper.findAll("button").every(button => button.attributes("disabled") !== undefined)).toBe(true)
  wrapper.unmount()
})

it("submits one v3 round with selected object IDs and typed temporary candidates", async () => {
  setBridgeOverrides({ api: { assistant: { capabilities: vi.fn(async () => ({ rehearsal: { available: true } })) } } })
  const actors = ["a", "b", "c", "d"].map(id => ({ id, name: `人物${id}` }))
  actors.push({ id: "character-placeholder", name: "未关联人物" })
  const wrapper = mount(SceneRehearsalPanel, { props: { projectId: "p1", characters: actors } })
  await flushPromises()

  expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(5)
  expect(wrapper.findAll('input[type="checkbox"]').slice(0, 4).every(input => input.attributes("disabled") === undefined)).toBe(true)
  expect(wrapper.findAll('input[type="checkbox"]')[4].attributes("disabled")).toBeDefined()
  await wrapper.findAll("textarea")[0].setValue("密信")
  await wrapper.find("input:not([type])").setValue("雾渡港")
  await wrapper.findAll("textarea")[1].setValue("旧桥")
  await wrapper.findAll("button").find(button => button.text() === "排演一回合").trigger("click")

  const payload = wrapper.emitted("run")[0][0]
  expect(payload).toMatchObject({ rehearsal: true, protocol: "simulation_v3", rounds: 1, characterIds: ["a", "b", "c", "d"] })
  expect(payload.seed.participants).toEqual(actors.filter(actor => !actor.id.startsWith("character-")).map(actor => ({ kind: "object", id: actor.id })))
  expect(payload.seed.resources).toEqual([{ resource: { kind: "candidate", id: "item-1", label: "密信" }, holder: null }])
  expect(payload.seed.locations[0]).toEqual({ kind: "candidate", id: "location-origin", label: "雾渡港" })
  expect(payload.seed.routes[0]).toEqual({
    origin: payload.seed.locations[0],
    destination: { kind: "candidate", id: "location-destination-1", label: "旧桥" },
  })
  wrapper.unmount()
})

it("keeps historical v1 and v2 runs readable without offering a fork", async () => {
  const rehearsal = { id: "old-run", protocol: "observation_v2", rounds: [{ number: 1, hash: "old-hash", events: [] }] }
  setBridgeOverrides({
    api: {
      assistant: { capabilities: vi.fn(async () => ({ rehearsal: { available: true } })) },
      story: { rehearsal: vi.fn(async () => rehearsal) },
    },
  })
  const wrapper = mount(SceneRehearsalPanel, { props: { projectId: "p1", rehearsalId: "old-run", characters: [{ id: "actor", name: "阿澄" }] } })
  await flushPromises()

  const fork = wrapper.findAll("button").find(button => button.text().includes("另试一种发展"))
  expect(wrapper.text()).toContain("这份旧记录仅供查看")
  expect(fork.attributes("disabled")).toBeDefined()
  expect(wrapper.emitted("run")).toBeUndefined()
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

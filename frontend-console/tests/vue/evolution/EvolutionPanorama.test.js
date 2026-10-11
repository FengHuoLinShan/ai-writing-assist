import { mount, flushPromises } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import EvolutionPanorama from "../../../vue/components/EvolutionPanorama.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
const claim = { label: "紧张时摸戒指", category: "conditional_behavior", statement: "甲在这次紧张时摸了戒指。", modality: "hypothesis", conditions: ["紧张"], targets: [], unresolved_subjects: ["甲"], competing_explanations: [], evidence: [{ quote: "甲紧张地摸了摸戒指。", position: { chapter_index: 1 }, role: "support", occurrence_kind: "event" }] }
const row = { entry_id: "entry", revision: 1, claim, counts: { occurrences: 1, observations: 1, sources: 1, unknown_occurrences: 0 }, source_status: "current", method_status: "current", author_decision: {} }
const detail = { ...row, head_revision: 1, current_author_decision: {}, history: [{ revision: 1, scene_index: 0, kind: "new" }] }
const panorama = { state: { scene_index: 0, dimensions: [], warnings: [] }, coverage: { status: "checked", note: "本次范围已检查。", found: 1, pending: [] }, plans: { items: [], note: "当前作者计划；不是已发生历史。" }, ledger: { items: [row], total: 1 } }
let api, wrappers, leaveGuard
beforeEach(() => {
  localStorage.clear(); wrappers = []
  api = { panorama: vi.fn().mockResolvedValue(panorama), ledger: vi.fn().mockResolvedValue({ items: [row], total: 1 }), ledgerEntry: vi.fn().mockResolvedValue(detail), ledgerEvidence: vi.fn().mockResolvedValue({ context: "甲紧张地摸了摸戒指。", historical: true }), ledgerDecision: vi.fn().mockResolvedValue({ saved: true }) }
  setBridgeOverrides({ api: { evolution: api, outline: { listScenesOrdered: vi.fn().mockResolvedValue([{ id: "scene", title: "灯塔" }, { id: "scene-b", title: "下一场" }]) } }, router: { registerLeaveGuard: guard => { leaveGuard = guard; return () => {} } } })
})
afterEach(() => { wrappers.forEach(wrapper => wrapper.unmount()); resetBridgeOverrides(); vi.restoreAllMocks() })
function make(project = `p-${crypto.randomUUID()}`) {
  const wrapper = mount(EvolutionPanorama, { props: { projectId: project, sceneId: "scene" }, global: { stubs: { SceneCheckpointHistory: true, SceneFieldProvenance: true } } }); wrappers.push(wrapper); return wrapper
}
async function click(wrapper, label) { const button = wrapper.findAll("button").find(item => item.text().includes(label)); expect(button, label).toBeTruthy(); await button.trigger("click"); await flushPromises() }
async function open(wrapper) { await click(wrapper, "查看本场全景"); await click(wrapper, "紧张时摸戒指") }
describe("author Evolution panorama", () => {
  it("separates coverage, filters, historical quotes and author decisions", async () => {
    const wrapper = make(); await open(wrapper)
    expect(wrapper.text()).toContain("已检查本次召回范围")
    expect(wrapper.text()).toContain("待核实理解")
    expect(wrapper.text()).toContain("1 次已定位发生")
    await click(wrapper, "回看这一版原文")
    expect(api.ledgerEvidence).toHaveBeenCalledWith(wrapper.props("projectId"), "entry", 0, 1)
    expect(wrapper.text()).toContain("这是历史版本，当前稿可能已修改")
    await wrapper.find('input[type="search"]').setValue("不存在的筛选")
    api.ledger.mockResolvedValueOnce({ items: [], total: 0 })
    await wrapper.findAll("form")[0].trigger("submit"); await flushPromises()
    expect(wrapper.text()).toContain("筛选后 0 项")
    expect(wrapper.text()).toContain("已检查本次召回范围")
  })
  it("shows same-condition exceptions separately from positive events and counterevidence", async () => {
    const negative = { ...row, counts: { ...row.counts, exception_occurrences: 2, counter_occurrences: 3 } }
    api.ledger.mockResolvedValueOnce({ items: [negative], total: 1 })
    api.ledgerEntry.mockResolvedValueOnce({ ...detail, ...negative, claim: { ...claim, evidence: [{ ...claim.evidence[0], role: "exception_case", purpose: "occurrence" }] } })
    const wrapper = make(); await open(wrapper)
    const table = wrapper.find('[aria-label="细节台账"] table')
    expect(table.text()).toContain("1 次已定位发生")
    expect(table.text()).toContain("2 次同条件例外")
    expect(table.text()).toContain("3 次明确反证")
    expect(wrapper.text()).toContain("同条件例外")
  })
  it("retains author input after failure and remount, retries the same operation", async () => {
    const project = `retry-${crypto.randomUUID()}`, wrapper = make(project); await open(wrapper)
    api.ledgerDecision.mockRejectedValueOnce(new Error("网络中断"))
    await wrapper.find('textarea:not([readonly])').setValue("我的窄范围判断")
    await wrapper.findAll("form")[1].trigger("submit"); await flushPromises()
    expect(wrapper.text()).toContain("网络中断")
    const operation = api.ledgerDecision.mock.calls[0][2]
    wrapper.unmount()
    const again = make(project); await open(again)
    expect(again.find('textarea:not([readonly])').element.value).toBe("我的窄范围判断")
    await again.findAll("form")[1].trigger("submit"); await flushPromises()
    expect(api.ledgerDecision.mock.calls[1][2]).toEqual(operation)
    expect(again.text()).toContain("判断已保存到作品")
  })
  it("keeps input on conflict and only rebinds after reading the latest revision", async () => {
    const wrapper = make(); await open(wrapper)
    api.ledgerDecision.mockRejectedValueOnce(Object.assign(new Error("记录已有新修订"), { status: 409 }))
    await wrapper.find('textarea:not([readonly])').setValue("我的修正不能被覆盖")
    await wrapper.findAll("form")[1].trigger("submit"); await flushPromises()
    api.ledgerEntry.mockImplementationOnce((_project, _id, revision) => Promise.resolve({ ...detail, revision: revision ?? 2, head_revision: 2 }))
    await click(wrapper, "读取新版并保留输入")
    expect(api.ledgerEntry.mock.calls.at(-1)[2]).toBeNull()
    expect(wrapper.find('textarea:not([readonly])').element.value).toBe("我的修正不能被覆盖")
    await wrapper.findAll("form")[1].trigger("submit"); await flushPromises()
    expect(api.ledgerDecision.mock.calls[1][2].expected_revision).toBe(2)
  })
  it("ignores old project responses and preserves inputs when local backup fails", async () => {
    let resolve
    api.panorama.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const wrapper = make()
    await wrapper.find('button').trigger('click'); await wrapper.setProps({ projectId: 'new-project' })
    resolve(panorama); await flushPromises()
    expect(wrapper.text()).not.toContain('紧张时摸戒指')
    await open(wrapper)
    vi.spyOn(localStorage, 'setItem').mockImplementation(() => { throw new Error('quota') })
    await wrapper.find('textarea:not([readonly])').setValue('不能丢失的输入')
    expect(wrapper.text()).toContain('本机备份失败')
    expect(wrapper.find('textarea:not([readonly])').element.value).toBe('不能丢失的输入')
    expect(wrapper.find('textarea[readonly]').element.value).toContain('不能丢失的输入')
    await click(wrapper, '刷新全景')
    expect(wrapper.text()).toContain('有输入尚未可靠备份')
    expect(wrapper.find('textarea[readonly]').element.value).toContain('不能丢失的输入')
    expect(leaveGuard()).toBe(false)
    vi.restoreAllMocks()
    await click(wrapper, '恢复这条未保存判断')
    await wrapper.findAll('form')[1].trigger('submit'); await flushPromises()
  })
  it("keeps existing theme scope and does not apply narrow corrections to later discoveries", async () => {
    const author = { decision: "corrected", corrected_statement: "只修正第一次", scope: "instance", basis_revision: 1, confirmed_scope_expansion: false }
    api.ledger.mockResolvedValueOnce({ items: [{ ...row, revision: 3, author_decision: author }], total: 1 })
    api.ledgerEntry.mockResolvedValueOnce({ ...detail, revision: 3, head_revision: 3, author_decision: author, current_author_decision: { ...author, scope: "theme", confirmed_scope_expansion: true } })
    const wrapper = make(); await open(wrapper)
    const table = wrapper.find('[aria-label="细节台账"] table')
    expect(table.text()).toContain(row.claim.statement)
    expect(table.text()).not.toContain("只修正第一次")
    expect(wrapper.text()).toContain("此前具体记录的作者修正")
    await wrapper.get('textarea:not([readonly])').setValue("只编辑备注")
    await wrapper.findAll('form')[1].trigger('submit'); await flushPromises()
    expect(api.ledgerDecision.mock.calls[0][2]).toMatchObject({ scope: "theme", confirmed_scope_expansion: true })
  })

  it("discloses uncertain review and keeps the earlier supported understanding visible", async () => {
    const reviewed = { ...row, independent_review: { verdict: "uncertain", reason: "原文没有支持这里的期限。" }, previous_supported: { revision: 1, claim: { statement: "此前只确认一次行为。" } } }
    api.ledger.mockResolvedValueOnce({ items: [reviewed], total: 1 })
    api.ledgerEntry.mockResolvedValueOnce({ ...detail, ...reviewed })
    const wrapper = make(); await open(wrapper)
    expect(wrapper.text()).toContain("不确定候选，独立核对未充分支持")
    expect(wrapper.text()).toContain("原文没有支持这里的期限。")
    expect(wrapper.text()).toContain("此前只确认一次行为。")
  })

  it("shows a supported question as a proposal beside the original understanding", async () => {
    const proposal = { ...row, proposal_target: { entry_id: "original", revision: 1 }, independent_review: { verdict: "supported", reason: "问题有依据，答案尚未确定。" }, previous_supported: { revision: 1, claim: { statement: "原承诺仍有明确原话。" } } }
    api.ledger.mockResolvedValueOnce({ items: [proposal], total: 1 })
    api.ledgerEntry.mockResolvedValueOnce({ ...detail, ...proposal })
    const wrapper = make(); await open(wrapper)
    expect(wrapper.text()).toContain("待核提案，问题依据已核对")
    expect(wrapper.text()).toContain("原承诺仍有明确原话。")
    expect(wrapper.text()).not.toContain("独立核对支持")
  })

  it("uses the saved server revision for the next edit without resurrecting an old draft", async () => {
    let version = 1, note = ""
    api.ledgerEntry.mockImplementation(() => Promise.resolve({ ...detail, revision: version, head_revision: version, current_author_decision: { decision: "keep", note, scope: "instance" } }))
    api.ledgerDecision.mockImplementation((_project, _entry, operation) => { expect(operation.expected_revision).toBe(version); version++; note = operation.note; return Promise.resolve({ saved: true }) })
    const wrapper = make(); await open(wrapper)
    await wrapper.get('textarea:not([readonly])').setValue("第一次保存")
    await wrapper.findAll('form')[1].trigger('submit'); await flushPromises()
    await wrapper.get('textarea:not([readonly])').setValue("第二次保存")
    await wrapper.findAll('form')[1].trigger('submit'); await flushPromises()
    expect(api.ledgerDecision).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain("判断已保存到作品")
  })

  it("clears the previous cutoff on failure while keeping author input recoverable", async () => {
    const wrapper = make(); await open(wrapper)
    vi.spyOn(localStorage, "setItem").mockImplementation(() => { throw new Error("quota") })
    await wrapper.get('textarea:not([readonly])').setValue("切场失败也不能丢失")
    api.panorama.mockRejectedValueOnce(new Error("下一场读取失败"))
    await wrapper.get('[aria-label="查看到哪一场"]').setValue("scene-b"); await flushPromises()
    expect(wrapper.get('[aria-label="查看到哪一场"]').element.value).toBe("scene-b")
    expect(wrapper.text()).toContain("下一场读取失败")
    expect(wrapper.find('[aria-label="截止场景的历史状态"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="细节台账"]').exists()).toBe(false)
    expect(wrapper.find('scene-checkpoint-history-stub').exists()).toBe(false)
    expect(wrapper.find('[aria-label="条目详情"]').exists()).toBe(false)
    expect(wrapper.find('textarea[readonly]').element.value).toContain("切场失败也不能丢失")
    await click(wrapper, "恢复这条未保存判断")
    expect(wrapper.get('textarea:not([readonly])').element.value).toBe("切场失败也不能丢失")
    expect(leaveGuard()).toBe(false)
    vi.restoreAllMocks()
    await wrapper.findAll('form')[0].trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain("判断已保存到作品")
  })

  it("shows a recorded zero in both historical state and before/after changes", async () => {
    api.panorama.mockResolvedValueOnce({ ...panorama,
      state: { ...panorama.state, dimensions: [{ label: "对象", status: "ok", facts: [{ subject_label: "仓库", field: "resource", value: 0, layer: "physical" }] }] },
      changes: { note: "已记录的资源变化", items: [{ subject_label: "仓库", dimension_label: "对象", field: "resource", layer: "physical", before_known: true, after_known: true, before: 5, after: 0 }] },
    })
    const wrapper = make(); await click(wrapper, "查看本场全景")
    const tables = wrapper.findAll('[aria-label="截止场景的历史状态"] table')
    expect(tables[0].findAll('tbody td').map(cell => cell.text()).slice(1)).toEqual(["5", "0"])
    expect(tables[1].findAll('tbody td')[1].text()).toBe("0")
  })

})

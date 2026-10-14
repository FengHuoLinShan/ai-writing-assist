import { afterEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import ReadingFlow from "../../../vue/components/ReadingFlow.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

afterEach(() => { resetBridgeOverrides(); vi.restoreAllMocks(); vi.useRealTimers() })
const button = (wrapper, label) => wrapper.findAll("button").find(item => item.text() === label)
async function open(wrapper) { wrapper.get("details").element.open = true; await wrapper.get("details").trigger("toggle"); await flushPromises() }

it("整理入口状态读取失败可见且可重试，换项目重新核对归属", async () => {
  const status = vi.fn().mockRejectedValueOnce(new Error("暂时无法读取"))
    .mockResolvedValue({ engine: { engine: "legacy", epoch: 1 }, run: null })
  setBridgeOverrides({ api: { evolution: { status } } })
  const wrapper = mount(ReadingFlow, { props: { projectId: "a", entry: true } })
  await flushPromises()
  expect(wrapper.get("details").element.open).toBe(true)
  expect(wrapper.get('[role="alert"]').text()).toBe("暂时无法读取")
  expect(wrapper.emitted("state")[0]).toEqual([null])
  await button(wrapper, "读取理解状态").trigger("click"); await flushPromises()
  wrapper.get("details").element.open = false
  await wrapper.get("details").trigger("toggle")
  await wrapper.setProps({ projectId: "b" }); await flushPromises()
  expect(status).toHaveBeenLastCalledWith("b")
  wrapper.unmount()
})

it("预览不启动任务，启动失联后按原授权重试，刷新只读进度", async () => {
  const status = vi.fn().mockResolvedValue({ engine: { engine: "evolution", epoch: 2 }, run: null })
  const preview = vi.fn().mockResolvedValue({ fingerprint: "f".repeat(64), scene_count: 2, request_limit: 20 })
  const done = { engine: { engine: "evolution", epoch: 2 }, run: { run_key: "run-a", status: "completed", completed_scenes: 2, total_scenes: 2 } }
  const start = vi.fn().mockRejectedValueOnce(new Error("暂时失联")).mockResolvedValue(done)
  setBridgeOverrides({ api: { evolution: { status, preview, start } } })
  const wrapper = mount(ReadingFlow, { props: { projectId: "a" } })
  expect(status).not.toHaveBeenCalled()
  await open(wrapper)
  await wrapper.findAll("input")[0].setValue(2)
  await wrapper.get("form").trigger("submit"); await flushPromises()
  expect(start).not.toHaveBeenCalled()
  await button(wrapper, "确认并开始理解").trigger("click"); await flushPromises()
  const frozen = JSON.parse(JSON.stringify(start.mock.calls[0][1]))
  expect(wrapper.findAll("input")[0].element.disabled).toBe(true)
  await button(wrapper, "确认启动结果").trigger("click"); await flushPromises()
  expect(start.mock.calls[1]).toEqual(["a", frozen])
  expect(wrapper.text()).toContain("所选范围理解已更新")
  status.mockResolvedValue(done)
  await button(wrapper, "刷新进度").trigger("click"); await flushPromises()
  expect(start).toHaveBeenCalledTimes(2)
  expect(preview).toHaveBeenCalledTimes(1)
  wrapper.unmount()
})

it("延迟确认不能切换另一个项目，卸载后停止轮询", async () => {
  vi.useFakeTimers()
  let resolve
  const confirmation = new Promise(done => { resolve = done })
  const status = vi.fn().mockResolvedValue({ engine: { engine: "legacy", epoch: 1 }, run: null })
  const switchEngine = vi.fn()
  setBridgeOverrides({ api: { evolution: { status, switchEngine } }, confirm: () => confirmation })
  const wrapper = mount(ReadingFlow, { props: { projectId: "a" } })
  await open(wrapper)
  await button(wrapper, "启用逐场景理解…").trigger("click")
  await wrapper.setProps({ projectId: "b" }); await flushPromises()
  resolve(true); await flushPromises()
  expect(switchEngine).not.toHaveBeenCalled()
  status.mockResolvedValue({ engine: { engine: "evolution", epoch: 2 }, run: { status: "running", completed_scenes: 1, total_scenes: 2 } })
  await button(wrapper, "刷新进度").trigger("click"); await flushPromises()
  await vi.advanceTimersByTimeAsync(5000)
  const count = status.mock.calls.length
  wrapper.unmount()
  await vi.advanceTimersByTimeAsync(15000)
  expect(status).toHaveBeenCalledTimes(count)
})

it("明确来源冲突后释放旧确认，保留章节输入并允许重新预览", async () => {
  const status = vi.fn().mockResolvedValue({ engine: { engine: "evolution", epoch: 2 }, run: null })
  const preview = vi.fn().mockResolvedValue({ fingerprint: "f".repeat(64), scene_count: 2, request_limit: 20 })
  const start = vi.fn().mockRejectedValue(Object.assign(new Error("正文已变化，请重新查看范围"), { status: 409 }))
  setBridgeOverrides({ api: { evolution: { status, preview, start } } })
  const wrapper = mount(ReadingFlow, { props: { projectId: "a" } })
  await open(wrapper)
  await wrapper.findAll("input")[0].setValue(2)
  await wrapper.get("form").trigger("submit"); await flushPromises()
  await button(wrapper, "确认并开始理解").trigger("click"); await flushPromises()
  expect(wrapper.findAll("input")[0].element.disabled).toBe(false)
  expect(wrapper.findAll("input")[0].element.value).toBe("2")
  await wrapper.get("form").trigger("submit"); await flushPromises()
  expect(preview).toHaveBeenCalledTimes(2)
  expect(preview.mock.calls[1][1].operation_id).not.toBe(preview.mock.calls[0][1].operation_id)
  wrapper.unmount()
})

it("引用失败后要求新的场景范围授权，预览说明继承与后续重算", async () => {
  const status = vi.fn().mockResolvedValue({ engine: { engine: "evolution", epoch: 2 }, run: {
    run_key: "old", status: "failed", completed_scenes: 1, total_scenes: 2,
    end_chapter: 2, preparing_scenes: false,
  } })
  const preview = vi.fn().mockResolvedValue({
    fingerprint: "f".repeat(64), scene_count: 2, request_limit: 20,
    inherited_scene_count: 1, recompute_from_scene_index: 1, expanded_scope: false,
  })
  const start = vi.fn().mockResolvedValue({ engine: { engine: "evolution", epoch: 2 }, run: {
    run_key: "new", status: "pending", completed_scenes: 1, total_scenes: 2,
  } })
  setBridgeOverrides({ api: { evolution: { status, preview, start } } })
  const wrapper = mount(ReadingFlow, { props: { projectId: "a" } })
  await open(wrapper)
  expect(wrapper.get('input[type="number"][max="2"]').element.value).toBe("2")
  await wrapper.get("form").trigger("submit"); await flushPromises()
  const request = preview.mock.calls[0][1]
  expect(request).toMatchObject({
    mode: "scoped_recompute", run_key: "old", from_scene_index: 1, end_chapter: 2,
  })
  expect(wrapper.text()).toContain("保留前 1 场")
  await button(wrapper, "确认并开始理解").trigger("click"); await flushPromises()
  expect(start.mock.calls[0][1]).toMatchObject({
    ...request, authorization_confirmed: true, expected_fingerprint: "f".repeat(64),
  })
  wrapper.unmount()
})

it("按原观察选定核对范围，展示保守扩大并绑定相同确认", async () => {
  const run = { run_key: "read-a", status: "completed", completed_scenes: 3, total_scenes: 3, end_chapter: 3 }
  const status = vi.fn().mockResolvedValue({ engine: { engine: "evolution", epoch: 2 }, run })
  const item = { id: "a".repeat(64), label: "<img>人物说桥断了", scene_index: 1, quote: "他说桥断了。" }
  const targets = vi.fn().mockResolvedValue({ items: [item], total: 1 })
  const preview = vi.fn().mockResolvedValue({ fingerprint: "f".repeat(64), recompute_from_scene_index: 0, inherited_scene_count: 0, expanded_scope: true, recompute_target: item, request_limit: 20 })
  const start = vi.fn().mockResolvedValue({ engine: { engine: "evolution" }, run: { ...run, status: "pending" } })
  setBridgeOverrides({ api: { evolution: { status, targets, preview, start } } })
  const wrapper = mount(ReadingFlow, { props: { projectId: "a" } })
  await open(wrapper)
  await wrapper.get('input[type="checkbox"]').setValue(true)
  await wrapper.get("select").setValue("observation")
  expect(button(wrapper, "查看理解范围").element.disabled).toBe(true)
  await wrapper.get('input[type="search"]').setValue("桥")
  await button(wrapper, "查找已读内容").trigger("click"); await flushPromises()
  expect(targets).toHaveBeenCalledWith("a", "read-a", { kind: "observation", query: "桥", offset: 0 })
  await wrapper.findAll("select")[1].setValue(item.id)
  await wrapper.get("form").trigger("submit"); await flushPromises()
  expect(preview.mock.calls[0][1]).toMatchObject({ mode: "scoped_recompute", observation_id: item.id, end_chapter: 3 })
  expect(preview.mock.calls[0][1]).not.toHaveProperty("from_scene_index")
  expect(wrapper.text()).toContain("范围已向前扩大")
  expect(wrapper.find("img").exists()).toBe(false)
  await button(wrapper, "确认并开始理解").trigger("click"); await flushPromises()
  expect(start.mock.calls[0][1]).toMatchObject({ observation_id: item.id, expected_fingerprint: "f".repeat(64), authorization_confirmed: true })
  wrapper.unmount()
})

it("按页回看世界提案，转义模型内容并丢弃跨项目迟到结果", async () => {
  const state = { engine: { engine: "evolution" }, run: { run_key: "one", status: "completed", total_scenes: 1, completed_scenes: 1, end_chapter: 1 } }
  const status = vi.fn().mockResolvedValue(state)
  const proposals = vi.fn().mockResolvedValue({ offset: 0, limit: 20, total: 21, items: [{ scene_index: 0, stale: true,
    review_groups: [
      { status: "passed", candidate_count: 2, issues: [] },
      { status: "blocked", candidate_count: 1, issues: ["单个候选超过审查容量，请结合原文核对。"] },
    ],
    entities: [{ name: "<img src=x>", summary: "候选摘要", evidence_quotes: ["正文证据"] }],
    aliases: [], relations: [], findings: ["描述超出原文"], uncertainties: [],
  }] })
  setBridgeOverrides({ api: { evolution: { status, proposals } } })
  const wrapper = mount(ReadingFlow, { props: { projectId: "a" } })
  await open(wrapper)
  await button(wrapper, "查看世界资料提案").trigger("click"); await flushPromises()
  expect(proposals).toHaveBeenCalledWith("a", "one", 0)
  expect(wrapper.text()).toContain("历史或尚未提交")
  expect(wrapper.find(".reading-review-groups").text()).toContain("1 / 2 项通过")
  expect(wrapper.find(".reading-review-groups").text()).toContain("单个候选超过审查容量")
  expect(wrapper.text()).toContain("描述超出原文")
  expect(wrapper.text()).toContain("<img src=x>")
  expect(wrapper.find("img").exists()).toBe(false)
  let resolve
  proposals.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  await button(wrapper, "下一页提案").trigger("click")
  await wrapper.setProps({ projectId: "b" }); await flushPromises()
  resolve({ offset: 20, limit: 20, total: 21, items: [{ scene_index: 9 }] }); await flushPromises()
  expect(wrapper.text()).not.toContain("第 10 场")
  expect(wrapper.text()).not.toContain("候选摘要")
  wrapper.unmount()
})

it("旧版整场延后先预览组数与调用额度，再经作者确认补审", async () => {
  const state = {
    engine: { engine: "evolution" },
    run: { run_key: "run-old", status: "completed", total_scenes: 1, completed_scenes: 1, end_chapter: 1 },
  }
  const status = vi.fn().mockResolvedValue(state)
  const deferred = {
    scene_index: 0,
    stale: false,
    review_status: "blocked",
    review_groups: [],
    supplement: { available: true, attempt_id: "a".repeat(32) },
    entities: [], aliases: [], relations: [], findings: [], uncertainties: [],
  }
  const reviewed = {
    ...deferred,
    review_status: "blocked",
    supplement: { available: false, status: "pending", reviewed_groups: 0, group_count: 2, result_refs: [] },
  }
  const proposals = vi.fn()
    .mockResolvedValueOnce({ offset: 0, limit: 20, total: 1, items: [deferred] })
    .mockResolvedValueOnce({ offset: 0, limit: 20, total: 1, items: [reviewed] })
  const supplementPreview = vi.fn().mockResolvedValue({
    fingerprint: "f".repeat(64), group_count: 2, call_count: 2,
    deferred_count: 1, budget_remaining: 1, additional_budget: 1,
  })
  const supplementStart = vi.fn().mockResolvedValue({ task_id: "task-a", status: "pending" })
  const confirm = vi.fn().mockResolvedValue(true)
  setBridgeOverrides({ api: { evolution: {
    status, proposals,
    worldAuditSupplementPreview: supplementPreview,
    worldAuditSupplementStart: supplementStart,
  } }, confirm })
  const wrapper = mount(ReadingFlow, { props: { projectId: "a" } })
  await open(wrapper)
  await button(wrapper, "查看世界资料提案").trigger("click"); await flushPromises()
  await button(wrapper, "预览延后场景补审").trigger("click"); await flushPromises()
  expect(supplementPreview).toHaveBeenCalledWith("a", "run-old", "a".repeat(32))
  expect(supplementStart).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain("预计 2 组、2 次模型调用")
  expect(wrapper.text()).toContain("需增加 1 次")
  await button(wrapper, "确认补审").trigger("click"); await flushPromises()
  expect(confirm.mock.calls[0][0]).toContain("分为 2 组，调用模型 2 次")
  expect(supplementStart).toHaveBeenCalledWith("a", "run-old", "a".repeat(32), expect.objectContaining({
    expected_fingerprint: "f".repeat(64), authorization_confirmed: true,
  }))
  expect(wrapper.text()).toContain("延后场景补审等待开始")
  wrapper.unmount()
})

it("仅对可恢复的明确失败补审显示继续入口", async () => {
  const state = {
    engine: { engine: "evolution" },
    run: { run_key: "run-old", status: "completed", total_scenes: 1, completed_scenes: 1, end_chapter: 1 },
  }
  const status = vi.fn().mockResolvedValue(state)
  const item = {
    scene_index: 0, stale: false, review_status: "blocked", review_groups: [],
    supplement: { available: false, can_resume: true, status: "failed", attempt_id: "a".repeat(32) },
    entities: [], aliases: [], relations: [], findings: [], uncertainties: [],
  }
  const resumedItem = {
    ...item,
    supplement: { ...item.supplement, can_resume: false, status: "running" },
  }
  const proposals = vi.fn()
    .mockResolvedValueOnce({ offset: 0, limit: 20, total: 1, items: [item] })
    .mockResolvedValueOnce({ offset: 0, limit: 20, total: 1, items: [resumedItem] })
  const resume = vi.fn().mockResolvedValue({ task_id: "task-a", status: "pending" })
  setBridgeOverrides({ api: { evolution: { status, proposals, worldAuditSupplementResume: resume } } })
  const wrapper = mount(ReadingFlow, { props: { projectId: "a" } })
  await open(wrapper)
  await button(wrapper, "查看世界资料提案").trigger("click"); await flushPromises()
  expect(button(wrapper, "继续补审")).toBeTruthy()
  await button(wrapper, "继续补审").trigger("click"); await flushPromises()
  expect(resume).toHaveBeenCalledWith("a", "run-old", "a".repeat(32))
  expect(wrapper.text()).toContain("延后场景补审进行中")
  expect(button(wrapper, "继续补审")).toBeUndefined()
  wrapper.unmount()
})

it("结构整理阶段在状态行与场景计数分开显示", async () => {
  const status = vi.fn().mockResolvedValue({
    engine: { engine: "evolution", epoch: 2 },
    run: { run_key: "run-s", status: "running", completed_scenes: 2, total_scenes: 2, preparing_scenes: false, preparing_structure: true },
  })
  setBridgeOverrides({ api: { evolution: { status } } })
  const wrapper = mount(ReadingFlow, { props: { projectId: "a", entry: true } })
  await flushPromises()
  const line = wrapper.get('[role="status"]').text()
  expect(line).toContain("整理剧情结构候选")
  expect(line).not.toContain("2 / 2 场景")
  wrapper.unmount()
})

it("补扫按选类范围预览、取消零启动、失联保持原授权、换作品隔离", async () => {
  const reading = { engine: { engine: "evolution", epoch: 2 }, run: {
    run_key: "run-a", status: "completed", completed_scenes: 3, total_scenes: 3, end_chapter: 3,
    discovery_categories: [{ key: "language_habit", label: "语言习惯" }, { key: "external_appearance", label: "外在特征" }], category_rescans: [],
  } }
  const status = vi.fn().mockResolvedValue(reading)
  const categoryRescanPreview = vi.fn().mockResolvedValue({ fingerprint: "c".repeat(64), scene_count: 3, call_count: 6, maximum_calls: 20, additional_budget: 12, budget_remaining: 8 })
  const categoryRescanStart = vi.fn().mockRejectedValueOnce(new Error("启动结果失联")).mockResolvedValue({ status: "pending" })
  setBridgeOverrides({ api: { evolution: { status, categoryRescanPreview, categoryRescanStart } } })
  const wrapper = mount(ReadingFlow, { props: { projectId: "a" } })
  await open(wrapper)
  await button(wrapper, "预览类别补扫").trigger("click"); await flushPromises()
  expect(categoryRescanPreview).toHaveBeenCalledWith("a", "run-a", expect.objectContaining({ from_scene_index: 0, through_scene_index: 2, categories: ["language_habit", "external_appearance"] }))
  expect(categoryRescanStart).not.toHaveBeenCalled()
  await button(wrapper, "取消补扫").trigger("click")
  expect(categoryRescanStart).not.toHaveBeenCalled()
  await button(wrapper, "预览类别补扫").trigger("click"); await flushPromises()
  await button(wrapper, "确认并开始补扫").trigger("click"); await flushPromises()
  const frozen = JSON.parse(JSON.stringify(categoryRescanStart.mock.calls[0]))
  expect(wrapper.get('.reading-category-rescan fieldset').element.disabled).toBe(true)
  await button(wrapper, "确认补扫启动结果").trigger("click"); await flushPromises()
  expect(categoryRescanStart.mock.calls[1]).toEqual(frozen)
  await wrapper.setProps({ projectId: "b" }); await flushPromises()
  expect(wrapper.find('.reading-category-rescan input[type="number"]').element.value).toBe("1")
  expect(wrapper.text()).not.toContain("启动结果失联")
  wrapper.unmount()
})


it("后续完成仍显示作者确认的未检查缺口", async () => {
  const status = vi.fn().mockResolvedValue({ engine: { engine: "evolution", epoch: 1 }, run: { run_key: "same-run", status: "completed", completed_scenes: 63, total_scenes: 63, unchecked_discovery_gaps: [{ coverage: "not_checked" }] } })
  setBridgeOverrides({ api: { evolution: { status } } })
  const wrapper = mount(ReadingFlow, { props: { projectId: "isolated" } })
  await open(wrapper)
  expect(wrapper.text()).toContain("保留 1 处作者确认的未检查缺口")
  expect(wrapper.text()).toContain("后续完成也不代表这部分已检查")
  expect(status).toHaveBeenCalledTimes(1)
  wrapper.unmount()
})

it("uses the confirmed range instead of a request quota for new Luna", async () => {
  const status = vi.fn().mockResolvedValue({ engine: { engine: "evolution" }, run: null, default_budget_mode: "confirmed_scope" })
  const preview = vi.fn().mockResolvedValue({ fingerprint: "f".repeat(64), scene_count: 2, budget_mode: "confirmed_scope", request_limit: null, model: "gpt-6-luna" })
  setBridgeOverrides({ api: { evolution: { status, preview } } })
  const wrapper = mount(ReadingFlow, { props: { projectId: "p", entry: true } })
  await flushPromises()
  expect(wrapper.text()).toContain("完成本次确认范围")
  expect(wrapper.text()).not.toContain("本次最多调用模型")
  await wrapper.find("form").trigger("submit")
  await flushPromises()
  expect(preview.mock.calls[0][1].request_limit).toBeNull()
  expect(wrapper.text()).not.toContain("合计最多调用模型")
  wrapper.unmount()
})


it.each([
  ["bounded", "confirmed_scope", 20],
  ["confirmed_scope", "bounded", null],
])("category rescan inherits %s even when recomputation uses %s", async (budgetMode, defaultMode, expectedLimit) => {
  const status = vi.fn().mockResolvedValue({ engine: { engine: "evolution", epoch: 1 }, default_budget_mode: defaultMode, run: {
    run_key: "old", status: "completed", completed_scenes: 1, total_scenes: 1, end_chapter: 1, budget_mode: budgetMode,
    discovery_categories: [{ key: "language_habit", label: "语言习惯" }], category_rescans: [],
  } })
  const categoryRescanPreview = vi.fn().mockResolvedValue({ fingerprint: "a".repeat(64), budget_mode: budgetMode })
  setBridgeOverrides({ api: { evolution: { status, categoryRescanPreview } } })
  const wrapper = mount(ReadingFlow, { props: { projectId: "p" } })
  await open(wrapper)
  await wrapper.get('form .reading-recompute-toggle input').setValue(true)
  await button(wrapper, "预览类别补扫").trigger("click"); await flushPromises()
  expect(categoryRescanPreview.mock.calls[0][2].request_limit).toBe(expectedLimit)
  wrapper.unmount()
})

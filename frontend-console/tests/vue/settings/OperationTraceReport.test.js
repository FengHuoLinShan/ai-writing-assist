import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import OperationTraceReport from "../../../vue/views/settings/components/OperationTraceReport.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

function makeReport(overrides = {}) {
  return {
    schema_version: "1",
    period: "30d",
    timezone: "UTC",
    as_of: "2026-10-16T00:00:00+00:00",
    window_start: "2026-09-17",
    window_end: "2026-10-16",
    collection_enabled_now: true,
    events: [],
    operation_candidates: [],
    sequences: [],
    parameter_profiles: [],
    lifecycle: [],
    metrics: [],
    coverage: {
      status: "no_records",
      completeness_provable: false,
      capture_enabled_now: true,
      first_record_date: null,
      last_record_date: null,
      days_with_records: 0,
      missing_metric_event_count: 0,
      missing_duration_event_count: 0,
      unmeasured_usage_event_count: 0,
      incomplete_usage_event_count: 0,
      unknown_usage_event_count: 0,
      pending_usage_total: null,
      missing_lifecycle_event_count: 0,
      incomplete_sequence_count: 0,
      parameter_profile_gap_by_operation: {},
      legacy_event_aggregates_preserved: true,
      note: "只展示实际记录样本。",
    },
    ...overrides,
  }
}

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

let state
let api

beforeEach(() => {
  state = { currentProjectId: "p1", currentView: "project-settings" }
  api = {
    assistant: {
      operationTraceReport: vi.fn(async () => makeReport()),
      exportOperationTraceReport: vi.fn(async () => new Blob(["aggregate export"])),
    },
  }
  setBridgeOverrides({ state, api })
})

afterEach(() => {
  resetBridgeOverrides()
  vi.restoreAllMocks()
})

describe("OperationTraceReport", () => {
  it("shows honest empty coverage and uses the selected project and fixed period", async () => {
    const wrapper = mount(OperationTraceReport, { props: { projectId: "p1" } })
    await flushPromises()

    expect(api.assistant.operationTraceReport).toHaveBeenCalledWith(
      "p1",
      "30d",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(wrapper.text()).toContain("当前范围没有留痕记录")
    expect(wrapper.text()).toContain("不会把缺少记录解释为零次操作")
    expect(wrapper.text()).toContain("截点 2026-10-16T00:00:00+00:00")
    await wrapper.get('select[aria-label="操作留痕时间范围"]').setValue("90d")
    await flushPromises()
    expect(api.assistant.operationTraceReport).toHaveBeenLastCalledWith(
      "p1",
      "90d",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it("drops a late previous-project response and reports the current scope only", async () => {
    const oldResponse = deferred()
    api.assistant.operationTraceReport.mockImplementation((projectId) => (
      projectId === "p1" ? oldResponse.promise : Promise.resolve(makeReport({
        coverage: { ...makeReport().coverage, status: "no_records", note: "当前作品 p2 的记录。" },
      }))
    ))
    const wrapper = mount(OperationTraceReport, { props: { projectId: "p1" } })
    state.currentProjectId = "p2"
    await wrapper.setProps({ projectId: "p2" })
    await flushPromises()
    oldResponse.resolve(makeReport({ coverage: { ...makeReport().coverage, note: "旧作品的内容" } }))
    await flushPromises()

    expect(wrapper.text()).toContain("当前作品 p2 的记录。")
    expect(wrapper.text()).not.toContain("旧作品的内容")
    expect(api.assistant.operationTraceReport).toHaveBeenCalledWith(
      "p2",
      "30d",
      expect.any(Object),
    )
  })

  it("gives a clear stale-scope error and confirms a successful local export", async () => {
    api.assistant.operationTraceReport.mockRejectedValueOnce(Object.assign(new Error("conflict"), { status: 409 }))
    const wrapper = mount(OperationTraceReport, { props: { projectId: "p1" } })
    await flushPromises()
    expect(wrapper.text()).toContain("作品状态已变化，请刷新当前作品的留痕报表")

    api.assistant.operationTraceReport.mockResolvedValueOnce(makeReport({
      coverage: { ...makeReport().coverage, status: "recorded_sample" },
      events: [{ date: "2026-10-16", operation: "project.add_task", event: "executed", count: 1 }],
    }))
    await wrapper.get(".otr-error button").trigger("click")
    await flushPromises()
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:trace-report")
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
    await wrapper.get(".otr-button-secondary").trigger("click")
    await flushPromises()

    expect(api.assistant.exportOperationTraceReport).toHaveBeenCalledWith(
      "p1",
      "30d",
      "csv",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(anchorClick).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain("近 30 天报告已下载")
  })
})

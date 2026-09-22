import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { reactive } from "vue"
import { createForecast } from "../../../vue/composables/useForecast.js"
import ForecastDock from "../../../vue/components/ForecastDock.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const projectA = "10000000-0000-4000-8000-000000000001"
const projectB = "10000000-0000-4000-8000-000000000002"
const draftId = "20000000-0000-4000-8000-000000000001"
const item = { candidate_id: "30000000-0000-4000-8000-000000000001", issue_key: "bell", notice_version: 0, assessment_hash: "a".repeat(64), title: "可以追问，也可以保留疑问", kind: "creative_opportunity", why_now: "人物仍在这里。", statements: [], directions: [], unknowns: ["也可能只是普通遗物"], evidence: [], actions: [{ action_id: "project.prepare_task", kind: "prepare_domain", label: "加入稍后处理", available: true }], notice_status: "unread" }
const feed = (body, title = "当前建议") => ({ client_context_id: body.context.client_context_id, focus_seq: body.context.focus_seq, context_hash: title, state: "ready", items: [{ ...item, title }], coverage: { scope_label: "本章保存资料", counts: {} }, next_cursor: null })
let instances, wrappers
function apiFixture() {
  return { forecasts: { capabilities: vi.fn(async () => ({ items: [{ available: true, compute_kind: "semantic" }] })), policy: vi.fn(async () => ({ generation: 0, policy: { automatic: false, shared_daily_limit: 12 } })), feed: vi.fn(async (_id, body) => feed(body)), prepare: vi.fn(), evaluate: vi.fn() }, assistant: { run: vi.fn(async () => ({ result: { actions: [{ key: "selected", title: "待办" }] } })), decide: vi.fn() } }
}
beforeEach(() => { localStorage.clear(); instances = []; wrappers = []; vi.useFakeTimers() })
afterEach(() => { for (const wrapper of wrappers) wrapper.unmount(); for (const instance of instances) instance.dispose(); resetBridgeOverrides(); vi.useRealTimers(); vi.restoreAllMocks() })

describe("forecast ownership and author control", () => {
  it("does not let a late feed replace another project's context", async () => {
    const api = apiFixture()
    let release
    api.forecasts.feed.mockImplementation((id, body) => id === projectA ? new Promise(resolve => { release = () => resolve(feed(body, "旧作品的资料")) }) : Promise.resolve(feed(body, "当前作品的资料")))
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const forecast = createForecast(); instances.push(forecast)
    const old = forecast.configure(projectA, { page: "writing", draft_id: draftId })
    await flushPromises()
    await forecast.configure(projectB, { page: "today" })
    release(); await old
    expect(forecast.state.projectId).toBe(projectB)
    expect(forecast.state.feed.items[0].title).toBe("当前作品的资料")
  })
  it("reuses an uncertain prepare operation and rejects new unsaved input", async () => {
    const api = apiFixture(), editor = { dirty: false }
    api.forecasts.prepare.mockRejectedValueOnce(new Error("连接中断")).mockResolvedValue({ operation_id: "same", run_id: "run", batch_id: "batch", batch_fingerprint: "b".repeat(64), status: "preview_ready" })
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const forecast = createForecast({ editor: () => editor }); instances.push(forecast)
    await forecast.configure(projectA, { page: "writing", draft_id: draftId })
    await forecast.prepare(item, item.actions[0])
    await forecast.prepare(item, item.actions[0])
    expect(api.forecasts.prepare.mock.calls[0][2].operation_id).toBe(api.forecasts.prepare.mock.calls[1][2].operation_id)
    editor.dirty = true
    await forecast.confirm()
    expect(api.assistant.decide).not.toHaveBeenCalled()
    expect(forecast.state.prepared.batch_id).toBe("batch")
  })
  it("holds open cards while new results arrive", async () => {
    const api = apiFixture()
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const forecast = createForecast(); instances.push(forecast)
    await forecast.configure(projectA, { page: "writing", draft_id: draftId })
    forecast.state.hold = true
    api.forecasts.feed.mockImplementation(async (_id, body) => feed(body, "新的建议"))
    await forecast.refresh()
    expect(forecast.state.feed.items[0].title).toBe("当前建议")
    expect(forecast.state.pendingFeed.items[0].title).toBe("新的建议")
    forecast.acceptFeed()
    expect(forecast.state.feed.items[0].title).toBe("新的建议")
  })
  it("does not refresh during composition or submit a dirty editor", async () => {
    const api = apiFixture(), editor = reactive({ dirty: true })
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const wrapper = mount(ForecastDock, { props: { projectId: projectA, context: { page: "writing", draft_id: draftId }, editor, composing: true } }); wrappers.push(wrapper)
    await flushPromises()
    const count = api.forecasts.feed.mock.calls.length
    await vi.advanceTimersByTimeAsync(30000)
    expect(api.forecasts.feed).toHaveBeenCalledTimes(count)
    const analyze = wrapper.findAll("button").find(button => button.text() === "帮我想下一步")
    expect(analyze.attributes("disabled")).toBeDefined()
    expect(wrapper.text()).toContain("尚有未保存文字")
    expect(api.forecasts.evaluate).not.toHaveBeenCalled()
  })
})

describe("selection snapshot stays bound to its source version (PR160-162 F2)", () => {
  beforeEach(() => { vi.useRealTimers() })  // focusFrom 的 crypto.subtle 是真实异步，fake timers 冲不净微任务链

  const savedWithSelection = "林舟走进白石城，星盘在袖中发亮。"
  const selectionContext = {
    page: "writing", draft_id: draftId, selection: "白石城",
    selection_start: Array.from("林舟走进").length,
    selection_end: Array.from("林舟走进白石城").length,
  }
  function editorWith(content, id = draftId) {
    return reactive({ projectId: projectA, draftId: id, sceneId: null, dirty: false, saving: false, lastSavedContent: content })
  }
  function lastFocus(api) {
    const calls = api.forecasts.feed.mock.calls
    return calls[calls.length - 1][1].context
  }
  async function settle() { await flushPromises(); await new Promise(resolve => setTimeout(resolve, 0)); await flushPromises() }
  it("carries the selected range while the saved content still matches at the captured offsets", async () => {
    const api = apiFixture()
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const forecast = createForecast({ editor: () => editorWith(savedWithSelection) }); instances.push(forecast)
    await forecast.configure(projectA, selectionContext)
    expect(lastFocus(api).selected_range).toEqual({ start_offset: selectionContext.selection_start, end_offset: selectionContext.selection_end })
  })
  it("invalidates the old offsets when text is inserted before the selection and saved", async () => {
    const api = apiFixture()
    const editor = editorWith(savedWithSelection)
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const wrapper = mount(ForecastDock, { props: { projectId: projectA, context: selectionContext, editor } }); wrappers.push(wrapper)
    await settle()
    expect(lastFocus(api).selected_range).toBeDefined()
    // 前文插字并保存：dock 以旧 props.context 重新 configure——新指纹不得
    // 配旧偏移，选区必须失效（不带范围），而不是静默指向别的文字。
    editor.lastSavedContent = "他在城门外停下。林舟走进文白石城，星盘在袖中发亮。"
    await settle()
    const focus = lastFocus(api)
    expect(focus.selected_range).toBeUndefined()
    expect(focus.draft_id).toBe(draftId)
    expect(focus.expected_source_hash).toHaveLength(64)
  })
  it("invalidates the selection when the editor has switched to another draft", async () => {
    const api = apiFixture()
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const otherDraft = "20000000-0000-4000-8000-000000000002"
    const forecast = createForecast({ editor: () => editorWith("柳青在青岚城外远望。", otherDraft) }); instances.push(forecast)
    await forecast.configure(projectA, selectionContext)
    const focus = lastFocus(api)
    expect(focus.draft_id).toBe(otherDraft)
    expect(focus.selected_range).toBeUndefined()
  })
  it("invalidates the selection on another draft even when identical text sits at the same offsets", async () => {
    // A05（2026-09-22 审查）：原稿 A 选「白石城」→ 切到稿 B（内容恰好
    // 同位置同文字）——切片文本重验会通过，但选区只对捕获它的原稿有效，
    // 不得把旧范围绑到新稿指纹上。既有「切稿失效」用例换了文字，证明
    // 不了草稿身份检测，此例补齐。
    const api = apiFixture()
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const otherDraft = "20000000-0000-4000-8000-000000000002"
    const forecast = createForecast({ editor: () => editorWith(savedWithSelection, otherDraft) }); instances.push(forecast)
    await forecast.configure(projectA, selectionContext)
    const focus = lastFocus(api)
    expect(focus.draft_id).toBe(otherDraft)
    expect(focus.expected_source_hash).toHaveLength(64)  // 新稿指纹照常携带
    expect(focus.selected_range).toBeUndefined()          // 旧选区跨稿失效
  })
})

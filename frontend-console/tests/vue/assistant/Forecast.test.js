import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { reactive } from "vue"
import { createForecast } from "../../../vue/composables/useForecast.js"
import { subscribeForecast } from "../../../vue/composables/forecastStore.js"
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

it("confirms a pending local forecast through the shared store", async () => {
  const api = apiFixture()
  api.localAgent = { approve: vi.fn(async () => ({ approved: true })) }
  api.forecasts.run = vi.fn(async () => ({ run_id: "run-1", task_id: "task-1", status: "pending", local_agent: { kind: "codex", approved: true } }))
  setBridgeOverrides({ api, state: { currentProjectId: projectA }, confirm: () => true })
  const wrapper = mount(ForecastDock, { props: { projectId: projectA, context: { page: "today" } } }); wrappers.push(wrapper)
  const shared = subscribeForecast(projectA)
  try {
    await flushPromises()
    shared.forecast.state.run = { run_id: "run-1", task_id: "task-1", status: "pending", local_agent: { kind: "codex", approved: false } }
    await wrapper.vm.$nextTick()
    await wrapper.findAll("button").find(button => button.text() === "确认本轮在本机执行").trigger("click")
    await flushPromises()
    expect(api.localAgent.approve).toHaveBeenCalledWith(projectA, "task-1")
    expect(api.forecasts.run).toHaveBeenCalledWith(projectA, "run-1")
    expect(shared.forecast.state.run.local_agent.approved).toBe(true)
  } finally { shared.release() }
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

describe("shared feed and authority fencing", () => {
  it("clears the old authorization before a replacement request fails", async () => {
    const api = apiFixture()
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const forecast = createForecast(); instances.push(forecast)
    await forecast.configure(projectA, { page: "writing", draft_id: draftId, context_confirmation_id: "first", context_confirmation_action: "writing.generate" })
    forecast.state.hold = true
    api.forecasts.feed.mockRejectedValue(new Error("CONFIRMATION_SCOPE_CONFLICT"))
    const next = forecast.configure(projectA, { page: "writing", draft_id: draftId, context_confirmation_id: "second", context_confirmation_action: "writing.generate" })
    expect(forecast.state.feed).toBeNull()
    await next
    expect(forecast.state.feed).toBeNull()
    expect(forecast.state.stale).toBe(true)
  })
  it("does not let an earlier read resurrect a card after a later refresh", async () => {
    const api = apiFixture(), pending = []
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const forecast = createForecast(); instances.push(forecast)
    await forecast.configure(projectA, { page: "today" })
    api.forecasts.feed.mockImplementation((_id, body) => new Promise(resolve => pending.push(title => resolve(feed(body, title)))))
    const first = forecast.refresh(), second = forecast.refresh()
    pending[1]("新的处置"); await second
    pending[0]("旧轮询"); await first
    expect(forecast.state.feed.items[0].title).toBe("新的处置")
  })
  it("shares one poll and one input across two hosts, releasing the last subscription", async () => {
    const api = apiFixture()
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const props = { projectId: projectA, context: { page: "today" } }
    const first = mount(ForecastDock, { props }), second = mount(ForecastDock, { props })
    wrappers.push(first, second)
    await flushPromises()
    expect(api.forecasts.feed).toHaveBeenCalledTimes(1)
    await first.find("textarea").setValue("保留未知")
    expect(second.find("textarea").element.value).toBe("保留未知")
    await vi.advanceTimersByTimeAsync(15000)
    expect(api.forecasts.feed).toHaveBeenCalledTimes(2)
    first.unmount(); wrappers.shift()
    await vi.advanceTimersByTimeAsync(15000)
    expect(api.forecasts.feed).toHaveBeenCalledTimes(3)
    second.unmount(); wrappers.shift()
    await vi.advanceTimersByTimeAsync(15000)
    expect(api.forecasts.feed).toHaveBeenCalledTimes(3)
  })
  it("keeps a held card valid for presentation changes but revokes changed sources", async () => {
    const api = apiFixture(), keys = { authority_scope_key: "scope", evidence_snapshot_key: "source", task_context_key: "task", presentation_focus: "first" }
    api.forecasts.feed.mockImplementation(async (_id, body) => ({ ...feed(body), context_keys: { ...keys } }))
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const forecast = createForecast(); instances.push(forecast)
    await forecast.configure(projectA, { page: "today" })
    forecast.state.hold = true
    keys.presentation_focus = "second"
    await forecast.refresh()
    expect(forecast.state.stale).toBe(false)
    keys.evidence_snapshot_key = "revised"
    await forecast.refresh()
    expect(forecast.state.stale).toBe(true)
  })
  it("hands a polish choice to exact revision with the selected saved range", async () => {
    vi.useRealTimers()
    const api = apiFixture(), assistantOpener = vi.fn(), content = "潮水来了。她关上门。"
    const editor = { draftId, lastSavedContent: content, dirty: false }
    setBridgeOverrides({ api, assistantOpener, state: { currentProjectId: projectA } })
    const forecast = createForecast({ editor: () => editor }); instances.push(forecast)
    await forecast.configure(projectA, { page: "writing", draft_id: draftId, task_hint: "polish", selection: "她关上门。", selection_start: 5, selection_end: 10 })
    const action = { action_id: "writing.discuss_revision.quiet" }
    await forecast.prepare({ ...item, directions: [{ direction_id: "quiet", proposal: "收短句子" }] }, action)
    expect(api.forecasts.prepare).not.toHaveBeenCalled()
    expect(assistantOpener).toHaveBeenCalledWith(expect.objectContaining({ context: expect.objectContaining({ task_hint: "polish", draft_id: draftId, selection: "她关上门。", selection_start: 5, selection_end: 10 }) }))
  })
})

describe("recovery and host handoff boundaries", () => {
  it("requires resolving an uncertain operation before evaluating a changed exclusion scope", async () => {
    const api = apiFixture()
    api.forecasts.evaluate.mockRejectedValue(new Error("connection lost"))
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const forecast = createForecast(); instances.push(forecast)
    await forecast.configure(projectA, { page: "today" })
    await forecast.evaluate()
    const original = forecast.state.pending
    await forecast.configure(projectA, { page: "today", excluded_targets: ["private"] })
    await forecast.evaluate()
    expect(api.forecasts.evaluate).toHaveBeenCalledTimes(1)
    expect(forecast.state.pending).toEqual(original)
    expect(forecast.state.error).toContain("不会按旧范围")
  })
  it("retries legacy pending bodies without adding new default fields", async () => {
    const api = apiFixture()
    api.forecasts.evaluate.mockRejectedValue(new Error("connection lost"))
    api.forecasts.prepare.mockRejectedValue(new Error("connection lost"))
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const forecast = createForecast(); instances.push(forecast)
    await forecast.configure(projectA, { page: "today" })
    await forecast.evaluate()
    delete forecast.state.pending.context.excluded_targets
    const pending = JSON.stringify(forecast.state.pending)
    await forecast.evaluate()
    expect(JSON.stringify(api.forecasts.evaluate.mock.lastCall[1])).toBe(pending)
    await forecast.prepare(item, item.actions[0])
    delete forecast.state.pendingPrepare.body.context.excluded_targets
    const prepare = JSON.stringify(forecast.state.pendingPrepare.body)
    await forecast.prepare(item, item.actions[0])
    expect(JSON.stringify(api.forecasts.prepare.mock.lastCall[2])).toBe(prepare)
  })
  it("starts again at the first page when pagination detects a new authority", async () => {
    const api = apiFixture()
    let scope = "old"
    api.forecasts.feed.mockImplementation(async (_id, body) => ({ ...feed(body, scope), context_keys: { authority_scope_key: scope, evidence_snapshot_key: "s", task_context_key: "t" }, items: scope === "old" ? [item] : [], next_cursor: scope === "old" ? "3" : null }))
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const forecast = createForecast(); instances.push(forecast)
    await forecast.configure(projectA, { page: "today" })
    scope = "new"
    await forecast.more()
    expect(forecast.state.feed.items).toEqual([])
    expect(api.forecasts.feed.mock.lastCall[1].cursor).toBeUndefined()
  })
  it("submits the intent of the host the author actually focused", async () => {
    const api = apiFixture()
    api.forecasts.evaluate.mockResolvedValue({ run: { status: "completed" } })
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const lower = mount(ForecastDock, { props: { projectId: projectA, context: { page: "writing", draft_id: draftId } } })
    const upper = mount(ForecastDock, { props: { projectId: projectA, context: { page: "writing", draft_id: draftId, task_hint: "continue" }, standalone: true } })
    wrappers.push(lower, upper)
    await flushPromises()
    await lower.find("select[aria-label='当前写作意图']").trigger("focusin")
    await lower.find("select[aria-label='当前写作意图']").setValue("polish")
    await flushPromises()
    await lower.find("form").trigger("submit")
    await flushPromises()
    expect(api.forecasts.evaluate).toHaveBeenCalledTimes(1)
    expect(api.forecasts.evaluate.mock.lastCall[1].context.task_hint).toBe("polish")
  })
  it("cancels an old analyze click when another host takes focus during its read", async () => {
    const api = apiFixture()
    setBridgeOverrides({ api, state: { currentProjectId: projectA } })
    const lower = mount(ForecastDock, { props: { projectId: projectA, context: { page: "writing", draft_id: draftId, task_hint: "polish" } } })
    const upper = mount(ForecastDock, { props: { projectId: projectA, context: { page: "writing", draft_id: draftId, task_hint: "continue" }, standalone: true } })
    wrappers.push(lower, upper)
    await flushPromises()
    let release
    api.forecasts.feed.mockImplementation((_id, body) => body.context.task_hint === "polish" ? new Promise(resolve => { release = () => resolve(feed(body)) }) : Promise.resolve(feed(body)))
    await lower.find("form").trigger("submit")
    await flushPromises()
    await upper.find("section").trigger("focusin")
    await flushPromises()
    release(); await flushPromises()
    expect(api.forecasts.evaluate).not.toHaveBeenCalled()
  })
  it("cancels a revision handoff when the draft changes during hashing", async () => {
    vi.useRealTimers()
    const api = apiFixture(), assistantOpener = vi.fn(), content = "甲乙丙丁"
    const editor = reactive({ draftId, lastSavedContent: content, dirty: false })
    setBridgeOverrides({ api, assistantOpener, state: { currentProjectId: projectA } })
    const forecast = createForecast({ editor: () => editor }); instances.push(forecast)
    await forecast.configure(projectA, { page: "writing", draft_id: draftId, task_hint: "polish", selection: "甲乙", selection_start: 0, selection_end: 2 })
    const digest = crypto.subtle.digest.bind(crypto.subtle)
    let release
    vi.spyOn(crypto.subtle, "digest").mockImplementationOnce((...args) => new Promise(resolve => { release = async () => resolve(await digest(...args)) }))
    const old = forecast.prepare({ ...item, directions: [{ direction_id: "a", proposal: "收短句子" }] }, { action_id: "writing.discuss_revision.a" })
    editor.draftId = "20000000-0000-4000-8000-000000000002"
    await forecast.configure(projectA, { page: "writing", draft_id: editor.draftId, task_hint: "revise", selection: "丙丁", selection_start: 2, selection_end: 4 })
    await release(); await old
    expect(assistantOpener).not.toHaveBeenCalled()
  })
})

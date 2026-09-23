import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises } from "@vue/test-utils"
import { setBridgeOverrides } from "../../../vue/bridge/index.js"
import { invalidateAccountBrowserState } from "../../../shared/accountStorage.js"
import { createProjectAssistant } from "../../../vue/composables/useProjectAssistant.js"

const mocks = vi.hoisted(() => ({ configs: [], adopt: vi.fn(), prepare: vi.fn() }))
vi.mock("../../../vue/shared/workflowManager.js", () => ({ createWorkflowManager: config => {
  mocks.configs.push(config)
  return { adopt: mocks.adopt, prepare: mocks.prepare, recover: vi.fn(), stop: vi.fn(), resetMemoryScope: vi.fn() }
} }))
let controller
let state
let api
function pending() { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
function run(body) { return { id: body.operation_id, task_id: body.operation_id, status: "pending", result: {}, usage: {} } }

beforeEach(() => {
  localStorage.clear()
  mocks.configs.length = 0
  vi.clearAllMocks()
  state = { currentProjectId: "p1" }
  api = {
    capabilities: vi.fn(async () => ({ enabled: true })),
    sessions: vi.fn(async projectId => ({ items: [{ id: `${projectId}-s`, title: "讨论" }], total: 1 })),
    session: vi.fn(async (_projectId, id) => ({ session: { id, title: "讨论" }, messages: [], message_total: 0, latest_run: null })),
    createSession: vi.fn(async projectId => ({ id: `${projectId}-new`, title: "新讨论" })),
    submit: vi.fn(async (_id, body) => run(body)),
    run: vi.fn(async (_id, id) => ({ id, task_id: id, status: "pending", result: {} })),
    messages: vi.fn(),
  }
  setBridgeOverrides({ api: { assistant: api }, state })
  controller = createProjectAssistant()
})
afterEach(() => { controller.dispose(); setBridgeOverrides({ api: undefined, state: undefined, writingFingerprint: undefined }); localStorage.clear() })

describe("project assistant durable interaction", () => {
  it("restores an uncertain team submission with the same receipt and no web permission", async () => {
    api.submitTeam = vi.fn().mockRejectedValueOnce(new Error("response lost")).mockImplementation(async (_id, body) => run(body))
    await controller.load("p1")
    controller.state.blueprint = "deep_review"
    controller.state.context = { page: "writing", draft_id: "draft", chapter_index: 1 }
    setBridgeOverrides({ writingFingerprint: async () => "frozen-source-hash" })
    controller.setInput("深度审稿")
    controller.setAllowWeb(true)
    await controller.send()
    const payload = api.submitTeam.mock.calls[0][1]
    expect(payload).toMatchObject({ blueprint: "deep_review", allow_web: false, web_backend: null, context: { source_hash: "frozen-source-hash" } })
    api.run.mockRejectedValue(Object.assign(new Error("not found"), { status: 404 }))
    await controller.recoverSubmission()
    expect(api.submitTeam.mock.calls[1][1]).toEqual(payload)
    expect(api.submit).not.toHaveBeenCalled()
    expect(controller.state.pendingSubmission).toBe(false)
  })
  it.each([false, true])("consumes team permission after an acknowledged submission, including recovery (%s)", async recover => {
    api.submitTeam = vi.fn(async (_id, body) => run(body))
    if (recover) api.submitTeam.mockRejectedValueOnce(new Error("response lost"))
    await controller.load("p1")
    controller.state.blueprint = "world_stress"
    controller.state.previousReportId = "old-report"
    controller.state.scenarioKeys = ["door"]
    controller.state.preservedConstraints = "保留机关"
    controller.setInput("重测")
    await controller.send()
    if (recover) await controller.recoverSubmission()
    expect(controller.state).toMatchObject({ blueprint: null, previousReportId: null, scenarioKeys: [], preservedConstraints: "" })
    const done = { ...controller.state.run, status: "completed" }
    api.session.mockResolvedValue({ session: { id: "p1-s" }, messages: [], latest_run: done })
    controller.dispose()
    controller = createProjectAssistant()
    await controller.load("p1")
    expect(controller.state.blueprint).toBeNull()
    controller.setInput("解释一下刚才的结论")
    await controller.send()
    expect(api.submit).toHaveBeenCalledTimes(1)
    expect(api.submit.mock.calls[0][1]).not.toHaveProperty("blueprint")
    expect(api.submitTeam).toHaveBeenCalledTimes(1)
  })
  it("does not restore legacy sticky team permission", async () => {
    localStorage.setItem("novel_assistant_v1:local:p1", JSON.stringify({ sessionId: "p1-s", drafts: { "p1-s": { text: "普通后续问题", blueprint: "deep_review" } } }))
    await controller.load("p1")
    expect(controller.state.input).toBe("普通后续问题")
    expect(controller.state.blueprint).toBeNull()
  })
  it("preserves retest scope and author constraints through backup and first session creation", async () => {
    api.sessions.mockResolvedValue({ items: [], total: 0 })
    api.submitTeam = vi.fn(async (_id, body) => run(body))
    await controller.load("p1")
    controller.state.blueprint = "world_stress"
    controller.state.context = { page: "world", target: { target_type: "world_entity", target_id: "rule" } }
    controller.state.preservedConstraints = "保留城门不便"
    controller.state.previousReportId = "report"
    controller.state.scenarioKeys = ["outside"]
    controller.setInput("只重测外侧推门")
    controller.dispose()
    controller = createProjectAssistant()
    await controller.load("p1")
    await controller.send()
    expect(api.submitTeam).toHaveBeenCalledWith("p1-new", expect.objectContaining({
      blueprint: "world_stress", preserved_constraints: ["保留城门不便"], previous_report_id: "report", scenario_keys: ["outside"],
      context: { page: "world", target: { target_type: "world_entity", target_id: "rule" } },
    }))
    await controller.selectSession(null)
    expect(controller.state.blueprint).toBeNull()
    expect(controller.state.input).toBe("")
  })
  it("keeps the first composition scope and explicit web choice when creating its session", async () => {
    api.sessions.mockResolvedValue({ items: [], total: 0 })
    api.capabilities.mockResolvedValue({ enabled: true, web_search: { available: true } })
    await controller.load("p1")
    controller.state.context = { page: "writing", chapter_index: 3, excluded_targets: ["world_entity:hidden"], scope: "current" }
    controller.setInput("核对 IANA")
    controller.setAllowWeb(true)
    // 组件契约（PR160-162 审查 F1 后）：send 始终携带 withIntent(state.context)
    // ——入参即新操作上下文权威，composition scope 经调用方保留。
    await controller.send({ ...controller.state.context, task_hint: "unknown" })
    expect(api.submit).toHaveBeenCalledWith("p1-new", expect.objectContaining({
      message: "核对 IANA", allow_web: true, web_backend: "searxng-v1",
      context: { page: "writing", chapter_index: 3, excluded_targets: ["world_entity:hidden"], scope: "current", task_hint: "unknown" },
    }))
  })
  it("freezes the passed context (with task_hint) as the new operation's authority instead of stale state.context", async () => {
    api.submit.mockImplementation(async (_id, body) => ({ ...run(body), status: "completed" }))
    await controller.load("p1")
    // 面板已打开：state.context 带旧意图；界面切换 polish 后发送——
    // 实际请求必须携带本次入参（PR160-162 审查 F1）。
    controller.state.context = { page: "writing", chapter_index: 2, task_hint: "review" }
    controller.setInput("只润色选中段落")
    await controller.send({ ...controller.state.context, task_hint: "polish" })
    expect(api.submit.mock.calls[0][1].context).toEqual({ page: "writing", chapter_index: 2, task_hint: "polish" })
    // 切换 review 再发：新操作使用 review，不被上一轮 state.context 覆盖。
    controller.state.context = { page: "writing", chapter_index: 2, task_hint: "polish" }
    controller.setInput("复查这一章")
    await controller.send({ ...controller.state.context, task_hint: "review" })
    expect(api.submit.mock.calls[1][1].context).toEqual({ page: "writing", chapter_index: 2, task_hint: "review" })
  })
  it("keeps an unconfirmed pending payload untouched when a newer intent arrives", async () => {
    api.submit.mockRejectedValueOnce(Object.assign(new Error("response lost"), { status: 502 }))
    await controller.load("p1")
    controller.state.context = { page: "writing", chapter_index: 2, task_hint: "polish" }
    controller.setInput("原请求")
    await controller.send({ ...controller.state.context })
    const body = api.submit.mock.calls[0][1]
    // 未确认请求仍以原幂等负载重试：新意图不重写旧 payload.context。
    controller.state.context = { page: "writing", chapter_index: 9, task_hint: "review" }
    controller.setInput("原请求")
    await controller.send({ ...controller.state.context })
    expect(api.submit.mock.calls[1][1]).toEqual(body)
    expect(body.context.task_hint).toBe("polish")
  })

  it("reopens an older partial receipt and preserves unsent input across reload", async () => {
    const latest = { id: "latest", status: "completed", result: {} }
    const old = { id: "old", status: "completed", result: { batch: { id: "old-batch", status: "partial", selected: ["edit"] } } }
    api.session.mockResolvedValue({ session: { id: "p1-s" }, messages: [{ id: "message", role: "assistant", assistant_run_id: "old", content: "原方案" }], message_total: 1, latest_run: latest })
    api.run.mockResolvedValue(old)
    await controller.load("p1")
    controller.setInput("尚未提交的想法")
    await controller.openRun("old")
    expect(controller.state.run.result.batch.id).toBe("old-batch")
    expect(controller.state.selected).toEqual(["edit"])
    controller.dispose()
    controller = createProjectAssistant()
    await controller.load("p1")
    expect(controller.state.run.id).toBe("old")
    expect(controller.state.input).toBe("尚未提交的想法")
    expect(controller.state.messages[0].assistant_run_id).toBe("old")
  })

  it("does not let a late historical receipt replace another session", async () => {
    await controller.load("p1")
    const response = pending()
    api.run.mockImplementation(() => response.promise)
    const opening = controller.openRun("old")
    await controller.selectSession("different")
    response.resolve({ id: "old", status: "completed", result: {} })
    await opening
    expect(controller.state.run).toBeNull()
    expect(controller.state.sessionId).toBe("different")
  })
  it("retains the reference scope after sending and restores it on another device", async () => {
    const scope = { page: "writing", chapter_index: 3, scope: "current", excluded_targets: ["world_entity:hidden"] }
    api.session.mockResolvedValue({ session: { id: "p1-s" }, messages: [], message_total: 0, latest_run: null, last_context: scope, last_allow_web: false })
    await controller.load("p1")
    expect(controller.state.context).toEqual(scope)
    controller.setInput("继续检查")
    // 组件契约：入参携带 withIntent(state.context)（此处 scope 即
    // state.context），入参是新操作的冻结权威。
    await controller.send({ ...scope })
    expect(api.submit.mock.calls[0][1].context).toEqual(scope)
    expect(api.submit.mock.calls[0][1].allow_web).toBe(false)
    expect(controller.state.context).toEqual(scope)
    await controller.load("p1")
    expect(controller.state.context).toEqual(scope)
    expect(controller.state.input).toBe("")
    expect(controller.state.allowWeb).toBe(false)
  })
  it("refuses a stale editor replacement before submitting approval", async () => {
    await controller.load("p1")
    api.decide = vi.fn()
    controller.state.run = { id: "run", result: { batch: { id: "batch", fingerprint: "hash", status: "pending" }, actions: [{ key: "edit", capability: "writing.revise", arguments: { draft_id: "draft", source_hash: "original" } }] } }
    setBridgeOverrides({ writingFingerprint: async () => "new-unsaved-input" })
    await controller.decide(["edit"])
    expect(api.decide).not.toHaveBeenCalled()
    expect(controller.state.error).toContain("编辑器已有新输入")
  })

  it("reuses a persisted retry receipt when an approval response was lost", async () => {
    await controller.load("p1")
    const result = { batch: { id: "batch", fingerprint: "hash", status: "partial", selected: ["todo"] }, actions: [{ key: "todo", capability: "project.add_task" }] }
    controller.state.run = { id: "run", result }
    api.decide = vi.fn().mockRejectedValueOnce(new Error("response lost")).mockResolvedValue({ status: "completed", results: [] })
    api.run.mockResolvedValue({ id: "run", result: { ...result, batch: { ...result.batch, status: "completed" } } })
    await controller.decide(["todo"], true)
    const receipt = api.decide.mock.calls[0][1].retry_operation_id
    expect(receipt).toBeTruthy()
    controller.dispose()
    controller = createProjectAssistant()
    api.session.mockResolvedValue({ session: { id: "p1-s" }, messages: [], message_total: 0, latest_run: { id: "run", result } })
    await controller.load("p1")
    await controller.decide(["todo"], true)
    expect(api.decide.mock.calls[1][1].retry_operation_id).toBe(receipt)
  })

  it("keeps the initial message and context while creating the first discussion", async () => {
    api.sessions.mockResolvedValue({ items: [], total: 0 })
    await controller.load("p1")
    controller.setInput("核对这一章")
    await controller.send({ page: "writing", chapter_index: 2 })
    expect(api.submit).toHaveBeenCalledWith("p1-new", expect.objectContaining({ message: "核对这一章", context: { page: "writing", chapter_index: 2 } }))
    expect(controller.state.input).toBe("")
    expect(controller.state.run.status).toBe("pending")
  })

  it("does not let a late submission overwrite another project's draft", async () => {
    const response = pending()
    api.submit.mockImplementation(() => response.promise)
    await controller.load("p1")
    controller.setInput("旧作品的问题")
    const sending = controller.send({ page: "today" })
    await flushPromises()
    const body = api.submit.mock.calls[0][1]
    state.currentProjectId = "p2"
    await controller.load("p2")
    controller.setInput("新作品的未提交内容")
    response.resolve(run(body))
    await sending
    expect(controller.state.input).toBe("新作品的未提交内容")
    expect(controller.state.run).toBeNull()
    expect(mocks.adopt).toHaveBeenLastCalledWith(expect.objectContaining({ id: body.operation_id }), expect.anything(), "p1")
  })

  it("keeps edits entered while acknowledgement is pending", async () => {
    const response = pending()
    api.submit.mockImplementation(() => response.promise)
    await controller.load("p1")
    controller.setInput("第一条")
    const sending = controller.send({ page: "today" })
    await flushPromises()
    const body = api.submit.mock.calls[0][1]
    controller.setInput("下一条还未发送")
    response.resolve(run(body))
    await sending
    expect(controller.state.input).toBe("下一条还未发送")
  })

  it("recovers an unknown submission without sending a changed message under its ID", async () => {
    api.submit.mockRejectedValueOnce(new Error("网络中断"))
    await controller.load("p1")
    controller.setInput("原请求")
    await controller.send({ page: "today" })
    const body = api.submit.mock.calls[0][1]
    controller.setInput("新的请求")
    await controller.send({ page: "world" })
    expect(api.submit).toHaveBeenCalledTimes(1)
    await controller.recoverSubmission()
    expect(api.run).toHaveBeenCalledWith("p1", body.operation_id)
    expect(api.submit).toHaveBeenCalledTimes(1)
    expect(controller.state.input).toBe("新的请求")
    expect(controller.state.pendingSubmission).toBe(false)
  })

  it("does not resurrect a previous account's backup after a late response", async () => {
    const response = pending()
    api.submit.mockImplementation(() => response.promise)
    await controller.load("p1")
    controller.setInput("私有讨论")
    const sending = controller.send({ page: "today" })
    await flushPromises()
    const body = api.submit.mock.calls[0][1]
    invalidateAccountBrowserState()
    response.resolve(run(body))
    await sending
    expect(controller.state.messages).toEqual([])
    expect(controller.state.input).toBe("")
    expect(Object.keys(localStorage).filter(key => key.startsWith("novel_assistant"))).toEqual([])
    expect(mocks.adopt).not.toHaveBeenCalled()
  })

  it("loads older discussion pages without dropping recent messages", async () => {
    const rows = Array.from({ length: 120 }, (_, index) => ({ id: `m${index}`, role: "author", content: String(index), created_at: String(index).padStart(3, "0") }))
    api.session.mockResolvedValue({ session: { id: "p1-s", title: "讨论" }, messages: rows.slice(80), message_total: 120, latest_run: null })
    api.messages.mockImplementation(async (_project, _session, { skip, limit }) => ({ items: rows.slice(skip, skip + limit), total: 120 }))
    await controller.load("p1")
    await controller.moreMessages()
    expect(api.messages).toHaveBeenCalledWith("p1", "p1-s", { skip: 50, limit: 30 })
    expect(controller.state.messages).toHaveLength(70)
    expect(controller.state.messages.at(-1).id).toBe("m119")
  })
})

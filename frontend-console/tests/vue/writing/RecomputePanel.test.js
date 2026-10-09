import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { clearRecomputeReceiptsForTests, normalizeInvalidationNotice } from "../../../vue/views/writing/invalidationModel.js"
import RecomputePanel from "../../../vue/views/writing/components/RecomputePanel.vue"

function deferred() {
  let resolve
  let reject
  const promise = new Promise((next, fail) => { resolve = next; reject = fail })
  return { promise, resolve, reject }
}

function notice(overrides = {}) {
  return normalizeInvalidationNotice({
    chapter_index: 3,
    affected: [
      { consumer: "story_scene_checkpoint", scene_index: 4, reason: "anchored_chapter_edited", basis: "known", note: "命中登记" },
      { consumer: "story_scene_checkpoint", scene_index: 5, reason: "conservative_expansion_unregistered", basis: "unknown" },
    ],
    unknown_scope: true,
    receipt_id: "receipt-abc",
    invalidated: [{ consumer: "evidence_chapter_index", label: "章节证据索引" }],
    unsupported: [{ consumer: "world_knowledge" }],
    coverage_note: "细粒度依赖登记后可收窄",
    recompute_options: [
      { kind: "reload_evidence" },
      { kind: "rebuild_derived_state" },
      { kind: "regenerate_prose" },
    ],
    ...overrides,
  }, { chapterIndex: 3 })
}

function previewResponse({ scope = "reload_evidence", targets }) {
  return {
    novel_id: "p1",
    operation_id: "op",
    request_hash: "hash",
    scope,
    targets: targets || (scope === "rebuild_derived_state" ? [{ scene_index: 4 }, { scene_index: 5 }] : [{ chapter_index: 3 }]),
    cost: `成本说明（${scope}）`,
    write_effect: "写入效果说明",
    covers: ["evidence_chapter_index"],
    executable: scope !== "regenerate_prose",
    actions: [
      { action: scope, chapter_index: 3, detail: "以当前工作稿重新读取第 3 章证据并重建章索引" },
    ],
    affected: [],
    baseline_receipt_digest: "receipt-abc",
    source_digest: "digest-v1",
    source_state: {
      chapters: {
        3: { draft_id: "d1", version_number: 4, content_hash: "f".repeat(64) },
      },
    },
    domain_write_performed: false,
  }
}

function evolutionApi(overrides = {}) {
  return {
    recomputePreview: vi.fn(async (_novelId, payload) => previewResponse({ scope: payload.scope })),
    recomputeExecute: vi.fn(async () => ({
      operation_id: "op",
      scope: "reload_evidence",
      confirmed: true,
      domain_write_performed: true,
      results: { "chapter:3": { action: "reload_evidence" } },
    })),
    recomputeReceipts: vi.fn(async (novelId) => ({ novel_id: novelId, items: [] })),
    ...overrides,
  }
}

async function chooseScopeAndPreview(wrapper, label) {
  const radio = wrapper.findAll("input[type=radio]").find((node) => {
    const value = node.element.value
    const choice = { reload_evidence: "重读证据", rebuild_derived_state: "重建派生状态", regenerate_prose: "重生成正文" }[value]
    return choice === label
  })
  await radio.setValue(true)
  await wrapper.findAll("button").find((node) => node.text() === "预览这次重算").trigger("click")
  await Promise.resolve()
}

describe("RecomputePanel", () => {
  beforeEach(() => {
    setBridgeOverrides({})
    clearRecomputeReceiptsForTests()
  })
  afterEach(() => {
    resetBridgeOverrides()
    vi.restoreAllMocks()
    clearRecomputeReceiptsForTests()
  })

  it("渲染受影响列表：场景 + 原因 + 已知/待核实徽章与缺口可见性", () => {
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    const badges = wrapper.findAll(".writing-recompute-panel__badge")
    expect(badges.map((badge) => badge.text())).toEqual(["已知", "待核实"])
    expect(wrapper.text()).toContain("场景 4 · 场景状态存档")
    expect(wrapper.text()).toContain("依赖的这一章被修改")
    expect(wrapper.text()).toContain("依赖未登记，按保守方式标记")
    expect(wrapper.text()).toContain("已标记失效：章节证据索引")
    expect(wrapper.text()).toContain("尚未接入依赖登记、无法自动核对：世界书理解")
    expect(wrapper.text()).toContain("部分影响范围待核实")
  })

  it("三分类单选各带成本与效果说明；未选时不能预览", async () => {
    const api = evolutionApi()
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    const previewButton = () => wrapper.findAll("button").find((node) => node.text() === "预览这次重算")
    expect(previewButton().attributes("disabled")).toBeDefined()

    const labels = wrapper.findAll(".writing-recompute-panel__scope strong").map((node) => node.text())
    expect(labels).toEqual(["重读证据", "重建派生状态", "重生成正文"])
    expect(wrapper.text()).toContain("成本低：只重新读取证据和章节索引")
    expect(wrapper.text()).toContain("会产生新草稿版本，须经你确认采用")

    await chooseScopeAndPreview(wrapper, "重读证据")

    expect(api.recomputePreview).toHaveBeenCalledTimes(1)
    expect(api.recomputePreview).toHaveBeenCalledWith("p1", {
      novel_id: "p1",
      operation_id: expect.any(String),
      scope: "reload_evidence",
      targets: [{ chapter_index: 3 }],
      baseline_receipt_digest: "receipt-abc",
    })
    const preview = wrapper.get(".writing-recompute-panel__preview")
    expect(preview.text()).toContain("成本说明（reload_evidence）")
    expect(preview.text()).toContain("以当前工作稿重新读取第 3 章证据")
    expect(preview.text()).toContain("不会改动任何内容")
  })

  it("rebuild_derived_state 的预览目标为受影响场景", async () => {
    const api = evolutionApi()
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重建派生状态")

    expect(api.recomputePreview).toHaveBeenCalledWith("p1", expect.objectContaining({
      scope: "rebuild_derived_state",
      targets: [{ scene_index: 4 }, { scene_index: 5 }],
    }))
  })

  it("预览失败给出作者语言错误与重试入口", async () => {
    const api = evolutionApi({
      recomputePreview: vi.fn(async () => { throw new Error("服务暂不可用") }),
    })
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重读证据")

    expect(wrapper.get(".writing-recompute-panel__state.is-error").text()).toContain("服务暂不可用")
    expect(wrapper.find(".writing-recompute-panel__preview").exists()).toBe(false)

    api.recomputePreview.mockImplementation(async (_novelId, payload) => previewResponse({ scope: payload.scope }))
    await wrapper.findAll("button").find((node) => node.text() === "重试预览").trigger("click")
    await Promise.resolve()

    expect(wrapper.get(".writing-recompute-panel__preview").text()).toContain("重读证据")
  })

  it("regenerate_prose 预览 executable=false：执行禁用并显示额度说明，不调用 adopt", async () => {
    const api = evolutionApi()
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重生成正文")

    const preview = wrapper.get(".writing-recompute-panel__preview")
    expect(preview.text()).toContain("需要你的明确确认与生成额度，当前不可自动执行")
    const adopt = wrapper.findAll("button").find((node) => node.text().startsWith("按预览执行"))
    expect(adopt.attributes("disabled")).toBeDefined()
    expect(api.recomputeExecute).not.toHaveBeenCalled()
  })

  it("采用走 adopt 端点：路径带 operation_id、体带 confirmed 与预览来源指纹", async () => {
    const api = evolutionApi()
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重读证据")
    const previewPayload = api.recomputePreview.mock.calls[0][1]
    await wrapper.findAll("button").find((node) => node.text() === "按预览执行重读证据").trigger("click")
    await Promise.resolve()

    expect(api.recomputeExecute).toHaveBeenCalledTimes(1)
    const [novelId, operationId, adoptPayload] = api.recomputeExecute.mock.calls[0]
    expect(novelId).toBe("p1")
    expect(operationId).toBe(previewPayload.operation_id)
    expect(adoptPayload).toEqual({
      novel_id: "p1",
      operation_id: previewPayload.operation_id,
      scope: "reload_evidence",
      targets: [{ chapter_index: 3 }],
      baseline_receipt_digest: "receipt-abc",
      confirmed: true,
      expected_source_digest: "digest-v1",
    })
    expect(wrapper.get(".writing-recompute-panel__outcome").text()).toContain("已提交重读证据（共 1 项）")
  })

  it("编辑器有未保存修改时禁止执行重算并给出指引", async () => {
    const api = evolutionApi()
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice(), editorDirty: true },
    })

    await chooseScopeAndPreview(wrapper, "重读证据")

    expect(wrapper.text()).toContain("先保存当前修改，再执行重算")
    const adopt = wrapper.findAll("button").find((node) => node.text().startsWith("按预览执行"))
    expect(adopt.attributes("disabled")).toBeDefined()
    expect(api.recomputeExecute).not.toHaveBeenCalled()
  })

  it("来源漂移 409：逐章比较预览时与当前版本，可基于当前稿重新预览后成功执行", async () => {
    const driftError = {
      status: 409,
      message: "请求冲突：重算目标章节在预览后已再次修改",
      body: {
        error: "recompute_source_drift",
        detail: "重算目标章节在预览后已再次修改",
        context: {
          expected_source_digest: "digest-v1",
          current_source_digest: "digest-v2",
          keep_current_draft: true,
          current: { 3: { draft_id: "d1", version_number: 5, content_hash: "a".repeat(64) } },
        },
      },
    }
    const execute = vi.fn()
      .mockRejectedValueOnce(driftError)
      .mockResolvedValueOnce({ operation_id: "op", scope: "reload_evidence", confirmed: true, domain_write_performed: true, results: { "chapter:3": {} } })
    const preview = vi.fn()
      .mockResolvedValueOnce(previewResponse({ scope: "reload_evidence" }))
      .mockResolvedValueOnce(previewResponse({ scope: "reload_evidence" }))
    const api = evolutionApi({ recomputePreview: preview, recomputeExecute: execute })
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重读证据")
    await wrapper.findAll("button").find((node) => node.text() === "按预览执行重读证据").trigger("click")
    await Promise.resolve()

    const conflict = wrapper.get(".writing-recompute-panel__conflict")
    expect(conflict.text()).toContain("重算依据的内容已经变化")
    expect(conflict.text()).toContain("第 3 章：预览时第 4 版 → 当前第 5 版")
    expect(conflict.text()).toContain("你的当前稿已原样保留")

    await wrapper.findAll("button").find((node) => node.text() === "基于当前稿重新预览").trigger("click")
    await Promise.resolve()

    expect(api.recomputePreview).toHaveBeenCalledTimes(2)
    expect(wrapper.find(".writing-recompute-panel__conflict").exists()).toBe(false)
    expect(wrapper.find(".writing-recompute-panel__preview").exists()).toBe(true)

    await wrapper.findAll("button").find((node) => node.text() === "按预览执行重读证据").trigger("click")
    await Promise.resolve()

    expect(execute).toHaveBeenCalledTimes(2)
    expect(wrapper.get(".writing-recompute-panel__outcome").text()).toContain("已提交重读证据")
  })

  it("来源漂移后选择保留当前稿：冲突清空、零额外写入", async () => {
    const driftError = {
      status: 409,
      body: {
        error: "recompute_source_drift",
        context: { keep_current_draft: true, current: { 3: { version_number: 5, content_hash: "a".repeat(64) } } },
      },
    }
    const api = evolutionApi({ recomputeExecute: vi.fn(async () => { throw driftError }) })
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重读证据")
    await wrapper.findAll("button").find((node) => node.text() === "按预览执行重读证据").trigger("click")
    await Promise.resolve()
    expect(wrapper.find(".writing-recompute-panel__conflict").exists()).toBe(true)

    await wrapper.findAll("button").find((node) => node.text() === "保留当前稿，暂不重算").trigger("click")

    expect(wrapper.find(".writing-recompute-panel__conflict").exists()).toBe(false)
    expect(api.recomputeExecute).toHaveBeenCalledTimes(1)
    expect(api.recomputePreview).toHaveBeenCalledTimes(1)
  })

  it("scope_unsupported 409 按作者语言失败展示，不进冲突比较", async () => {
    const scopeError = {
      status: 409,
      message: "请求冲突：正文重生成需经既有生成任务的确认与采用流程",
      body: {
        error: "recompute_scope_unsupported",
        detail: "正文重生成需经既有生成任务的确认与采用流程",
        context: { scope: "regenerate_prose", author_choice_only: true },
      },
    }
    const api = evolutionApi({
      recomputeExecute: vi.fn(async () => { throw scopeError }),
    })
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重读证据")
    await wrapper.findAll("button").find((node) => node.text() === "按预览执行重读证据").trigger("click")
    await Promise.resolve()

    expect(wrapper.find(".writing-recompute-panel__conflict").exists()).toBe(false)
    expect(wrapper.get(".writing-recompute-panel__state.is-error").text())
      .toContain("正文重生成需要你的明确确认与生成额度，当前不可自动执行")
  })

  it("执行失败（非冲突）可重试且复用同一幂等键与来源指纹", async () => {
    const execute = vi.fn()
      .mockRejectedValueOnce(new Error("网络中断"))
      .mockResolvedValueOnce({ operation_id: "op", scope: "reload_evidence", confirmed: true, domain_write_performed: true, results: { "chapter:3": {} } })
    const api = evolutionApi({ recomputeExecute: execute })
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重读证据")
    await wrapper.findAll("button").find((node) => node.text() === "按预览执行重读证据").trigger("click")
    await Promise.resolve()
    expect(wrapper.get(".writing-recompute-panel__state.is-error").text()).toContain("网络中断")

    await wrapper.findAll("button").find((node) => node.text() === "重试执行").trigger("click")
    await Promise.resolve()

    expect(execute).toHaveBeenCalledTimes(2)
    expect(execute.mock.calls[0]).toEqual(execute.mock.calls[1])
    expect(wrapper.get(".writing-recompute-panel__outcome").text()).toContain("已提交重读证据")
  })

  it("暂不重算直接关闭面板，零请求零副作用（无服务端取消动作）", async () => {
    const api = evolutionApi()
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await wrapper.findAll("button").find((node) => node.text() === "暂不重算").trigger("click")

    expect(wrapper.emitted("close")).toHaveLength(1)
    expect(api.recomputePreview).not.toHaveBeenCalled()
    expect(api.recomputeExecute).not.toHaveBeenCalled()
    expect(Object.keys(api)).not.toContain("recomputeCancel")
  })

  it("执行进行中禁止离开；完成后恢复", async () => {
    const gate = deferred()
    const api = evolutionApi({ recomputeExecute: vi.fn(() => gate.promise) })
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重读证据")
    expect(wrapper.vm.canLeave()).toBe(true)

    const adopting = wrapper.findAll("button").find((node) => node.text() === "按预览执行重读证据").trigger("click")
    await Promise.resolve()

    expect(wrapper.vm.canLeave()).toBe(false)
    expect(wrapper.get(".writing-recompute-panel__close").attributes("disabled")).toBeDefined()

    gate.resolve({ operation_id: "op", scope: "reload_evidence", confirmed: true, domain_write_performed: true, results: {} })
    await adopting
    await Promise.resolve()

    expect(wrapper.vm.canLeave()).toBe(true)
  })

  it("adopt 后回执即时入列、项目隔离，并随挂载回读服务端留档合并展示", async () => {
    const api = evolutionApi({
      recomputeReceipts: vi.fn(async (novelId) => ({ novel_id: novelId, items: [] })),
    })
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })
    await flushPromises()

    await chooseScopeAndPreview(wrapper, "重读证据")
    await wrapper.findAll("button").find((node) => node.text() === "按预览执行重读证据").trigger("click")
    await Promise.resolve()

    const history = wrapper.get(".writing-recompute-panel__history")
    expect(history.text()).toContain("重读证据 · 已提交 1 项")
    expect(history.text()).toContain("回执在服务端留档")
    expect(history.text()).toContain("不会重复写入")
    expect(api.recomputeReceipts).toHaveBeenCalledWith("p1")

    const other = mount(RecomputePanel, {
      props: { projectId: "p2", chapterIndex: 3, notice: notice() },
    })
    expect(other.get(".writing-recompute-panel__history").text()).toContain("本次写作会话里还没有执行过重算")
  })

  it("服务端回执在挂载后并入历史：跨会话的已完成重算看得到", async () => {
    const api = evolutionApi({
      recomputeReceipts: vi.fn(async () => ({
        novel_id: "p1",
        items: [
          { operation_id: "op-server-1", scope: "rebuild_derived_state", request_hash: "h", handled_count: 3, completed_at: "2026-10-07T12:00:00Z" },
          { operation_id: "op-server-2", scope: "regenerate_prose", request_hash: "h2", handled_count: 0, completed_at: null },
        ],
      })),
    })
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })
    await flushPromises()

    const history = wrapper.get(".writing-recompute-panel__history")
    expect(history.text()).toContain("重建派生状态 · 已处理 3 项")
    // 没有完成时间的回执不编造时刻，仍能列出这一次重算
    expect(history.text()).toContain("重生成正文 · 已处理 0 项")
    expect(history.text()).not.toContain("1970")
  })

  it("回执端点不可用或失败时静默降级为本地会话记录", async () => {
    const api = evolutionApi({ recomputeReceipts: vi.fn(async () => { throw new Error("服务暂不可用") }) })
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })
    await flushPromises()

    await chooseScopeAndPreview(wrapper, "重读证据")
    await wrapper.findAll("button").find((node) => node.text() === "按预览执行重读证据").trigger("click")
    await Promise.resolve()

    expect(wrapper.get(".writing-recompute-panel__history").text()).toContain("重读证据 · 已提交 1 项")
    expect(wrapper.get(".writing-recompute-panel__outcome").text()).toContain("已提交重读证据")
  })

  it("重算能力缺失时给出作者语言失败而非空白", async () => {
    setBridgeOverrides({ api: { evolution: {} } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重读证据")

    expect(wrapper.get(".writing-recompute-panel__state.is-error").text()).toContain("重算功能暂时不可用")
  })

  it("新一轮保存带来新回执时面板复位（旧预览与冲突不残留）", async () => {
    const api = evolutionApi()
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重读证据")
    expect(wrapper.find(".writing-recompute-panel__preview").exists()).toBe(true)

    await wrapper.setProps({ notice: notice({ receipt_id: "receipt-next", chapter_index: 4 }) })

    expect(wrapper.find(".writing-recompute-panel__preview").exists()).toBe(false)
    expect(wrapper.findAll("input[type=radio]").filter((node) => node.element.checked)).toHaveLength(0)
  })

  it("预览在途时新回执到达：忙碌标记归位，旧回复不写预览，可再次预览", async () => {
    const gate = deferred()
    const api = evolutionApi({ recomputePreview: vi.fn(() => gate.promise) })
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重读证据")
    expect(wrapper.findAll("button").map((node) => node.text())).toContain("正在核对…")

    await wrapper.setProps({ notice: notice({ receipt_id: "receipt-next" }) })

    // 复位必须顺带解除忙碌：否则按钮永久禁用、离开守卫永久阻塞
    expect(wrapper.vm.canLeave()).toBe(true)
    expect(wrapper.findAll("button").map((node) => node.text())).not.toContain("正在核对…")

    // 旧回执的预览回复属于过去的选择，落地即等于「预览与执行内容不一致」
    gate.resolve(previewResponse({ scope: "reload_evidence" }))
    await flushPromises()
    expect(wrapper.find(".writing-recompute-panel__preview").exists()).toBe(false)

    const radio = wrapper.findAll("input[type=radio]").find((node) => node.element.value === "rebuild_derived_state")
    await radio.setValue(true)
    const previewButton = wrapper.findAll("button").find((node) => node.text() === "预览这次重算")
    expect(previewButton.attributes("disabled")).toBeUndefined()
  })

  it("切换重算方式会作废在途预览：旧回复不进预览，也不会按旧方式执行", async () => {
    const gate = deferred()
    const execute = vi.fn(async () => ({
      operation_id: "op", scope: "rebuild_derived_state", confirmed: true, domain_write_performed: true, results: {},
    }))
    const api = evolutionApi({ recomputePreview: vi.fn(() => gate.promise), recomputeExecute: execute })
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重读证据")
    const radio = wrapper.findAll("input[type=radio]").find((node) => node.element.value === "rebuild_derived_state")
    await radio.setValue(true)

    gate.resolve(previewResponse({ scope: "reload_evidence" }))
    await flushPromises()

    expect(wrapper.find(".writing-recompute-panel__preview").exists()).toBe(false)
    const adopt = wrapper.findAll("button").find((node) => node.text().startsWith("按预览执行"))
    expect(adopt).toBeUndefined()
    expect(execute).not.toHaveBeenCalled()
  })

  it("执行按预览快照发出：预览过的方式就是真正执行的方式", async () => {
    const api = evolutionApi()
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重建派生状态")
    const previewPayload = api.recomputePreview.mock.calls[0][1]
    await wrapper.findAll("button").find((node) => node.text() === "按预览执行重建派生状态").trigger("click")
    await Promise.resolve()

    const [, operationId, adoptPayload] = api.recomputeExecute.mock.calls[0]
    expect(operationId).toBe(previewPayload.operation_id)
    expect(adoptPayload.scope).toBe("rebuild_derived_state")
    expect(adoptPayload.targets).toEqual([{ scene_index: 4 }, { scene_index: 5 }])
  })

  it("执行途中新回执到达：执行完成前保持忙碌，已发出的重算仍留回执与结果", async () => {
    const gate = deferred()
    const api = evolutionApi({ recomputeExecute: vi.fn(() => gate.promise) })
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })

    await chooseScopeAndPreview(wrapper, "重读证据")
    const adopting = wrapper.findAll("button").find((node) => node.text() === "按预览执行重读证据").trigger("click")
    await Promise.resolve()
    expect(wrapper.vm.canLeave()).toBe(false)

    await wrapper.setProps({ notice: notice({ receipt_id: "receipt-next" }) })
    expect(wrapper.vm.canLeave()).toBe(false)
    expect(wrapper.get(".writing-recompute-panel__close").attributes("disabled")).toBeDefined()

    gate.resolve({
      operation_id: "op", scope: "reload_evidence", confirmed: true, domain_write_performed: true, results: { "chapter:3": {} },
    })
    await adopting
    await flushPromises()

    expect(wrapper.vm.canLeave()).toBe(true)
    expect(wrapper.find(".writing-recompute-panel__outcome").exists()).toBe(false)
    expect(wrapper.get(".writing-recompute-panel__history").text()).toContain("重读证据 · 已提交 1 项")
  })
  it("执行在途时新提示不能解锁重复执行，旧成功只记入原项目回执", async () => {
    const gate = deferred()
    const api = evolutionApi({ recomputeExecute: vi.fn(() => gate.promise) })
    setBridgeOverrides({ api: { evolution: api } })
    const wrapper = mount(RecomputePanel, {
      props: { projectId: "p1", chapterIndex: 3, notice: notice() },
    })
    await chooseScopeAndPreview(wrapper, "重读证据")
    await wrapper.findAll("button").find((node) => node.text().startsWith("按预览执行")).trigger("click")
    expect(wrapper.vm.canLeave()).toBe(false)
    await wrapper.setProps({ projectId: "p2", notice: notice({ receipt_id: "new" }) })
    expect(wrapper.vm.canLeave()).toBe(false)
    expect(wrapper.findAll("input[type=radio]").every((node) => node.element.disabled)).toBe(true)
    gate.resolve({ operation_id: "old", scope: "reload_evidence", results: { "chapter:3": {} } })
    await flushPromises()
    expect(wrapper.vm.canLeave()).toBe(true)
    expect(wrapper.find(".writing-recompute-panel__outcome").exists()).toBe(false)
    expect(api.recomputeExecute).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).not.toContain("已提交 1 项")
  })

})

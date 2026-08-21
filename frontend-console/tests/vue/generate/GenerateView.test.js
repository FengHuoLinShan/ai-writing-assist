import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"

const confirmAiReference = vi.hoisted(() => vi.fn())
vi.mock("../../../shared/aiReferenceModal.js", () => ({ confirmAiReference }))
vi.mock("../../../shared/referencePicker.js", () => ({
  createReferencePicker: vi.fn(() => ({ destroy: vi.fn(), resolve: vi.fn(async () => []), setItems: vi.fn() })),
}))

import GenerateView from "../../../vue/views/generate/GenerateView.vue"
import {
  emptyGenerateSession,
  generateSessionKey,
  readCreativeContinuation,
  readGenerateSession,
  writeCreativeContinuation,
  writeGenerateSession,
  writeGenerateContextPreview,
} from "../../../vue/views/generate/generateSession.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)

let api
let state
let router
let toast
let showModalHtml

function baseProps(overrides = {}) {
  return {
    projectId: "p1", tab: "world", preset: "custom", sourcePageId: null, targetKind: "core_entity",
    sessionKey: generateSessionKey("p1"), initialSession: emptyGenerateSession(),
    templates: [{ id: "builtin:none", value: "builtin:none", label: "不带模板", prompt: "自由", object_template: "none", is_builtin: true, version_number: 1 }],
    activationProfiles: [], sourcePage: null, sourceDraft: null, worldCategories: [{ category_key: "custom", name: "自定义", status: "active" }],
    worldPageTemplates: [], worldScenes: [], worldThreads: [], worldCharacters: [], worldEntities: [], worldWorkspaceWarning: null,
    restoredWorldResult: null, povChapters: [], povCharacters: [], povLoadWarning: null,
    ...overrides,
  }
}

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

function convergenceResponse({ complete = true, excluded = 0 } = {}) {
  return {
    coverage: {
      scope_label: "最近 2 条对话、相关项目背景",
      source_count: 2,
      covered_source_keys: complete ? ["m1", "m2"] : ["m1"],
      missing_source_keys: complete ? [] : ["m2"],
      stale_source_keys: [],
      excluded_message_count: excluded,
      manifest_hash: "a".repeat(64),
      complete,
      issues: complete ? [] : ["缺少一个来源块"],
    },
    manifest: [
      { key: "m1", kind: "conversation", label: "对话第 1 条 · 你", content_hash: "1".repeat(64), source_ref: { source_type: "author_message", title: "对话第 1 条 · 你" } },
      { key: "m2", kind: "conversation", label: "对话第 2 条 · AI", content_hash: "2".repeat(64), source_ref: { source_type: "author_message", title: "对话第 2 条 · AI" } },
    ],
    detail_summary: { before_grouping: 84, after_deduplication: 10, retained_in_sources: 8 },
    decision_cards: [{
      card_id: "C1",
      title: "制度骨架与精度边界",
      common_ground: ["保留制度运行方式"],
      items: [
        { item_id: "C1I1", text: "保留税制骨架", suggested_disposition: "include" },
        { item_id: "C1I2", text: "具体税率继续留白", suggested_disposition: "open" },
      ],
      dependencies: ["后续人物选择会受税制影响"],
      affected_targets: ["current_world_target", "outline"],
      source_keys: ["m1", "m2"],
      why_now: "继续增加组织前需要先决定制度边界。",
    }],
    next_boundary: "只有新材料会改变人物选择时再横向扩展。",
    source_snapshot: { kind: "project" },
  }
}

function worldCoreResponse() {
  const response = convergenceResponse()
  response.manifest[0].source_ref.source_hash = "1".repeat(64)
  response.manifest[1].source_ref = { source_type: "assistant_message", source_hash: "2".repeat(64), title: "对话第 2 条 · AI" }
  response.decision_cards[0].items = ["tide", "cost", "failure", "maintenance"].map((key, index) => ({
    item_id: `C1I${index + 1}`,
    text: ["潮门通行", "维护配额", "断供边界", "每日校准"][index],
    suggested_disposition: index === 2 ? "discard" : "include",
    world_core_rule_key: key,
  }))
  response.world_core = {
    ready_for_handoff: true,
    issues: [],
    author_seed_source_keys: ["m1"],
    rule_count: 4,
    snapshot: {
      author_seeds: [{ source_key: "m1", disposition: "included" }],
      rule_atoms: ["tide", "cost", "failure", "maintenance"].map((key, index) => ({
        rule_key: key,
        title: ["潮门通行", "维护配额", "断供边界", "每日校准"][index],
        source_keys: ["m1"],
        can: "按潮窗通行",
        cannot: "逆潮连续通行",
        cost: "消耗配额",
        failure: "街区断供",
        maintenance: "每日校准",
      })),
      blocking_contradictions: [],
      vertical_slice: { rule_key: "tide", daily_consequence: "居民按潮通勤", failure_consequence: "故障后断供" },
    },
  }
  return response
}

function explorationResponse() {
  const evidence = [{ key: "source-page:1", kind: "source_page", label: "世界背景", content_hash: "3".repeat(64), source_ref: { source_type: "world_bible_page", page_id: "page-1", title: "世界背景" } }]
  return {
    depth: 1,
    request_fingerprint: "f".repeat(64),
    targets: ["边境道路", "地方税契", "夜航邮驿"].map((title, index) => ({
      item_id: `E${index + 1}`,
      title,
      gap: `${title}尚未说明如何受当前制度约束。`,
      why_it_matters: "会改变普通人的移动与资源选择。",
      author_boundary: "具体执行者和代价仍由作者决定。",
      reverse_check_focus: "来源页是否需要补充这条制度后果。",
      source_keys: ["source-page:1"],
      evidence,
    })),
    stop_reason: "本次只到一个相邻世界书页，不继续下一跳。",
    source_snapshot: { kind: "world_bible_page", page_id: "page-1", page_version: 1 },
  }
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  writeGenerateContextPreview("p1", {})
  document.body.innerHTML = '<div id="topbar-module"></div><div id="modal-body"></div>'
  const worldTaskResults = new Map()
  const generateWorldSuggestion = vi.fn()
  const enqueueWorldSuggestion = vi.fn(async (payload) => {
    const { operation_id: operationId, ...request } = payload
    const result = await generateWorldSuggestion(request, { signal: new AbortController().signal })
    worldTaskResults.set(operationId, result)
    return { task_id: operationId, status: "pending" }
  })
  api = {
    generate: {
      worldChat: vi.fn(), convergeWorld: vi.fn(), exploreWorld: vi.fn(), generateWorldSuggestion, enqueueWorldSuggestion, applyWorldPageDraft: vi.fn(),
      listPromptTemplates: vi.fn(), createPromptTemplate: vi.fn(), copyPromptTemplate: vi.fn(), updatePromptTemplate: vi.fn(), listPromptTemplateRevisions: vi.fn(),
    },
    context: { compile: vi.fn(), render: vi.fn() },
    world: {
      listBiblePages: vi.fn(), listBibleDrafts: vi.fn(), listBibleCategories: vi.fn(), listBiblePageTemplates: vi.fn(), listCharacters: vi.fn(), listEntities: vi.fn(), getEntity: vi.fn(),
      saveCoreCheckpoint: vi.fn(),
    },
    outline: { listScenesOrdered: vi.fn(), listThreads: vi.fn(), listScenesByChapter: vi.fn(), getSceneWorkbench: vi.fn(), getScene: vi.fn() },
    writing: { listChapters: vi.fn(), get: vi.fn(), getDraft: vi.fn(), generate: vi.fn() },
    tasks: {
      get: vi.fn(async (taskId) => worldTaskResults.has(taskId)
        ? { task_id: taskId, task_type: "world_generation_suggestion", status: "done", result: worldTaskResults.get(taskId) }
        : { task_id: taskId, status: "pending", progress: 0 }),
      cancel: vi.fn(),
    },
  }
  state = { currentProjectId: "p1", currentProject: { title: "项目一" }, viewStates: {} }
  router = { navigate: vi.fn(), getCurrentQuery: vi.fn(() => new URLSearchParams()) }
  toast = vi.fn()
  showModalHtml = vi.fn((title, body) => { document.getElementById("modal-body").innerHTML = body })
  setBridgeOverrides({ api, state, router, toast, confirm: vi.fn(() => true), showModalHtml, closeModal: vi.fn(), esc: globalThis.esc })
  confirmAiReference.mockReset()
})

afterEach(() => resetBridgeOverrides())

describe("GenerateView Vue behavior matrix", () => {
  it("restores unsent composer text inside the bounded session without starting a request", async () => {
    const key = generateSessionKey("p1", null, "core_entity")
    const first = mount(GenerateView, { props: baseProps({ sessionKey: key }), attachTo: document.body })
    await first.get("#generate-chat-input").setValue("尚未发送的白堤校验说明")
    await flushPromises()

    expect(readGenerateSession(key).composer).toBe("尚未发送的白堤校验说明")
    expect(readCreativeContinuation("p1")).toMatchObject({
      destination: "generate",
      route: { source_page_id: null, target: "core_entity" },
    })
    expect(api.generate.worldChat).not.toHaveBeenCalled()
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()

    first.unmount()
    const second = mount(GenerateView, {
      props: baseProps({ sessionKey: key, initialSession: readGenerateSession(key) }),
      attachTo: document.body,
    })
    expect(second.get("#generate-chat-input").element.value).toBe("尚未发送的白堤校验说明")
    expect(api.generate.worldChat).not.toHaveBeenCalled()
  })

  it("invalidates the continuation when unsent input exceeds the existing session bound", async () => {
    const key = generateSessionKey("p1", null, "core_entity")
    writeGenerateSession(key, { composer: "原快照", messages: [] })
    writeCreativeContinuation("p1", {
      destination: "generate",
      route: { source_page_id: null, target: "core_entity" },
    })
    const wrapper = mount(GenerateView, {
      props: baseProps({ sessionKey: key, initialSession: readGenerateSession(key) }),
      attachTo: document.body,
    })

    await wrapper.get("#generate-chat-input").setValue("界".repeat(180_000))
    await flushPromises()

    expect(readCreativeContinuation("p1")).toBeNull()
    expect(readGenerateSession(key).composer).toBe("原快照")
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("512 KiB"), "warning")
  })

  it("renders the world workspace without v-html and completes chat", async () => {
    api.generate.worldChat.mockResolvedValue({ reply: "旧友型反派", context_usage: { revision_id: "r-chat" } })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get("#generate-chat-input").setValue("帮我设计反派")
    await wrapper.get('[data-action="send-chat-message"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get("#generate-chat-messages").text()).toContain("旧友型反派"))
    expect(api.generate.worldChat).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p1", messages: [{ role: "user", content: "帮我设计反派" }] }), expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.html()).not.toContain("v-html")
  })

  it("runs bounded World Core rounds and never saves from a shortcut or the third reply", async () => {
    api.generate.worldChat.mockResolvedValue({ reply: "只生长当前一层。" })
    const key = generateSessionKey("p1", null, "core_entity", "world_core")
    const wrapper = mount(GenerateView, { props: baseProps({ preset: "world_core", sessionKey: key }), attachTo: document.body })

    await wrapper.get('[data-action="world-core-pressure"]').trigger("click")
    expect(wrapper.get("#generate-chat-input").element.value).toContain("压力测试")
    expect(api.generate.worldChat).not.toHaveBeenCalled()
    for (let round = 0; round < 3; round += 1) {
      if (round) await wrapper.get("#generate-chat-input").setValue(`第 ${round + 1} 轮`)
      await wrapper.get('[data-action="send-chat-message"]').trigger("click")
      await flushPromises()
      await vi.waitFor(() => expect(api.generate.worldChat).toHaveBeenCalledTimes(round + 1))
    }

    expect(api.generate.worldChat.mock.calls[0][0]).toMatchObject({
      workflow_preset: "world_core",
      target: { kind: "core_entity", template: "none" },
    })
    expect(wrapper.get("[data-action='save-world-core-checkpoint']").element.disabled).toBe(true)
    expect(wrapper.text()).toContain("未保存前只保证在当前浏览器恢复")
    expect(api.world.saveCoreCheckpoint).not.toHaveBeenCalled()
    expect(readGenerateSession(key).successfulRounds).toBe(3)
    expect(wrapper.find('[data-action="generate-world-suggestion"]').exists()).toBe(false)
  })

  it("saves a ready World Core checkpoint only after explicit confirmation", async () => {
    api.generate.convergeWorld.mockResolvedValue(worldCoreResponse())
    api.world.saveCoreCheckpoint.mockResolvedValue({ id: "checkpoint-1" })
    const key = generateSessionKey("p1", null, "core_entity", "world_core")
    const initialSession = { ...emptyGenerateSession(), successfulRounds: 3, messages: [{ role: "user", content: "潮汐改变城市通行" }] }
    const wrapper = mount(GenerateView, { props: baseProps({ preset: "world_core", sessionKey: key, initialSession }), attachTo: document.body })

    await wrapper.get('[data-action="converge-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.text()).toContain("世界核心已通过交接门"))
    expect(api.generate.convergeWorld.mock.calls[0][0]).toMatchObject({ workflow_preset: "world_core" })
    expect(wrapper.findAll(".generate-convergence-items select")[2].element.value).toBe("rejected")
    expect(api.world.saveCoreCheckpoint).not.toHaveBeenCalled()

    await wrapper.get('[data-action="save-world-core-checkpoint"]').trigger("click")
    await vi.waitFor(() => expect(api.world.saveCoreCheckpoint).toHaveBeenCalledTimes(1))

    expect(api.world.saveCoreCheckpoint.mock.calls[0][0]).toMatchObject({
      novel_id: "p1",
      checkpoint: {
        schema_version: "world_core_checkpoint.v1",
        round_no: 3,
        action: "consolidate",
        source_manifest_hash: "a".repeat(64),
        decisions: expect.arrayContaining([expect.objectContaining({ disposition: "rejected", rule_key: "failure" })]),
      },
    })
    expect(readGenerateSession(key).checkpointId).toBe("checkpoint-1")
    expect(readCreativeContinuation("p1")).toMatchObject({ route: { preset: "world_core", checkpoint_id: "checkpoint-1" } })
  })

  it("uses readable fallbacks instead of raw IDs or object enums in exact-context choices", () => {
    const wrapper = mount(GenerateView, { props: baseProps({
      worldThreads: [{ id: "internal-thread-id" }],
      worldCharacters: [{ entity_id: "internal-character-id" }],
      worldEntities: [{ id: "internal-entity-id", entity_type: "location" }],
    }), attachTo: document.body })

    expect(wrapper.get("#generate-world-threads option").text()).toBe("未命名剧情线")
    expect(wrapper.get("#generate-world-characters option").text()).toBe("未命名人物")
    expect(wrapper.get("#generate-world-entities option").text()).toBe("未命名世界对象")
  })

  it("keeps a source-bound workspace read-only when lazy baseline loading fails", async () => {
    api.world.listBiblePages.mockRejectedValue(new Error("页面列表暂时不可用"))
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const initialSession = { ...emptyGenerateSession(), composer: "保留的未发送内容" }
    writeCreativeContinuation("p1", {
      destination: "generate",
      route: { source_page_id: "page-1", target: "world_bible_page" },
    })
    const wrapper = mount(GenerateView, { props: baseProps({
      tab: "task",
      sourcePageId: "page-1",
      targetKind: "world_bible_page",
      sessionKey: key,
      initialSession,
    }), attachTo: document.body })

    await wrapper.get('[data-subtab="world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.text()).toContain("原来源与生成上下文暂时无法核对"))

    expect(wrapper.get("#generate-chat-input").element.value).toBe("保留的未发送内容")
    expect(wrapper.get('[data-action="generate-world-suggestion"]').element.disabled).toBe(true)
    expect(readCreativeContinuation("p1")).toMatchObject({
      destination: "generate",
      route: { source_page_id: "page-1", target: "world_bible_page" },
    })
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()
  })

  it("converges the visible range without writes and turns choices into an editable author message", async () => {
    api.generate.convergeWorld.mockResolvedValue(convergenceResponse())
    const initialSession = {
      ...emptyGenerateSession(),
      messages: [
        { role: "user", content: "保留制度骨架" },
        { role: "assistant", content: "建议确定三成税率" },
      ],
    }
    const key = generateSessionKey("p1")
    const wrapper = mount(GenerateView, { props: baseProps({ sessionKey: key, initialSession }), attachTo: document.body })

    await wrapper.get('[data-action="converge-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get('[data-section="convergence-preview"]').text()).toContain("制度骨架与精度边界"))

    expect(api.generate.convergeWorld).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      messages: initialSession.messages,
      excluded_message_count: 0,
    }), expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(api.generate.worldChat).not.toHaveBeenCalled()
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()
    expect(wrapper.get('[data-section="convergence-preview"]').text()).toContain("84")
    expect(wrapper.get('[data-section="convergence-preview"]').text()).toContain("故事结构")
    expect(wrapper.get('[data-section="convergence-preview"]').text()).toContain("核心前提、叙事读法、基调与读者承诺")
    await wrapper.get('[data-action="open-story-outline"]').trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("outline", "story-outline")

    const choices = wrapper.findAll(".generate-convergence-items select")
    await choices[1].setValue("discard")
    expect(wrapper.get(".generate-convergence-message textarea").element.value).toContain("明确放弃")
    expect(wrapper.get(".generate-convergence-message textarea").element.value).toContain("具体税率继续留白")
    await wrapper.get(".generate-convergence-message textarea").setValue("作者改写后的决定消息")
    await wrapper.get('[data-action="apply-convergence-message"]').trigger("click")
    await flushPromises()

    expect(wrapper.find('[data-section="convergence-preview"]').exists()).toBe(false)
    expect(wrapper.get("#generate-chat-messages").text()).toContain("作者改写后的决定消息")
    expect(readGenerateSession(key).messages.at(-1)).toEqual({ role: "user", content: "作者改写后的决定消息" })
    expect(api.generate.worldChat).not.toHaveBeenCalled()
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()
  })

  it("opens map facts in the canonical Map workspace", async () => {
    const response = convergenceResponse()
    response.manifest[0] = {
      ...response.manifest[0],
      label: "白堤港口仍被封锁",
      source_ref: { source_type: "map_fact", source_id: "fact-1", title: "白堤港口仍被封锁" },
    }
    api.generate.convergeWorld.mockResolvedValue(response)
    const wrapper = mount(GenerateView, {
      props: baseProps({ initialSession: { ...emptyGenerateSession(), messages: [{ role: "user", content: "整理地图事实" }] } }),
      attachTo: document.body,
    })

    await wrapper.get('[data-action="converge-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.text()).toContain("白堤港口仍被封锁"))
    const sourceButton = wrapper.findAll(".generate-convergence-sources button").find((button) => button.text().includes("白堤港口仍被封锁"))
    await sourceButton.trigger("click")

    expect(router.navigate).toHaveBeenCalledWith("map", null, true)
  })

  it("adds only author-selected related World Bible pages to the existing convergence request", async () => {
    api.generate.convergeWorld.mockResolvedValue(convergenceResponse())
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const initialSession = { ...emptyGenerateSession(), messages: [{ role: "user", content: "把分散候选收束成一次决定" }] }
    const wrapper = mount(GenerateView, {
      props: baseProps({
        sourcePageId: "page-1",
        targetKind: "world_bible_page",
        sessionKey: key,
        initialSession,
        sourcePage: { id: "page-1", title: "当前页", version_number: 1 },
        worldPages: [
          { id: "page-1", title: "当前页", status: "canonical" },
          { id: "page-2", title: "候选集 A", status: "canonical" },
          { id: "page-3", title: "候选集 B", status: "confirmed" },
        ],
      }),
      attachTo: document.body,
    })

    expect(wrapper.get("#generate-world-pages").text()).not.toContain("当前页")
    await wrapper.get("#generate-world-pages").setValue(["page-2", "page-3"])
    await wrapper.get('[data-action="converge-world"]').trigger("click")
    await vi.waitFor(() => expect(api.generate.convergeWorld).toHaveBeenCalledTimes(1))

    expect(api.generate.convergeWorld.mock.calls[0][0].selected_asset_refs).toEqual([
      { type: "world_bible_page", id: "page-2" },
      { type: "world_bible_page", id: "page-3" },
    ])
    expect(readGenerateSession(key).selectedWorldPageIds).toEqual(["page-2", "page-3"])
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()
  })

  it("previews three adjacent gaps but sends only the author-selected one", async () => {
    api.generate.exploreWorld.mockResolvedValue(explorationResponse())
    api.generate.generateWorldSuggestion.mockResolvedValue({
      result: {
        kind: "world_bible_new_page",
        suggestion: { id: "suggestion-new", status: "pending" },
        proposal: { operation: "create_new", page: { title: "地方税契", page_type: "custom", free_text: "地方以税契约束道路。", sections_json: [], linked_asset_refs_json: [] }, review_notes: [] },
      },
      source_revision: {
        kind: "world_bible_page",
        suggestion: { id: "suggestion-source", status: "pending" },
        proposal: { operation: "replace_existing", target_page_id: "page-1", page: { title: "世界背景", page_type: "background", free_text: "补充税契后果。", sections_json: [], linked_asset_refs_json: [] } },
      },
    })
    const initialSession = { ...emptyGenerateSession(), messages: [{ role: "user", content: "只探索会改变人物选择的相邻缺口" }] }
    const wrapper = mount(GenerateView, {
      props: baseProps({
        targetKind: "world_bible_new_page",
        sourcePageId: "page-1",
        sourcePage: { id: "page-1", title: "世界背景", page_type: "background", version_number: 1, sections_json: [] },
        sessionKey: generateSessionKey("p1", "page-1", "world_bible_new_page"),
        initialSession,
      }),
      attachTo: document.body,
    })

    await wrapper.get('[data-action="explore-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.findAll(".generate-exploration__results article")).toHaveLength(3))
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()

    await wrapper.findAll(".generate-exploration__results article button").filter((button) => button.text().includes("选择这一条"))[1].trigger("click")
    expect(wrapper.get('[data-action="generate-world-suggestion"]').text()).toBe("生成所选探索建议")
    await wrapper.get('[data-action="generate-world-suggestion"]').trigger("click")
    await vi.waitFor(() => expect(api.generate.generateWorldSuggestion).toHaveBeenCalledTimes(1))

    const payload = api.generate.generateWorldSuggestion.mock.calls[0][0]
    expect(payload.exploration_selection).toEqual(expect.objectContaining({ depth: 1, item_id: "E2", title: "地方税契", request_fingerprint: "f".repeat(64) }))
    expect(JSON.stringify(payload.exploration_selection)).not.toContain("边境道路")
    expect(JSON.stringify(payload.exploration_selection)).not.toContain("夜航邮驿")
    expect(wrapper.get('[data-state="source-revision-created"]').text()).toContain("1 条待处理修订")
    await wrapper.get('[data-state="source-revision-created"] button').trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("world", "bible", true, expect.any(URLSearchParams))
  })

  it("restores convergence choices locally and marks them stale after inputs change", async () => {
    api.generate.convergeWorld.mockResolvedValue(convergenceResponse())
    const key = generateSessionKey("p1")
    const initialSession = { ...emptyGenerateSession(), messages: [{ role: "user", content: "整理本轮" }] }
    const first = mount(GenerateView, { props: baseProps({ sessionKey: key, initialSession }), attachTo: document.body })
    await first.get('[data-action="converge-world"]').trigger("click")
    await vi.waitFor(() => expect(first.find('[data-section="convergence-preview"]').exists()).toBe(true))
    await first.findAll(".generate-convergence-items select")[0].setValue("open")
    await first.get(".generate-convergence-message textarea").setValue("刷新后仍要保留的作者消息")
    await flushPromises()
    first.unmount()

    const restored = readGenerateSession(key)
    expect(restored.convergenceDraft.cards[0].items[0].disposition).toBe("open")
    expect(restored.convergenceDraft.authorMessage).toBe("刷新后仍要保留的作者消息")
    api.generate.convergeWorld.mockClear()
    const second = mount(GenerateView, { props: baseProps({ sessionKey: key, initialSession: restored }), attachTo: document.body })
    expect(second.get(".generate-convergence-message textarea").element.value).toBe("刷新后仍要保留的作者消息")
    expect(api.generate.convergeWorld).not.toHaveBeenCalled()

    await second.get("#generate-chat-input").setValue("来源发生了变化")
    await flushPromises()
    expect(second.get('[data-section="convergence-preview"]').text()).toContain("材料已变化")
    expect(second.get('[data-action="apply-convergence-message"]').element.disabled).toBe(true)
    expect(api.generate.convergeWorld).not.toHaveBeenCalled()
  })

  it("only suggests convergence near the 40-message boundary and reports excluded history", async () => {
    api.generate.convergeWorld.mockResolvedValue(convergenceResponse({ excluded: 2 }))
    const messages = Array.from({ length: 42 }, (_, index) => ({
      role: index % 2 ? "assistant" : "user",
      content: `第 ${index + 1} 条`,
    }))
    const wrapper = mount(GenerateView, {
      props: baseProps({ initialSession: { ...emptyGenerateSession(), messages } }),
      attachTo: document.body,
    })

    expect(wrapper.text()).toContain("对话接近 40 条发送边界")
    expect(api.generate.convergeWorld).not.toHaveBeenCalled()
    await wrapper.get('[data-action="converge-world"]').trigger("click")
    await vi.waitFor(() => expect(api.generate.convergeWorld).toHaveBeenCalledTimes(1))
    expect(api.generate.convergeWorld.mock.calls[0][0].messages).toHaveLength(40)
    expect(api.generate.convergeWorld.mock.calls[0][0].excluded_message_count).toBe(2)
    expect(wrapper.get('[data-section="convergence-preview"]').text()).toContain("2 条更早对话未纳入")
  })

  it("keeps incomplete convergence read-only and disables the author-message action", async () => {
    api.generate.convergeWorld.mockResolvedValue(convergenceResponse({ complete: false }))
    const wrapper = mount(GenerateView, {
      props: baseProps({ initialSession: { ...emptyGenerateSession(), messages: [{ role: "user", content: "整理" }] } }),
      attachTo: document.body,
    })

    await wrapper.get('[data-action="converge-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get('[data-section="convergence-preview"]').text()).toContain("范围不完整"))
    expect(wrapper.get('[data-section="convergence-preview"]').text()).toContain("缺少一个来源块")
    expect(wrapper.get('[data-action="apply-convergence-message"]').element.disabled).toBe(true)
    expect(wrapper.get('[data-action="open-story-outline"]').element.disabled).toBe(true)
    expect(api.generate.worldChat).not.toHaveBeenCalled()
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()
  })

  it("protects an edited page proposal before routing a complete convergence to Story Overview", async () => {
    api.generate.convergeWorld.mockResolvedValue(convergenceResponse())
    const confirmDiscard = vi.fn(() => false)
    setBridgeOverrides({ confirm: confirmDiscard })
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const result = {
      kind: "world_bible_page", suggestion: { id: "suggestion-story-route", status: "pending" },
      proposal: { operation: "replace_existing", page: { title: "初始", page_type: "custom", sections_json: [], linked_asset_refs_json: [] } },
    }
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key,
      initialSession: { ...emptyGenerateSession(), suggestionId: "suggestion-story-route", messages: [{ role: "user", content: "收束叙事基调" }] },
      restoredWorldResult: result,
    }), attachTo: document.body })

    await wrapper.get("#generate-page-title").setValue("仍未应用的标题")
    await wrapper.get('[data-action="converge-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-action="open-story-outline"]').exists()).toBe(true))
    await wrapper.get('[data-action="open-story-outline"]').trigger("click")

    expect(confirmDiscard).toHaveBeenCalledTimes(1)
    expect(router.navigate).not.toHaveBeenCalled()
    expect(readGenerateSession(key).pageProposalDraft?.editor.title).toBe("仍未应用的标题")

    confirmDiscard.mockReturnValue(true)
    await wrapper.get('[data-action="open-story-outline"]').trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("outline", "story-outline")
    expect(readGenerateSession(key).pageProposalDraft).toBeNull()
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()
    expect(api.generate.applyWorldPageDraft).not.toHaveBeenCalled()
  })

  it("routes one bounded external return and skips it only after an author message exists", async () => {
    api.generate.convergeWorld.mockImplementation(async (payload) => {
      const response = convergenceResponse()
      response.external_packet = payload.external_packet
      response.decision_cards[0].items[0].external_disposition = "repair"
      response.decision_cards[0].items[1].external_disposition = "candidate"
      return response
    })
    const key = generateSessionKey("p1")
    const wrapper = mount(GenerateView, { props: baseProps({ sessionKey: key }), attachTo: document.body })
    const packet = "packet_index: 2\npacket_total: 5\nchecks_run: strict\nFIX-147：修订港口税制"
    await wrapper.get("#generate-chat-input").setValue("只核对当前港口制度，不处理故事大纲")
    await wrapper.get("#generate-external-packet").setValue(packet)
    await wrapper.get('[data-action="preview-external-packet"]').trigger("click")
    await vi.waitFor(() => expect(api.generate.convergeWorld).toHaveBeenCalledTimes(1))

    expect(api.generate.convergeWorld).toHaveBeenCalledWith(expect.objectContaining({
      pasted_context: packet,
      external_packet: {
        sha256: expect.stringMatching(/^[0-9a-f]{64}$/),
        packet_index: 2,
        packet_total: 5,
      },
      messages: [{ role: "user", content: "只核对当前港口制度，不处理故事大纲" }],
    }), expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()
    expect(wrapper.get('[data-section="external-handoff"]').text()).toContain("第 2/5 包 · 已形成预览")
    expect(wrapper.get('[data-section="external-handoff"]').text()).toContain("本地尚未验证")
    expect(wrapper.get('[data-section="convergence-preview"]').text()).toContain("需要修复")
    await vi.waitFor(() => expect(wrapper.get('[data-action="preview-external-packet"]').element.disabled).toBe(false))

    await wrapper.get('[data-action="preview-external-packet"]').trigger("click")
    await vi.waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining("当前已显示"), "info"))
    expect(api.generate.convergeWorld).toHaveBeenCalledTimes(1)
    expect(readGenerateSession(key).externalPackets).toHaveLength(1)
    expect(readGenerateSession(key).externalPackets[0].status).toBe("previewed")

    await wrapper.get('[data-action="apply-convergence-message"]').trigger("click")
    await flushPromises()
    expect(readGenerateSession(key).externalPackets[0]).toMatchObject({ packetIndex: 2, packetTotal: 5, status: "decision_ready" })

    await wrapper.get('[data-action="preview-external-packet"]').trigger("click")
    await vi.waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining("完全相同"), "info"))
    expect(api.generate.convergeWorld).toHaveBeenCalledTimes(1)
    expect(readGenerateSession(key).externalPackets.at(-1).status).toBe("exact_duplicate")
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()
  })

  it("allows the same external return to retry after incomplete coverage", async () => {
    api.generate.convergeWorld
      .mockResolvedValueOnce(convergenceResponse({ complete: false }))
      .mockResolvedValueOnce(convergenceResponse())
    const key = generateSessionKey("p1")
    const wrapper = mount(GenerateView, { props: baseProps({ sessionKey: key }), attachTo: document.body })
    const packet = "packet_index: 1\npacket_total: 1\n港口税制回包"
    await wrapper.get("#generate-chat-input").setValue("核对当前港口制度")
    await wrapper.get("#generate-external-packet").setValue(packet)

    await wrapper.get('[data-action="preview-external-packet"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get('[data-section="convergence-preview"]').text()).toContain("范围不完整"))
    expect(readGenerateSession(key).externalPackets.at(-1).status).toBe("incomplete")
    expect(wrapper.get('[data-action="rerun-external-packet"]').text()).toBe("重新整理这份回包")

    await wrapper.get('[data-action="rerun-external-packet"]').trigger("click")
    await vi.waitFor(() => expect(api.generate.convergeWorld).toHaveBeenCalledTimes(2))
    expect(wrapper.get('[data-section="convergence-preview"]').text()).toContain("范围已覆盖")
    expect(readGenerateSession(key).externalPackets.map((item) => item.status)).toEqual([
      "incomplete",
      "previewed",
    ])
  })

  it("rejects an oversized external return before any LLM call and keeps the original text", async () => {
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    const packet = "界".repeat(55_001)
    await wrapper.get("#generate-chat-input").setValue("核对当前目标")
    await wrapper.get("#generate-external-packet").setValue(packet)

    expect(wrapper.get('[data-section="external-handoff"]').text()).toContain("已超限")
    await wrapper.get('[data-action="preview-external-packet"]').trigger("click")
    await flushPromises()

    expect(api.generate.convergeWorld).not.toHaveBeenCalled()
    expect(wrapper.get("#generate-external-packet").element.value).toBe(packet)
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("超过 55,000 字符上限"), "warning")
  })

  it("keeps a late external result read-only when the author edits its source while waiting", async () => {
    let resolveConvergence
    api.generate.convergeWorld.mockImplementation(() => new Promise((resolve) => { resolveConvergence = resolve }))
    const key = generateSessionKey("p1")
    const wrapper = mount(GenerateView, { props: baseProps({ sessionKey: key }), attachTo: document.body })
    await wrapper.get("#generate-chat-input").setValue("核对当前目标")
    await wrapper.get("#generate-external-packet").setValue("第一版外部回包")
    wrapper.get('[data-action="preview-external-packet"]').element.click()
    await vi.waitFor(() => expect(api.generate.convergeWorld).toHaveBeenCalledOnce())
    await wrapper.get("#generate-external-packet").setValue("等待期间修订的第二版")
    resolveConvergence(convergenceResponse())
    await flushPromises()

    expect(wrapper.get('[data-section="convergence-preview"]').text()).toContain("材料已变化")
    expect(wrapper.get('[data-action="apply-convergence-message"]').element.disabled).toBe(true)
    expect(readGenerateSession(key).externalPackets[0].status).toBe("incomplete")
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("输入在整理期间发生变化"), "warning")
  })

  it("copies and downloads the exact same ID-free handoff without another model call", async () => {
    api.generate.convergeWorld.mockResolvedValue(convergenceResponse())
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } })
    const createObjectURL = vi.fn(() => "blob:handoff")
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
    const wrapper = mount(GenerateView, {
      props: baseProps({ initialSession: { ...emptyGenerateSession(), messages: [{ role: "user", content: "整理当前制度" }] } }),
      attachTo: document.body,
    })
    await wrapper.get('[data-action="converge-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-action="copy-world-handoff"]').exists()).toBe(true))

    await wrapper.get('[data-action="copy-world-handoff"]').trigger("click")
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledOnce())
    const copied = writeText.mock.calls[0][0]
    await wrapper.get('[data-action="download-world-handoff"]').trigger("click")
    const blob = createObjectURL.mock.calls[0][0]

    expect(await blob.text()).toBe(copied)
    expect(copied).toContain("handoff_version: world-handoff-v1")
    expect(copied).toContain("未运行：全项目一致性检查")
    expect(api.generate.convergeWorld).toHaveBeenCalledTimes(1)
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()
    expect(click).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:handoff")
    click.mockRestore()
  })

  it("keeps the handoff available for manual copy when clipboard access fails synchronously", async () => {
    api.generate.convergeWorld.mockResolvedValue(convergenceResponse())
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn(() => { throw new Error("denied") }) },
    })
    const wrapper = mount(GenerateView, {
      props: baseProps({ initialSession: { ...emptyGenerateSession(), messages: [{ role: "user", content: "整理当前制度" }] } }),
      attachTo: document.body,
    })
    await wrapper.get('[data-action="converge-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-action="copy-world-handoff"]').exists()).toBe(true))

    await wrapper.get('[data-action="copy-world-handoff"]').trigger("click")
    await vi.waitFor(() => expect(showModalHtml).toHaveBeenCalledWith(
      "手动复制创作交接快照",
      expect.stringContaining("handoff_version: world-handoff-v1"),
      [],
      { size: "large" },
    ))

    expect(api.generate.convergeWorld).toHaveBeenCalledTimes(1)
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("快照已保留"), "warning")
  })

  it("confirms a source-bound visual brief without writes, then opens the atlas and fails closed on drift", async () => {
    api.generate.convergeWorld.mockResolvedValue(convergenceResponse())
    const key = generateSessionKey("p1")
    const wrapper = mount(GenerateView, {
      props: baseProps({ sessionKey: key, initialSession: { ...emptyGenerateSession(), messages: [{ role: "user", content: "准备白堤总览" }] } }),
      attachTo: document.body,
    })
    await wrapper.get('[data-action="converge-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-action="create-visual-brief"]').exists()).toBe(true))
    await wrapper.get('[data-action="create-visual-brief"]').trigger("click")

    const visual = wrapper.get('[data-section="visual-brief"]')
    expect(visual.text()).toContain("来源设定")
    expect(visual.text()).toContain("尚未生成图片")
    await visual.findAll("textarea")[0].setValue("白堤旧名不得出现在图中")
    await visual.get('[data-action="confirm-visual-brief"]').trigger("click")
    expect(readGenerateSession(key).visualBrief).toMatchObject({ purpose: "overview", exactLabels: "白堤旧名不得出现在图中", stale: false })
    expect(readGenerateSession(key).visualBrief.confirmedAt).toEqual(expect.any(String))
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()

    await visual.get('[data-action="preview-visual-map"]').trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("map", null, true)
    expect(toast).toHaveBeenCalledWith("视觉简报已保留；地图册只会在你确认后开始生成", "success")

    await wrapper.get("#generate-chat-input").setValue("来源新增了一条边界")
    await flushPromises()
    expect(visual.text()).toContain("来源已变化，需复核")
    expect(visual.findAll("textarea")[0].element.value).toBe("白堤旧名不得出现在图中")
    expect(visual.get('[data-action="confirm-visual-brief"]').element.disabled).toBe(true)
    expect(visual.get('[data-action="preview-visual-map"]').element.disabled).toBe(true)
    expect(api.generate.convergeWorld).toHaveBeenCalledTimes(1)
  })

  it("keeps the previous convergence visible but stale when the source changes during rerun", async () => {
    api.generate.convergeWorld.mockResolvedValueOnce(convergenceResponse())
    const wrapper = mount(GenerateView, {
      props: baseProps({ initialSession: { ...emptyGenerateSession(), messages: [{ role: "user", content: "整理" }] } }),
      attachTo: document.body,
    })
    await wrapper.get('[data-action="converge-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-section="convergence-preview"]').exists()).toBe(true))
    const previousMessage = wrapper.get(".generate-convergence-message textarea").element.value
    api.generate.convergeWorld.mockRejectedValueOnce(Object.assign(new Error("source changed"), { status: 409 }))

    await wrapper.get('[data-action="converge-world"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get('[data-section="convergence-preview"]').text()).toContain("材料已变化"))

    expect(wrapper.get(".generate-convergence-message textarea").element.value).toBe(previousMessage)
    expect(wrapper.get('[data-action="apply-convergence-message"]').element.disabled).toBe(true)
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("旧预览仅供回看"), "warning")
  })

  it("exposes linked tabs and panels while roving focus does not activate a mode", async () => {
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    const worldTab = wrapper.get("#generate-mode-tab-world")
    const povTab = wrapper.get("#generate-mode-tab-pov_prose")
    const taskTab = wrapper.get("#generate-mode-tab-task")
    const previewTab = wrapper.get("#generate-mode-tab-preview")

    for (const tab of [worldTab, povTab, taskTab, previewTab]) {
      expect(tab.attributes()).toMatchObject({ type: "button", role: "tab" })
      expect(tab.attributes("aria-controls")).toBe(`generate-mode-panel-${tab.attributes("id").replace("generate-mode-tab-", "")}`)
    }
    expect(worldTab.attributes()).toMatchObject({ "aria-selected": "true", tabindex: "0" })
    expect(taskTab.attributes()).toMatchObject({ "aria-selected": "false", tabindex: "-1" })
    expect(wrapper.get("#generate-mode-panel-world").attributes()).toMatchObject({ role: "tabpanel", "aria-labelledby": "generate-mode-tab-world" })

    await worldTab.trigger("keydown", { key: "ArrowRight" })
    expect(document.activeElement).toBe(povTab.element)
    expect(worldTab.attributes("aria-selected")).toBe("true")
    expect(wrapper.find("#generate-mode-panel-pov_prose").exists()).toBe(false)
    await povTab.trigger("keydown", { key: "End" })
    expect(document.activeElement).toBe(previewTab.element)
    await previewTab.trigger("keydown", { key: "Home" })
    expect(document.activeElement).toBe(worldTab.element)

    const sibling = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    const siblingWorldTab = sibling.get("#generate-mode-tab-world")
    const siblingPovTab = sibling.get("#generate-mode-tab-pov_prose")
    await siblingWorldTab.trigger("keydown", { key: "ArrowRight" })
    expect(document.activeElement).toBe(siblingPovTab.element)
    sibling.unmount()

    await taskTab.trigger("click")
    expect(taskTab.attributes()).toMatchObject({ "aria-selected": "true", tabindex: "0" })
    expect(wrapper.get("#generate-mode-panel-task").attributes()).toMatchObject({ role: "tabpanel", "aria-labelledby": "generate-mode-tab-task" })
    expect(wrapper.find("#generate-mode-panel-world").exists()).toBe(false)
  })

  it("marks exclusive world targets and object templates as pressed", () => {
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    expect(wrapper.get('[data-action="select-world-target"]:first-child').attributes()).toMatchObject({ type: "button", "aria-pressed": "true" })
    expect(wrapper.get('[data-action="select-world-target"]:last-child').attributes("aria-pressed")).toBe("false")
    expect(wrapper.get('[data-action="select-object-template"]').attributes()).toMatchObject({ type: "button", "aria-pressed": "true" })
  })

  it("turns pasted composer text into a project-scoped pending world suggestion", async () => {
    api.generate.generateWorldSuggestion.mockResolvedValue({
      result: {
        kind: "core_entity",
        suggestion: {
          id: "suggestion-1",
          payload_json: { name: "雾港", entity_type: "location" },
          decision_state: {
            current_author_goal: "把外部对话收束为港口设定",
            confirmed_requirements: ["保留潮汐贸易"],
            supported_developments: ["发展夜间码头生活"],
            rejected_elements: ["废弃的军港方向"],
            forbidden_exact_terms: ["旧港名"],
            unresolved_choices: [],
            knowledge_expression_boundaries: ["作者知道潮汐机制；水手只用潮谚表达"],
            naming_policy: "allowed",
            confidence: 0.4,
          },
        },
      },
      context_usage: { revision_id: "revision-1" },
    })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get("#generate-chat-input").setValue("把这段外部对话收束为港口设定")
    await wrapper.get('[data-action="generate-world-suggestion"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get("#generate-result").text()).toContain("雾港"))
    const decision = wrapper.get('[data-section="author-decision-summary"]')
    expect(decision.attributes("open")).toBeUndefined()
    expect(decision.text()).toContain("AI 本次理解 · 请核对")
    expect(decision.text()).toContain("作者知道潮汐机制；水手只用潮谚表达")
    expect(decision.text()).not.toContain("0.4")
    expect(api.generate.generateWorldSuggestion).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      target: expect.objectContaining({ kind: "core_entity" }),
      messages: [{ role: "user", content: "把这段外部对话收束为港口设定" }],
    }), expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it("rejects synchronous double clicks before the pending disabled state renders", async () => {
    let resolveSuggestion
    api.generate.generateWorldSuggestion.mockImplementation(() => new Promise((resolve) => {
      resolveSuggestion = resolve
    }))
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get("#generate-chat-input").setValue("只提交一次")
    const button = wrapper.get('[data-action="generate-world-suggestion"]').element

    button.click()
    button.click()

    expect(api.generate.generateWorldSuggestion).toHaveBeenCalledTimes(1)
    resolveSuggestion({
      result: {
        kind: "core_entity",
        suggestion: { id: "single-suggestion", payload_json: { name: "唯一结果" } },
      },
    })
    await flushPromises()
    expect(wrapper.get("#generate-result").text()).toContain("唯一结果")
  })

  it("keeps the current world generation session locked after the receipt returns", async () => {
    api.generate.enqueueWorldSuggestion.mockResolvedValue({ task_id: "world-running", status: "pending" })
    api.tasks.get.mockResolvedValue({ task_id: "world-running", task_type: "world_generation_suggestion", status: "running" })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get("#generate-chat-input").setValue("生成期间不要重复提交")

    await wrapper.get('[data-action="generate-world-suggestion"]').trigger("click")
    await vi.waitFor(() => expect(api.tasks.get).toHaveBeenCalledWith("world-running", "p1"))

    const button = wrapper.get('[data-action="generate-world-suggestion"]')
    expect(button.element.disabled).toBe(true)
    await button.trigger("click")
    expect(api.generate.enqueueWorldSuggestion).toHaveBeenCalledTimes(1)
  })

  it("does not recover another tab's world receipt from shared local storage", async () => {
    const sessionKey = generateSessionKey("p1")
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
      id: "p1:world_generation_suggestion:world-other-tab",
      taskId: "world-other-tab",
      workflowType: "world_generation_suggestion",
      projectId: "p1",
      view: "generate",
      meta: { session_key: sessionKey, target_kind: "core_entity" },
    }]))

    mount(GenerateView, { props: baseProps({ sessionKey }), attachTo: document.body })
    await flushPromises()

    expect(api.tasks.get).not.toHaveBeenCalled()
  })

  it("recovers the page-local world receipt without replaying generation", async () => {
    const sessionKey = generateSessionKey("p1")
    sessionStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
      id: "p1:world_generation_suggestion:world-recover",
      taskId: "world-recover",
      workflowType: "world_generation_suggestion",
      projectId: "p1",
      view: "generate",
      meta: { session_key: sessionKey, target_kind: "core_entity", proposal_draft_baseline: "null" },
    }]))
    api.tasks.get.mockResolvedValue({
      task_id: "world-recover",
      task_type: "world_generation_suggestion",
      status: "done",
      result: { result: { kind: "core_entity", suggestion: { id: "suggestion-recover", payload_json: { name: "恢复雾港" } } } },
    })

    const wrapper = mount(GenerateView, { props: baseProps({ sessionKey }), attachTo: document.body })
    await vi.waitFor(() => expect(wrapper.get("#generate-result").text()).toContain("恢复雾港"))

    expect(api.generate.enqueueWorldSuggestion).not.toHaveBeenCalled()
    expect(api.tasks.get).toHaveBeenCalledWith("world-recover", "p1")
    expect(sessionStorage.getItem("novel_active_workflows_v1")).toBe("[]")
  })

  it("keeps world chat, suggestion generation, and apply mutually exclusive", async () => {
    let resolveChat
    api.generate.worldChat.mockImplementation(() => new Promise((resolve) => { resolveChat = resolve }))
    const wrapper = mount(GenerateView, {
      props: baseProps({
        targetKind: "world_bible_page",
        restoredWorldResult: { kind: "world_bible_page", suggestion: { id: "suggestion-1" } },
      }),
      attachTo: document.body,
    })
    await wrapper.get("#generate-chat-input").setValue("先等聊天完成")
    wrapper.get('[data-action="send-chat-message"]').element.click()
    await flushPromises()

    expect(wrapper.get('[data-action="send-chat-message"]').element.disabled).toBe(true)
    expect(wrapper.get('[data-action="generate-world-suggestion"]').element.disabled).toBe(true)
    wrapper.findComponent({ name: "WorldWorkspace" }).vm.$emit("apply-page", { title: "不应应用" })
    wrapper.get('[data-action="generate-world-suggestion"]').element.click()
    await flushPromises()
    expect(api.generate.applyWorldPageDraft).not.toHaveBeenCalled()
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()

    resolveChat({ reply: "聊天完成" })
    await flushPromises()
    expect(wrapper.get('[data-action="send-chat-message"]').element.disabled).toBe(true)
    expect(wrapper.get('[data-action="generate-world-suggestion"]').element.disabled).toBe(false)
    await wrapper.get("#generate-chat-input").setValue("下一条")
    expect(wrapper.get('[data-action="send-chat-message"]').element.disabled).toBe(false)
  })

  it("keeps send beside the composer and supports IME-safe Cmd/Ctrl+Enter", async () => {
    api.generate.worldChat.mockResolvedValue({ reply: "继续完善" })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    const input = wrapper.get("#generate-chat-input")
    const send = wrapper.get('[data-action="send-chat-message"]')

    expect(send.element.closest(".generate-composer")).not.toBeNull()
    expect(wrapper.find(".generate-toolbar [data-action='send-chat-message']").exists()).toBe(false)
    await input.setValue("")
    expect(send.element.disabled).toBe(true)

    await input.setValue("用快捷键发送")
    await input.trigger("keydown", { key: "Enter", metaKey: true, isComposing: true })
    expect(api.generate.worldChat).not.toHaveBeenCalled()
    await input.trigger("compositionstart")
    await input.trigger("keydown", { key: "Enter", ctrlKey: true, isComposing: false })
    expect(api.generate.worldChat).not.toHaveBeenCalled()
    await input.trigger("compositionend")
    await input.trigger("keydown", { key: "Enter", ctrlKey: true, isComposing: false })
    await vi.waitFor(() => expect(api.generate.worldChat).toHaveBeenCalledTimes(1))
    await vi.waitFor(() => expect(document.activeElement).toBe(input.element))
  })

  it("shows loading before a lazy POV load can confirm the project has no chapters", async () => {
    let resolveChapters
    let resolveCharacters
    api.writing.listChapters.mockImplementation(() => new Promise((resolve) => { resolveChapters = resolve }))
    api.world.listCharacters.mockImplementation(() => new Promise((resolve) => { resolveCharacters = resolve }))
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })

    await wrapper.get("#generate-mode-tab-pov_prose").trigger("click")
    expect(wrapper.text()).toContain("正在加载章节和角色信息")
    expect(wrapper.text()).not.toContain("角色视角正文需要先准备章节")
    expect(wrapper.find('[data-action="generate-pov-prose"]').exists()).toBe(false)

    resolveChapters({ chapters: [] })
    resolveCharacters({ items: [] })
    await vi.waitFor(() => expect(wrapper.text()).toContain("角色视角正文需要先准备章节"))
  })

  it("offers zero-chapter POV prerequisites and routes without starting a generation", async () => {
    const wrapper = mount(GenerateView, { props: baseProps({ tab: "pov_prose" }), attachTo: document.body })

    expect(wrapper.text()).toContain("角色视角正文需要先准备章节")
    expect(wrapper.text()).toContain("至少一个章节，再补充场景和视角角色")
    expect(wrapper.find("#generate-pov-chapter").exists()).toBe(false)
    expect(wrapper.find("#generate-pov-scene").exists()).toBe(false)
    expect(wrapper.find("#generate-pov-instruction").exists()).toBe(false)
    expect(wrapper.find("#generate-pov-result").exists()).toBe(false)
    expect(wrapper.find('[data-action="generate-pov-prose"]').exists()).toBe(false)

    await wrapper.get('[data-action="open-writing-from-pov-empty"]').trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("writing")
    await wrapper.get('[data-action="return-world-from-pov-empty"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find("#generate-mode-panel-world").exists()).toBe(true))
    expect(confirmAiReference).not.toHaveBeenCalled()
    expect(api.writing.generate).not.toHaveBeenCalled()
  })

  it("shows the POV load warning instead of an empty-project prerequisite", () => {
    const wrapper = mount(GenerateView, {
      props: baseProps({ tab: "pov_prose", povLoadWarning: "加载章节或角色失败：网络暂不可用" }),
      attachTo: document.body,
    })

    expect(wrapper.text()).toContain("加载章节或角色失败：网络暂不可用")
    expect(wrapper.text()).not.toContain("角色视角正文需要先准备章节")
    expect(wrapper.find("#generate-pov-chapter").exists()).toBe(false)
    expect(wrapper.find('[data-action="generate-pov-prose"]').exists()).toBe(false)
  })

  it("keeps the POV form and generation action available when Scene loading warns", async () => {
    api.outline.listScenesByChapter.mockRejectedValue(new Error("Scene 暂不可用"))
    const wrapper = mount(GenerateView, {
      props: baseProps({
        tab: "pov_prose",
        povChapters: [{ chapter_index: 1, title: "旧怨" }],
        povCharacters: [{ entity_id: "char-1", name: "秦岚" }],
      }),
      attachTo: document.body,
    })

    await wrapper.get("#generate-pov-chapter").setValue("1")
    await vi.waitFor(() => expect(wrapper.text()).toContain("加载场景失败：Scene 暂不可用"))
    expect(wrapper.find("#generate-pov-chapter").exists()).toBe(true)
    expect(wrapper.find("#generate-pov-scene").exists()).toBe(true)
    expect(wrapper.find("#generate-pov-character").exists()).toBe(true)
    expect(wrapper.find('[data-action="generate-pov-prose"]').exists()).toBe(true)
    expect(wrapper.get("#generate-pov-chapter").attributes("disabled")).toBeUndefined()
    expect(confirmAiReference).not.toHaveBeenCalled()
    expect(api.writing.generate).not.toHaveBeenCalled()
  })

  it("keeps the Scene list for the latest chapter when requests finish B then A", async () => {
    const resolveScenes = new Map()
    api.outline.listScenesByChapter.mockImplementation((_projectId, chapter) => new Promise((resolve) => {
      resolveScenes.set(chapter, resolve)
    }))
    const wrapper = mount(GenerateView, {
      props: baseProps({
        tab: "pov_prose",
        povChapters: [
          { chapter_index: 1, title: "旧怨" },
          { chapter_index: 2, title: "追击" },
        ],
        povCharacters: [{ entity_id: "char-1", name: "秦岚" }],
      }),
      attachTo: document.body,
    })

    const chapter = wrapper.get("#generate-pov-chapter")
    await chapter.setValue("1")
    await chapter.setValue("2")
    resolveScenes.get(2)([{ id: "scene-b", title: "B 章场景" }])
    await flushPromises()
    expect(wrapper.get("#generate-pov-scene").text()).toContain("B 章场景")

    resolveScenes.get(1)([{ id: "scene-a", title: "A 章场景" }])
    await flushPromises()
    expect(chapter.element.value).toBe("2")
    expect(wrapper.get("#generate-pov-scene").text()).toContain("B 章场景")
    expect(wrapper.get("#generate-pov-scene").text()).not.toContain("A 章场景")
  })

  it("生成期间改选角色不会篡改已发起请求的结果归属", async () => {
    const generated = deferred()
    confirmAiReference.mockResolvedValue({ id: "confirm-1", user_note: "" })
    api.writing.generate.mockReturnValue(generated.promise)
    api.tasks.get.mockResolvedValue({ status: "done", progress: 1, result: { draft_id: "draft-1" } })
    const wrapper = mount(GenerateView, {
      props: baseProps({
        tab: "pov_prose",
        povChapters: [{ chapter_index: 1, title: "第一章" }],
        povCharacters: [{ id: "char-a", name: "甲" }, { id: "char-b", name: "乙" }],
      }),
      attachTo: document.body,
    })
    api.outline.listScenesByChapter.mockResolvedValueOnce([{ id: "scene-1", title: "场景", pov_character_id: "char-a" }])
    await wrapper.get("#generate-pov-chapter").setValue("1")
    await vi.waitFor(() => expect(wrapper.findAll("#generate-pov-scene option").length).toBeGreaterThan(1))
    await wrapper.get("#generate-pov-scene").setValue("scene-1")
    await wrapper.get("#generate-pov-character").setValue("char-a")
    const pending = wrapper.get('[data-action="generate-pov-prose"]').trigger("click")
    await vi.waitFor(() => expect(api.writing.generate).toHaveBeenCalled())

    await wrapper.get("#generate-pov-character").setValue("char-b")
    generated.resolve({ task_id: "task-1" })
    await pending
    await flushPromises()

    expect(wrapper.get("#generate-pov-result").text()).toContain("角色视角正文建议已生成")
    expect(wrapper.get("#generate-pov-result").text()).toContain("甲")
    expect(wrapper.get("#generate-pov-result").text()).not.toContain("乙")
  })

  it("aborts an in-flight world request and rejects its late response after unmount", async () => {
    let resolve
    api.generate.worldChat.mockImplementation((_payload, options) => new Promise((done) => { resolve = done; expect(options.signal.aborted).toBe(false) }))
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get("#generate-chat-input").setValue("迟到请求")
    const button = wrapper.get('[data-action="send-chat-message"]')
    await button.trigger("click")
    const signal = api.generate.worldChat.mock.calls[0][1].signal
    wrapper.unmount()
    expect(signal.aborted).toBe(true)
    resolve({ reply: "不应回写" })
    await Promise.resolve()
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("不应回写"), expect.anything())
  })

  it("marks the snapshot interrupted before browser unload can report a navigation fetch failure", async () => {
    let reject
    api.generate.worldChat.mockImplementation(() => new Promise((_resolve, fail) => { reject = fail }))
    const key = generateSessionKey("p1")
    const wrapper = mount(GenerateView, { props: baseProps({ sessionKey: key }), attachTo: document.body })
    await wrapper.get("#generate-chat-input").setValue("刷新前的问题")
    await wrapper.get('[data-action="send-chat-message"]').trigger("click")
    const signal = api.generate.worldChat.mock.calls[0][1].signal

    window.dispatchEvent(new Event("beforeunload"))
    expect(signal.aborted).toBe(true)
    reject(new Error("无法访问 API 服务"))
    await flushPromises()

    const messages = readGenerateSession(key).messages
    expect(messages.at(-1)).toEqual(expect.objectContaining({ role: "assistant", error: true, interrupted: true }))
    expect(messages.at(-1).content).toContain("上次回复在离开或刷新时尚未返回")
    expect(messages.at(-1).content).not.toContain("无法访问 API 服务")
    wrapper.unmount()
  })

  it("disarms the unload listener after a settled world chat", async () => {
    api.generate.worldChat
      .mockResolvedValueOnce({ reply: "第一条回复" })
      .mockResolvedValueOnce({ reply: "第二条回复" })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get("#generate-chat-input").setValue("第一条")
    await wrapper.get('[data-action="send-chat-message"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get("#generate-chat-messages").text()).toContain("第一条回复"))

    window.dispatchEvent(new Event("beforeunload"))
    await wrapper.get("#generate-chat-input").setValue("第二条")
    await wrapper.get('[data-action="send-chat-message"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get("#generate-chat-messages").text()).toContain("第二条回复"))
    expect(api.generate.worldChat).toHaveBeenCalledTimes(2)
  })

  it("recovers an interrupted chat as a terminal local message and leaves the composer usable", async () => {
    let resolve
    api.generate.worldChat.mockImplementation(() => new Promise((done) => { resolve = done }))
    const key = generateSessionKey("p1")
    const first = mount(GenerateView, { props: baseProps({ sessionKey: key }), attachTo: document.body })
    await first.get("#generate-chat-input").setValue("离开前的问题")
    await first.get('[data-action="send-chat-message"]').trigger("click")

    expect(first.get("#generate-chat-messages").text()).toContain("正在思考...")
    const interruptedSnapshot = readGenerateSession(key).messages
    expect(interruptedSnapshot).toEqual([
      { role: "user", content: "离开前的问题" },
      expect.objectContaining({ role: "assistant", error: true, interrupted: true }),
    ])
    expect(interruptedSnapshot.at(-1)).not.toHaveProperty("pending")
    const signal = api.generate.worldChat.mock.calls[0][1].signal
    first.unmount()
    expect(signal.aborted).toBe(true)

    resolve({ reply: "迟到回复" })
    await flushPromises()
    expect(readGenerateSession(key).messages.at(-1)).toEqual(expect.objectContaining({ error: true, interrupted: true }))
    expect(readGenerateSession(key).messages.at(-1).content).not.toContain("迟到回复")

    const second = mount(GenerateView, {
      props: baseProps({ sessionKey: key, initialSession: readGenerateSession(key) }),
      attachTo: document.body,
    })
    expect(second.get("#generate-chat-messages").text()).toContain("离开前的问题")
    expect(second.get("#generate-chat-messages").text()).toContain("上次回复在离开或刷新时尚未返回")
    await second.get("#generate-chat-input").setValue("确认后重试")
    expect(second.get('[data-action="send-chat-message"]').element.disabled).toBe(false)
    expect(api.generate.worldChat).toHaveBeenCalledTimes(1)
  })

  it("keeps silent preview errors inline and does not toast", async () => {
    api.context.compile.mockRejectedValue(new Error("compile down"))
    const wrapper = mount(GenerateView, { props: baseProps({ tab: "task" }), attachTo: document.body })
    await wrapper.get("#gen-task").setValue("测试任务")
    await wrapper.get('[data-action="preview-task-context"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get("#gen-task-output").text()).toContain("compile down"))
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("compile down"), "error")
  })

  it("compiles a task into preview and renders API markdown as text", async () => {
    api.context.compile.mockResolvedValue({
      scope: "arc", reveal_mode: "author_safe", total_tokens: 12,
      sections: [{ key: '<img src=x onerror="boom">', tier: "core", token_count: 12 }],
    })
    api.context.render.mockResolvedValue({ markdown: '<img src=x onerror="boom">' })
    const wrapper = mount(GenerateView, { props: baseProps({ tab: "task" }), attachTo: document.body })
    await wrapper.get("#gen-task").setValue("检查主线冲突")
    await wrapper.get('[data-action="run-task"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.text()).toContain("已加载 1 段上下文"))
    expect(api.context.compile).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p1", task: "检查主线冲突", budget_tokens: 0 }), expect.objectContaining({ signal: expect.any(AbortSignal) }))
    await wrapper.get('[data-action="render-task-md"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get(".generate-markdown-pre").text()).toContain("<img"))
    expect(wrapper.find("img").exists()).toBe(false)
  })

  it("编译后跨目标重挂载仍保留当前项目的上下文预览", async () => {
    api.context.compile.mockResolvedValue({
      scope: "arc",
      total_tokens: 12,
      sections: [{ key: "story_outline", tier: "core", token_count: 12 }],
    })
    const first = mount(GenerateView, {
      props: baseProps({ tab: "task" }),
      attachTo: document.body,
    })
    await first.get("#gen-task").setValue("跨目标检查")
    await first.get('[data-action="run-task"]').trigger("click")
    await vi.waitFor(() => expect(first.text()).toContain("已加载 1 段上下文"))
    first.unmount()

    const second = mount(GenerateView, {
      props: baseProps({
        tab: "preview",
        targetKind: "new_page",
        sessionKey: generateSessionKey("p1", null, "new_page"),
      }),
      attachTo: document.body,
    })

    expect(second.text()).toContain("已加载 1 段上下文")
  })

  it("uses character confirmation, polls with project ownership, then opens the exact writing candidate", async () => {
    api.outline.listScenesByChapter.mockResolvedValue([{ id: "scene-1", title: "第一场", pov_character_id: "char-1" }])
    confirmAiReference.mockResolvedValue({ id: "confirm-1", user_note: "避免剧透" })
    api.writing.generate.mockResolvedValue({ task_id: "task-1" })
    api.tasks.get.mockResolvedValue({ status: "done", progress: 1, result: { draft_id: "draft-1" } })
    const wrapper = mount(GenerateView, { props: baseProps({ tab: "pov_prose", povChapters: [{ chapter_index: 1, title: "旧怨" }], povCharacters: [{ entity_id: "char-1", name: "秦岚" }] }), attachTo: document.body })
    await wrapper.get("#generate-pov-chapter").setValue("1")
    await vi.waitFor(() => expect(wrapper.findAll("#generate-pov-scene option")).toHaveLength(2))
    await wrapper.get("#generate-pov-scene").setValue("scene-1")
    await wrapper.get("#generate-pov-instruction").setValue("保持克制")
    await wrapper.get('[data-action="generate-pov-prose"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get("#generate-pov-result").text()).toContain("打开并审阅建议"))
    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p1", reveal_mode: "character", viewpoint_character_id: "char-1" }))
    expect(api.tasks.get).toHaveBeenCalledWith("task-1", "p1")
    expect(api.writing.generate.mock.calls[0][0].instruction).toContain("用户指令是作者意图，不等于角色知识")
    await wrapper.get('[data-action="open-generated-destination"]').trigger("click")
    expect(state.viewStates.writing).toEqual(expect.objectContaining({ projectId: "p1", currentChapter: 1, currentDraftId: "draft-1", isReadonly: true }))
    const query = router.navigate.mock.calls.at(-1)[3]
    expect(query.get("draft_id")).toBe("draft-1")
  })

  it("loads template history into the owned modal without injecting API text as markup", async () => {
    api.generate.listPromptTemplateRevisions.mockResolvedValue([{ version_number: 2, prompt_text: '<img src=x onerror="boom">' }])
    const wrapper = mount(GenerateView, { props: baseProps({ templates: [{ id: "tpl-1", value: "tpl-1", label: "自定义", prompt: "当前", object_template: "custom", is_builtin: false, version_number: 3 }], initialSession: { ...emptyGenerateSession(), selectedTemplateId: "tpl-1" } }), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    document.getElementById("generate-template-history-load").click()
    await vi.waitFor(() => expect(document.getElementById("generate-template-history").textContent).toContain("v2"))
    expect(document.getElementById("generate-template-history").querySelector("img")).toBeNull()
    expect(api.generate.listPromptTemplateRevisions).toHaveBeenCalledWith("tpl-1", "p1")
  })

  it("does not render template A history after the editor switches to template B", async () => {
    const revisions = deferred()
    api.generate.listPromptTemplateRevisions.mockReturnValue(revisions.promise)
    const wrapper = mount(GenerateView, { props: baseProps({
      templates: [
        { id: "tpl-a", value: "tpl-a", label: "模板 A", prompt: "A 当前提示词", object_template: "custom", is_builtin: false, version_number: 2 },
        { id: "tpl-b", value: "tpl-b", label: "模板 B", prompt: "B 当前提示词", object_template: "custom", is_builtin: false, version_number: 1 },
      ],
      initialSession: { ...emptyGenerateSession(), selectedTemplateId: "tpl-a" },
    }), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    document.getElementById("generate-template-history-load").click()
    await vi.waitFor(() => expect(api.generate.listPromptTemplateRevisions).toHaveBeenCalledWith("tpl-a", "p1"))

    const select = document.getElementById("generate-template-editor-select")
    select.value = "tpl-b"
    select.dispatchEvent(new Event("change"))
    revisions.resolve([{ version_number: 1, prompt_text: "A 历史提示词" }])
    await flushPromises()

    expect(document.getElementById("generate-template-editor-prompt").value).toBe("B 当前提示词")
    expect(document.getElementById("generate-template-history").textContent).not.toContain("A 历史提示词")
  })

  it("copies a builtin template into the project before saving its prompt", async () => {
    api.generate.copyPromptTemplate.mockResolvedValue({ id: "tpl-copy", version_number: 1 })
    api.generate.updatePromptTemplate.mockResolvedValue({
      id: "tpl-copy", name: "不带模板副本", prompt_text: "只保留可验证事实",
      object_template: "none", is_builtin: false, version_number: 2,
    })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    document.getElementById("generate-template-editor-prompt").value = "只保留可验证事实"
    const save = showModalHtml.mock.calls[0][2][0].handler
    await save()
    expect(api.generate.copyPromptTemplate).toHaveBeenCalledWith("builtin:none", { novel_id: "p1", name: "不带模板" })
    expect(api.generate.updatePromptTemplate).toHaveBeenCalledWith("tpl-copy", "p1", { prompt_text: "只保留可验证事实", template_version: 1 })
  })

  it("弹窗被替换后仍完成已发起的内置模板复制链", async () => {
    const copied = deferred()
    api.generate.copyPromptTemplate.mockReturnValue(copied.promise)
    api.generate.updatePromptTemplate.mockResolvedValue({
      id: "tpl-copy", name: "不带模板", prompt_text: "新提示词", object_template: "none", is_builtin: false, version_number: 2,
    })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    document.getElementById("generate-template-editor-prompt").value = "新提示词"
    const save = showModalHtml.mock.calls[0][2][0].handler()
    await vi.waitFor(() => expect(api.generate.copyPromptTemplate).toHaveBeenCalled())

    document.getElementById("modal-body").innerHTML = '<div class="replacement-modal">后续弹窗</div>'
    copied.resolve({ id: "tpl-copy", version_number: 1 })
    await save

    expect(api.generate.updatePromptTemplate).toHaveBeenCalledWith("tpl-copy", "p1", { prompt_text: "新提示词", template_version: 1 })
    expect(readGenerateSession(generateSessionKey("p1")).selectedTemplateId).toBe("builtin:none")
    expect(toast).not.toHaveBeenCalledWith("模板已保存", "success")
  })

  it("内置模板更新失败后重试复用已创建副本", async () => {
    api.generate.copyPromptTemplate.mockResolvedValue({ id: "tpl-copy", version_number: 1 })
    api.generate.updatePromptTemplate
      .mockRejectedValueOnce(new Error("update failed"))
      .mockResolvedValueOnce({ id: "tpl-copy", name: "不带模板", prompt_text: "新提示词", object_template: "none", is_builtin: false, version_number: 2 })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    document.getElementById("generate-template-editor-prompt").value = "新提示词"
    const save = showModalHtml.mock.calls[0][2][0].handler

    await expect(save()).resolves.toBe(false)
    await expect(save()).resolves.toBe(true)

    expect(api.generate.copyPromptTemplate).toHaveBeenCalledTimes(1)
    expect(api.generate.updatePromptTemplate).toHaveBeenCalledTimes(2)
  })

  it("内置模板保存进行中忽略重复提交", async () => {
    const copied = deferred()
    api.generate.copyPromptTemplate.mockReturnValue(copied.promise)
    api.generate.updatePromptTemplate.mockResolvedValue({
      id: "tpl-copy", name: "不带模板", prompt_text: "新提示词", object_template: "none", is_builtin: false, version_number: 2,
    })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    document.getElementById("generate-template-editor-prompt").value = "新提示词"
    const save = showModalHtml.mock.calls[0][2][0].handler

    const first = save()
    await vi.waitFor(() => expect(api.generate.copyPromptTemplate).toHaveBeenCalledOnce())
    await expect(save()).resolves.toBe(false)
    copied.resolve({ id: "tpl-copy", version_number: 1 })
    await expect(first).resolves.toBe(true)

    expect(api.generate.copyPromptTemplate).toHaveBeenCalledOnce()
    expect(api.generate.updatePromptTemplate).toHaveBeenCalledOnce()
  })

  it("creates and selects a new project template", async () => {
    api.generate.createPromptTemplate.mockResolvedValue({
      id: "tpl-new", name: "推理约束", prompt_text: "优先检查时间线",
      object_template: "custom", is_builtin: false, version_number: 1,
    })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    document.getElementById("generate-template-editor-name").value = "推理约束"
    document.getElementById("generate-template-editor-prompt").value = "优先检查时间线"

    const created = await showModalHtml.mock.calls[0][2][1].handler()

    expect(created).not.toBe(false)
    expect(api.generate.createPromptTemplate).toHaveBeenCalledWith({
      novel_id: "p1", name: "推理约束", object_template: "custom", prompt_text: "优先检查时间线",
    })
    await vi.waitFor(() => expect(wrapper.findAll('[data-action="select-object-template"]').some((button) => button.text() === "推理约束")).toBe(true))
  })

  it("keeps the current template modal open for validation and API failures", async () => {
    api.generate.updatePromptTemplate.mockRejectedValue(new Error("update failed"))
    const wrapper = mount(GenerateView, { props: baseProps({
      templates: [{ id: "tpl-1", value: "tpl-1", label: "自定义", prompt: "当前", object_template: "custom", is_builtin: false, version_number: 1 }],
      initialSession: { ...emptyGenerateSession(), selectedTemplateId: "tpl-1" },
    }), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    const save = showModalHtml.mock.calls[0][2][0].handler

    document.getElementById("generate-template-editor-prompt").value = ""
    await expect(save()).resolves.toBe(false)
    document.getElementById("generate-template-editor-prompt").value = "可重试提示词"
    await expect(save()).resolves.toBe(false)

    expect(toast).toHaveBeenCalledWith("请输入模板提示词", "warning")
    expect(toast).toHaveBeenCalledWith("保存模板失败：update failed", "error")
  })

  it("drops a late template create after its modal is replaced", async () => {
    const creation = deferred()
    api.generate.createPromptTemplate.mockReturnValue(creation.promise)
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    document.getElementById("generate-template-editor-name").value = "新模板"
    document.getElementById("generate-template-editor-prompt").value = "新提示词"
    const pending = showModalHtml.mock.calls[0][2][1].handler()
    await vi.waitFor(() => expect(api.generate.createPromptTemplate).toHaveBeenCalled())

    document.getElementById("modal-body").innerHTML = '<div class="replacement-modal">后续弹窗</div>'
    creation.resolve({ id: "tpl-new", name: "新模板", prompt_text: "新提示词", object_template: "custom", is_builtin: false, version_number: 1 })

    await expect(pending).resolves.toBe(true)
    expect(document.querySelector(".replacement-modal").textContent).toBe("后续弹窗")
    expect(wrapper.findAll('[data-action="select-object-template"]').some((button) => button.text() === "新模板")).toBe(false)
    expect(readGenerateSession(generateSessionKey("p1")).selectedTemplateId).toBe("builtin:none")
    expect(toast).not.toHaveBeenCalledWith("新模板已创建", "success")
  })

  it("loads chapter previews in batches of five and enforces the 20 chapter UI cap", async () => {
    const chapters = Array.from({ length: 21 }, (_, index) => ({ id: `draft-${index + 1}`, chapter_index: index + 1, title: `第 ${index + 1} 章` }))
    api.writing.listChapters.mockResolvedValue({ chapters })
    let active = 0
    let maxActive = 0
    api.writing.get.mockImplementation(async (id) => {
      active += 1
      maxActive = Math.max(maxActive, active)
      await Promise.resolve()
      active -= 1
      return { title: id, content: `${id} 正文` }
    })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })

    await wrapper.get('[data-action="select-source-chapters"]').trigger("click")
    await vi.waitFor(() => expect(showModalHtml).toHaveBeenCalledWith(
      "选择附带正文", expect.any(String), expect.any(Array), undefined,
    ))

    expect(maxActive).toBe(5)
    expect(api.writing.get).toHaveBeenCalledTimes(21)
    document.querySelectorAll('.generate-chapter-card input[type="checkbox"]').forEach((input) => { input.checked = true })
    const confirmSelection = showModalHtml.mock.calls.at(-1)[2].find((button) => button.text === "确认选择").handler
    expect(confirmSelection()).toBe(false)
    expect(toast).toHaveBeenCalledWith("每次最多附带 20 章正文", "warning")
  })

  it("does not replace a newer modal when chapter preview prefetch finishes late", async () => {
    const preview = deferred()
    api.writing.listChapters.mockResolvedValue({ chapters: [{ id: "draft-1", chapter_index: 1, title: "第一章" }] })
    api.writing.get.mockReturnValue(preview.promise)
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })

    await wrapper.get('[data-action="select-source-chapters"]').trigger("click")
    await vi.waitFor(() => expect(api.writing.get).toHaveBeenCalledWith("draft-1", "p1"))
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    const editor = document.querySelector(".generate-template-editor")
    preview.resolve({ title: "第一章", content: "晚到正文" })
    await flushPromises()

    expect(showModalHtml).toHaveBeenCalledTimes(1)
    expect(showModalHtml.mock.calls[0][0]).toBe("编辑模板")
    expect(document.getElementById("modal-body").firstElementChild).toBe(editor)
  })

  it("retries transient POV polling failures and finishes the owned task", async () => {
    vi.useFakeTimers()
    try {
      api.outline.listScenesByChapter.mockResolvedValue([{ id: "scene-1", title: "第一场", pov_character_id: "char-1" }])
      confirmAiReference.mockResolvedValue({ id: "confirm-1", user_note: "" })
      api.writing.generate.mockResolvedValue({ task_id: "task-retry" })
      api.tasks.get
        .mockRejectedValueOnce(new Error("temporary network failure"))
        .mockResolvedValueOnce({ status: "running", progress: 0.4 })
        .mockResolvedValueOnce({ status: "done", progress: 1, result: { draft_id: "draft-retry" } })
      const wrapper = mount(GenerateView, { props: baseProps({
        tab: "pov_prose",
        povChapters: [{ chapter_index: 1, title: "旧怨" }],
        povCharacters: [{ entity_id: "char-1", name: "秦岚" }],
      }), attachTo: document.body })
      await wrapper.get("#generate-pov-chapter").setValue("1")
      await flushPromises()
      await wrapper.get("#generate-pov-scene").setValue("scene-1")
      await wrapper.get('[data-action="generate-pov-prose"]').trigger("click")
      await flushPromises()
      expect(api.tasks.get).toHaveBeenCalledTimes(1)

      await vi.advanceTimersByTimeAsync(1500)
      await flushPromises()
      expect(api.tasks.get).toHaveBeenCalledTimes(2)
      expect(wrapper.get("#generate-pov-result").text()).toContain("40%")

      await vi.advanceTimersByTimeAsync(1500)
      await flushPromises()
      expect(api.tasks.get).toHaveBeenCalledTimes(3)
      expect(wrapper.get("#generate-pov-result").text()).toContain("打开并审阅建议")
      expect(toast).toHaveBeenCalledWith("角色视角正文建议已生成", "success")
    } finally {
      vi.useRealTimers()
    }
  })

  it.each([
    ["失败", { status: "failed", error_message: "上游生成失败" }, "上游生成失败"],
    ["取消", { status: "cancelled" }, "角色视角正文生成已取消"],
    ["缺少建议", { status: "done", result: {} }, "任务已完成，但正文建议未能加载"],
  ])("shows the POV %s terminal state instead of leaving an empty result", async (_label, task, expectedMessage) => {
    api.outline.listScenesByChapter.mockResolvedValue([{ id: "scene-1", title: "第一场", pov_character_id: "char-1" }])
    confirmAiReference.mockResolvedValue({ id: "confirm-1", user_note: "" })
    api.writing.generate.mockResolvedValue({ task_id: "task-terminal" })
    api.tasks.get.mockResolvedValue(task)
    const wrapper = mount(GenerateView, { props: baseProps({
      tab: "pov_prose",
      povChapters: [{ chapter_index: 1, title: "旧怨" }],
      povCharacters: [{ entity_id: "char-1", name: "秦岚" }],
    }), attachTo: document.body })
    await wrapper.get("#generate-pov-chapter").setValue("1")
    await vi.waitFor(() => expect(wrapper.findAll("#generate-pov-scene option")).toHaveLength(2))
    await wrapper.get("#generate-pov-scene").setValue("scene-1")
    await wrapper.get('[data-action="generate-pov-prose"]').trigger("click")

    await vi.waitFor(() => expect(wrapper.get("#generate-pov-result").text()).toContain(expectedMessage))
    expect(toast).toHaveBeenCalledWith(`角色视角正文生成失败：${expectedMessage}`, "error")
  })

  it("shows escaped context provenance returned by the generation API", async () => {
    api.generate.worldChat.mockResolvedValue({
      reply: "已生成",
      context_usage: {
        section_key: "world_bible_synopsis", status: "fresh", token_count: 42,
        revision_id: '<img src=x onerror="boom">', source_hash: "source-1",
        block_hash: "block-1", context_snapshot_id: "snapshot-1", stale: false, fallback: false,
      },
    })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })
    await wrapper.get("#generate-chat-input").setValue("审计上下文")
    await wrapper.get('[data-action="send-chat-message"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-action="view-generation-context"]').exists()).toBe(true))
    await wrapper.get('[data-action="view-generation-context"]').trigger("click")

    expect(showModalHtml).toHaveBeenLastCalledWith("本次实际使用的上下文", expect.any(String), [], { size: "large" })
    expect(document.getElementById("modal-body").textContent).toContain('<img src=x onerror="boom">')
    expect(document.getElementById("modal-body").querySelector("img")).toBeNull()
    expect(document.getElementById("modal-body").textContent).toContain("snapshot-1")
  })

  it("copies and exports rendered context with the browser APIs", async () => {
    api.context.compile.mockResolvedValue({ scope: "arc", sections: [], total_tokens: 0 })
    api.context.render.mockResolvedValue({ markdown: "# 审计上下文" })
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } })
    const createObjectURL = vi.fn(() => "blob:context")
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
    const wrapper = mount(GenerateView, { props: baseProps({ tab: "task" }), attachTo: document.body })
    await wrapper.get("#gen-task").setValue("审计上下文")
    await wrapper.get('[data-action="run-task"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-action="render-task-md"]').exists()).toBe(true))
    await wrapper.get('[data-action="render-task-md"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get(".generate-markdown-pre").text()).toBe("# 审计上下文"))

    await wrapper.get('[data-action="copy-task-md"]').trigger("click")
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith("# 审计上下文"))
    await wrapper.get('[data-action="export-task-md"]').trigger("click")

    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob))
    expect(click).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:context")
    expect(toast).toHaveBeenCalledWith("上下文已导出为 Markdown 文件", "success")
    click.mockRestore()
  })

  it("warns when the clipboard API rejects without losing rendered context", async () => {
    api.context.compile.mockResolvedValue({ scope: "arc", sections: [], total_tokens: 0 })
    api.context.render.mockResolvedValue({ markdown: "# 仍可手动复制" })
    const writeText = vi.fn(async () => { throw new Error("clipboard denied") })
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } })
    const wrapper = mount(GenerateView, { props: baseProps({ tab: "task" }), attachTo: document.body })
    await wrapper.get("#gen-task").setValue("复制失败测试")
    await wrapper.get('[data-action="run-task"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-action="render-task-md"]').exists()).toBe(true))
    await wrapper.get('[data-action="render-task-md"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.get(".generate-markdown-pre").text()).toBe("# 仍可手动复制"))

    await wrapper.get('[data-action="copy-task-md"]').trigger("click")
    await vi.waitFor(() => expect(toast).toHaveBeenCalledWith("复制失败，请手动选择复制", "warning"))
    expect(wrapper.get(".generate-markdown-pre").text()).toBe("# 仍可手动复制")
  })

  it("keeps the chapter picker usable when individual preview fetches fail", async () => {
    api.writing.listChapters.mockResolvedValue({ chapters: [
      { id: "draft-broken", chapter_index: 1, title: "回退标题" },
      { chapter_index: 2, title: "摘要标题" },
    ] })
    api.writing.get.mockRejectedValue(new Error("draft unavailable"))
    api.writing.getDraft.mockResolvedValue({ title: "可用工作稿", content: "这是可用的第二章正文" })
    const wrapper = mount(GenerateView, { props: baseProps(), attachTo: document.body })

    await wrapper.get('[data-action="select-source-chapters"]').trigger("click")
    await vi.waitFor(() => expect(showModalHtml).toHaveBeenCalledWith(
      "选择附带正文", expect.any(String), expect.any(Array), undefined,
    ))

    expect(api.writing.get).toHaveBeenCalledWith("draft-broken", "p1")
    expect(api.writing.getDraft).toHaveBeenCalledWith(2, "p1")
    expect(document.getElementById("modal-body").textContent).toContain("回退标题")
    expect(document.getElementById("modal-body").textContent).toContain("暂无正文摘录")
    expect(document.getElementById("modal-body").textContent).toContain("这是可用的第二章正文")
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("加载章节失败"), "error")
  })

  it("drops a late custom-template save after the Generate view unmounts", async () => {
    const update = deferred()
    api.generate.updatePromptTemplate.mockReturnValue(update.promise)
    const wrapper = mount(GenerateView, { props: baseProps({
      templates: [{
        id: "tpl-owned", value: "tpl-owned", label: "当前自定义", prompt: "旧提示词",
        object_template: "custom", is_builtin: false, version_number: 1,
      }],
      initialSession: { ...emptyGenerateSession(), selectedTemplateId: "tpl-owned" },
    }), attachTo: document.body })
    await wrapper.get('[data-action="edit-object-templates"]').trigger("click")
    document.getElementById("generate-template-editor-name").value = "修订名称"
    document.getElementById("generate-template-editor-prompt").value = "修订提示词"
    const pending = showModalHtml.mock.calls[0][2][0].handler()
    await flushPromises()
    expect(api.generate.updatePromptTemplate).toHaveBeenCalledWith("tpl-owned", "p1", {
      name: "修订名称", prompt_text: "修订提示词", template_version: 1,
    })

    wrapper.unmount()
    update.resolve({
      id: "tpl-owned", name: "修订名称", prompt_text: "修订提示词",
      object_template: "custom", is_builtin: false, version_number: 2,
    })
    await expect(pending).resolves.toBe(true)
    expect(readGenerateSession(generateSessionKey("p1")).selectedTemplateId).toBe("tpl-owned")
    expect(toast).not.toHaveBeenCalledWith("模板已保存", "success")
  })

  it("applies an edited full-page proposal only to the owned project draft", async () => {
    api.generate.applyWorldPageDraft.mockResolvedValue({ draft: { id: "draft-page-1", page_id: "page-1" } })
    const result = {
      kind: "world_bible_page",
      suggestion: { id: "suggestion-page-1" },
      proposal: { operation: "replace_existing", page: { title: "旧标题", page_type: "custom", free_text: "概览", sections_json: [], linked_asset_refs_json: [] } },
    }
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sourcePage: { id: "page-1", title: "旧标题", sections_json: [] }, restoredWorldResult: result,
    }), attachTo: document.body })
    await wrapper.get("#generate-page-title").setValue("作者修订标题")
    await wrapper.get('[data-action="apply-world-page-draft"]').trigger("click")
    await vi.waitFor(() => expect(router.navigate).toHaveBeenCalled())
    expect(api.generate.applyWorldPageDraft).toHaveBeenCalledWith(
      "suggestion-page-1",
      expect.objectContaining({ page: expect.objectContaining({ title: "作者修订标题" }) }),
      "p1",
      { signal: expect.any(AbortSignal) },
    )
    expect(router.navigate.mock.calls.at(-1)[3].get("draft_id")).toBe("draft-page-1")
    expect(readCreativeContinuation("p1")).toMatchObject({
      destination: "world_bible_draft",
      route: { draft_id: "draft-page-1", page_id: "page-1" },
    })
  })

  it("应用响应晚到时不清理提交后的新编辑", async () => {
    const applied = deferred()
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const result = {
      kind: "world_bible_page", suggestion: { id: "suggestion-late-edit" },
      proposal: { operation: "replace_existing", page: { title: "初始", page_type: "custom", sections_json: [], linked_asset_refs_json: [] } },
    }
    api.generate.applyWorldPageDraft.mockReturnValue(applied.promise)
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key,
      initialSession: { ...emptyGenerateSession(), suggestionId: "suggestion-late-edit" }, restoredWorldResult: result,
    }), attachTo: document.body })
    await wrapper.get("#generate-page-title").setValue("提交版本")
    const pending = wrapper.get('[data-action="apply-world-page-draft"]').trigger("click")
    await vi.waitFor(() => expect(api.generate.applyWorldPageDraft).toHaveBeenCalled())
    expect(wrapper.get(".generate-page-result").attributes()).toHaveProperty("inert")

    await wrapper.get("#generate-page-title").setValue("响应前新编辑")
    applied.resolve({ draft: { id: "draft-1", page_id: "page-1" } })
    await pending
    await flushPromises()

    expect(readGenerateSession(key).pageProposalDraft?.editor.title).toBe("响应前新编辑")
    expect(router.navigate).toHaveBeenCalled()
  })

  it("页面卸载后仍记录已成功应用的未变提案", async () => {
    const applied = deferred()
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const result = {
      kind: "world_bible_page", suggestion: { id: "suggestion-unmounted" },
      proposal: { operation: "replace_existing", page: { title: "初始", page_type: "custom", sections_json: [], linked_asset_refs_json: [] } },
    }
    api.generate.applyWorldPageDraft.mockReturnValue(applied.promise)
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key,
      initialSession: { ...emptyGenerateSession(), suggestionId: "suggestion-unmounted" }, restoredWorldResult: result,
    }), attachTo: document.body })
    await wrapper.get("#generate-page-title").setValue("已提交编辑")
    const pending = wrapper.get('[data-action="apply-world-page-draft"]').trigger("click")
    await vi.waitFor(() => expect(api.generate.applyWorldPageDraft).toHaveBeenCalled())

    wrapper.unmount()
    applied.resolve({ draft: { id: "draft-1", page_id: "page-1" } })
    await pending
    await flushPromises()

    expect(readGenerateSession(key).pageProposalDraft).toBeNull()
    expect(router.navigate).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalledWith("提案已应用到工作稿，尚未发布", "success")
  })

  it("keeps an edited page proposal in place when the baseline conflicts", async () => {
    api.generate.applyWorldPageDraft.mockRejectedValue(Object.assign(new Error("conflict"), { status: 409 }))
    const result = {
      kind: "world_bible_page",
      suggestion: { id: "suggestion-conflict" },
      proposal: { operation: "replace_existing", page: { title: "旧标题", page_type: "custom", sections_json: [], linked_asset_refs_json: [] } },
    }
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sourcePage: { id: "page-1", title: "旧标题", sections_json: [] }, restoredWorldResult: result,
    }), attachTo: document.body })
    await wrapper.get("#generate-page-title").setValue("尚未应用的作者修订")
    await wrapper.get('[data-action="apply-world-page-draft"]').trigger("click")
    await vi.waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining("未覆盖新修改"), "warning"))
    expect(wrapper.get("#generate-page-title").element.value).toBe("尚未应用的作者修订")
    expect(router.navigate).not.toHaveBeenCalled()
  })

  it("syncs exact page proposal fields and restores them only for the matching pending suggestion", async () => {
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const result = {
      kind: "world_bible_page", suggestion: { id: "suggestion-recover", status: "pending" },
      proposal: { operation: "replace_existing", page: { title: "初始", page_type: "custom", free_text: "初始概览", sections_json: [{ title: "原始" }], linked_asset_refs_json: [] } },
    }
    const first = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key,
      initialSession: { ...emptyGenerateSession(), suggestionId: "suggestion-recover" }, restoredWorldResult: result,
    }), attachTo: document.body })
    await first.get("#generate-page-title").setValue("作者修订")
    await first.get("#generate-page-type").setValue("custom")
    await first.get("#generate-page-free-text").setValue("保留的概览 🐉")
    await first.get("#generate-page-sections").setValue('[{"title":"嵌套","body":{"name":"黎明"}}]')
    await first.get("#generate-page-assets").setValue('[{"asset_id":"潮汐"}]')
    await flushPromises()
    expect(first.find('[data-state="recovered-page-proposal"]').exists()).toBe(false)
    first.unmount()

    let allowDiscard = false
    const restoredConfirm = vi.fn(() => allowDiscard)
    setBridgeOverrides({ confirm: restoredConfirm })
    const second = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key,
      initialSession: readGenerateSession(key), restoredWorldResult: result,
    }), attachTo: document.body })
    expect(second.get('[data-state="recovered-page-proposal"]').text()).toContain("已恢复")
    expect(second.get("#generate-page-title").element.value).toBe("作者修订")
    expect(second.get("#generate-page-free-text").element.value).toBe("保留的概览 🐉")
    expect(second.get("#generate-page-sections").element.value).toBe('[{"title":"嵌套","body":{"name":"黎明"}}]')
    expect(second.get('[data-section="advanced-page-data"]').attributes("open")).toBeUndefined()
    await second.get('[data-subtab="task"]').trigger("click")
    expect(restoredConfirm).toHaveBeenCalledOnce()
    expect(second.get("#generate-page-title").exists()).toBe(true)
    expect(readGenerateSession(key).pageProposalDraft?.editor.title).toBe("作者修订")
    allowDiscard = true
    await second.get('[data-subtab="task"]').trigger("click")
    expect(readGenerateSession(key).pageProposalDraft).toBeNull()

    second.unmount()
    const mismatch = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key,
      initialSession: readGenerateSession(key), restoredWorldResult: { ...result, suggestion: { id: "another-suggestion" } },
    }), attachTo: document.body })
    expect(mismatch.find('[data-state="recovered-page-proposal"]').exists()).toBe(false)
    expect(mismatch.get("#generate-page-title").element.value).toBe("初始")
  })

  it("clears the stored working copy after a successful apply but retains it on 409", async () => {
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const result = {
      kind: "world_bible_page", suggestion: { id: "suggestion-apply" },
      proposal: { operation: "replace_existing", page: { title: "初始", page_type: "custom", sections_json: [], linked_asset_refs_json: [] } },
    }
    api.generate.applyWorldPageDraft.mockRejectedValueOnce(Object.assign(new Error("conflict"), { status: 409 }))
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key,
      initialSession: { ...emptyGenerateSession(), suggestionId: "suggestion-apply" }, restoredWorldResult: result,
    }), attachTo: document.body })
    await wrapper.get("#generate-page-title").setValue("冲突仍保留")
    await wrapper.get('[data-action="apply-world-page-draft"]').trigger("click")
    await flushPromises()
    expect(readGenerateSession(key).pageProposalDraft?.editor.title).toBe("冲突仍保留")

    api.generate.applyWorldPageDraft.mockResolvedValueOnce({ draft: { id: "draft-1", page_id: "page-1" } })
    await wrapper.get('[data-action="apply-world-page-draft"]').trigger("click")
    await vi.waitFor(() => expect(router.navigate).toHaveBeenCalled())
    expect(readGenerateSession(key).pageProposalDraft).toBeNull()
  })

  it("requires an explicit revision choice and only replaces local edits after success", async () => {
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const result = {
      kind: "world_bible_page", suggestion: { id: "suggestion-discard", status: "pending" },
      proposal: { operation: "replace_existing", page: { title: "初始", page_type: "custom", sections_json: [], linked_asset_refs_json: [] } },
    }
    let acceptsDiscard = false
    const confirmDiscard = vi.fn(() => acceptsDiscard)
    setBridgeOverrides({ confirm: confirmDiscard })
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key,
      initialSession: { ...emptyGenerateSession(), suggestionId: "suggestion-discard" }, restoredWorldResult: result,
    }), attachTo: document.body })
    await wrapper.get("#generate-page-title").setValue("先别放弃")
    await wrapper.get("#generate-chat-input").setValue("把这版改成港口制度")
    await wrapper.get('[data-action="generate-another"]').trigger("click")
    const choice = showModalHtml.mock.calls.at(-1)
    expect(choice[0]).toBe("如何继续这个提案？")
    expect(choice[1]).toContain("修订此版")
    expect(choice[1]).toContain("另起方案")
    const revise = choice[2].find((button) => button.text === "修订此版")
    await revise.handler()
    expect(readGenerateSession(key).pageProposalDraft?.editor.title).toBe("先别放弃")
    expect(api.generate.generateWorldSuggestion).not.toHaveBeenCalled()

    acceptsDiscard = true
    api.generate.generateWorldSuggestion.mockResolvedValue({
      result: {
        kind: "world_bible_page",
        suggestion: {
          id: "suggestion-revised",
          status: "pending",
          revision_link: { predecessor_suggestion_id: "suggestion-discard", successor_suggestion_id: null },
        },
        proposal: { operation: "replace_existing", page: { title: "港口制度", page_type: "custom", sections_json: [], linked_asset_refs_json: [] } },
      },
    })
    await revise.handler()
    await vi.waitFor(() => expect(wrapper.get("#generate-page-title").element.value).toBe("港口制度"))
    expect(api.generate.generateWorldSuggestion).toHaveBeenCalledWith(
      expect.objectContaining({ revises_suggestion_id: "suggestion-discard" }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(readGenerateSession(key).pageProposalDraft).toBeNull()
    expect(wrapper.get('[data-state="revision-lineage"]').text()).toContain("上一版 → 当前版")
    expect(wrapper.get('[data-section="revision-comparison"]').text()).toContain("初始")
    expect(wrapper.get('[data-section="revision-comparison"]').text()).toContain("港口制度")
  })

  it("does not let a newly generated suggestion inherit the previous proposal working copy", async () => {
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const oldResult = {
      kind: "world_bible_page", suggestion: { id: "suggestion-old", status: "pending" },
      proposal: { operation: "replace_existing", page: { title: "旧提案", page_type: "custom", sections_json: [], linked_asset_refs_json: [] } },
    }
    const newResult = {
      kind: "world_bible_page", suggestion: { id: "suggestion-new" },
      proposal: { operation: "replace_existing", page: { title: "新提案", page_type: "custom", sections_json: [], linked_asset_refs_json: [] } },
    }
    api.generate.generateWorldSuggestion.mockResolvedValue({ result: newResult })
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key,
      initialSession: { ...emptyGenerateSession(), suggestionId: "suggestion-old" }, restoredWorldResult: oldResult,
    }), attachTo: document.body })
    await wrapper.get("#generate-page-title").setValue("旧编辑不应复活")
    await wrapper.get("#generate-chat-input").setValue("重新生成")
    await wrapper.get('[data-action="generate-world-suggestion"]').trigger("click")
    await showModalHtml.mock.calls.at(-1)[2].find((button) => button.text === "另起方案").handler()
    await vi.waitFor(() => expect(wrapper.get("#generate-page-title").element.value).toBe("新提案"))
    expect(api.generate.generateWorldSuggestion.mock.calls[0][0]).not.toHaveProperty("revises_suggestion_id")
    expect(readGenerateSession(key)).toMatchObject({ suggestionId: "suggestion-new", pageProposalDraft: null })
  })

  it("keeps a stored proposal invisible and non-dirty while result restoration is unavailable", async () => {
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const initialSession = {
      ...emptyGenerateSession(), suggestionId: "suggestion-unavailable",
      pageProposalDraft: { schemaVersion: 1, suggestionId: "suggestion-unavailable", editor: { title: "等待恢复的标题", pageType: "custom", freeText: "", sectionsText: "[]", assetsText: "[]" } },
    }
    writeGenerateSession(key, initialSession)
    const confirmDiscard = vi.fn(() => false)
    setBridgeOverrides({ confirm: confirmDiscard })
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key,
      initialSession: readGenerateSession(key), restoredWorldResult: null,
    }), attachTo: document.body })

    expect(readGenerateSession(key).pageProposalDraft?.editor.title).toBe("等待恢复的标题")
    expect(wrapper.find('[data-state="recovered-page-proposal"]').exists()).toBe(false)
    expect(wrapper.find("#generate-page-title").exists()).toBe(false)
    await wrapper.get('[data-subtab="task"]').trigger("click")
    expect(confirmDiscard).not.toHaveBeenCalled()
  })

  it("clears a stored proposal when a concrete pending result has another suggestion ID", async () => {
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const initialSession = {
      ...emptyGenerateSession(), suggestionId: "suggestion-old",
      pageProposalDraft: { schemaVersion: 1, suggestionId: "suggestion-old", editor: { title: "旧编辑", pageType: "custom", freeText: "", sectionsText: "[]", assetsText: "[]" } },
    }
    writeGenerateSession(key, initialSession)
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key,
      initialSession: readGenerateSession(key),
      restoredWorldResult: { kind: "world_bible_page", suggestion: { id: "suggestion-new", status: "pending" }, proposal: { operation: "replace_existing", page: { title: "新提案", page_type: "custom", sections_json: [], linked_asset_refs_json: [] } } },
    }), attachTo: document.body })

    await flushPromises()
    expect(readGenerateSession(key).pageProposalDraft).toBeNull()
    expect(wrapper.find('[data-state="recovered-page-proposal"]').exists()).toBe(false)
    expect(wrapper.get("#generate-page-title").element.value).toBe("新提案")
  })

  it("retains visible proposal edits when a confirmed revision fails", async () => {
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const result = {
      kind: "world_bible_page", suggestion: { id: "suggestion-regenerate", status: "pending" },
      proposal: { operation: "replace_existing", page: { title: "原提案", page_type: "custom", sections_json: [{ title: "原始分区" }], linked_asset_refs_json: [] } },
    }
    const confirmDiscard = vi.fn(() => true)
    api.generate.generateWorldSuggestion.mockRejectedValue(Object.assign(new Error("baseline changed"), { status: 409 }))
    setBridgeOverrides({ confirm: confirmDiscard })
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key,
      initialSession: { ...emptyGenerateSession(), suggestionId: "suggestion-regenerate" }, restoredWorldResult: result,
    }), attachTo: document.body })
    await wrapper.get("#generate-page-title").setValue("放弃的标题")
    await wrapper.get("#generate-page-sections").setValue('[{"title":"放弃的分区"}]')
    await wrapper.get("#generate-chat-input").setValue("再生成一次")
    await wrapper.get('[data-action="generate-world-suggestion"]').trigger("click")
    await showModalHtml.mock.calls.at(-1)[2].find((button) => button.text === "修订此版").handler()
    await vi.waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining("当前对话和编辑仍保留"), "warning"))

    expect(wrapper.get("#generate-page-title").element.value).toBe("放弃的标题")
    expect(wrapper.get("#generate-page-sections").element.value).toBe('[{"title":"放弃的分区"}]')
    expect(readGenerateSession(key).pageProposalDraft?.editor.title).toBe("放弃的标题")
    await wrapper.get('[data-subtab="task"]').trigger("click")
    expect(confirmDiscard).toHaveBeenCalledTimes(2)
  })

  it("keeps visible fields and the dirty guard when regeneration discard is rejected", async () => {
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const result = {
      kind: "world_bible_page", suggestion: { id: "suggestion-reject-regenerate", status: "pending" },
      proposal: { operation: "replace_existing", page: { title: "原提案", page_type: "custom", sections_json: [], linked_asset_refs_json: [] } },
    }
    const confirmDiscard = vi.fn(() => false)
    setBridgeOverrides({ confirm: confirmDiscard })
    const wrapper = mount(GenerateView, { props: baseProps({
      targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key,
      initialSession: { ...emptyGenerateSession(), suggestionId: "suggestion-reject-regenerate" }, restoredWorldResult: result,
    }), attachTo: document.body })
    await wrapper.get("#generate-page-title").setValue("仍保留的标题")
    await wrapper.get("#generate-chat-input").setValue("尝试重新生成")
    await wrapper.get('[data-action="generate-world-suggestion"]').trigger("click")
    await showModalHtml.mock.calls.at(-1)[2].find((button) => button.text === "修订此版").handler()
    expect(wrapper.get("#generate-page-title").element.value).toBe("仍保留的标题")
    expect(readGenerateSession(key).pageProposalDraft?.editor.title).toBe("仍保留的标题")
    await wrapper.get('[data-subtab="task"]').trigger("click")
    expect(confirmDiscard).toHaveBeenCalledTimes(2)
    expect(wrapper.get("#generate-page-title").exists()).toBe(true)
  })

  it("does not send an apply request for recovered invalid JSON", async () => {
    const key = generateSessionKey("p1", "page-1", "world_bible_page")
    const result = {
      kind: "world_bible_page", suggestion: { id: "suggestion-invalid-json", status: "pending" },
      proposal: { operation: "replace_existing", page: { title: "初始", page_type: "custom", sections_json: [], linked_asset_refs_json: [] } },
    }
    const initialSession = {
      ...emptyGenerateSession(), suggestionId: "suggestion-invalid-json",
      pageProposalDraft: { schemaVersion: 1, suggestionId: "suggestion-invalid-json", editor: { title: "仍可编辑", pageType: "custom", freeText: "", sectionsText: "{broken", assetsText: "[]" } },
    }
    const wrapper = mount(GenerateView, { props: baseProps({ targetKind: "world_bible_page", sourcePageId: "page-1", sessionKey: key, initialSession, restoredWorldResult: result }), attachTo: document.body })
    await wrapper.get('[data-action="apply-world-page-draft"]').trigger("click")
    expect(wrapper.text()).toContain("不是有效 JSON")
    expect(api.generate.applyWorldPageDraft).not.toHaveBeenCalled()
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import SceneWorkbenchView from "../../../vue/views/scene/SceneWorkbenchView.vue"
import { sceneRuntimeManager } from "../../../vue/views/scene/sceneRuntimeManager.js"
import {
  persistSceneRuntimeDraft,
  resetSceneRuntimeSession,
  sceneRuntimeDraftKey,
  sceneRuntimeSession,
} from "../../../vue/views/scene/sceneRuntimeSession.js"

const payload = {
  total: 2,
  skip: 0,
  health: {
    unreviewed: { label: "未复核", count: 0 },
    unassigned: { label: "未关联章节", count: 0 },
    missing_setup: { label: "缺设定", count: 0 },
    needs_organize: { label: "待整理", count: 0, breakdown: {} },
  },
  progress: { as_of_chapter: 2, current: 1, upcoming: 1, past: 0, unassigned: 0 },
  unassigned_chapters: [],
  fusion_suggestions: { pending_count: 0 },
  items: [
    {
      scene: {
        id: "s1", scene_index: 0, title: "潜入", status: "draft", source: "manual",
        narrative_tag: "draft", goal: "找到入口", core_conflict: "守卫巡查",
        must_happen: "留下线索", must_not_happen: "不能暴露", chapter_ids: ["1"], structure_meta: {},
      },
      health: [], chapter_range: "第 1 章", summary: "潜入",
    },
    {
      scene: {
        id: "s2", scene_index: 1, title: "撤离", status: "draft", source: "manual",
        narrative_tag: "transition", goal: "安全离开", core_conflict: "追兵", chapter_ids: ["2"], structure_meta: {},
      },
      health: [], chapter_range: "第 2 章", summary: "撤离",
    },
  ],
}

describe("Story Scene workspace panels", () => {
  let wrapper
  let story
  let state
  let router
  let tasks
  let toast

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    resetSceneRuntimeSession("p1", "s1")
    resetSceneRuntimeSession("p1", "s2")
    sceneRuntimeManager.resetMemory()
    window.history.replaceState({}, "", "#workbench/p1/outline/scenes")
    state = {
      currentProjectId: "p1",
      currentView: "outline",
      currentSubView: "scenes",
      viewStates: {},
    }
    router = {
      getCurrentQuery: vi.fn(() => {
        const index = window.location.hash.indexOf("?")
        return new URLSearchParams(index >= 0 ? window.location.hash.slice(index + 1) : "")
      }),
      commitCurrentQuery: vi.fn((query, mode = "replace") => {
        const base = "#workbench/p1/outline/scenes"
        window.history[mode === "push" ? "pushState" : "replaceState"]({}, "", query.toString() ? `${base}?${query}` : base)
        return true
      }),
      navigate: vi.fn(),
    }
    story = {
      getSceneContext: vi.fn().mockResolvedValue({ character_cards: [], script_files: [] }),
      listCharacterCards: vi.fn().mockResolvedValue({ items: [], total: 0 }),
      listSceneScripts: vi.fn().mockResolvedValue({ items: [], total: 0 }),
      listSceneScriptRevisions: vi.fn().mockResolvedValue([]),
      startOneClickTask: vi.fn(),
      startReactionTask: vi.fn(),
      startScriptTask: vi.fn(),
      startCharacterCardTask: vi.fn(),
      startSceneSimulation: vi.fn(),
      saveSceneScript: vi.fn().mockResolvedValue({ status: "saved" }),
      saveCharacterCard: vi.fn(),
      listCharacterCardRevisions: vi.fn().mockResolvedValue([]),
      restoreCharacterCardRevision: vi.fn(),
      adoptSceneScriptRevision: vi.fn(),
      unadoptSceneScriptFile: vi.fn(),
    }
    tasks = { get: vi.fn(), cancel: vi.fn() }
    toast = vi.fn()
    const api = {
      outline: {
        getSceneWorkbench: vi.fn().mockResolvedValue(payload),
        listFusionSuggestions: vi.fn().mockResolvedValue({ items: [], total: 0 }),
        updateScene: vi.fn().mockResolvedValue({ id: "s1" }),
      },
      world: { listEntities: vi.fn().mockResolvedValue({ items: [], total: 0 }) },
      story,
      tasks,
      imports: { startStage: vi.fn() },
    }
    setBridgeOverrides({ api, state, router, toast, showModalHtml: vi.fn(), closeModal: vi.fn(), esc: (value) => String(value ?? "") })
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    sceneRuntimeManager.resetMemory()
    resetBridgeOverrides()
  })

  function createWrapper(extra = {}) {
    wrapper = mount(SceneWorkbenchView, {
      attachTo: document.body,
      props: { projectId: "p1", workbench: payload, viewMode: "hot", sceneFilters: {}, ...extra },
    })
    return wrapper
  }

  it("keeps management as the first tab and switches panels without a new route", async () => {
    createWrapper()
    expect(wrapper.get('[data-action="scene-runtime-tab-management"]').attributes("aria-selected")).toBe("true")
    expect(wrapper.find('[data-action="select-workbench-scene"]').exists()).toBe(true)

    await wrapper.get('[data-action="select-workbench-scene"]').trigger("click")
    await wrapper.get('[data-action="scene-runtime-tab-characters"]').trigger("click")
    await flushPromises()

    expect(wrapper.find(".scene-character-cards-panel").exists()).toBe(true)
    expect(window.location.hash).toContain("scene_id=s1")
    expect(window.location.hash).toContain("tab=characters")
    expect(router.navigate).not.toHaveBeenCalled()

    await wrapper.get('[data-action="scene-runtime-tab-management"]').trigger("click")
    expect(wrapper.find(".scene-workbench-list").exists()).toBe(true)
  })

  it("shows an empty state before a scene is selected and a loading state while cards resolve", async () => {
    let resolveContext
    story.getSceneContext.mockImplementation(() => new Promise((resolve) => { resolveContext = resolve }))
    createWrapper()
    await wrapper.get('[data-action="scene-runtime-tab-characters"]').trigger("click")
    expect(wrapper.get('[data-role="scene-runtime-character-empty"]').text()).toContain("先从“管理”选择")

    await wrapper.get('[data-action="scene-runtime-tab-management"]').trigger("click")
    await wrapper.get('[data-action="select-workbench-scene"]').trigger("click")
    await wrapper.get('[data-action="scene-runtime-tab-characters"]').trigger("click")
    expect(wrapper.get(".scene-runtime-loading").text()).toContain("加载")
    resolveContext({ character_cards: [{ character_id: "c1", name: "阿遥", content: { personality: "谨慎" } }] })
    await flushPromises()
    expect(wrapper.get(".scene-character-cards").text()).toContain("阿遥")
  })

  it("restores a project-and-scene scoped script draft", async () => {
    persistSceneRuntimeDraft("p1", "s1", { scriptDraft: "本场留下的草稿" })
    createWrapper({ selectedSceneId: "s1" })
    await wrapper.get('[data-action="scene-runtime-tab-script"]').trigger("click")
    await flushPromises()

    expect(wrapper.get('[data-action="scene-script-draft-input"]').element.value).toBe("本场留下的草稿")
    expect(wrapper.find(".scene-scripts-panel").text()).toContain("正式正文继续在写作页维护")
  })

  it("loads the saved script revision when no local draft exists", async () => {
    story.getSceneContext.mockResolvedValue({
      character_cards: [],
      script_files: [{ file_id: "file-1", file_key: "main", title: "主稿", revision: { id: "rev-1", content: "服务端已保存的剧本" } }],
    })
    createWrapper({ selectedSceneId: "s1" })
    await wrapper.get('[data-action="scene-runtime-tab-script"]').trigger("click")
    await flushPromises()

    expect(wrapper.get('[data-action="scene-script-draft-input"]').element.value).toBe("服务端已保存的剧本")
  })

  it("shows narrative character state instead of persistence lifecycle", async () => {
    story.getSceneContext.mockResolvedValue({
      character_cards: [{ character_id: "c1", name: "阿遥", status: "active", content: { personality: "谨慎", current_state: "带伤潜伏" } }],
      script_files: [],
    })
    createWrapper({ selectedSceneId: "s1" })
    await wrapper.get('[data-action="scene-runtime-tab-characters"]').trigger("click")
    await flushPromises()

    expect(wrapper.get(".scene-character-card__facts").text()).toContain("带伤潜伏")
    expect(wrapper.get(".scene-character-card__facts").text()).not.toContain("active")
  })

  it("persists generated character-card provenance after the suggestion is applied", async () => {
    story.getSceneContext.mockResolvedValue({
      character_cards: [{ character_id: "c1", name: "阿遥", content: { personality: "谨慎" } }],
      script_files: [],
    })
    story.saveCharacterCard.mockResolvedValue({
      id: "card-1", character_id: "c1", current_revision_id: "rev-1",
      revision: { id: "rev-1", content: { personality: "更谨慎" } },
    })
    createWrapper({ selectedSceneId: "s1" })
    await wrapper.get('[data-action="scene-runtime-tab-characters"]').trigger("click")
    await flushPromises()
    await wrapper.get('[data-action="edit-scene-character-c1"]').trigger("click")
    tasks.get.mockResolvedValue({
      task_id: "task-card-1",
      status: "done",
      result: {
        context_snapshot_id: "snapshot-card-1",
        preview: { content: { personality: "更谨慎" } },
      },
    })
    sceneRuntimeManager.adopt(
      { task_id: "task-card-1", status: "pending" },
      { sceneId: "s1", stage: "character-card" },
      "p1",
      "s1",
    )
    await vi.waitFor(() => expect(wrapper.find('[data-action="apply-generated-scene-character-card"]').exists()).toBe(true))
    await wrapper.get('[data-action="apply-generated-scene-character-card"]').trigger("click")
    await wrapper.get('[data-action="save-scene-character-card"]').trigger("click")
    await flushPromises()

    expect(story.saveCharacterCard).toHaveBeenCalledWith("p1", "s1", "c1", expect.objectContaining({
      source_task_id: "task-card-1",
      context_snapshot_id: "snapshot-card-1",
    }))
  })

  it("stores a genuinely bounded multi-file draft while keeping the active draft", () => {
    const activeDraft = "甲".repeat(200000)
    persistSceneRuntimeDraft("p1", "s1", {
      activeScriptFileId: "file-2",
      scriptDraft: activeDraft,
      scriptDrafts: { "file-1": "乙".repeat(200000), "file-2": activeDraft },
    })

    const raw = localStorage.getItem(sceneRuntimeDraftKey("p1", "s1"))
    expect(raw.length).toBeLessThanOrEqual(256 * 1024)
    resetSceneRuntimeSession("p1", "s1")
    expect(sceneRuntimeSession("p1", "s1").scriptDraft).toBe(activeDraft)
  })

  it("keeps the Scene script in memory and reports whether local persistence really succeeded", () => {
    const originalSetItem = localStorage.setItem.bind(localStorage)
    const storage = vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
      if (String(key).startsWith("scene_runtime_draft:")) {
        throw new DOMException("quota", "QuotaExceededError")
      }
      return originalSetItem(key, value)
    })

    const failed = persistSceneRuntimeDraft("p1", "s1", { scriptDraft: "只留在内存的剧本" })
    expect(failed.backupComplete).toBe(false)
    expect(sceneRuntimeSession("p1", "s1")).toMatchObject({
      scriptDraft: "只留在内存的剧本",
      backupComplete: false,
    })
    expect(localStorage.getItem(sceneRuntimeDraftKey("p1", "s1"))).toBeNull()

    storage.mockRestore()
    const recovered = persistSceneRuntimeDraft("p1", "s1", { scriptDraft: "只留在内存的剧本" })
    expect(recovered.backupComplete).toBe(true)
    expect(localStorage.getItem(sceneRuntimeDraftKey("p1", "s1"))).toContain("只留在内存的剧本")
  })

  it("剧本服务和本地备份都失败时不显示已保存并保留当前输入", async () => {
    const originalSetItem = localStorage.setItem.bind(localStorage)
    const storage = vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
      if (String(key).startsWith("scene_runtime_draft:")) {
        throw new DOMException("quota", "QuotaExceededError")
      }
      return originalSetItem(key, value)
    })
    story.saveSceneScript.mockRejectedValueOnce(new Error("剧本服务断开"))
    createWrapper({ selectedSceneId: "s1" })
    await wrapper.get('[data-action="scene-runtime-tab-script"]').trigger("click")
    await flushPromises()
    await wrapper.get('[data-action="scene-script-draft-input"]').setValue("无法备份的剧本正文")

    expect(wrapper.get('[role="alert"]').text()).toContain("本地暂存不可用")
    expect(wrapper.text()).not.toContain("草稿已保存")
    await wrapper.get('[data-action="save-scene-script-draft"]').trigger("click")
    await flushPromises()

    expect(toast).toHaveBeenLastCalledWith(
      "剧本服务断开；本地备份不可用，离开或刷新会丢失未保存修改",
      "error",
    )
    expect(wrapper.get('[data-action="scene-script-draft-input"]').element.value).toBe("无法备份的剧本正文")
    expect(wrapper.text()).not.toContain("草稿已保存")

    storage.mockRestore()
  })

  it("restores preview provenance, sends it when saving, and clears it after manual edits", async () => {
    story.getSceneContext.mockResolvedValue({
      character_cards: [{ character_id: "c1", name: "阿遥", content: { personality: "谨慎" } }],
      script_files: [{ file_id: "file-1", file_key: "main", title: "主稿", revision: { id: "rev-1", content: "已有剧本" } }],
    })
    story.saveSceneScript.mockResolvedValue({
      file_id: "file-1",
      file_key: "main",
      title: "主稿",
      current_revision_id: "rev-2",
      revision: { id: "rev-2", content: "预览内容" },
    })
    persistSceneRuntimeDraft("p1", "s1", {
      scriptDraft: "预览内容",
      scriptPreview: { content: "预览内容", sourceTaskId: "task-script-1", contextSnapshotId: "snapshot-1" },
      scriptDraftSource: { sourceTaskId: "task-script-1", contextSnapshotId: "snapshot-1" },
    })
    createWrapper({ selectedSceneId: "s1" })
    await wrapper.get('[data-action="scene-runtime-tab-script"]').trigger("click")
    await flushPromises()

    expect(wrapper.find(".scene-script-preview").exists()).toBe(true)
    await wrapper.get('[data-action="save-scene-script-draft"]').trigger("click")
    await flushPromises()
    expect(story.saveSceneScript).toHaveBeenLastCalledWith("p1", "s1", expect.objectContaining({
      source_task_id: "task-script-1",
      context_snapshot_id: "snapshot-1",
      provenance: expect.objectContaining({ source_task_id: "task-script-1", context_snapshot_id: "snapshot-1" }),
    }))

    await wrapper.get('[data-action="scene-script-draft-input"]').setValue("作者手改后的剧本")
    await wrapper.get('[data-action="save-scene-script-draft"]').trigger("click")
    await flushPromises()
    const manualPayload = story.saveSceneScript.mock.calls.at(-1)[2]
    expect(manualPayload).not.toHaveProperty("source_task_id")
    expect(manualPayload).not.toHaveProperty("context_snapshot_id")
    expect(manualPayload.provenance).not.toHaveProperty("source_task_id")
    expect(manualPayload.provenance).not.toHaveProperty("context_snapshot_id")
  })

  it("keeps a readable error state when Story and World sources are unavailable", async () => {
    story.getSceneContext.mockRejectedValue(new Error("资料服务暂不可用"))
    story.listCharacterCards.mockRejectedValue(new Error("人物卡读取失败"))
    story.listSceneScripts.mockRejectedValue(new Error("剧本读取失败"))
    const api = { world: { listEntities: vi.fn().mockRejectedValue(new Error("世界资料读取失败")) } }
    setBridgeOverrides({
      api: {
        ...api,
        outline: {
          getSceneWorkbench: vi.fn().mockResolvedValue(payload),
          listFusionSuggestions: vi.fn().mockResolvedValue({ items: [], total: 0 }),
          updateScene: vi.fn().mockResolvedValue({ id: "s1" }),
        },
        story,
        tasks: { get: vi.fn(), cancel: vi.fn() },
        imports: { startStage: vi.fn() },
      },
      state,
      router,
      toast: vi.fn(),
      showModalHtml: vi.fn(),
      closeModal: vi.fn(),
      esc: (value) => String(value ?? ""),
    })
    createWrapper({ selectedSceneId: "s1" })
    await wrapper.get('[data-action="scene-runtime-tab-characters"]').trigger("click")
    await flushPromises()

    expect(wrapper.get(".scene-runtime-error").text()).toContain("资料服务暂不可用")
  })

  it("ignores a late character response after switching to another scene", async () => {
    let resolveFirst
    story.getSceneContext.mockImplementation((_projectId, sceneId) => (
      sceneId === "s1"
        ? new Promise((resolve) => { resolveFirst = resolve })
        : Promise.resolve({ character_cards: [{ character_id: "c2", name: "阿衡", content: { personality: "果断" } }] })
    ))
    createWrapper({ selectedSceneId: "s1" })
    await wrapper.get('[data-action="scene-runtime-tab-characters"]').trigger("click")
    await wrapper.get('[data-action="scene-runtime-tab-management"]').trigger("click")
    await wrapper.get('.scene-workbench-row[data-id="s2"] [data-action="select-workbench-scene"]').trigger("click")
    await wrapper.get('[data-action="scene-runtime-tab-characters"]').trigger("click")
    await flushPromises()
    resolveFirst({ character_cards: [{ character_id: "c1", name: "晚到的人物", content: { personality: "不应覆盖" } }] })
    await flushPromises()

    expect(wrapper.get(".scene-character-cards").text()).toContain("阿衡")
    expect(wrapper.get(".scene-character-cards").text()).not.toContain("晚到的人物")
  })

  it("uses the authorized one-click Story task and never fabricates a local preview", async () => {
    story.getSceneContext.mockResolvedValue({
      character_cards: [{ character_id: "c1", name: "阿遥", content: { personality: "谨慎" } }],
      script_files: [],
    })
    story.startOneClickTask.mockResolvedValue({
      task_id: "task-one-click",
      status: "pending",
    })
    createWrapper()
    await wrapper.get('[data-action="select-workbench-scene"]').trigger("click")
    await wrapper.get('[data-action="scene-runtime-tab-simulation"]').trigger("click")
    await flushPromises()
    expect(wrapper.get('[data-action="run-scene-simulation"]').text()).toContain("推演并补齐人物卡")
    expect(wrapper.get(".scene-simulation-panel").text()).toContain("人物反应与剧本仍只作为待确认预览，不会自动保存")
    await wrapper.get('[data-action="run-scene-simulation"]').trigger("click")
    await flushPromises()

    expect(story.startOneClickTask).toHaveBeenCalledWith(expect.objectContaining({
      submit_authorized: true,
      scene_id: "s1",
      character_ids: ["c1"],
    }))
    expect(wrapper.find(".scene-reaction-card").exists()).toBe(false)
  })

  it("keeps a clear error and no fake reactions when the Story task is unavailable", async () => {
    story.getSceneContext.mockResolvedValue({
      character_cards: [{ character_id: "c1", name: "阿遥", content: { personality: "谨慎" } }],
      script_files: [],
    })
    const error = Object.assign(new Error("Story 服务暂不可用"), { status: 404 })
    story.startOneClickTask.mockRejectedValue(error)
    createWrapper()
    await wrapper.get('[data-action="select-workbench-scene"]').trigger("click")
    await wrapper.get('[data-action="scene-runtime-tab-simulation"]').trigger("click")
    await flushPromises()
    await wrapper.get('[data-action="run-scene-simulation"]').trigger("click")
    await flushPromises()

    expect(wrapper.get(".scene-runtime-error").text()).toContain("Story 服务暂不可用")
    expect(wrapper.find(".scene-reaction-card").exists()).toBe(false)
  })

  it("does not turn a full-world character response into scene characters", async () => {
    story.getSceneContext.mockResolvedValue({ character_cards: [], script_files: [] })
    const api = {
      outline: {
        getSceneWorkbench: vi.fn().mockResolvedValue(payload),
        listFusionSuggestions: vi.fn().mockResolvedValue({ items: [], total: 0 }),
        updateScene: vi.fn().mockResolvedValue({ id: "s1" }),
      },
      world: { listEntities: vi.fn().mockResolvedValue({ items: [{ id: "global", name: "全书人物" }], total: 1 }) },
      story,
      tasks: { get: vi.fn(), cancel: vi.fn() },
      imports: { startStage: vi.fn() },
    }
    setBridgeOverrides({ api, state, router, toast: vi.fn(), showModalHtml: vi.fn(), closeModal: vi.fn(), esc: (value) => String(value ?? "") })
    createWrapper()
    await wrapper.get('[data-action="select-workbench-scene"]').trigger("click")
    await wrapper.get('[data-action="scene-runtime-tab-characters"]').trigger("click")
    await flushPromises()

    expect(wrapper.get(".scene-runtime-empty").text()).toContain("还没有人物卡")
    expect(wrapper.find(".scene-character-card").exists()).toBe(false)
  })
})

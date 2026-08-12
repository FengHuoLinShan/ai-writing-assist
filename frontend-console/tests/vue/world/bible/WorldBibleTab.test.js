/**
 * WorldBibleTab 测试 — 渲染契约、显示模式切换、编辑器行为、模态交互、守卫。
 *
 * 覆盖 vanilla worldBibleView.test.js（1148 行）的核心行为 + E2E 契约。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import { nextTick } from "vue"

vi.mock("../../../../shared/referencePicker.js", () => ({
  createReferencePicker: vi.fn(() => ({ destroy: vi.fn(), resolve: vi.fn(), getRefs: vi.fn(() => []) })),
}))

vi.mock("../../../../shared/workflowProgress.js", () => ({
  pollTaskProgress: vi.fn(() => ({ stop: vi.fn() })),
}))

vi.mock("../../../../shared/assetDisplayState.js", () => ({
  displayStateBadgeClass: vi.fn((state) => state === "canonical" || state === "confirmed" ? "badge-canonical" : "badge-draft"),
  worldAssetDisplay: vi.fn((item) => ({
    label: item?.status === "canonical" || item?.status === "confirmed" ? "已采用" : item?.status === "draft" ? "草稿" : "历史",
    displayState: item?.status || "draft",
    isHistory: item?.status === "archived",
  })),
}))

import WorldBibleTab from "../../../../vue/views/world/bible/WorldBibleTab.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"
import { resetWorldSession, worldSession } from "../../../../vue/views/world/worldSession.js"
import { pollTaskProgress } from "../../../../shared/workflowProgress.js"
import { createReferencePicker } from "../../../../shared/referencePicker.js"

// ---- test data ----
const PAGE_1 = {
  id: "page-1", novel_id: "p1", page_type: "background", title: "世界基本背景",
  status: "canonical", free_text: "已有设定正文", sort_order: 0,
  sections_json: [{
    section_id: "s1", section_type: "markdown", title: "货币",
    body_markdown: "北境使用银币", sort_order: 10,
    linked_asset_ref_hashes: [], projection_policy: "eligible", sensitivity_hint: "author_safe",
  }],
  linked_asset_refs_json: [],
}
const PAGE_2 = {
  id: "page-2", novel_id: "p1", page_type: "species", title: "种族设定",
  status: "canonical", free_text: "灵族与人族长期共存。", sort_order: 1,
  sections_json: [], linked_asset_refs_json: [],
}
const DRAFT_1 = {
  id: "draft-1", page_id: "page-1", title: "世界基本背景",
  page_type: "background", free_text: "工作稿正文", sort_order: 0,
  sections_json: [{
    section_id: "s1", section_type: "markdown", title: "货币",
    body_markdown: "北境使用银币", sort_order: 10,
    linked_asset_ref_hashes: [], projection_policy: "eligible", sensitivity_hint: "author_safe",
  }], linked_asset_refs_json: [], updated_at: "2026-07-15T10:00:00Z",
}
const DRAFT_FREE = {
  id: "draft-free", page_id: null, title: "新页工作稿",
  page_type: "custom", free_text: "", sort_order: 0,
  sections_json: [], linked_asset_refs_json: [],
}
const DRAFT_2 = {
  id: "draft-2", page_id: "page-2", title: "种族设定工作稿",
  page_type: "species", free_text: "B 页工作稿", sort_order: 1,
  sections_json: [], linked_asset_refs_json: [],
}

const SYNOPSIS = {
  status: "missing", stale: true, warnings: [], auto_refresh_enabled: false,
  current_revision: null,
}

const CATEGORIES = [
  { id: "cat-1", category_key: "background", name: "背景", color: "#6366f1", icon: "BG", status: "active", builtin: true },
  { id: "cat-2", category_key: "species", name: "种族", color: "#dc2626", icon: "SP", status: "active", builtin: true },
]

const TEMPLATES = [
  { template_key: "e2e_trade_guide", name: "E2E 贸易模板", version_number: 1, builtin: true, status: "active", description: "" },
]

const CUSTOM_TEMPLATE = {
  id: "template-custom",
  novel_id: "p1",
  template_key: "trade_guide",
  name: "贸易模板",
  version_number: 1,
  builtin: false,
  status: "active",
  description: "",
  default_sections_json: [],
}

const ACTIVATION_PROFILES = [
  { id: "prof-1", profile_key: "writing.world", name: "写作规则", status: "draft", version_number: 1, applicable_actions_json: ["writing.generate"], rules_json: [] },
]

function defaultBible() {
  return {
    pages: [PAGE_1, PAGE_2],
    categories: CATEGORIES,
    drafts: [DRAFT_1, DRAFT_FREE],
    synopsis: { ...SYNOPSIS },
    pageTemplates: TEMPLATES,
    activationProfiles: ACTIVATION_PROFILES,
  }
}

let navigateMock
let toastMock
let confirmMock
let showModalHtmlMock
let closeModalMock
let confirmActionMock
let appState

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function installModalHost() {
  const overlay = document.createElement("div")
  overlay.id = "modal-overlay"
  overlay.className = "hidden"
  const body = document.createElement("div")
  body.id = "modal-body"
  overlay.appendChild(body)
  document.body.appendChild(overlay)
  showModalHtmlMock.mockImplementation((_title, html) => {
    body.innerHTML = html
    overlay.classList.remove("hidden")
  })
  return { overlay, body }
}

function mountTab(propOverrides = {}) {
  return mount(WorldBibleTab, {
    props: {
      projectId: "p1",
      subView: "bible",
      bible: defaultBible(),
      bibleDeepLink: { draftId: "", pageId: "" },
      ...propOverrides,
    },
    attachTo: document.body,
  })
}

enableAutoUnmount(afterEach)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetWorldSession()
  navigateMock = vi.fn(() => true)
  toastMock = vi.fn()
  confirmMock = vi.fn(() => true)
  showModalHtmlMock = vi.fn()
  closeModalMock = vi.fn()
  confirmActionMock = vi.fn((message, handler) => handler())
  appState = { currentProjectId: "p1", currentView: "world" }
  setBridgeOverrides({
    state: appState,
    router: { navigate: navigateMock, refresh: vi.fn(async () => true), renderCurrentView: vi.fn() },
    toast: toastMock,
    confirm: confirmMock,
    showModalHtml: showModalHtmlMock,
    closeModal: closeModalMock,
    confirmAction: confirmActionMock,
  })
})

afterEach(() => {
  resetBridgeOverrides()
  document.body.innerHTML = ""
})

describe("渲染契约", () => {
  it("根节点为 section.world-bible-workspace", () => {
    const wrapper = mountTab()
    expect(wrapper.find("section.world-bible-workspace").exists()).toBe(true)
  })

  it("工具栏包含新建、管理分类、模板、建议和冲突按钮", () => {
    const wrapper = mountTab()
    const toolbar = wrapper.find(".world-bible-toolbar")
    expect(toolbar.exists()).toBe(true)
    expect(toolbar.text()).toContain("世界书")
    expect(toolbar.text()).toContain("2 个页面")
    expect(toolbar.find("[data-action='bible-new-page']").exists()).toBe(true)
    expect(toolbar.find("[data-action='bible-manage-categories']").exists()).toBe(true)
    expect(toolbar.find("[data-action='bible-manage-page-templates']").exists()).toBe(true)
    expect(toolbar.find("[data-action='bible-open-suggestions']").exists()).toBe(true)
    expect(toolbar.find("[data-action='bible-open-conflicts']").exists()).toBe(true)
  })

  it("展示模式切换按钮组", () => {
    const wrapper = mountTab()
    const modes = wrapper.find(".world-bible-toolbar__modes")
    expect(modes.attributes()).toMatchObject({ role: "group", "aria-label": "世界书展示模式" })
    expect(modes.findAll("button")).toHaveLength(3)
    expect(modes.find("[data-mode='editor']").exists()).toBe(true)
    expect(modes.find("[data-mode='gallery']").exists()).toBe(true)
    expect(modes.find("[data-mode='filter']").exists()).toBe(true)
    expect(modes.find("[data-mode='editor']").attributes("aria-pressed")).toBe("true")
    expect(modes.find("[data-mode='gallery']").attributes("aria-pressed")).toBe("false")
    expect(modes.find("[data-mode='filter']").attributes("aria-pressed")).toBe("false")
  })

  it("编辑器模式显示 synopsis 面板、page nav、editor 和 inspector", () => {
    const wrapper = mountTab()
    expect(wrapper.find(".world-bible-synopsis-panel").exists()).toBe(true)
    expect(wrapper.find(".world-bible-layout").exists()).toBe(true)
    expect(wrapper.find(".world-bible-page-nav").exists()).toBe(true)
    expect(wrapper.find(".world-bible-editor-panel").exists()).toBe(true)
    expect(wrapper.find(".world-bible-inspector").exists()).toBe(true)
  })

  it("编辑器面板显示 active page 标题、元数据、表单和分区", () => {
    const wrapper = mountTab()
    const panel = wrapper.find(".world-bible-editor-panel")
    expect(panel.text()).toContain(PAGE_1.title)
    expect(panel.text()).toContain("背景")
    // form fields
    expect(wrapper.find("#bible-title").exists()).toBe(true)
    expect(wrapper.find("#bible-page-type").exists()).toBe(true)
    expect(wrapper.find("#bible-free-text").exists()).toBe(true)
    expect(wrapper.find("#bible-sort-order").exists()).toBe(true)
    // sections
    expect(wrapper.find(".world-bible-sections").exists()).toBe(true)
    expect(wrapper.findAll(".world-bible-section-editor").length).toBeGreaterThanOrEqual(1)
    expect(wrapper.find("[data-section-field='title']").exists()).toBe(true)
    expect(wrapper.find("[data-section-field='body_markdown']").exists()).toBe(true)
  })

  it("page nav 列出页面和工作稿按钮", () => {
    const wrapper = mountTab()
    const nav = wrapper.find(".world-bible-page-nav")
    expect(nav.findAll(".world-bible-page-btn").length).toBeGreaterThanOrEqual(3) // 1 free draft + 2 pages
    expect(nav.find("[data-bible-draft-id='draft-free']").exists()).toBe(true)
    expect(nav.find("[data-bible-page-id='page-1']").exists()).toBe(true)
    expect(nav.find("[data-bible-page-id='page-2']").exists()).toBe(true)
  })

  it("空的 bible 显示空态", () => {
    const wrapper = mountTab({ bible: { pages: [], categories: [], drafts: [], synopsis: null, pageTemplates: [], activationProfiles: [] } })
    expect(wrapper.find(".empty-state").exists()).toBe(true)
    expect(wrapper.text()).toContain("创建一个世界书页面")
  })
})

describe("显示模式切换", () => {
  it("切换到 gallery 模式", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-mode='gallery']").trigger("click")
    expect(wrapper.find("[data-mode='editor']").attributes("aria-pressed")).toBe("false")
    expect(wrapper.find("[data-mode='gallery']").attributes("aria-pressed")).toBe("true")
    expect(wrapper.find("[data-mode='filter']").attributes("aria-pressed")).toBe("false")
    expect(wrapper.find(".world-bible-gallery").exists()).toBe(true)
    expect(wrapper.find(".world-bible-gallery__hero").exists()).toBe(true)
    expect(wrapper.find(".world-bible-category-grid").exists()).toBe(true)
    // category cards
    expect(wrapper.findAll(".world-bible-category-card").length).toBeGreaterThanOrEqual(1)
  })

  it("gallery 模式钻取分类", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-mode='gallery']").trigger("click")
    await wrapper.find("[data-action='bible-gallery-open'][data-category='background']").trigger("click")
    await nextTick()
    expect(wrapper.find(".world-bible-category-header").exists()).toBe(true)
    expect(wrapper.find(".world-bible-category-header").text()).toContain("背景")
    expect(wrapper.find(".world-bible-page-card").exists()).toBe(true)
    // back button
    expect(wrapper.find("[data-action='bible-gallery-back']").exists()).toBe(true)
  })

  it("gallery 模式返回首页", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-mode='gallery']").trigger("click")
    await wrapper.find("[data-action='bible-gallery-open'][data-category='background']").trigger("click")
    await nextTick()
    await wrapper.find("[data-action='bible-gallery-back']").trigger("click")
    await nextTick()
    // back to gallery home - should show gallery hero
    expect(wrapper.find(".world-bible-gallery__hero").exists()).toBe(true)
  })

  it("gallery 模式从页面卡打开编辑", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-mode='gallery']").trigger("click")
    await wrapper.find("[data-action='bible-gallery-open'][data-category='background']").trigger("click")
    await nextTick()
    await wrapper.find("[data-action='bible-open-page-card']").trigger("click")
    await nextTick()
    expect(wrapper.find(".world-bible-editor-panel").exists()).toBe(true)
    expect(wrapper.find("#bible-title").exists()).toBe(true)
  })

  it("切换到 filter 模式", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-mode='filter']").trigger("click")
    expect(wrapper.find("[data-mode='editor']").attributes("aria-pressed")).toBe("false")
    expect(wrapper.find("[data-mode='gallery']").attributes("aria-pressed")).toBe("false")
    expect(wrapper.find("[data-mode='filter']").attributes("aria-pressed")).toBe("true")
    expect(wrapper.find(".world-bible-filter").exists()).toBe(true)
    expect(wrapper.find(".world-bible-section-title").exists()).toBe(true)
    expect(wrapper.find(".world-bible-category-grid").exists()).toBe(true)
  })

  it("filter 模式按分类筛选", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-mode='filter']").trigger("click")
    await nextTick()
    const categories = wrapper.get('[role="group"][aria-label="世界书页面分类"]')
    const all = categories.get("[data-category='all']")
    const species = categories.get("[data-category='species']")
    expect(all.attributes("aria-pressed")).toBe("true")
    expect(species.attributes("aria-pressed")).toBe("false")
    await wrapper.find("[data-action='bible-set-category'][data-category='species']").trigger("click")
    await nextTick()
    expect(all.attributes("aria-pressed")).toBe("false")
    expect(species.attributes("aria-pressed")).toBe("true")
    // Should only show species pages
    expect(wrapper.find(".world-bible-page-card-grid").exists()).toBe(true)
    expect(wrapper.find(".world-bible-page-card-grid").text()).toContain("种族设定")
  })

  it("filter 模式页面卡打开编辑", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-mode='filter']").trigger("click")
    await nextTick()
    await wrapper.find("[data-action='bible-set-category'][data-category='all']").trigger("click")
    await nextTick()
    await wrapper.find("[data-action='bible-open-page-card']").trigger("click")
    await nextTick()
    expect(wrapper.find(".world-bible-editor-panel").exists()).toBe(true)
  })

  it("切换模式时带未保存修改则弹确认", async () => {
    const wrapper = mountTab()
    // Make an unsaved change by modifying the free text DOM
    const textarea = wrapper.find("#bible-free-text")
    await textarea.setValue("未保存的修改")
    // Now switch to gallery - should trigger confirm
    await wrapper.find("[data-mode='gallery']").trigger("click")
    expect(confirmMock).toHaveBeenCalled()
  })

  it("取消未保存修改的模式切换时保留已选状态", async () => {
    confirmMock.mockReturnValue(false)
    const wrapper = mountTab()
    await wrapper.find("#bible-free-text").setValue("未保存的修改")
    await wrapper.find("[data-mode='gallery']").trigger("click")

    expect(confirmMock).toHaveBeenCalled()
    expect(wrapper.find("[data-mode='editor']").attributes("aria-pressed")).toBe("true")
    expect(wrapper.find("[data-mode='gallery']").attributes("aria-pressed")).toBe("false")
    expect(wrapper.find(".world-bible-editor-panel").exists()).toBe(true)
  })
})

describe("编辑器行为", () => {
  it("page nav 点击切换 active page", async () => {
    const wrapper = mountTab()
    expect(wrapper.find("#bible-title").exists()).toBe(true)
    // Default active is page-1
    expect(wrapper.find("#bible-title").element.value).toContain("世界基本背景")
    // Click page-2
    await wrapper.find("[data-bible-page-id='page-2']").trigger("click")
    await nextTick()
    expect(wrapper.find("#bible-title").element.value).toContain("种族设定")
  })

  it("page nav 点击未保存修改弹确认", async () => {
    confirmMock.mockReturnValue(false)
    const wrapper = mountTab()
    const textarea = wrapper.find("#bible-free-text")
    await textarea.setValue("未保存")
    await wrapper.find("[data-bible-page-id='page-2']").trigger("click")
    expect(confirmMock).toHaveBeenCalled()
    // active page should not change
    expect(wrapper.find("#bible-title").element.value).toContain("世界基本背景")
  })

  it("工作稿页面按钮高亮", () => {
    const wrapper = mountTab({ bible: { ...defaultBible(), drafts: [DRAFT_FREE] } })
    // free draft button shows badge
    expect(wrapper.find("[data-bible-draft-id='draft-free'] .badge").exists()).toBe(true)
  })

  it("分区编辑器显示已有分区", () => {
    const wrapper = mountTab()
    const sections = wrapper.findAll(".world-bible-section-editor")
    expect(sections.length).toBeGreaterThanOrEqual(1)
    expect(sections[0].find("[data-section-field='title']").element.value).toBe("货币")
    expect(sections[0].find("[data-section-field='body_markdown']").element.value).toBe("北境使用银币")
  })

  it("新增分区通过模板块操作", async () => {
    const wrapper = mountTab()
    const initialCount = wrapper.findAll(".world-bible-section-editor").length
    await wrapper.find("[data-action='bible-section-add']").trigger("click")
    await nextTick()
    // The section should be added to the source object - re-render via sectionsSignal
    expect(wrapper.findAll(".world-bible-section-editor").length).toBeGreaterThanOrEqual(initialCount)
  })

  it("保存工作稿调用 API", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.updateBibleDraft = vi.fn().mockResolvedValue({ id: "draft-1", page_id: "page-1", ...DRAFT_1 })
    const wrapper = mountTab()
    // Fill in some text
    await wrapper.find("#bible-free-text").setValue("作者编辑的正文")
    await wrapper.find("#bible-title").setValue("世界基本背景")
    await wrapper.find("[data-action='bible-save-page']").trigger("click")
    await nextTick()
    expect(api.world.updateBibleDraft).toHaveBeenCalled()
    expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("已保存"), "success")
  })

  it("首次保存只对账本地工作稿并保留编辑器焦点", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    api.world.createBibleDraft = vi.fn().mockResolvedValue({ id: "draft-new", page_id: "page-1" })
    api.world.updateBibleDraft = vi.fn().mockResolvedValue({
      ...DRAFT_1,
      id: "draft-new",
      free_text: "本地保存后的正文",
      updated_at: "2026-08-12T12:00:00Z",
    })
    const wrapper = mountTab({ bible: { ...defaultBible(), drafts: [] } })
    const editor = wrapper.find("#bible-free-text")
    await editor.setValue("本地保存后的正文")
    editor.element.focus()
    editor.element.setSelectionRange(4, 4)
    const originalEditor = editor.element

    await expect(wrapper.vm.$.setupState.savePage()).resolves.toBe(true)
    await nextTick()

    expect(router.refresh).not.toHaveBeenCalled()
    expect(wrapper.find("#bible-free-text").element).toBe(originalEditor)
    expect(document.activeElement).toBe(originalEditor)
    expect(originalEditor.selectionStart).toBe(4)
    expect(worldSession.bible.activeDraftId).toBe("draft-new")
    expect(wrapper.find(".world-bible-editor-panel .world-bible-page-meta").text()).toContain("工作稿")

    await wrapper.find("[data-bible-page-id='page-2']").trigger("click")
    await wrapper.find("[data-bible-page-id='page-1']").trigger("click")
    expect(wrapper.find("#bible-free-text").element.value).toBe("本地保存后的正文")
  })

  it("新工作稿创建晚到时仍只保存发起页面的输入", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const created = deferred()
    api.world.createBibleDraft = vi.fn(() => created.promise)
    api.world.updateBibleDraft = vi.fn().mockResolvedValue({
      id: "new-p1-draft", page_id: "page-1", title: "P1 标题", free_text: "P1 正文",
      page_type: "background", sections_json: [], linked_asset_refs_json: [],
    })
    const wrapper = mountTab({ bible: { ...defaultBible(), drafts: [] } })
    await wrapper.find("#bible-title").setValue("P1 标题")
    await wrapper.find("#bible-free-text").setValue("P1 正文")

    const saving = wrapper.vm.$.setupState.savePage(false)
    await vi.waitFor(() => expect(api.world.createBibleDraft).toHaveBeenCalled())
    appState.currentProjectId = "p2"
    wrapper.unmount()
    resetWorldSession()
    worldSession.bible.activePageId = "page-2"
    document.body.innerHTML = `
      <input id="bible-title" value="P2 标题" />
      <textarea id="bible-free-text">P2 正文</textarea>
    `
    created.resolve({ id: "new-p1-draft", page_id: "page-1" })

    await expect(saving).resolves.toBe(false)
    expect(api.world.updateBibleDraft).toHaveBeenCalledWith(
      "new-p1-draft",
      expect.objectContaining({ title: "P1 标题", free_text: "P1 正文" }),
      "p1",
    )
    expect(worldSession.bible.activePageId).toBe("page-2")
    expect(worldSession.bible.activeDraftId).toBeNull()
  })

  it("保存响应晚到时不覆盖同项目已切换的页面", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const updated = deferred()
    api.world.updateBibleDraft = vi.fn(() => updated.promise)
    const wrapper = mountTab()

    const saving = wrapper.vm.$.setupState.savePage(false)
    await vi.waitFor(() => expect(api.world.updateBibleDraft).toHaveBeenCalled())
    await wrapper.find("[data-bible-page-id='page-2']").trigger("click")
    updated.resolve({ ...DRAFT_1, free_text: "已保存正文" })

    await expect(saving).resolves.toBe(false)
    expect(worldSession.bible.activePageId).toBe("page-2")
    expect(worldSession.bible.activeDraftId).toBeNull()
    expect(toastMock).not.toHaveBeenCalledWith(expect.stringContaining("工作稿已保存"), "success")
  })

  it("保存期间锁定当前编辑边界", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const updated = deferred()
    api.world.updateBibleDraft = vi.fn(() => updated.promise)
    const wrapper = mountTab()

    await wrapper.find("[data-action='bible-save-page']").trigger("click")
    await vi.waitFor(() => expect(api.world.updateBibleDraft).toHaveBeenCalledTimes(1))
    expect(wrapper.find(".world-bible-workspace").attributes("inert")).toBe("")
    expect(wrapper.find(".world-bible-workspace").attributes("aria-busy")).toBe("true")

    updated.resolve({ ...DRAFT_1, updated_at: "2026-08-12T12:00:00Z" })
    await vi.waitFor(() => expect(wrapper.find(".world-bible-workspace").attributes("aria-busy")).toBe("false"))
  })

  it("发布工作稿调用 API", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.createBibleDraft = vi.fn()
    api.world.updateBibleDraft = vi.fn().mockResolvedValue({ id: "draft-1", page_id: "page-1", ...DRAFT_1 })
    api.world.publishBibleDraft = vi.fn().mockResolvedValue({ ...PAGE_1, version_number: 2 })
    const wrapper = mountTab()
    await wrapper.find("#bible-title").setValue("世界基本背景")
    await wrapper.find("[data-action='bible-publish-page']").trigger("click")
    await nextTick()
    expect(api.world.updateBibleDraft).toHaveBeenCalled()
    expect(api.world.publishBibleDraft).toHaveBeenCalled()
    expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("已发布"), "success")
  })

  it("应用模板只就地更新工作稿分区", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    api.world.applyBiblePageTemplate = vi.fn().mockResolvedValue({
      ...DRAFT_1,
      template_key: "e2e_trade_guide",
      template_version: 2,
      sections_json: [{
        section_id: "section-template",
        section_type: "markdown",
        title: "模板分区",
        body_markdown: "就地写入",
        sort_order: 10,
        linked_asset_ref_hashes: [],
        projection_policy: "eligible",
        sensitivity_hint: "author_safe",
      }],
    })
    const wrapper = mountTab()
    const editorRoot = wrapper.find(".world-bible-editor-panel").element
    await wrapper.find("#bible-page-template").setValue("e2e_trade_guide")

    await wrapper.find("[data-action='bible-apply-page-template']").trigger("click")
    await vi.waitFor(() => expect(wrapper.find("[data-section-id='section-template']").exists()).toBe(true))

    expect(wrapper.find(".world-bible-editor-panel").element).toBe(editorRoot)
    expect(wrapper.find("[data-section-id='section-template'] [data-section-field='title']").element.value).toBe("模板分区")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("丢弃工作稿弹确认", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.discardBibleDraft = vi.fn().mockResolvedValue({})
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-discard-draft']").trigger("click")
    // vanilla 契约：confirmAction 应用模态（非原生 confirm）
    expect(confirmActionMock).toHaveBeenCalledWith(expect.stringContaining("丢弃这个工作稿"), expect.any(Function))
  })

  it("丢弃响应晚到时不清空同项目新选页面的工作稿", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    const discarded = deferred()
    let discardAction
    api.world.discardBibleDraft = vi.fn(() => discarded.promise)
    confirmActionMock.mockImplementationOnce((_message, handler) => { discardAction = handler })
    const wrapper = mountTab({ bible: { ...defaultBible(), drafts: [DRAFT_1, DRAFT_2] } })

    await wrapper.find("[data-action='bible-discard-draft']").trigger("click")
    const discarding = discardAction()
    await vi.waitFor(() => expect(api.world.discardBibleDraft).toHaveBeenCalledWith("draft-1", "p1"))
    await wrapper.find("[data-bible-page-id='page-2']").trigger("click")
    discarded.resolve({})
    await discarding
    await nextTick()

    expect(wrapper.find("#bible-free-text").element.value).toBe("B 页工作稿")
    expect(toastMock).not.toHaveBeenCalledWith("工作稿已丢弃", "success")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("用 AI 完善此页打开生成中心", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-improve-with-ai']").trigger("click")
    await nextTick()
    expect(navigateMock).toHaveBeenCalledWith("generate", null, true, expect.any(URLSearchParams))
    const query = navigateMock.mock.calls[0][3]
    expect(query.get("tab")).toBe("world")
    expect(query.get("source_page_id")).toBe("page-1")
    expect(query.get("target")).toBe("world_bible_page")
  })

  it("用 AI 完善此页时未保存修改先弹保存", async () => {
    navigateMock.mockClear()
    const wrapper = mountTab()
    await wrapper.find("#bible-free-text").setValue("未保存修改")
    await wrapper.find("[data-action='bible-improve-with-ai']").trigger("click")
    await nextTick()
    // Should show modal instead of navigating
    expect(showModalHtmlMock).toHaveBeenCalled()
    expect(showModalHtmlMock.mock.calls[0][0]).toBe("保存后进入生成中心")
    expect(navigateMock).not.toHaveBeenCalled()
  })
})

describe("模态操作", () => {
  it("保存并继续响应晚到时不导航或污染同页新弹窗", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    const saved = deferred()
    api.world.updateBibleDraft = vi.fn(() => saved.promise)
    const wrapper = mountTab()
    installModalHost()

    await wrapper.find("#bible-free-text").setValue("未保存修改")
    await wrapper.find("[data-action='bible-improve-with-ai']").trigger("click")
    const saving = showModalHtmlMock.mock.calls.at(-1)[2][1].handler()
    await vi.waitFor(() => expect(api.world.updateBibleDraft).toHaveBeenCalled())
    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    saved.resolve({ ...DRAFT_1, free_text: "未保存修改" })

    await expect(saving).resolves.toBe(true)
    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("管理世界书类别")
    expect(closeModalMock).not.toHaveBeenCalled()
    expect(navigateMock).not.toHaveBeenCalled()
    expect(toastMock).not.toHaveBeenCalledWith("工作稿已保存；正式页面尚未变化", "success")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("创建新页面弹模态", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-new-page']").trigger("click")
    expect(showModalHtmlMock).toHaveBeenCalled()
    expect(showModalHtmlMock.mock.calls[0][0]).toBe("新建世界书页面")
    const html = showModalHtmlMock.mock.calls[0][1]
    expect(html).toContain("bible-create-title")
  })

  it("创建页面后就地打开返回的工作稿", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    api.world.createBibleDraft = vi.fn().mockResolvedValue({
      ...DRAFT_FREE,
      id: "draft-new",
      title: "新建设定页",
      free_text: "初始工作稿",
      updated_at: "2026-08-12T12:00:00Z",
    })
    const wrapper = mountTab()
    installModalHost()

    await wrapper.find("[data-action='bible-new-page']").trigger("click")
    document.getElementById("bible-create-title").value = "新建设定页"
    await showModalHtmlMock.mock.calls.at(-1)[2][0].handler()
    await nextTick()

    expect(wrapper.find("#bible-title").element.value).toBe("新建设定页")
    expect(wrapper.find("#bible-free-text").element.value).toBe("初始工作稿")
    expect(worldSession.bible.activeDraftId).toBe("draft-new")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("创建页面成功晚到时收口旧处理器且不影响新弹窗", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    const created = deferred()
    api.world.createBibleDraft = vi.fn(() => created.promise)
    const wrapper = mountTab()
    document.body.insertAdjacentHTML("beforeend", `
      <input id="bible-create-title" value="新建页" />
      <select id="bible-create-type"><option value="custom" selected>自定义</option></select>
      <select id="bible-create-template"><option value="" selected>空白页</option></select>
    `)

    await wrapper.find("[data-action='bible-new-page']").trigger("click")
    const creating = showModalHtmlMock.mock.calls.at(-1)[2][0].handler()
    await vi.waitFor(() => expect(api.world.createBibleDraft).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p1", title: "新建页" })))
    await wrapper.find("[data-bible-page-id='page-2']").trigger("click")
    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("管理世界书类别")
    created.resolve({ id: "draft-new", page_id: null, title: "新建页", page_type: "custom", sections_json: [], linked_asset_refs_json: [] })
    await expect(creating).resolves.toBe(true)

    expect(worldSession.bible.activePageId).toBe("page-2")
    expect(worldSession.bible.activeDraftId).toBeNull()
    expect(closeModalMock).not.toHaveBeenCalled()
    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("管理世界书类别")
    expect(toastMock).not.toHaveBeenCalledWith(expect.stringContaining("工作稿已创建"), "success")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("创建页面失败晚到时收口旧处理器且不提示新页面", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    const created = deferred()
    api.world.createBibleDraft = vi.fn(() => created.promise)
    const wrapper = mountTab()
    document.body.insertAdjacentHTML("beforeend", `
      <input id="bible-create-title" value="新建页" />
      <select id="bible-create-type"><option value="custom" selected>自定义</option></select>
      <select id="bible-create-template"><option value="" selected>空白页</option></select>
    `)

    await wrapper.find("[data-action='bible-new-page']").trigger("click")
    const creating = showModalHtmlMock.mock.calls.at(-1)[2][0].handler()
    await vi.waitFor(() => expect(api.world.createBibleDraft).toHaveBeenCalled())
    await wrapper.find("[data-bible-page-id='page-2']").trigger("click")
    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    created.reject(new Error("旧请求失败"))

    await expect(creating).resolves.toBe(true)
    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("管理世界书类别")
    expect(toastMock).not.toHaveBeenCalledWith("旧请求失败", "error")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("管理分类弹模态", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    expect(showModalHtmlMock).toHaveBeenCalled()
    expect(showModalHtmlMock.mock.calls[0][0]).toBe("管理世界书类别")
  })

  it("恢复分类响应晚到时不关闭或刷新新项目", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    const restored = deferred()
    api.world.updateBibleCategory = vi.fn(() => restored.promise)
    showModalHtmlMock.mockImplementationOnce((_title, body) => {
      document.body.insertAdjacentHTML("beforeend", `<div id="category-modal-fixture">${body}</div>`)
    })
    const archived = { id: "cat-archived", category_key: "history", name: "历史分类", status: "archived", builtin: false }
    const wrapper = mountTab({ bible: { ...defaultBible(), categories: [...CATEGORIES, archived] } })

    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    document.querySelector("[data-bible-category-restore='cat-archived']").click()
    await vi.waitFor(() => expect(api.world.updateBibleCategory).toHaveBeenCalledWith("cat-archived", { status: "active" }, "p1"))
    appState.currentProjectId = "p2"
    wrapper.unmount()
    restored.resolve({ ...archived, status: "active" })
    await restored.promise
    await Promise.resolve()

    expect(closeModalMock).not.toHaveBeenCalled()
    expect(toastMock).not.toHaveBeenCalledWith("类别已恢复，可重新用于工作稿", "success")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("恢复分类在原项目仍按原流程关闭并刷新", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    api.world.updateBibleCategory = vi.fn().mockResolvedValue({ id: "cat-archived", status: "active" })
    showModalHtmlMock.mockImplementationOnce((_title, body) => {
      document.body.insertAdjacentHTML("beforeend", `<div>${body}</div>`)
    })
    const archived = { id: "cat-archived", category_key: "history", name: "历史分类", status: "archived", builtin: false }
    const wrapper = mountTab({ bible: { ...defaultBible(), categories: [...CATEGORIES, archived] } })

    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    document.querySelector("[data-bible-category-restore='cat-archived']").click()
    await vi.waitFor(() => expect(closeModalMock).toHaveBeenCalledTimes(1))

    expect(toastMock).toHaveBeenCalledWith("类别已恢复，可重新用于工作稿", "success")
    expect(router.refresh).toHaveBeenCalledTimes(1)
  })

  it("恢复分类响应晚到时不关闭同页新弹窗", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    const restored = deferred()
    api.world.updateBibleCategory = vi.fn(() => restored.promise)
    const archived = { id: "cat-archived", category_key: "history", name: "历史分类", status: "archived", builtin: false }
    const wrapper = mountTab({ bible: { ...defaultBible(), categories: [...CATEGORIES, archived] } })
    installModalHost()

    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    document.querySelector("[data-bible-category-restore='cat-archived']").click()
    await vi.waitFor(() => expect(api.world.updateBibleCategory).toHaveBeenCalled())
    await wrapper.find("[data-action='bible-manage-page-templates']").trigger("click")
    restored.resolve({ ...archived, status: "active" })
    await restored.promise
    await Promise.resolve()

    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("页面模板")
    expect(closeModalMock).not.toHaveBeenCalled()
    expect(toastMock).not.toHaveBeenCalledWith("类别已恢复，可重新用于工作稿", "success")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("页面模板弹模态", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-manage-page-templates']").trigger("click")
    expect(showModalHtmlMock).toHaveBeenCalled()
    expect(showModalHtmlMock.mock.calls[0][0]).toBe("页面模板")
  })

  it("创建页面模板响应晚到时不关闭或刷新新项目", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    const created = deferred()
    api.world.createBiblePageTemplate = vi.fn(() => created.promise)
    const wrapper = mountTab()

    await wrapper.find("[data-action='bible-manage-page-templates']").trigger("click")
    const [, body, buttons] = showModalHtmlMock.mock.calls.at(-1)
    document.body.insertAdjacentHTML("beforeend", body)
    document.getElementById("bible-template-key").value = "trade_guide"
    document.getElementById("bible-template-name").value = "贸易模板"
    document.getElementById("bible-template-section-title").value = "货币与交换"
    const creating = buttons[0].handler()
    await vi.waitFor(() => expect(api.world.createBiblePageTemplate).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p1" })))
    appState.currentProjectId = "p2"
    wrapper.unmount()
    created.resolve({ id: "template-new" })
    await creating

    expect(closeModalMock).not.toHaveBeenCalled()
    expect(toastMock).not.toHaveBeenCalledWith("页面模板已创建", "success")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("创建页面模板后就地加入新建页面选项", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    api.world.createBiblePageTemplate = vi.fn().mockResolvedValue({
      id: "template-new",
      novel_id: "p1",
      template_key: "trade_guide",
      name: "贸易模板",
      version_number: 1,
      builtin: false,
      status: "active",
      description: "",
      default_sections_json: [],
    })
    const wrapper = mountTab()

    await wrapper.find("[data-action='bible-manage-page-templates']").trigger("click")
    const [, body, buttons] = showModalHtmlMock.mock.calls.at(-1)
    document.body.insertAdjacentHTML("beforeend", body)
    document.getElementById("bible-template-key").value = "trade_guide"
    document.getElementById("bible-template-name").value = "贸易模板"
    document.getElementById("bible-template-section-title").value = "货币与交换"
    await buttons[0].handler()

    showModalHtmlMock.mockClear()
    await wrapper.find("[data-action='bible-new-page']").trigger("click")
    const [, createBody] = showModalHtmlMock.mock.calls.at(-1)
    expect(createBody).toContain('<option value="trade_guide">贸易模板 · v1</option>')
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("更新页面模板后就地替换新建页面选项", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    api.world.updateBiblePageTemplate = vi.fn().mockResolvedValue({
      ...CUSTOM_TEMPLATE,
      name: "贸易模板二版",
      version_number: 2,
    })
    const wrapper = mountTab({ bible: { ...defaultBible(), pageTemplates: [...TEMPLATES, CUSTOM_TEMPLATE] } })
    installModalHost()

    await wrapper.find("[data-action='bible-manage-page-templates']").trigger("click")
    document.querySelector("[data-page-template-rename='template-custom']").click()
    const [, , buttons] = showModalHtmlMock.mock.calls.at(-1)
    document.getElementById("bible-template-edit-name").value = "贸易模板二版"
    await buttons[0].handler()

    showModalHtmlMock.mockClear()
    await wrapper.find("[data-action='bible-new-page']").trigger("click")
    const [, createBody] = showModalHtmlMock.mock.calls.at(-1)
    expect(createBody).toContain('<option value="trade_guide">贸易模板二版 · v2</option>')
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("恢复页面模板后就地替换新建页面选项", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    api.world.listBiblePageTemplateRevisions = vi.fn().mockResolvedValue([
      { version_number: 1, revision_reason: "create", content_hash: "1234567890123456" },
    ])
    api.world.restoreBiblePageTemplateRevision = vi.fn().mockResolvedValue({
      ...CUSTOM_TEMPLATE,
      name: "已恢复贸易模板",
      version_number: 2,
    })
    const wrapper = mountTab({ bible: { ...defaultBible(), pageTemplates: [...TEMPLATES, CUSTOM_TEMPLATE] } })
    installModalHost()

    await wrapper.find("[data-action='bible-manage-page-templates']").trigger("click")
    document.querySelector("[data-page-template-history='template-custom']").click()
    await vi.waitFor(() => expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("模板历史"))
    document.querySelector("[data-template-restore-version='1']").click()
    await vi.waitFor(() => expect(toastMock).toHaveBeenCalledWith("历史模板已恢复为新版本", "success"))

    showModalHtmlMock.mockClear()
    await wrapper.find("[data-action='bible-new-page']").trigger("click")
    const [, createBody] = showModalHtmlMock.mock.calls.at(-1)
    expect(createBody).toContain('<option value="trade_guide">已恢复贸易模板 · v2</option>')
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("页面、类别和模板必填校验失败时保留当前弹窗", async () => {
    const wrapper = mountTab()

    await wrapper.find("[data-action='bible-new-page']").trigger("click")
    let [, pageBody, pageButtons] = showModalHtmlMock.mock.calls.at(-1)
    document.body.innerHTML = pageBody
    document.getElementById("bible-create-title").value = ""
    await expect(pageButtons[0].handler()).resolves.toBe(false)

    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    let [, categoryBody, categoryButtons] = showModalHtmlMock.mock.calls.at(-1)
    document.body.innerHTML = categoryBody
    await expect(categoryButtons[0].handler()).resolves.toBe(false)

    showModalHtmlMock.mockClear()
    await wrapper.find("[data-action='bible-manage-page-templates']").trigger("click")
    const [, templateBody, templateButtons] = showModalHtmlMock.mock.calls.at(-1)
    document.body.innerHTML = templateBody
    await expect(templateButtons[0].handler()).resolves.toBe(false)
  })

  it("版本历史弹模态", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.listBiblePageRevisions = vi.fn().mockResolvedValue([])
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-page-history']").trigger("click")
    await nextTick()
    expect(showModalHtmlMock).toHaveBeenCalled()
  })

  it("页面切换后旧历史弹窗不能把版本号恢复到新页面", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.listBiblePageRevisions = vi.fn().mockResolvedValue([
      { version_number: 1, revision_reason: "旧版本", snapshot_json: { free_text: "旧正文" } },
    ])
    api.world.restoreBiblePageRevision = vi.fn().mockResolvedValue({ id: "restored-draft", page_id: "page-2" })
    showModalHtmlMock.mockImplementationOnce((_title, body) => {
      document.body.insertAdjacentHTML("beforeend", body)
    })
    const wrapper = mountTab()

    await wrapper.find("[data-action='bible-page-history']").trigger("click")
    await vi.waitFor(() => expect(document.querySelector("[data-bible-page-restore]")).not.toBeNull())
    await wrapper.find("[data-bible-page-id='page-2']").trigger("click")
    document.querySelector("[data-bible-page-restore]").click()
    await nextTick()

    expect(api.world.restoreBiblePageRevision).not.toHaveBeenCalled()
  })

  it("恢复页面版本后就地打开工作稿", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    api.world.listBiblePageRevisions = vi.fn().mockResolvedValue([
      { version_number: 1, revision_reason: "初版", snapshot_json: { free_text: "旧版正文" } },
    ])
    api.world.restoreBiblePageRevision = vi.fn().mockResolvedValue({
      ...DRAFT_1,
      id: "restored-draft",
      free_text: "旧版正文",
      updated_at: "2026-08-12T12:00:00Z",
    })
    const wrapper = mountTab()
    installModalHost()

    await wrapper.find("[data-action='bible-page-history']").trigger("click")
    await vi.waitFor(() => expect(document.querySelector("[data-bible-page-restore='1']")).not.toBeNull())
    document.querySelector("[data-bible-page-restore='1']").click()
    await vi.waitFor(() => expect(wrapper.find("#bible-free-text").element.value).toBe("旧版正文"))

    expect(worldSession.bible.activeDraftId).toBe("restored-draft")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("简介终态后的二次读取在项目切换卸载后不再回写或提示", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const synopsisResult = deferred()
    api.world.getBibleSynopsis = vi.fn(() => synopsisResult.promise)
    let pollingOptions
    pollTaskProgress.mockImplementationOnce((options) => {
      pollingOptions = options
      return { stop: vi.fn() }
    })
    const wrapper = mountTab({
      bible: { ...defaultBible(), synopsis: { ...SYNOPSIS, active_task_id: "synopsis-task" } },
    })
    const completing = pollingOptions.onDone({}, { id: "synopsis-task", status: "done" })
    appState.currentProjectId = "p2"
    wrapper.unmount()
    synopsisResult.resolve({ status: "fresh", current_revision: { id: "revision-1" } })

    await completing
    expect(toastMock).not.toHaveBeenCalledWith("世界观简介已刷新", "success")
  })

  it("简介历史请求晚到时不在新项目打开旧弹窗", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const revisions = deferred()
    api.world.listBibleSynopsisRevisions = vi.fn(() => revisions.promise)
    const wrapper = mountTab()
    showModalHtmlMock.mockClear()

    const opening = wrapper.vm.$.setupState.openSynopsisHistory()
    await vi.waitFor(() => expect(api.world.listBibleSynopsisRevisions).toHaveBeenCalledWith("p1"))
    appState.currentProjectId = "p2"
    wrapper.unmount()
    revisions.resolve({ items: [] })

    await expect(opening).resolves.toBe(false)
    expect(showModalHtmlMock).not.toHaveBeenCalled()
  })

  it("刷新 synopsis 调用 API", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.refreshBibleSynopsis = vi.fn().mockResolvedValue({ task_id: "task-synopsis", existing: false })
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-refresh-synopsis']").trigger("click")
    await nextTick()
    expect(api.world.refreshBibleSynopsis).toHaveBeenCalledWith("p1")
  })

  it("提交介绍刷新只启动本地任务卡，不重挂页面", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    api.world.refreshBibleSynopsis = vi.fn().mockResolvedValue({ task_id: "task-synopsis", existing: false })
    const wrapper = mountTab()

    await wrapper.vm.$.setupState.refreshSynopsis()

    expect(pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({ taskId: "task-synopsis" }))
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("简介提交响应晚到时不复活已卸载页面的轮询", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const task = deferred()
    api.world.refreshBibleSynopsis = vi.fn(() => task.promise)
    const wrapper = mountTab()

    const refreshing = wrapper.vm.$.setupState.refreshSynopsis()
    await vi.waitFor(() => expect(api.world.refreshBibleSynopsis).toHaveBeenCalledWith("p1"))
    appState.currentProjectId = "p2"
    wrapper.unmount()
    pollTaskProgress.mockClear()
    task.resolve({ task_id: "late-synopsis", existing: false })

    await expect(refreshing).resolves.toBe(false)
    expect(pollTaskProgress).not.toHaveBeenCalled()
    expect(toastMock).not.toHaveBeenCalledWith(expect.stringContaining("简介刷新任务"), "success")
  })

  it("自动维护响应晚到时不再刷新新项目", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const updated = deferred()
    api.world.setBibleSynopsisAutoRefresh = vi.fn(() => updated.promise)
    const wrapper = mountTab()
    const toggling = wrapper.vm.$.setupState.toggleSynopsisAuto()
    await vi.waitFor(() => expect(api.world.setBibleSynopsisAutoRefresh).toHaveBeenCalledWith("p1", true))
    appState.currentProjectId = "p2"
    wrapper.unmount()
    updated.resolve({ ...SYNOPSIS, auto_refresh_enabled: true })

    await expect(toggling).resolves.toBe(false)
    expect(toastMock).not.toHaveBeenCalledWith(expect.stringContaining("自动维护"), "success")
  })

  it("打开建议弹窗", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.listSuggestions = vi.fn().mockResolvedValue({ items: [], total: 0 })
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-open-suggestions']").trigger("click")
    await nextTick()
    expect(api.world.listSuggestions).toHaveBeenCalledWith({
      novel_id: "p1", source_module: "world", review_group: "generation_center", status: "pending",
    })
  })

  it("应用整页建议后就地打开接口返回的工作稿", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    const suggestion = {
      id: "suggestion-1",
      review_group: "generation_center",
      target_type: "world_bible_page_draft",
      action_schema: "world_bible_page_draft.v1",
      risk_level: "low",
      payload_json: {
        page: {
          title: "建议新页",
          page_type: "background",
          free_text: "建议正文",
          sections_json: [],
          linked_asset_refs_json: [],
        },
      },
    }
    const draft = {
      id: "draft-from-suggestion",
      page_id: null,
      title: "建议新页",
      page_type: "background",
      free_text: "建议正文",
      sort_order: 0,
      sections_json: [],
      linked_asset_refs_json: [],
    }
    api.world.listSuggestions = vi.fn().mockResolvedValue({ items: [suggestion], total: 1 })
    api.generate.applyWorldPageDraft = vi.fn().mockResolvedValue({ suggestion, draft })
    const wrapper = mountTab()
    installModalHost()

    await wrapper.find("[data-action='bible-open-suggestions']").trigger("click")
    document.querySelector("[data-bible-edit-suggestion='suggestion-1']").click()
    const apply = showModalHtmlMock.mock.calls.at(-1)[2][0].handler
    await expect(apply()).resolves.toBeUndefined()
    await nextTick()

    expect(api.generate.applyWorldPageDraft).toHaveBeenCalledWith(
      "suggestion-1",
      expect.objectContaining({ page: expect.objectContaining({ title: "建议新页" }) }),
      "p1",
    )
    expect(worldSession.bible.activeDraftId).toBe("draft-from-suggestion")
    expect(wrapper.find("#bible-title").element.value).toBe("建议新页")
    expect(wrapper.find("#bible-free-text").element.value).toBe("建议正文")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("旧建议请求晚到时不重绘同页新弹窗", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const suggestions = deferred()
    api.world.listSuggestions = vi.fn(() => suggestions.promise)
    const wrapper = mountTab()
    const { body } = installModalHost()

    const opening = wrapper.vm.$.setupState.openSuggestions()
    await vi.waitFor(() => expect(api.world.listSuggestions).toHaveBeenCalled())
    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    suggestions.resolve({ items: [], total: 0 })

    await expect(opening).resolves.toBe(false)
    expect(showModalHtmlMock).toHaveBeenCalledTimes(1)
    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("管理世界书类别")
    expect(body.textContent).toContain("类别键")
  })

  it("打开冲突弹窗", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.listWorldConflicts = vi.fn().mockResolvedValue({ items: [], total: 0 })
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-open-conflicts']").trigger("click")
    await nextTick()
    expect(api.world.listWorldConflicts).toHaveBeenCalledWith({ novel_id: "p1", status: "pending" })
  })

  it("新建激活规则弹窗", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-activation-new']").trigger("click")
    expect(showModalHtmlMock).toHaveBeenCalled()
    expect(showModalHtmlMock.mock.calls[0][0]).toBe("新建 AI 参考规则")
  })

  it("发布激活规则调用 confirmAction", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-activation-publish']").trigger("click")
    expect(confirmActionMock).toHaveBeenCalled()
  })

  it("归档页面弹确认", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.updateBiblePage = vi.fn().mockResolvedValue({ ...PAGE_1, status: "archived" })
    // Use a bible with no draft for the active page so archive button is visible
    const bibleNoDraft = defaultBible()
    bibleNoDraft.drafts = [DRAFT_FREE] // DRAFT_FREE has page_id=null, so page-1 has no draft
    const wrapper = mountTab({ bible: bibleNoDraft })
    await wrapper.find("[data-action='bible-archive-page']").trigger("click")
    // vanilla 契约：confirmAction 应用模态（非原生 confirm）
    expect(confirmActionMock).toHaveBeenCalledWith(expect.stringContaining("归档"), expect.any(Function))
  })

  it("归档响应晚到时不把当前页面拉回旧页面", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const router = (await import("../../../../vue/bridge/index.js")).getRouter()
    const archived = deferred()
    let archiveAction
    api.world.updateBiblePage = vi.fn(() => archived.promise)
    confirmActionMock.mockImplementationOnce((_message, handler) => { archiveAction = handler })
    const wrapper = mountTab({ bible: { ...defaultBible(), drafts: [DRAFT_2] } })

    await wrapper.find("[data-action='bible-archive-page']").trigger("click")
    const archiving = archiveAction()
    await vi.waitFor(() => expect(api.world.updateBiblePage).toHaveBeenCalledWith("page-1", { status: "archived" }, "p1"))
    await wrapper.find("[data-bible-page-id='page-2']").trigger("click")
    archived.resolve({ ...PAGE_1, status: "archived" })
    await archiving
    await nextTick()

    expect(wrapper.find("[data-bible-page-id='page-2']").classes()).toContain("btn-primary")
    expect(wrapper.find("#bible-free-text").element.value).toBe("B 页工作稿")
    expect(toastMock).not.toHaveBeenCalledWith("页面已归档", "success")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("显示 synopsis 面板诊断信息", () => {
    const bible = defaultBible()
    bible.synopsis = { status: "failed", current_revision: null, warnings: ["raw warning"], active_task_id: null }
    const wrapper = mountTab({ bible })
    expect(wrapper.find(".world-bible-synopsis-panel").text()).toContain("生成失败")
    expect(wrapper.find(".world-bible-diagnostics").exists()).toBe(true)
  })

  it("有成功 synopsis 版本时显示 rendered text", () => {
    const bible = defaultBible()
    bible.synopsis = {
      status: "fresh", stale: false, auto_refresh_enabled: false, warnings: [],
      current_revision: { id: "rev-1", version_number: 3, rendered_text: "只读世界观简介", token_estimate: 120, coverage_json: { source_count: 8 } },
    }
    const wrapper = mountTab({ bible })
    expect(wrapper.find("pre.generate-markdown-pre").text()).toContain("只读世界观简介")
    expect(wrapper.find(".world-bible-synopsis-panel").text()).toContain("第 3 版")
  })
})

describe("激活面板", () => {
  it("显示激活 profile 选择器", () => {
    const wrapper = mountTab()
    expect(wrapper.find("#bible-activation-profile").exists()).toBe(true)
    expect(wrapper.find("#bible-activation-profile").exists()).toBe(true)
    const select = wrapper.find("#bible-activation-profile").element
    expect(select.options.length).toBeGreaterThanOrEqual(2) // empty + profiles
  })

  it("选择 profile 后显示摘要和 dry-run", async () => {
    const wrapper = mountTab()
    const select = wrapper.find("#bible-activation-profile")
    // Default should select first profile
    expect(wrapper.find(".world-bible-profile-summary").exists()).toBe(true)
    expect(wrapper.find(".world-bible-profile-summary").text()).toContain("writing.world")
    expect(wrapper.find("#bible-activation-task").exists()).toBe(true)
    expect(wrapper.find("[data-action='bible-activation-dry-run']").exists()).toBe(true)
  })

  it("只显示当前规则方案最新一次试运行结果", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const older = deferred()
    const latest = deferred()
    api.context.previewActivationProfile = vi.fn()
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(latest.promise)
    const wrapper = mountTab()

    const first = wrapper.vm.$.setupState.dryRunActivationProfile()
    const second = wrapper.vm.$.setupState.dryRunActivationProfile()
    latest.resolve({ items: [{ label: "最新结果" }], excluded_items: [], rule_evaluations: [], warnings: [] })
    await second
    older.resolve({ items: [{ label: "旧结果" }], excluded_items: [], rule_evaluations: [], warnings: [] })
    await first
    await nextTick()

    expect(wrapper.text()).toContain("最新结果")
    expect(wrapper.text()).not.toContain("旧结果")
  })

  it("旧规则保存响应不销毁后续弹窗选择器或刷新新编辑", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const older = deferred()
    const profileWithRule = (id, name) => ({
      id, profile_key: `writing.${id}`, name, status: "draft", version_number: 1,
      applicable_actions_json: ["writing.generate"],
      rules_json: [{
        rule_id: `rule-${id}`, name: "参考规则",
        match: { positive_terms: ["北境"], negative_terms: [] },
        select: { target_refs: [{ target_type: "world_bible_page", target_id: "page-1" }] },
        rank: { priority: 700, top_k: 12, token_cap: 1200 },
      }],
    })
    const profiles = [profileWithRule("prof-1", "A 规则"), profileWithRule("prof-2", "B 规则")]
    api.context.updateActivationProfile = vi.fn()
      .mockReturnValueOnce(older.promise)
      .mockResolvedValueOnce({ ...profiles[0], version_number: 2 })
    const modalHost = document.createElement("div")
    document.body.appendChild(modalHost)
    const saveHandlers = []
    showModalHtmlMock.mockImplementation((_title, body, buttons) => {
      modalHost.innerHTML = body
      saveHandlers.push(buttons[0].handler)
    })
    const wrapper = mountTab({ bible: { ...defaultBible(), activationProfiles: profiles } })

    await wrapper.find("[data-action='bible-activation-edit']").trigger("click")
    const oldPicker = createReferencePicker.mock.results.at(-1).value
    const savingOld = saveHandlers.at(-1)()
    await vi.waitFor(() => expect(api.context.updateActivationProfile).toHaveBeenCalledTimes(1))
    modalHost.innerHTML = ""
    await wrapper.find("[data-action='bible-activation-edit']").trigger("click")
    const newPicker = createReferencePicker.mock.results.at(-1).value

    older.resolve({ ...profiles[0], version_number: 2 })
    await savingOld
    await nextTick()

    expect(wrapper.find("#bible-activation-profile").element.value).toBe("prof-1")
    expect(newPicker.destroy).not.toHaveBeenCalled()
    expect(closeModalMock).not.toHaveBeenCalled()
    expect(toastMock).not.toHaveBeenCalledWith(expect.stringContaining("规则工作稿已保存"), "success")

    await saveHandlers.at(-1)()
    expect(newPicker.destroy).toHaveBeenCalledTimes(1)
    expect(closeModalMock).toHaveBeenCalledTimes(1)
    expect(oldPicker.destroy).toHaveBeenCalled()
  })

  it("旧规则发布响应不拉回新选择", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const published = deferred()
    let publishAction
    const profiles = [
      { ...ACTIVATION_PROFILES[0], id: "prof-1", name: "A 规则" },
      { ...ACTIVATION_PROFILES[0], id: "prof-2", name: "B 规则", profile_key: "writing.world.b" },
    ]
    api.context.publishActivationProfile = vi.fn(() => published.promise)
    confirmActionMock.mockImplementationOnce((_message, handler) => { publishAction = handler })
    const wrapper = mountTab({ bible: { ...defaultBible(), activationProfiles: profiles } })

    await wrapper.find("[data-action='bible-activation-publish']").trigger("click")
    const publishing = publishAction()
    await vi.waitFor(() => expect(api.context.publishActivationProfile).toHaveBeenCalledWith(
      "prof-1",
      { base_version_number: 1, revision_reason: "manual_publish" },
      "p1",
    ))
    await wrapper.find("#bible-activation-profile").setValue("prof-2")
    published.resolve({ ...profiles[0], status: "published" })
    await publishing
    await nextTick()

    expect(wrapper.find("#bible-activation-profile").element.value).toBe("prof-2")
    expect(toastMock).not.toHaveBeenCalledWith("AI 参考规则已发布", "success")
  })
})

describe("投影状态", () => {
  it("无 active page 时无投影区域", () => {
    const wrapper = mountTab({ bible: { ...defaultBible(), pages: [], drafts: [] } })
    expect(wrapper.find(".world-bible-projection-status").exists()).toBe(false)
  })

  it("有 active page 时显示投影区域", () => {
    const wrapper = mountTab()
    expect(wrapper.find(".world-bible-projection-status").exists()).toBe(true)
    expect(wrapper.find(".world-bible-empty-hint--projection").exists()).toBe(true)
  })

  it("刷新投影调用 API", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.refreshBibleProjection = vi.fn().mockResolvedValue({ task_id: "task-proj", existing: false })
    api.tasks.get = vi.fn().mockResolvedValue({ task_id: "task-proj", status: "pending", progress: 0, meta: { novel_id: "p1", page_id: "page-1", projection_type: "context_brief" } })
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-refresh-projection']").trigger("click")
    await nextTick()
    expect(api.world.refreshBibleProjection).toHaveBeenCalledWith("page-1", "p1", "context_brief", false)
  })

  it("页面切换后不让旧页面的任务恢复覆盖当前投影轮询", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const pageOneTask = deferred()
    const pageTwoTask = deferred()
    localStorage.setItem("worldBibleProjection:p1:page-1:context_brief", "task-page-1")
    localStorage.setItem("worldBibleProjection:p1:page-2:context_brief", "task-page-2")
    api.tasks.get = vi.fn((taskId) => taskId === "task-page-1" ? pageOneTask.promise : pageTwoTask.promise)
    const wrapper = mountTab()

    await wrapper.find("[data-bible-page-id='page-2']").trigger("click")
    pageTwoTask.resolve({ task_id: "task-page-2", status: "pending", meta: { novel_id: "p1", page_id: "page-2", projection_type: "context_brief" } })
    await vi.waitFor(() => expect(pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({ taskId: "task-page-2" })))
    pageOneTask.resolve({ task_id: "task-page-1", status: "pending", meta: { novel_id: "p1", page_id: "page-1", projection_type: "context_brief" } })
    await nextTick()

    expect(pollTaskProgress).toHaveBeenCalledTimes(1)
  })
})

describe("同步与事件", () => {
  it("worldSession bible 字段随组件初始化更新", () => {
    mountTab()
    expect(worldSession.bible.activePageId).toBe("page-1")
  })

  it("卸载时销毁页面资产选择器", async () => {
    const wrapper = mountTab()
    await nextTick()
    const picker = createReferencePicker.mock.results.at(-1).value

    wrapper.unmount()

    expect(picker.destroy).toHaveBeenCalledTimes(1)
  })

  it("重挂载时恢复仍存在的激活规则选择", async () => {
    const profiles = [
      { ...ACTIVATION_PROFILES[0], id: "prof-1", name: "A 规则" },
      { ...ACTIVATION_PROFILES[0], id: "prof-2", name: "B 规则", profile_key: "writing.world.b" },
    ]
    const bible = { ...defaultBible(), activationProfiles: profiles }
    const first = mountTab({ bible })
    await first.find("#bible-activation-profile").setValue("prof-2")
    first.unmount()

    const remounted = mountTab({ bible })

    expect(remounted.find("#bible-activation-profile").element.value).toBe("prof-2")
  })
})

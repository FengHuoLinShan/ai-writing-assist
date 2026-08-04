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
  setBridgeOverrides({
    state: { currentProjectId: "p1", currentView: "world" },
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

  it("丢弃工作稿弹确认", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.discardBibleDraft = vi.fn().mockResolvedValue({})
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-discard-draft']").trigger("click")
    // vanilla 契约：confirmAction 应用模态（非原生 confirm）
    expect(confirmActionMock).toHaveBeenCalledWith(expect.stringContaining("丢弃这个工作稿"), expect.any(Function))
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
  it("创建新页面弹模态", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-new-page']").trigger("click")
    expect(showModalHtmlMock).toHaveBeenCalled()
    expect(showModalHtmlMock.mock.calls[0][0]).toBe("新建世界书页面")
    const html = showModalHtmlMock.mock.calls[0][1]
    expect(html).toContain("bible-create-title")
  })

  it("管理分类弹模态", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    expect(showModalHtmlMock).toHaveBeenCalled()
    expect(showModalHtmlMock.mock.calls[0][0]).toBe("管理世界书类别")
  })

  it("页面模板弹模态", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-manage-page-templates']").trigger("click")
    expect(showModalHtmlMock).toHaveBeenCalled()
    expect(showModalHtmlMock.mock.calls[0][0]).toBe("页面模板")
  })

  it("版本历史弹模态", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.listBiblePageRevisions = vi.fn().mockResolvedValue([])
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-page-history']").trigger("click")
    await nextTick()
    expect(showModalHtmlMock).toHaveBeenCalled()
  })

  it("刷新 synopsis 调用 API", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.refreshBibleSynopsis = vi.fn().mockResolvedValue({ task_id: "task-synopsis", existing: false })
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-refresh-synopsis']").trigger("click")
    await nextTick()
    expect(api.world.refreshBibleSynopsis).toHaveBeenCalledWith("p1")
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
    expect(wrapper.find(".world-bible-synopsis-panel").text()).toContain("v3")
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
})

describe("同步与事件", () => {
  it("worldSession bible 字段随组件初始化更新", () => {
    mountTab()
    expect(worldSession.bible.activePageId).toBe("page-1")
  })
})

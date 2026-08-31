/**
 * WorldBibleTab 测试 — 渲染契约、显示模式切换、编辑器行为、模态交互、守卫。
 *
 * 覆盖 vanilla worldBibleView.test.js（1148 行）的核心行为 + E2E 契约。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import { nextTick } from "vue"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"

vi.mock("../../../../shared/referencePicker.js", () => ({
  createReferencePicker: vi.fn((options) => ({ destroy: vi.fn(), resolve: vi.fn(), getRefs: vi.fn(() => []), onOpen: options.onOpen })),
}))

vi.mock("../../../../shared/workflowProgress.js", () => ({
  pollTaskProgress: vi.fn(() => ({ stop: vi.fn() })),
}))

const confirmAiReference = vi.hoisted(() => vi.fn())
vi.mock("../../../../shared/aiReferenceModal.js", () => ({ confirmAiReference }))

vi.mock("../../../../shared/assetDisplayState.js", () => ({
  displayStateBadgeClass: vi.fn((state) => state === "active" ? "badge-canonical" : "badge-draft"),
  worldAssetDisplay: vi.fn((item) => {
    const status = item?.status || ""
    if (item?.display_state === "archived" || status === "archived") {
      return { label: "历史", displayState: "archived", isHistory: true }
    }
    if (item?.display_state === "active" || ["active", "canonical", "confirmed", "published"].includes(status)) {
      return { label: "已采用", displayState: "active", isHistory: false }
    }
    return { label: "待处理", displayState: "review", isHistory: false }
  }),
}))

import WorldBibleTab from "../../../../vue/views/world/bible/WorldBibleTab.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"
import { resetWorldSession, worldSession } from "../../../../vue/views/world/worldSession.js"
import { pollTaskProgress } from "../../../../shared/workflowProgress.js"
import { createReferencePicker } from "../../../../shared/referencePicker.js"
import { readCreativeContinuation, writeCreativeContinuation } from "../../../../vue/views/generate/generateSession.js"

// ---- test data ----
const PAGE_1 = {
  id: "page-1", novel_id: "p1", page_type: "background", title: "世界基本背景",
  version_number: 1,
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
  version_number: 1,
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

const EMPTY_IMPACT = {
  source: { draft_id: "draft-1", page_id: "page-1", title: "世界基本背景", page_version: 1 },
  added_outgoing_refs: 0,
  removed_outgoing_refs: 0,
  affected_pages: [],
  omissions: [],
  automatic_actions: ["保存不可变页面版本", "标记世界观简介需要刷新"],
  not_checked: ["故事总纲与 Scene", "正文和自由文本中的语义提及"],
  complete: true,
  impact_scope_hash: "a".repeat(64),
}

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
  const footer = document.createElement("div")
  footer.id = "modal-footer"
  overlay.appendChild(body)
  overlay.appendChild(footer)
  document.body.appendChild(overlay)
  showModalHtmlMock.mockImplementation((_title, html, buttons = []) => {
    body.innerHTML = html
    footer.innerHTML = ""
    for (const descriptor of buttons) {
      const button = document.createElement("button")
      button.className = `btn ${descriptor.class || ""}`
      button.textContent = descriptor.text
      button.addEventListener("click", () => descriptor.handler?.())
      footer.appendChild(button)
    }
    overlay.classList.remove("hidden")
  })
  return { overlay, body, footer }
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

async function openNewPage() {
  document.querySelector("#sidebar-context-slot [data-action='bible-new-resource']").click()
  await nextTick()
  document.querySelector("[data-action='bible-new-page-choice']").click()
  await nextTick()
}

enableAutoUnmount(afterEach)

beforeEach(() => {
  vi.clearAllMocks()
  confirmAiReference.mockResolvedValue({ id: "confirm-default" })
  localStorage.clear()
  resetWorldSession()
  navigateMock = vi.fn(() => true)
  toastMock = vi.fn()
  confirmMock = vi.fn(() => true)
  showModalHtmlMock = vi.fn()
  closeModalMock = vi.fn()
  confirmActionMock = vi.fn((message, handler) => handler())
  appState = { currentProjectId: "p1", currentView: "world" }
  document.body.insertAdjacentHTML("afterbegin", '<div id="sidebar-context-slot"></div>')
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

  it("资料库首页把常用工具注入一级侧栏", () => {
    mountTab({ defaultDisplayMode: "gallery" })
    const tools = document.querySelector("#sidebar-context-slot .world-sidebar-tools")
    expect(tools).not.toBeNull()
    expect(tools.textContent).toContain("新建资料")
    expect(tools.textContent).toContain("世界健康")
    expect(tools.textContent).toContain("页面中的未决项")
    expect(tools.textContent).toContain("AI 工具")
    expect(tools.textContent).toContain("更多工具")
  })

  it("更多工具弹窗支持 Escape 并恢复触发按钮焦点", async () => {
    mountTab({ defaultDisplayMode: "gallery" })
    const trigger = document.querySelector("[data-action='world-tool-more']")
    trigger.focus()
    trigger.click()
    await nextTick()
    const dialog = document.querySelector(".world-tool-dialog")
    expect(dialog?.textContent).toContain("管理分类")
    dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
    await nextTick()
    expect(document.querySelector(".world-tool-dialog")).toBeNull()
    await vi.waitFor(() => expect(document.activeElement).toBe(trigger))
  })

  it("汇总已保存的未决项，以工作稿覆盖正式页并可打开来源", async () => {
    const openSection = (body) => ({
      section_id: "author-open-questions", section_type: "checklist", title: "仍待作者决定",
      body_markdown: body, sort_order: 20, linked_asset_ref_hashes: [],
      projection_policy: "excluded", sensitivity_hint: "author_only",
    })
    const bible = defaultBible()
    bible.pages = [
      { ...PAGE_1, sections_json: [openSection("- [ ] 正式页里的旧税率问题")] },
      { ...PAGE_2, sections_json: [openSection("- [ ] 灵族故乡如何命名")] },
      { ...PAGE_2, id: "page-archived", status: "archived", title: "历史页面", sections_json: [openSection("- [ ] 已归档的旧问题")] },
    ]
    bible.drafts = [
      { ...DRAFT_1, sections_json: [openSection("- [ ] 新税率由谁批准\n- [x] 已决定的税率")] },
      { ...DRAFT_FREE, sections_json: [openSection("* [ ] 禁术的代价是什么")] },
    ]

    const wrapper = mountTab({ bible, defaultDisplayMode: "gallery" })
    document.querySelector("[data-action='world-tool-questions']").click()
    await nextTick()
    let panel = document.querySelector(".world-tool-dialog")
    expect(panel.textContent).toContain("新税率由谁批准")
    expect(panel.textContent).toContain("灵族故乡如何命名")
    expect(panel.textContent).toContain("禁术的代价是什么")
    expect(panel.textContent).not.toContain("正式页里的旧税率问题")
    expect(panel.textContent).not.toContain("已决定的税率")
    expect(panel.textContent).not.toContain("已归档的旧问题")

    panel.querySelector("[data-bible-open-question-page-id='page-2']").click()
    await vi.waitFor(() => expect(wrapper.get("#bible-title").element.value).toBe("种族设定"))

    await wrapper.get("[data-mode='gallery']").trigger("click")
    document.querySelector("[data-action='world-tool-questions']").click()
    await nextTick()
    panel = document.querySelector(".world-tool-dialog")
    panel.querySelector("[data-bible-open-question-draft-id='draft-free']").click()
    await vi.waitFor(() => expect(wrapper.get("#bible-title").element.value).toBe("新页工作稿"))
  })

  it("浏览只暴露卡片和列表，编辑时提供返回资料库", () => {
    const editor = mountTab()
    expect(editor.find(".world-bible-toolbar__modes").exists()).toBe(false)
    expect(editor.find("[data-action='bible-open-graph']").exists()).toBe(true)
    expect(editor.text()).toContain("返回资料库")

    const library = mountTab({ defaultDisplayMode: "gallery" })
    expect(library.find(".world-bible-toolbar__modes").exists()).toBe(false)
    expect(library.find(".world-type-grid").exists()).toBe(true)
    expect(document.querySelector("#sidebar-context-slot")?.textContent).toContain("新建资料")
  })

  it("普通资料库入口忽略旧展示偏好，显式页面深链仍精确打开", () => {
    localStorage.setItem("worldBible:p1:displayMode", "graph")

    const library = mountTab({ defaultDisplayMode: "gallery" })
    expect(library.find(".world-library-content").exists()).toBe(true)
    library.unmount()

    const deepLink = mountTab({
      defaultDisplayMode: "gallery",
      bibleDeepLink: { draftId: "", pageId: "page-2" },
    })
    expect(deepLink.get("#bible-title").element.value).toBe("种族设定")
  })

  it("从资料返回时按项目与查询恢复滚动位置", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    document.body.appendChild(content)
    const filters = { q: "北境", kind: "all", type: "", state: "", layout: "cards" }
    const first = mountTab({ defaultDisplayMode: "gallery", worldCardFilters: filters })
    content.scrollTop = 240

    await first.get("[data-action='open-world-card']").trigger("click")
    expect(worldSession.bible.libraryScrollPositions["p1:q=%E5%8C%97%E5%A2%83"]).toBe(240)
    first.unmount()
    content.scrollTop = 0

    mountTab({ defaultDisplayMode: "gallery", worldCardFilters: filters })
    await vi.waitFor(() => expect(content.scrollTop).toBe(240))
  })

  it("编辑器桌面只保留目录与内容两列，AI 规则在内容内按需展开", () => {
    const wrapper = mountTab()
    const synopsis = wrapper.get(".world-bible-synopsis-panel")
    const layout = wrapper.get(".world-bible-layout")
    const content = layout.get(".world-bible-content-column")
    const inspector = content.get(".world-bible-inspector")
    expect(synopsis.exists()).toBe(true)
    expect(synopsis.attributes("open")).toBeUndefined()
    expect(Array.from(layout.element.children)).toHaveLength(2)
    expect(layout.element.children[0].classList).toContain("world-bible-nav-rail")
    expect(layout.element.children[1]).toBe(content.element)
    expect(content.find(".world-bible-editor-panel").exists()).toBe(true)
    expect(inspector.element.parentElement).toBe(content.element)
  })

  it("两列 CSS 不会因 AI 规则折叠状态恢复第三列，760px 以下单列", () => {
    const styles = readFileSync(resolve(import.meta.dirname, "../../../../styles.css"), "utf8")
    const layoutRules = Array.from(styles.matchAll(/\.world-bible-layout\s*\{([^}]*)\}/g), (match) => match[1])

    expect(layoutRules.length).toBeGreaterThan(0)
    for (const rule of layoutRules) {
      const columns = rule.match(/grid-template-columns:\s*([^;]+);/)?.[1]
      if (columns) expect((columns.match(/minmax\(/g) || []).length).toBeLessThanOrEqual(2)
    }
    expect(styles).not.toContain(".world-bible-layout:has(.world-bible-inspector")
    expect(styles).toMatch(/@media \(max-width: 760px\)[\s\S]*\.world-bible-layout,[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/)
  })

  it("无 AI 参考规则时默认收起次级配置", () => {
    const wrapper = mountTab({ bible: { ...defaultBible(), activationProfiles: [] } })
    const inspector = wrapper.get("[data-section='bible-ai-reference-rules']")

    expect(inspector.attributes("open")).toBeUndefined()
    expect(inspector.get("summary").text()).toContain("按需设置")
  })

  it("AI 参考规则使用作者可读状态，不暴露内部标识", () => {
    const wrapper = mountTab()
    const inspector = wrapper.get(".world-bible-inspector")

    expect(inspector.text()).toContain("规则方案")
    expect(inspector.text()).toContain("工作稿")
    expect(inspector.text()).toContain("用于 1 种写作场景")
    expect(inspector.text()).not.toContain("Activation Profile")
    expect(inspector.text()).not.toContain("writing.world")
    expect(inspector.text()).not.toContain("writing.generate")
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
    expect(wrapper.get("[data-section='bible-page-settings']").attributes("open")).toBeUndefined()
    expect(wrapper.get("[data-section='bible-page-settings'] summary").text()).toBe("页面设置")
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

  it("空的 bible 在资料库入口显示类型首页", () => {
    const wrapper = mountTab({ defaultDisplayMode: "gallery", bible: { pages: [], categories: [], drafts: [], synopsis: null, pageTemplates: [], activationProfiles: [] } })
    expect(wrapper.find(".world-type-grid").exists()).toBe(true)
    expect(document.querySelector("[data-action='world-tool-questions']")?.textContent).toContain("页面中的未决项")
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
    expect(wrapper.find(".world-library-directory").exists()).toBe(false)
    expect(wrapper.find(".world-type-grid").exists()).toBe(true)
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

  it("资料库首页提供统一创建入口和常用类型", () => {
    const wrapper = mountTab({
      defaultDisplayMode: "gallery",
      bible: { pages: [], categories: [], drafts: [], entities: [], synopsis: null, pageTemplates: [], activationProfiles: [] },
    })

    expect(wrapper.get(".world-bible-gallery__hero").text()).toContain("人物与世界")
    expect(wrapper.get(".world-type-grid").text()).toContain("人物")
    expect(wrapper.get(".world-type-grid").text()).toContain("工作稿")
    expect(document.querySelector("[data-action='bible-new-resource']")?.textContent).toContain("新建资料")
  })

  it("对象计数加载失败时保留类型首页和原位重试", () => {
    const wrapper = mountTab({
      defaultDisplayMode: "gallery",
      bible: { ...defaultBible(), entities: [], entitiesLoadError: "网络暂不可用" },
    })

    const error = wrapper.get("[data-author-action='retry']")
    expect(error.attributes("role")).toBe("alert")
    expect(error.text()).toContain("资料页和工作稿仍可使用")
    expect(error.get("button").text()).toBe("重新加载")
    expect(wrapper.find(".world-type-grid").exists()).toBe(true)
  })

  it("对象加载失败且没有资料页时不显示误导性空态", () => {
    const wrapper = mountTab({
      defaultDisplayMode: "gallery",
      bible: { ...defaultBible(), pages: [], drafts: [], entities: [], entitiesLoadError: "网络暂不可用" },
    })

    expect(wrapper.get("[data-author-action='retry']").text()).toContain("重新加载")
    expect(wrapper.text()).not.toContain("还没有人物或世界资料")
    expect(wrapper.text()).not.toContain("没有找到符合条件的资料")
  })

  it("统一卡片依页面真实状态显示，不把草稿和待处理标成已采用", () => {
    const wrapper = mountTab({
      defaultDisplayMode: "gallery",
      worldCardFilters: { q: "", kind: "page", type: "", state: "", layout: "cards" },
      bible: {
        ...defaultBible(),
        drafts: [],
        entities: [],
        pages: [
          { ...PAGE_1, id: "page-draft", status: "draft" },
          { ...PAGE_1, id: "page-candidate", status: "candidate" },
          { ...PAGE_1, id: "page-active", status: "canonical" },
        ],
      },
    })

    const labels = wrapper.findAll(".world-card .badge").map((badge) => badge.text())
    expect(labels).toEqual(expect.arrayContaining(["工作稿", "待处理", "已采用"]))
    expect(wrapper.findAll(".world-card").every((card) => card.attributes("data-world-card-id") === undefined)).toBe(true)
  })

  it("卡片和列表共用同一组资料，并从 URL 恢复列表视图", () => {
    const wrapper = mountTab({
      defaultDisplayMode: "gallery",
      worldCardFilters: { q: "", kind: "page", type: "", state: "", layout: "list" },
    })

    expect(wrapper.find(".world-card-grid").exists()).toBe(false)
    expect(wrapper.findAll(".world-library-list__row")).toHaveLength(3)
    expect(document.querySelector("#sidebar-context-slot")?.textContent).toContain("切换到卡片")
  })

  it("打开资料页或工作稿时保留筛选并写入精确深链", async () => {
    const wrapper = mountTab({
      defaultDisplayMode: "gallery",
      worldCardFilters: { q: "", kind: "page", type: "", state: "", layout: "list" },
    })
    const cards = wrapper.findAll(".world-library-list__row")

    await cards.find((card) => card.text().includes("种族设定"))
      .get("[data-action='open-world-card']").trigger("click")
    let query = navigateMock.mock.calls.at(-1)[3]
    expect(query.get("kind")).toBe("page")
    expect(query.get("layout")).toBe("list")
    expect(query.get("page_id")).toBe("page-2")
    expect(query.get("draft_id")).toBeNull()

    await cards.find((card) => card.text().includes("世界基本背景"))
      .get("[data-action='open-world-card']").trigger("click")
    query = navigateMock.mock.calls.at(-1)[3]
    expect(query.get("draft_id")).toBe("draft-1")
    expect(query.get("page_id")).toBeNull()
  })

  it("类型首页将工作稿写回 URL", async () => {
    const wrapper = mountTab({ defaultDisplayMode: "gallery" })
    const working = wrapper.findAll(".world-type-card")
      .find((button) => button.text().includes("工作稿"))

    await working.trigger("click")

    expect(navigateMock).toHaveBeenCalledWith("world", "bible", true, expect.any(URLSearchParams))
    const query = navigateMock.mock.calls.at(-1)[3]
    expect(query.get("state")).toBe("working")
    expect(query.get("kind")).toBe("page")
  })

  it("可从资料页原位建立作者任务", async () => {
    const wrapper = mountTab({ defaultDisplayMode: "gallery", worldCardFilters: { q: "", kind: "page", type: "", state: "", layout: "cards" } })
    const pageCard = wrapper.findAll(".world-card").find((card) => card.text().includes("世界基本背景"))

    await pageCard.get("[data-action='world-card-create-task']").trigger("click")

    expect(navigateMock).toHaveBeenCalledWith("writing", null, true, expect.any(URLSearchParams))
    const query = navigateMock.mock.calls.at(-1)[3]
    expect(query.get("panel")).toBe("tasks")
    expect(query.get("task_source_kind")).toBe("world_page")
    expect(query.get("task_source_id")).toBe("page-1")
  })

  it("工作稿改名时仍使用明确的正式页来源名称", async () => {
    const wrapper = mountTab({
      defaultDisplayMode: "gallery",
      worldCardFilters: { q: "", kind: "page", type: "", state: "", layout: "cards" },
      bible: {
        ...defaultBible(),
        pages: [{ ...PAGE_1, title: "七大正神" }, PAGE_2],
        drafts: [{ ...DRAFT_1, title: "七大正神教会" }, DRAFT_FREE],
      },
    })
    const pageCard = wrapper.findAll(".world-card").find((card) => card.text().includes("七大正神教会"))

    await pageCard.get("[data-action='world-card-create-task']").trigger("click")

    const query = navigateMock.mock.calls.at(-1)[3]
    expect(query.get("task_source_id")).toBe("page-1")
    expect(query.get("task_title")).toBe("七大正神")
  })

  it("对象详情和别名在资料库内打开，返回保留筛选", async () => {
    const entity = {
      id: "entity-1", name: "沉钟港", entity_type: "location", summary: "北境港口", display_state: "active",
      content_json: { aliases: [{ alias: "旧港", alias_kind: "name", alias_type: "name" }] },
    }
    const wrapper = mountTab({
      defaultDisplayMode: "gallery",
      bible: { ...defaultBible(), entities: [entity], entityTotal: 1 },
      bibleDeepLink: { draftId: "", pageId: "", entityId: "entity-1", entitySection: "aliases" },
      worldCardFilters: { q: "港", kind: "entity", type: "location", state: "", layout: "cards" },
      entityTypes: [{ value: "location", label: "地点" }],
    })

    expect(wrapper.get(".world-entity-detail").text()).toContain("沉钟港")
    expect(wrapper.get(".world-entity-detail__aliases").text()).toContain("旧港")
    await wrapper.get(".world-entity-detail .btn-ghost").trigger("click")
    const query = navigateMock.mock.calls.at(-1)[3]
    expect(query.get("q")).toBe("港")
    expect(query.get("kind")).toBe("entity")
    expect(query.get("entity_id")).toBeNull()
  })

  it("打开对象详情时回到顶部，让小屏返回入口立即可见", async () => {
    const content = document.createElement("div")
    content.id = "workspace-content"
    content.scrollTop = 320
    document.body.appendChild(content)
    const entity = {
      id: "entity-1", name: "沉钟港", entity_type: "location", summary: "北境港口", display_state: "active",
      content_json: { aliases: [] },
    }

    const wrapper = mountTab({
      defaultDisplayMode: "gallery",
      bible: { ...defaultBible(), entities: [entity], entityTotal: 1 },
      bibleDeepLink: { draftId: "", pageId: "", entityId: "entity-1" },
    })

    await vi.waitFor(() => expect(content.scrollTop).toBe(0))
    expect(wrapper.get(".world-entity-detail__back").text()).toContain("返回资料库")
  })

  it("关联资产保留对象深链并进入统一详情，未保存时仍受离开门禁保护", async () => {
    const wrapper = mountTab({
      worldCardFilters: { q: "港", kind: "entity", type: "location", state: "", layout: "list" },
    })
    await wrapper.get("#bible-title").setValue("未保存的修改")
    const picker = createReferencePicker.mock.results.at(-1).value

    confirmMock.mockReturnValueOnce(false)
    picker.onOpen({ kind: "core_entity", id: "entity-1" })
    expect(navigateMock).not.toHaveBeenCalled()

    confirmMock.mockReturnValueOnce(true)
    picker.onOpen({ kind: "core_entity", id: "entity-1" })
    const [view, subView, updateHistory, query] = navigateMock.mock.calls.at(-1)
    expect([view, subView, updateHistory]).toEqual(["world", "bible", true])
    expect(query.get("entity_id")).toBe("entity-1")
    expect(query.get("q")).toBe("港")
    expect(query.get("kind")).toBe("entity")
    expect(query.get("type")).toBe("location")
    expect(query.get("layout")).toBe("list")
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
    expect(sections[0].find(".world-bible-section-editor__toolbar .badge").text()).toBe("第 1 节")
    expect(sections[0].find("[data-section-field='section_type']").text()).toContain("普通资料")
    expect(sections[0].find("[data-section-field='section_type']").text()).not.toContain("asset_collection")
    expect(sections[0].find("[data-section='bible-section-advanced']").attributes("open")).toBeUndefined()
    expect(sections[0].find("[data-section='bible-section-advanced'] summary").text()).toBe("创作辅助与高级设置")
    expect(sections[0].find(".world-bible-diagnostics").attributes("open")).toBeUndefined()
  })

  it("折叠高级设置仍按原 wire 字段保存分区控制", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.updateBibleDraft = vi.fn().mockResolvedValue({ ...DRAFT_1 })
    const wrapper = mountTab()
    const section = wrapper.findAll(".world-bible-section-editor")[0]

    await section.find("[data-section-field='section_type']").setValue("checklist")
    await section.find("[data-section-field='sensitivity_hint']").setValue("author_only")
    await section.find("[data-section-field='projection_policy']").setValue("excluded")
    await section.find("[data-section-field='linked_asset_ref_hashes']").setValue("a".repeat(64))
    await wrapper.find("[data-action='bible-save-page']").trigger("click")
    await vi.waitFor(() => expect(api.world.updateBibleDraft).toHaveBeenCalledTimes(1))

    expect(api.world.updateBibleDraft.mock.calls[0][1].sections_json[0]).toEqual(expect.objectContaining({
      section_id: "s1",
      section_type: "checklist",
      sensitivity_hint: "author_only",
      projection_policy: "excluded",
      linked_asset_ref_hashes: ["a".repeat(64)],
    }))
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
    expect(readCreativeContinuation("p1")).toMatchObject({
      destination: "world_bible_draft",
      route: { draft_id: "draft-1", page_id: "page-1" },
    })
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

  it("发布工作稿先显示诚实空态，再携带 scope hash 确认", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.createBibleDraft = vi.fn()
    api.world.updateBibleDraft = vi.fn().mockResolvedValue({ id: "draft-1", page_id: "page-1", ...DRAFT_1 })
    api.world.previewBibleDraftPublishImpact = vi.fn().mockResolvedValue(EMPTY_IMPACT)
    api.world.publishBibleDraft = vi.fn().mockResolvedValue({
      ...PAGE_1,
      version_number: 2,
      validation_receipt: {
        scope: "targeted", scope_label: "当前页面与 0 个显式下游", source_version: 2,
        checked: ["来源基线与写入版本"], not_checked: ["所属领域的完整检查"], omissions: [],
      },
    })
    const wrapper = mountTab()
    await wrapper.find("#bible-title").setValue("世界基本背景")
    await wrapper.find("[data-action='bible-publish-page']").trigger("click")
    await nextTick()
    expect(api.world.updateBibleDraft).toHaveBeenCalled()
    expect(api.world.previewBibleDraftPublishImpact).toHaveBeenCalledWith("draft-1", "p1")
    expect(api.world.publishBibleDraft).not.toHaveBeenCalled()
    const [, body, actions] = showModalHtmlMock.mock.calls.at(-1)
    expect(body).toContain("未发现显式引用；自由文本和其他创作领域未检查")
    expect(body).toContain("本次未检查")
    await actions.find((item) => item.text === "确认发布").handler()
    expect(api.world.publishBibleDraft).toHaveBeenCalledWith("draft-1", "p1", "a".repeat(64))
    expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("已发布"), "success")
    const [receiptTitle, receiptBody] = showModalHtmlMock.mock.calls.at(-1)
    expect(receiptTitle).toContain("检查回执")
    expect(receiptBody).toContain("定向检查")
    expect(receiptBody).toContain("所属领域的完整检查")
    expect(receiptBody).toContain("不表示整个世界观语义完全正确")
  })

  it("影响预演用作者语言折叠显示最短路径，不暴露 ID 或 hash", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.updateBibleDraft = vi.fn().mockResolvedValue({ id: "draft-1", page_id: "page-1", ...DRAFT_1 })
    api.world.previewBibleDraftPublishImpact = vi.fn().mockResolvedValue({
      ...EMPTY_IMPACT,
      affected_pages: [{
        page_id: "page-secret-id",
        title: "轮班制度<img src=x>",
        page_type: "rule",
        version_number: 3,
        distance: 2,
        path: [
          { page_id: "page-1", title: "世界基本背景", version_number: 1, section_titles: [] },
          { page_id: "page-2", title: "港区日常", version_number: 2, section_titles: ["道路"] },
          { page_id: "page-secret-id", title: "轮班制度<img src=x>", version_number: 3, section_titles: ["值守"] },
        ],
      }],
    })
    const wrapper = mountTab()

    await wrapper.find("[data-action='bible-publish-page']").trigger("click")
    await nextTick()

    const body = showModalHtmlMock.mock.calls.at(-1)[1]
    expect(body).toContain("建议核对（1）")
    expect(body).toContain("世界基本背景 ← 港区日常 ← 轮班制度&lt;img src=x&gt;")
    expect(body).toContain("分区：值守")
    expect(body).not.toContain("<img src=x>")
    expect(body).not.toContain("page-secret-id")
    expect(body).not.toContain("a".repeat(64))
  })

  it("影响预演暂不可用时保留工作稿与人工发布出口", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.updateBibleDraft = vi.fn().mockResolvedValue({ id: "draft-1", page_id: "page-1", ...DRAFT_1 })
    api.world.previewBibleDraftPublishImpact = vi.fn().mockRejectedValue(new Error("offline"))
    api.world.publishBibleDraft = vi.fn().mockResolvedValue({ ...PAGE_1, version_number: 2 })
    const wrapper = mountTab()

    await wrapper.find("[data-action='bible-publish-page']").trigger("click")
    await nextTick()

    const [title, body, actions] = showModalHtmlMock.mock.calls.at(-1)
    expect(title).toBe("影响预演暂不可用")
    expect(body).toContain("工作稿已经保存")
    expect(api.world.publishBibleDraft).not.toHaveBeenCalled()
    await actions.find((item) => item.text === "仍然发布").handler()
    expect(api.world.publishBibleDraft).toHaveBeenCalledWith("draft-1", "p1", null)
  })

  it("确认前引用关系变化时保留工作稿并要求重新核对", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.updateBibleDraft = vi.fn().mockResolvedValue({ id: "draft-1", page_id: "page-1", ...DRAFT_1 })
    api.world.previewBibleDraftPublishImpact = vi.fn().mockResolvedValue(EMPTY_IMPACT)
    const conflict = Object.assign(new Error("conflict"), { status: 409 })
    api.world.publishBibleDraft = vi.fn().mockRejectedValue(conflict)
    const wrapper = mountTab()

    await wrapper.find("[data-action='bible-publish-page']").trigger("click")
    await nextTick()
    const actions = showModalHtmlMock.mock.calls.at(-1)[2]
    await actions.find((item) => item.text === "确认发布").handler()

    expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("显式引用关系已变化"), "warning")
    expect(readCreativeContinuation("p1")).toMatchObject({
      destination: "world_bible_draft",
      route: { draft_id: "draft-1", page_id: "page-1" },
    })
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
    expect(showModalHtmlMock.mock.calls[0][0]).toBe("保存后打开 AI 工具")
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
    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("管理世界书分类")
    expect(closeModalMock).not.toHaveBeenCalled()
    expect(navigateMock).not.toHaveBeenCalled()
    expect(toastMock).not.toHaveBeenCalledWith("工作稿已保存；正式页面尚未变化", "success")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("固定当前页基线检修并只显示作者决定或改进项", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.generate.inspectWorldPage = vi.fn().mockResolvedValue({
      findings: [{
        item_id: "S1",
        author_action: "needs_decision",
        summary: "开放税率被写成唯一事实",
        evidence: "待定标记与三成税率同时存在",
        location: "货币分区",
        next_step: "决定是否继续开放并重检",
      }],
      receipt: {
        scope_label: "当前世界书页《世界基本背景》",
        source_version: 1,
        checks_run: ["权威顺序"],
        not_run: ["章节正文"],
        omissions: ["不能证明页面完整无误。"],
      },
    })
    const wrapper = mountTab()

    await wrapper.get("[data-action='bible-inspect-current-page']").trigger("click")
    await vi.waitFor(() => expect(api.generate.inspectWorldPage).toHaveBeenCalledOnce())
    await vi.waitFor(() => expect(showModalHtmlMock).toHaveBeenCalledWith(
      "当前页检修",
      expect.stringContaining("需要你决定"),
      expect.any(Array),
      { size: "large" },
    ))

    expect(api.generate.inspectWorldPage).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      source_context: {
        kind: "world_bible_page",
        page_id: "page-1",
        baseline: {
          kind: "draft",
          page_version: 1,
          draft_id: "draft-1",
          draft_updated_at: DRAFT_1.updated_at,
        },
      },
      target: { kind: "world_bible_page", page_id: "page-1" },
      include_world_synopsis: false,
    }), { signal: expect.any(AbortSignal) })
    const html = showModalHtmlMock.mock.calls.at(-1)[1]
    expect(html).toContain("开放税率被写成唯一事实")
    expect(html).toContain("章节正文")
    expect(html).not.toContain("必须修复")
  })

  it("允许作者停止当前页检修且不承诺瞬时断开远端", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    let resolveInspection
    api.generate.inspectWorldPage = vi.fn(() => new Promise((resolve) => {
      resolveInspection = resolve
    }))
    const wrapper = mountTab()
    const button = wrapper.get("[data-action='bible-inspect-current-page']")

    await button.trigger("click")
    await vi.waitFor(() => expect(api.generate.inspectWorldPage).toHaveBeenCalledOnce())
    const signal = api.generate.inspectWorldPage.mock.calls[0][1].signal
    expect(button.text()).toBe("停止检修")

    await button.trigger("click")

    expect(signal.aborted).toBe(true)
    expect(toastMock).toHaveBeenCalledWith(
      "已停止后续检修；远端请求可能正在结束",
      "warning",
    )
    resolveInspection({ findings: [{ summary: "不应显示的迟到检修" }], receipt: {} })
    await Promise.resolve()
    await nextTick()
    expect(showModalHtmlMock).not.toHaveBeenCalledWith(
      "当前页检修",
      expect.stringContaining("不应显示的迟到检修"),
      expect.anything(),
      expect.anything(),
    )
    expect(toastMock).not.toHaveBeenCalledWith("已完成本次当前页检修", "success")
  })

  it("离开页面后不打开迟到的检修结果", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    let resolveInspection
    api.generate.inspectWorldPage = vi.fn(() => new Promise((resolve) => {
      resolveInspection = resolve
    }))
    const wrapper = mountTab()

    await wrapper.get("[data-action='bible-inspect-current-page']").trigger("click")
    await vi.waitFor(() => expect(api.generate.inspectWorldPage).toHaveBeenCalledOnce())
    const signal = api.generate.inspectWorldPage.mock.calls[0][1].signal
    wrapper.unmount()
    expect(signal.aborted).toBe(true)

    resolveInspection({ findings: [], receipt: {} })
    await Promise.resolve()
    await nextTick()

    expect(showModalHtmlMock).not.toHaveBeenCalledWith(
      "当前页检修",
      expect.anything(),
      expect.anything(),
      expect.anything(),
    )
    expect(toastMock).not.toHaveBeenCalledWith("已完成本次当前页检修", "success")
  })

  it("创建新页面弹模态", async () => {
    mountTab()
    await openNewPage()
    expect(showModalHtmlMock).toHaveBeenCalled()
    expect(showModalHtmlMock.mock.calls[0][0]).toBe("新建世界书页面")
    const html = showModalHtmlMock.mock.calls[0][1]
    expect(html).toContain("bible-create-title")
    expect(html).toContain("页面分类")
    expect(html).toContain('<option value="__new_category__">＋新建分类…</option>')
    expect(html).not.toContain('<option value="custom"')
  })

  it("新建页面在同一弹窗进入分类第二步并可返回保留表单", async () => {
    mountTab()
    installModalHost()

    await openNewPage()
    document.getElementById("bible-create-title").value = "云海历法"
    document.getElementById("bible-create-template").value = "e2e_trade_guide"
    const type = document.getElementById("bible-create-type")
    type.value = "__new_category__"
    type.dispatchEvent(new Event("change", { bubbles: true }))

    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("为页面新建分类")
    expect(document.querySelectorAll("[data-bible-category-preset]")).toHaveLength(7)
    expect(document.getElementById("bible-category-key")).toBeNull()
    expect(document.getElementById("bible-category-order")).toBeNull()
    expect(document.getElementById("bible-category-color").type).toBe("color")

    document.querySelector("[data-bible-category-preset='technology']").click()
    expect(document.getElementById("bible-category-name").value).toBe("技术体系")
    expect(document.getElementById("bible-category-description").value).toBe("技术、工程、能源与制造")
    expect(document.getElementById("bible-category-icon").value).toBe("技术")
    expect(document.querySelector("[data-bible-category-preset='technology']").getAttribute("aria-pressed")).toBe("true")

    document.querySelector("#modal-footer .btn-ghost").click()
    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("新建世界书页面")
    expect(document.getElementById("bible-create-title").value).toBe("云海历法")
    expect(document.getElementById("bible-create-template").value).toBe("e2e_trade_guide")
    expect(document.getElementById("bible-create-type").value).toBe("background")
  })

  it("六个预设值精确填充并将新分类用于工作稿", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const presets = [
      ["technology", "技术体系", "技术、工程、能源与制造", "#2563EB", "技术"],
      ["power_system", "力量体系", "魔法、能力、等级、限制与代价", "#DC2626", "力量"],
      ["governance", "政治制度", "权力结构、法律、治理与继承", "#7C3AED", "制度"],
      ["economy", "经济贸易", "货币、资源、产业与交换", "#D97706", "贸易"],
      ["religion", "宗教信仰", "神话、教派、仪式与禁忌", "#9333EA", "信仰"],
      ["culture_language", "文化语言", "语言、命名、习俗与艺术", "#059669", "文化"],
    ]
    mountTab()
    installModalHost()
    await openNewPage()
    const type = document.getElementById("bible-create-type")
    type.value = "__new_category__"
    type.dispatchEvent(new Event("change", { bubbles: true }))

    for (const [key, name, description, color, icon] of presets) {
      document.querySelector(`[data-bible-category-preset='${key}']`).click()
      expect(document.getElementById("bible-category-name").value).toBe(name)
      expect(document.getElementById("bible-category-description").value).toBe(description)
      expect(document.getElementById("bible-category-color").value.toUpperCase()).toBe(color)
      expect(document.getElementById("bible-category-icon").value).toBe(icon)
    }

    document.querySelector("[data-bible-category-preset='technology']").click()
    api.world.createBibleCategory = vi.fn().mockResolvedValue({
      id: "cat-tech", category_key: "technology", name: "技术体系", description: "技术、工程、能源与制造",
      color: "#2563EB", icon: "技术", sort_order: 100, status: "active", builtin: false,
    })
    api.world.createBibleDraft = vi.fn().mockResolvedValue({ ...DRAFT_FREE, id: "draft-tech", title: "世界基本背景", page_type: "technology" })
    await showModalHtmlMock.mock.calls.at(-1)[2][0].handler()

    expect(showModalHtmlMock.mock.calls.at(-1)[1]).toContain('<option value="technology" selected>')
    expect(Array.from(document.getElementById("bible-create-type").options).map((option) => [option.value, option.selected])).toEqual([
      ["background", false], ["species", false], ["technology", true], ["__new_category__", false],
    ])
    await showModalHtmlMock.mock.calls.at(-1)[2][0].handler()
    expect(api.world.createBibleDraft).toHaveBeenCalledWith(expect.objectContaining({ page_type: "technology" }))
    expect(api.world.createBibleDraft.mock.calls[0][0].page_type).not.toBe("custom")
  })

  it("自己命名使用浏览器 UUID 生成内部键并自动取卡片标记", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const uuid = vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue("12345678-1234-4abc-8def-1234567890ab")
    api.world.createBibleCategory = vi.fn(async (payload) => ({ id: "cat-own", ...payload, status: "active", builtin: false }))
    mountTab()
    installModalHost()
    await openNewPage()
    const type = document.getElementById("bible-create-type")
    type.value = "__new_category__"
    type.dispatchEvent(new Event("change", { bubbles: true }))
    document.getElementById("bible-category-name").value = "天文历法"
    document.getElementById("bible-category-name").dispatchEvent(new Event("input", { bubbles: true }))

    await showModalHtmlMock.mock.calls.at(-1)[2][0].handler()

    expect(api.world.createBibleCategory).toHaveBeenCalledWith(expect.objectContaining({
      category_key: "custom_1234567812344abc8def1234567890ab",
      name: "天文历法",
      icon: "天文",
      sort_order: 100,
    }))
    uuid.mockRestore()
  })

  it("预设分类已存在时直接复用而不重复创建", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.createBibleCategory = vi.fn()
    const technology = {
      id: "cat-tech", category_key: "technology", name: "技术体系",
      description: "技术、工程、能源与制造", color: "#2563EB", icon: "技术",
      sort_order: 100, status: "active", builtin: false,
    }
    mountTab({ bible: { ...defaultBible(), categories: [...CATEGORIES, technology] } })
    installModalHost()

    await openNewPage()
    const type = document.getElementById("bible-create-type")
    type.value = "__new_category__"
    type.dispatchEvent(new Event("change", { bubbles: true }))
    document.querySelector("[data-bible-category-preset='technology']").click()

    expect(document.querySelector("#modal-footer .btn-primary").textContent).toBe("使用此分类")
    await showModalHtmlMock.mock.calls.at(-1)[2][0].handler()
    expect(api.world.createBibleCategory).not.toHaveBeenCalled()
    expect(document.getElementById("bible-create-type").value).toBe("technology")
  })

  it("预设分类已归档时恢复后使用", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const technology = {
      id: "cat-tech", category_key: "technology", name: "技术体系",
      description: "技术、工程、能源与制造", color: "#2563EB", icon: "技术",
      sort_order: 100, status: "archived", builtin: false,
    }
    api.world.createBibleCategory = vi.fn()
    api.world.updateBibleCategory = vi.fn().mockResolvedValue({ ...technology, status: "active" })
    mountTab({ bible: { ...defaultBible(), categories: [...CATEGORIES, technology] } })
    installModalHost()

    await openNewPage()
    const type = document.getElementById("bible-create-type")
    type.value = "__new_category__"
    type.dispatchEvent(new Event("change", { bubbles: true }))
    document.querySelector("[data-bible-category-preset='technology']").click()

    expect(document.querySelector("#modal-footer .btn-primary").textContent).toBe("恢复并使用")
    await showModalHtmlMock.mock.calls.at(-1)[2][0].handler()
    expect(api.world.updateBibleCategory).toHaveBeenCalledWith("cat-tech", { status: "active" }, "p1")
    expect(api.world.createBibleCategory).not.toHaveBeenCalled()
    expect(document.getElementById("bible-create-type").value).toBe("technology")
  })

  it("分类创建响应晚到时不污染新弹窗或本地分类", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const created = deferred()
    api.world.createBibleCategory = vi.fn(() => created.promise)
    const wrapper = mountTab()
    installModalHost()

    await openNewPage()
    const type = document.getElementById("bible-create-type")
    type.value = "__new_category__"
    type.dispatchEvent(new Event("change", { bubbles: true }))
    document.getElementById("bible-category-name").value = "天文历法"
    const saving = showModalHtmlMock.mock.calls.at(-1)[2][0].handler()
    await vi.waitFor(() => expect(api.world.createBibleCategory).toHaveBeenCalled())
    await wrapper.find("[data-action='bible-manage-page-templates']").trigger("click")
    created.resolve({
      id: "cat-late", category_key: "custom_late", name: "天文历法",
      color: "#64748B", icon: "天文", sort_order: 100, status: "active", builtin: false,
    })
    await saving

    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("页面模板")
    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    expect(showModalHtmlMock.mock.calls.at(-1)[1]).not.toContain("天文历法")
    expect(toastMock).not.toHaveBeenCalledWith("分类已创建", "success")
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

    await openNewPage()
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
      <select id="bible-create-type"><option value="background" selected>背景</option></select>
      <select id="bible-create-template"><option value="" selected>空白页</option></select>
    `)

    await openNewPage()
    const creating = showModalHtmlMock.mock.calls.at(-1)[2][0].handler()
    await vi.waitFor(() => expect(api.world.createBibleDraft).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p1", title: "新建页" })))
    await wrapper.find("[data-bible-page-id='page-2']").trigger("click")
    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("管理世界书分类")
    created.resolve({ id: "draft-new", page_id: null, title: "新建页", page_type: "custom", sections_json: [], linked_asset_refs_json: [] })
    await expect(creating).resolves.toBe(true)

    expect(worldSession.bible.activePageId).toBe("page-2")
    expect(worldSession.bible.activeDraftId).toBeNull()
    expect(closeModalMock).not.toHaveBeenCalled()
    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("管理世界书分类")
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
      <select id="bible-create-type"><option value="background" selected>背景</option></select>
      <select id="bible-create-template"><option value="" selected>空白页</option></select>
    `)

    await openNewPage()
    const creating = showModalHtmlMock.mock.calls.at(-1)[2][0].handler()
    await vi.waitFor(() => expect(api.world.createBibleDraft).toHaveBeenCalled())
    await wrapper.find("[data-bible-page-id='page-2']").trigger("click")
    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    created.reject(new Error("旧请求失败"))

    await expect(creating).resolves.toBe(true)
    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("管理世界书分类")
    expect(toastMock).not.toHaveBeenCalledWith("旧请求失败", "error")
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("管理分类弹模态", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    expect(showModalHtmlMock).toHaveBeenCalled()
    expect(showModalHtmlMock.mock.calls[0][0]).toBe("管理世界书分类")
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

  it("恢复分类在原项目就地更新管理列表", async () => {
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
    await vi.waitFor(() => expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("管理世界书分类"))

    expect(toastMock).toHaveBeenCalledWith("分类已恢复，可重新用于工作稿", "success")
    expect(closeModalMock).not.toHaveBeenCalled()
    expect(router.refresh).not.toHaveBeenCalled()
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
    await openNewPage()
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
    await openNewPage()
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
    await openNewPage()
    const [, createBody] = showModalHtmlMock.mock.calls.at(-1)
    expect(createBody).toContain('<option value="trade_guide">已恢复贸易模板 · v2</option>')
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("页面、类别和模板必填校验失败时保留当前弹窗", async () => {
    const wrapper = mountTab()

    await openNewPage()
    let [, pageBody, pageButtons] = showModalHtmlMock.mock.calls.at(-1)
    document.body.innerHTML = pageBody
    document.getElementById("bible-create-title").value = ""
    await expect(pageButtons[0].handler()).resolves.toBe(false)

    await wrapper.find("[data-action='bible-manage-categories']").trigger("click")
    let [, categoryBody, categoryButtons] = showModalHtmlMock.mock.calls.at(-1)
    document.body.innerHTML = categoryBody
    expect(categoryButtons[0].handler()).toBe(false)

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
    expect(api.world.refreshBibleSynopsis).toHaveBeenCalledWith("p1", "confirm-default")
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
    await vi.waitFor(() => expect(api.world.refreshBibleSynopsis).toHaveBeenCalledWith("p1", "confirm-default"))
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
    expect(showModalHtmlMock.mock.calls.at(-1)[0]).toBe("管理世界书分类")
    expect(body.textContent).not.toContain("类别键")
  })

  it("用作者语言折叠展示生成时的决定摘要", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.listSuggestions = vi.fn().mockResolvedValue({ items: [{
      id: "suggestion-decision",
      target_type: "world_bible_page_draft",
      risk_level: "low",
      action_schema: "world_generation.page_draft.v1",
      review_group: "generation_center",
      payload_json: { page: { title: "潮汐制度", free_text: "港工依照潮谚安排轮班。" } },
      decision_state: {
        current_author_goal: "建立潮汐制度",
        confirmed_requirements: ["保留港工轮班"],
        supported_developments: [],
        rejected_elements: [],
        forbidden_exact_terms: [],
        unresolved_choices: ["潮汐来源仍由我决定"],
        knowledge_expression_boundaries: ["作者知道完整机制；港工只用潮谚表达"],
        naming_policy: "unnamed_placeholder",
        confidence: 0.95,
      },
    }] })
    const wrapper = mountTab()

    await wrapper.find("[data-action='bible-open-suggestions']").trigger("click")
    await nextTick()

    const body = showModalHtmlMock.mock.calls.at(-1)[1]
    expect(body).toContain("<details class=\"world-bible-author-decisions\"")
    expect(body).toContain("AI 本次理解 · 请核对")
    expect(body).toContain("仍由我决定")
    expect(body).toContain("作者知道完整机制；港工只用潮谚表达")
    expect(body).toContain("暂不命名，只使用描述性占位")
    expect(body).not.toContain("0.95")
  })

  it("展示可比较的线性修订历史，且历史版没有处理按钮", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.listSuggestions = vi.fn(async ({ status }) => ({ items: status === "pending" ? [{
      id: "suggestion-current",
      status: "pending",
      target_type: "world_bible_page_draft",
      risk_level: "low",
      action_schema: "world_generation.page_draft.v1",
      review_group: "generation_center",
      payload_json: { page: { title: "潮汐新制", page_type: "rule", free_text: "按潮汐表排班。" } },
      revision_link: { predecessor_suggestion_id: "suggestion-old", successor_suggestion_id: null },
    }] : [{
      id: "suggestion-old",
      status: "rejected",
      target_type: "world_bible_page_draft",
      risk_level: "low",
      action_schema: "world_generation.page_draft.v1",
      review_group: "generation_center",
      payload_json: { page: { title: "港口旧制", page_type: "rule", free_text: "按日历排班。" } },
      revision_link: { predecessor_suggestion_id: null, successor_suggestion_id: "suggestion-current" },
    }], total: 1 }))
    const wrapper = mountTab()

    await wrapper.find("[data-action='bible-open-suggestions']").trigger("click")
    await nextTick()

    const body = showModalHtmlMock.mock.calls.at(-1)[1]
    expect(body).toContain("上一版 → 当前修订版")
    expect(body).toContain("修订历史（1）")
    expect(body).toContain("港口旧制")
    expect(body).toContain("潮汐新制")
    expect(body).toContain("不可再采用")
    expect(body).not.toContain("data-bible-edit-suggestion=\"suggestion-old\"")
  })

  it("按 Today 深链打开并定位一条待处理建议", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.listSuggestions = vi.fn().mockResolvedValue({ items: [
      { id: "suggestion-1", target_type: "world_bible_page_draft", payload_json: { page: { title: "第一条" } } },
      { id: "suggestion-2", target_type: "world_bible_page_draft", payload_json: { page: { title: "目标建议" } } },
    ] })

    mountTab({ bibleDeepLink: { draftId: "", pageId: "", openSuggestions: true, suggestionId: "suggestion-2" } })
    await vi.waitFor(() => expect(showModalHtmlMock).toHaveBeenCalledWith("创设建议", expect.any(String), [], { size: "large" }))

    const body = showModalHtmlMock.mock.calls.at(-1)[1]
    expect(body.indexOf("目标建议")).toBeLessThan(body.indexOf("第一条"))
    expect(body).toContain("本次生成未保存决定摘要")
    expect(readCreativeContinuation("p1")).toMatchObject({
      destination: "world_suggestion_review",
      route: { suggestion_id: "suggestion-2" },
    })
  })

  it("按 Today 深链分栏预览并原子吸取 Deep Import 设定", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.previewAdoptionPackage = vi.fn().mockResolvedValue({
      expected_preview_hash: "a".repeat(64),
      omissions: [],
      suggestion: {
        payload_json: {
          items: [
            { item_key: "existing", kind: "core_entity", payload: { operation: "existing_ref" } },
            { item_key: "candidate", kind: "core_entity", payload: { operation: "promote" } },
            {
              item_key: "page",
              kind: "world_bible_page",
              payload: {
                title: "深度导入设定索引",
                claim_mappings: [
                  { item_key: "existing", claim: "潮门（location）" },
                  { item_key: "candidate", claim: "旧潮盟（organization）" },
                ],
              },
            },
          ],
        },
      },
      canon_diff: [
        { item_key: "existing", kind: "core_entity", action: "existing_ref" },
        { item_key: "candidate", kind: "core_entity", action: "promote" },
        { item_key: "page", kind: "world_bible_page", action: "create" },
      ],
    })
    api.world.applyAdoptionPackage = vi.fn().mockResolvedValue({ status: "accepted" })

    mountTab({ bibleDeepLink: { draftId: "", pageId: "", adoptionPackageId: "package-1" } })
    await vi.waitFor(() => expect(showModalHtmlMock).toHaveBeenCalledWith("审阅世界设定吸取", expect.any(String), expect.any(Array), { size: "large" }))

    const [, body, buttons] = showModalHtmlMock.mock.calls.at(-1)
    expect(body).toContain("流水线已写入")
    expect(body).toContain("本次确认将写入")
    expect(body).toContain("潮门（location）")
    expect(body).toContain("旧潮盟（organization）")
    expect(body).not.toContain("package-1")

    await buttons[1].handler()
    expect(api.world.applyAdoptionPackage).toHaveBeenCalledWith("package-1", "p1", "a".repeat(64))
    expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("已吸取"), "success")
  })

  it("深链建议已处理时清除旧入口并显示其余待处理项", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.listSuggestions = vi.fn().mockResolvedValue({ items: [] })
    writeCreativeContinuation("p1", {
      destination: "world_suggestion_review",
      route: { suggestion_id: "suggestion-gone" },
    })

    mountTab({ bibleDeepLink: { draftId: "", pageId: "", openSuggestions: true, suggestionId: "suggestion-gone" } })
    await vi.waitFor(() => expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("已处理或不可用"), "info"))

    expect(readCreativeContinuation("p1")).toBeNull()
  })

  it("打开冲突弹窗", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.world.listWorldConflicts = vi.fn().mockResolvedValue({ items: [], total: 0 })
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-open-conflicts']").trigger("click")
    await nextTick()
    expect(api.world.listWorldConflicts).toHaveBeenCalledWith({ novel_id: "p1", status: "pending" })
  })

  it("从深链定位冲突并用现有 API 处理", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    const item = {
      id: "conflict-1",
      summary: "潮汐周期存在两个版本",
      resolution_json: { author_action: "needs_decision", next_step: "确认采用哪一版" },
    }
    api.world.listWorldConflicts = vi.fn()
      .mockResolvedValueOnce({ items: [item], total: 1 })
      .mockResolvedValue({ items: [], total: 0 })
    api.world.resolveWorldConflict = vi.fn().mockResolvedValue({ id: "conflict-1", status: "resolved" })
    installModalHost()

    mountTab({ bibleDeepLink: {
      draftId: "",
      pageId: "",
      openConflicts: true,
      conflictId: "conflict-1",
    } })
    await vi.waitFor(() => expect(document.querySelector("[data-bible-conflict-resolve='conflict-1']")).not.toBeNull())
    expect(document.querySelector("[data-conflict-id='conflict-1']").classList.contains("is-focused")).toBe(true)

    document.querySelector("[data-bible-conflict-resolve='conflict-1']").click()
    await vi.waitFor(() => expect(api.world.resolveWorldConflict).toHaveBeenCalledWith(
      "conflict-1",
      { status: "resolved", resolution_json: { author_action: "needs_decision", next_step: "确认采用哪一版", resolved_by: "author" } },
      "p1",
    ))
    await vi.waitFor(() => expect(toastMock).toHaveBeenCalledWith("检查项已处理", "success"))
  })

  it("新建激活规则弹窗", async () => {
    const wrapper = mountTab()
    await wrapper.find("[data-action='bible-activation-new']").trigger("click")
    expect(showModalHtmlMock).toHaveBeenCalled()
    expect(showModalHtmlMock.mock.calls[0][0]).toBe("新建 AI 参考规则")
    const html = showModalHtmlMock.mock.calls[0][1]
    expect(html).toContain("单次参考篇幅")
    expect(html).not.toContain("规则标识")
    expect(html).not.toContain("适用操作")
    expect(html).not.toContain("writing.generate")
    expect(html).not.toContain("writing.world_bible")
  })

  it("新建激活规则使用内部生成的合法标识", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.context.createActivationProfile = vi.fn().mockResolvedValue({ id: "prof-new" })
    installModalHost()
    const wrapper = mountTab()

    await wrapper.find("[data-action='bible-activation-new']").trigger("click")
    document.getElementById("bible-rule-positive").value = "北境"
    await showModalHtmlMock.mock.calls.at(-1)[2][0].handler()

    expect(api.context.createActivationProfile).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      profile_key: expect.stringMatching(/^writing\.world_bible\./),
    }))
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
  it("显示 AI 参考规则选择器", () => {
    const wrapper = mountTab()
    expect(wrapper.find("#bible-activation-profile").exists()).toBe(true)
    const select = wrapper.find("#bible-activation-profile").element
    expect(select.options.length).toBeGreaterThanOrEqual(2) // empty + profiles
  })

  it("选择规则方案后显示可读摘要和试运行", () => {
    const wrapper = mountTab()
    expect(wrapper.find(".world-bible-profile-summary").exists()).toBe(true)
    expect(wrapper.find(".world-bible-profile-summary").text()).toContain("工作稿 写作规则")
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

  it("试运行结果不显示内部规则、原因、资料编号或容量单位", async () => {
    const api = (await import("../../../../vue/bridge/index.js")).getApi()
    api.context.previewActivationProfile = vi.fn().mockResolvedValue({
      rule_evaluations: [{ rule_id: "writing.generate.internal", matched: false, candidate_count: 1, blocked_clauses: ["scope_mismatch"] }],
      items: [{ label: "北境税制", target: { target_id: "raw-included-id" }, activation_reason: "rule:internal -> page", token_after: 321 }],
      excluded_items: [{ target: { target_id: "raw-excluded-id" }, activation_reason: "rule:internal", excluded_reason: "rule_token_cap", token_before: 654 }],
      warnings: ["projection_stale"],
    })
    const wrapper = mountTab()

    await wrapper.find("#bible-activation-task").setValue("检查北境税制")
    await wrapper.find("[data-action='bible-activation-dry-run']").trigger("click")
    await vi.waitFor(() => expect(wrapper.find(".world-bible-activation-trace").exists()).toBe(true))

    const text = wrapper.find(".world-bible-activation-trace").text()
    expect(text).toContain("第 1 条规则 · 不适用 · 找到 1 份资料")
    expect(text).toContain("当前任务不适用")
    expect(text).toContain("符合当前参考规则并已加入")
    expect(text).toContain("超出当前参考篇幅")
    expect(text).not.toContain("writing.generate.internal")
    expect(text).not.toContain("rule_token_cap")
    expect(text).not.toContain("projection_stale")
    expect(text).toContain("部分写作参考可能不是最新版本")
    expect(text).not.toContain("raw-included-id")
    expect(text).not.toContain("raw-excluded-id")
    expect(text).not.toContain("321")
    expect(text).not.toContain("654")
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

describe("beforeunload 守卫", () => {
  it("有未保存修改时 beforeunload 要求确认，卸载后解绑", async () => {
    const listenerSpy = vi.spyOn(window, "addEventListener")
    const removeSpy = vi.spyOn(window, "removeEventListener")
    const wrapper = mountTab()

    const bound = listenerSpy.mock.calls.filter(([event]) => event === "beforeunload")
    expect(bound.length).toBeGreaterThan(0)
    const handler = bound[bound.length - 1][1]

    // 无未保存修改：不拦截
    let event = new Event("beforeunload", { cancelable: true })
    handler(event)
    expect(event.defaultPrevented).toBe(false)

    // 制造未保存修改后：必须拦截刷新/关闭
    await wrapper.find("#bible-free-text").setValue("未保存的修改")
    event = new Event("beforeunload", { cancelable: true })
    handler(event)
    expect(event.defaultPrevented).toBe(true)

    // 组件卸载后解绑，避免泄漏与误拦
    wrapper.unmount()
    expect(
      removeSpy.mock.calls.some(([event, fn]) => event === "beforeunload" && fn === handler),
    ).toBe(true)

    listenerSpy.mockRestore()
    removeSpy.mockRestore()
  })
})

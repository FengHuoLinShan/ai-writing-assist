/**
 * WorldObjectsTab 测试 — 渲染契约、筛选导航、热点概览、提取抽屉、批次分组、批量。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount, shallowMount } from "@vue/test-utils"

vi.mock("../../../../shared/referencePicker.js", () => ({
  createReferencePicker: vi.fn(() => ({ destroy: vi.fn(), resolve: vi.fn() })),
}))

import WorldObjectsTab from "../../../vue/views/world/components/WorldObjectsTab.vue"
import WorldView from "../../../vue/views/world/WorldView.vue"
import { autoExtractManager } from "../../../vue/views/world/workflowManagers.js"
import { resetWorldSession, worldSession } from "../../../vue/views/world/worldSession.js"
import { getBulkSelection } from "../../../vue/views/world/logic/worldBulkSelection.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const ENTITIES = [
  { id: "e1", name: "沉钟港", entity_type: "location", status: "canonical", source: "manual", summary: "旧港", importance: 0.5 },
  { id: "e2", name: "林澈", entity_type: "character", status: "candidate", source: "deep_import", summary: "巡港人", needs_review: true },
]

let navigateMock
let toastMock
let refreshMock

function mountTab(propOverrides = {}, mountOptions = {}) {
  return mount(WorldObjectsTab, {
    ...mountOptions,
    props: {
      projectId: "p-obj",
      entities: ENTITIES,
      entitiesTotal: 2,
      entityTypes: [
        { value: "location", label: "地点" },
        { value: "character", label: "人物" },
      ],
      ...propOverrides,
    },
  })
}

enableAutoUnmount(afterEach)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetWorldSession()
  autoExtractManager.stop()
  autoExtractManager.state.taskId = null
  autoExtractManager.state.status = "就绪"
  autoExtractManager.state.meta = null
  autoExtractManager.state.progress = null
  navigateMock = vi.fn()
  toastMock = vi.fn()
  refreshMock = vi.fn(async () => true)
  setBridgeOverrides({
    state: { currentProjectId: "p-obj", currentView: "world" },
    router: { navigate: navigateMock, refresh: refreshMock },
    toast: toastMock,
  })
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("表格渲染契约", () => {
  it("知识 deep link 打开既有角色知识进程", async () => {
    const listKnowledge = vi.fn(async () => ({ items: [], total: 0 }))
    const getEntity = vi.fn(async () => ENTITIES[1])
    const showModalHtml = vi.fn()
    setBridgeOverrides({
      api: { world: { listKnowledge, getEntity } },
      state: { currentProjectId: "p-obj", currentView: "world" },
      router: { navigate: navigateMock, refresh: vi.fn(async () => true) },
      toast: toastMock,
      showModalHtml,
    })
    mountTab({ knowledgeCharacterId: "e2" })
    await vi.waitFor(() => expect(listKnowledge).toHaveBeenCalledWith("e2", "p-obj"))
    await vi.waitFor(() => expect(showModalHtml).toHaveBeenCalledWith("人物认知进程", expect.any(String), expect.any(Array), { size: "large" }))
  })

  it("表格把对象身份和资料概览收敛为四列并保留注意状态", () => {
    const wrapper = mountTab()
    expect(wrapper.findAll("thead th").map((cell) => cell.text())).toEqual(["全选当前页对象", "对象", "资料概览", "操作"])
    const rows = wrapper.findAll("tbody tr[data-id]")
    expect(rows).toHaveLength(2)
    expect(rows[0].attributes("data-id")).toBe("e1")
    expect(rows[0].find('input[data-action="bulk-toggle-one"][data-scope="world-objects"][data-id="e1"]').exists()).toBe(true)
    expect(rows[0].get('[data-label="对象"]').text()).toContain("沉钟港")
    expect(rows[0].get('[data-label="资料概览"]').text()).toContain("旧港")
    expect(rows[0].get('[data-label="资料概览"]').text()).toContain("来源：手动")
    expect(rows[1].get(".world-object-table__attention").text()).toContain("需要留意")
    expect(rows[1].find('[data-action="mark-entity-reviewed"]').exists()).toBe(true)
    expect(rows[1].find('[data-action="edit-entity"]').text()).toBe("编辑后采用")
    expect(wrapper.find('input[data-action="bulk-toggle-all"][data-scope="world-objects"]').exists()).toBe(true)
  })

  it("行内菜单使用对象名称并承载上传图片等低频操作", async () => {
    const wrapper = mountTab({}, { attachTo: document.body })
    const row = wrapper.find('tbody tr[data-id="e1"]')
    const input = row.get('input[type="file"]')
    const inputClick = vi.spyOn(input.element, "click")
    const trigger = row.get(".action-menu-btn")
    expect(trigger.attributes("aria-label")).toBe("沉钟港的更多操作")
    await trigger.trigger("click")
    expect(row.get('[data-action="upload-entity-image"]').text()).toBe("上传图片")
    expect(row.find('[data-action="delete-entity"]').attributes("data-id")).toBe("e1")
    await row.get('[data-action="upload-entity-image"]').trigger("click")
    expect(inputClick).toHaveBeenCalledTimes(1)
  })

  it("空态渲染新建入口；错误态可原位重新加载", async () => {
    const empty = mountTab({ entities: [], entitiesTotal: 0 })
    expect(empty.text()).toContain("还没有世界对象")
    expect(empty.find('[data-action="new"]').exists()).toBe(true)
    expect(empty.find(".empty-icon").exists()).toBe(false)

    const failed = mountTab({ entities: [], entitiesTotal: 0, entitiesLoadError: "网络错误" })
    expect(failed.find('.empty-state[role="alert"]').exists()).toBe(true)
    expect(failed.text()).toContain("网络错误")
    expect(failed.find(".empty-icon").exists()).toBe(false)
    await failed.get('[data-action="retry-objects-load"]').trigger("click")
    expect(refreshMock).toHaveBeenCalledOnce()
  })

  it("卡片模式渲染 world-object-card", () => {
    const wrapper = mountTab({ objectViewMode: "card" })
    expect(wrapper.findAll(".world-object-card[data-id]")).toHaveLength(2)
    expect(wrapper.find(".world-filter-panel__card-hint").text()).toBe("点击卡片展开详情")
    wrapper.unmount()

    const table = mountTab()
    expect(table.find(".world-filter-panel__card-hint").exists()).toBe(false)
  })
})

describe("对象图片与卡片详情", () => {
  it("卡片用原生按钮单次打开详情，复选框不触发详情", async () => {
    const showModalHtml = vi.fn()
    setBridgeOverrides({
      api: { world: {} },
      state: { currentProjectId: "p-obj", currentView: "world" },
      router: { navigate: navigateMock, refresh: vi.fn(async () => true) },
      toast: toastMock,
      showModalHtml,
    })
    const wrapper = mountTab({ objectViewMode: "card" })
    const card = wrapper.get('.world-object-card[data-id="e1"]')
    const open = card.get('[data-action="open-entity-detail"]')

    expect(open.element.tagName).toBe("BUTTON")
    expect(card.find('[data-action="edit-entity"]').exists()).toBe(false)

    // 原生 button 会在真实浏览器中将 Enter/Space 转为 click；组件不额外
    // 处理 keydown，以免同一次激活打开两个详情弹窗。
    await open.trigger("keydown", { key: "Enter" })
    expect(showModalHtml).not.toHaveBeenCalled()
    await open.trigger("click")
    expect(showModalHtml).toHaveBeenCalledTimes(1)
    expect(showModalHtml.mock.calls[0][3]).toEqual({ size: "large" })

    await card.get('input[data-action="bulk-toggle-one"]').setValue(true)
    expect(showModalHtml).toHaveBeenCalledTimes(1)
  })

  it("上传控件独立于卡片详情，上传期间防止重复提交", async () => {
    let finishUpload
    const uploadEntityImage = vi.fn(() => new Promise((resolve) => { finishUpload = resolve }))
    const fetchEntityImage = vi.fn(async () => new Blob(["thumbnail"], { type: "image/webp" }))
    const refresh = vi.fn(async () => true)
    const showModalHtml = vi.fn()
    setBridgeOverrides({
      api: { world: { uploadEntityImage, fetchEntityImage } },
      state: { currentProjectId: "p-obj", currentView: "world" },
      router: { navigate: navigateMock, refresh },
      toast: toastMock,
      showModalHtml,
    })
    const wrapper = mountTab(
      { objectViewMode: "card", entities: [{ ...ENTITIES[0], has_image: false }] },
      { attachTo: document.body },
    )
    const card = wrapper.get('.world-object-card[data-id="e1"]')
    const input = card.get('input[type="file"]')
    const button = card.get('[data-action="upload-entity-image"]')
    expect(input.attributes("tabindex")).toBe("-1")
    const inputClick = vi.spyOn(input.element, "click")
    const file = new File(["image"], "portrait.png", { type: "image/png" })

    await button.trigger("click")
    expect(inputClick).toHaveBeenCalledTimes(1)

    Object.defineProperty(input.element, "files", { configurable: true, value: [file] })
    await input.trigger("change")
    await vi.waitFor(() => expect(uploadEntityImage).toHaveBeenCalledWith(
      "e1",
      file,
      "p-obj",
      null,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    ))
    expect(button.attributes("disabled")).toBeDefined()

    await input.trigger("change")
    expect(uploadEntityImage).toHaveBeenCalledTimes(1)
    expect(showModalHtml).not.toHaveBeenCalled()

    finishUpload({})
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledTimes(1))
    expect(wrapper.props("entities")[0].has_image).toBe(true)
    expect(toastMock).toHaveBeenCalledWith("图片已上传", "success")
  })

  it("图片读取失败时保留首字回退", async () => {
    const fetchEntityImage = vi.fn(async () => { throw new Error("S3 unavailable") })
    setBridgeOverrides({
      api: { world: { fetchEntityImage } },
      state: { currentProjectId: "p-obj", currentView: "world" },
      router: { navigate: navigateMock, refresh: vi.fn(async () => true) },
      toast: toastMock,
    })
    const wrapper = mountTab({ objectViewMode: "card", entities: [{ ...ENTITIES[0], has_image: true }] })
    const avatar = wrapper.get('.world-object-card[data-id="e1"] .world-object-card__avatar')

    await vi.waitFor(() => expect(fetchEntityImage).toHaveBeenCalled())
    await flushPromises()
    expect(avatar.find("img").exists()).toBe(false)
    expect(avatar.text()).toBe("沉")
  })

  it("缩略图解码失败时释放 Blob URL 并回退首字", async () => {
    const fetchEntityImage = vi.fn(async () => new Blob(["broken"], { type: "image/webp" }))
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:broken-thumbnail")
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL")
    setBridgeOverrides({
      api: { world: { fetchEntityImage } },
      state: { currentProjectId: "p-obj", currentView: "world" },
      router: { navigate: navigateMock, refresh: vi.fn(async () => true) },
      toast: toastMock,
    })
    const wrapper = mountTab({ objectViewMode: "card", entities: [{ ...ENTITIES[0], has_image: true }] })
    const avatar = wrapper.get('.world-object-card[data-id="e1"] .world-object-card__avatar')

    await vi.waitFor(() => expect(avatar.find("img").exists()).toBe(true))
    await avatar.get("img").trigger("error")

    expect(avatar.find("img").exists()).toBe(false)
    expect(avatar.text()).toBe("沉")
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:broken-thumbnail")
  })

  it("上传失败保留已显示的旧缩略图", async () => {
    const fetchEntityImage = vi.fn(async () => new Blob(["thumbnail"], { type: "image/webp" }))
    const uploadEntityImage = vi.fn(async () => { throw new Error("格式不支持") })
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:existing-thumbnail")
    setBridgeOverrides({
      api: { world: { fetchEntityImage, uploadEntityImage } },
      state: { currentProjectId: "p-obj", currentView: "world" },
      router: { navigate: navigateMock, refresh: vi.fn(async () => true) },
      toast: toastMock,
    })
    const wrapper = mountTab(
      { objectViewMode: "card", entities: [{ ...ENTITIES[0], has_image: true }] },
      { attachTo: document.body },
    )
    const card = wrapper.get('.world-object-card[data-id="e1"]')
    await vi.waitFor(() => expect(card.find(".world-object-card__avatar img").exists()).toBe(true))
    const imageBeforeFailure = card.get(".world-object-card__avatar img").attributes("src")
    const input = card.get('input[type="file"]')
    Object.defineProperty(input.element, "files", {
      configurable: true,
      value: [new File(["image"], "portrait.gif", { type: "image/gif" })],
    })

    await input.trigger("change")
    await vi.waitFor(() => expect(toastMock).toHaveBeenCalledWith("图片上传失败：格式不支持", "error"))
    expect(card.get(".world-object-card__avatar img").attributes("src")).toBe(imageBeforeFailure)
  })

  it("卸载时取消晚到缩略图并回收已创建的对象 URL", async () => {
    let finishImage
    const imageRequest = new Promise((resolve) => { finishImage = resolve })
    const fetchEntityImage = vi.fn(() => imageRequest)
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:thumbnail")
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL")
    setBridgeOverrides({
      api: { world: { fetchEntityImage } },
      state: { currentProjectId: "p-obj", currentView: "world" },
      router: { navigate: navigateMock, refresh: vi.fn(async () => true) },
      toast: toastMock,
    })
    const pending = mountTab({ objectViewMode: "card", entities: [{ ...ENTITIES[0], has_image: true }] })

    await vi.waitFor(() => expect(fetchEntityImage).toHaveBeenCalled())
    pending.unmount()
    finishImage(new Blob(["late"], { type: "image/webp" }))
    await flushPromises()
    expect(createObjectURL).not.toHaveBeenCalled()

    const ready = mountTab({ objectViewMode: "card", entities: [{ ...ENTITIES[0], has_image: true }] })
    await vi.waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1))
    expect(ready.get(".world-object-card__avatar img").attributes("src")).toBe("blob:thumbnail")
    ready.unmount()
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:thumbnail")
  })
})

describe("筛选", () => {
  it("应用：读取表单 → skip 归零 → navigate 写 query", async () => {
    const wrapper = mountTab()
    await wrapper.find("#filter-entity-type").setValue("location")
    await wrapper.find("#filter-q").setValue("港")
    await wrapper.find('[data-action="apply-filters"]').trigger("click")
    expect(navigateMock).toHaveBeenCalledTimes(1)
    const [view, subView, _replace, query] = navigateMock.mock.calls[0]
    expect([view, subView]).toEqual(["world", "objects"])
    expect(query.get("entity_type")).toBe("location")
    expect(query.get("q")).toBe("港")
    expect(query.has("page")).toBe(false)
  })

  it("重置：恢复默认筛选", async () => {
    const wrapper = mountTab({ objectFilters: { entity_type: "location", display_state: "review", q: "港", source: "", workflow_id: "", needs_review: "", auto_ingested: "", focus: "", skip: 40, limit: 20 } })
    await wrapper.find('[data-action="reset-filters"]').trigger("click")
    const [, , , query] = navigateMock.mock.calls[0]
    expect(query.get("entity_type")).toBeNull()
    expect(query.get("display_state")).toBe("active")
  })

  it("筛选面板开合持久化到 localStorage", async () => {
    const wrapper = mountTab()
    const toggle = wrapper.find('[data-action="toggle-filter-panel"][data-filter-key="objects"]')
    expect(toggle.attributes("aria-expanded")).toBe("false")
    expect(wrapper.find("#filter-q").isVisible()).toBe(false)
    await toggle.trigger("click")
    expect(toggle.attributes("aria-expanded")).toBe("true")
    expect(JSON.parse(localStorage.getItem("novel_world_filter_panels:p-obj")).objects).toBe(true)
  })

  it("同一 query 重挂载保留未应用草稿，外部 query 变更仍以 URL 为准", async () => {
    const first = mountTab()
    await first.find("#filter-q").setValue("尚未应用")
    first.unmount()

    const remounted = mountTab()
    expect(remounted.find("#filter-q").element.value).toBe("尚未应用")
    remounted.unmount()

    const external = mountTab({
      objectFilters: {
        entity_type: "", display_state: "active", q: "外部链接", source: "",
        workflow_id: "", needs_review: "", auto_ingested: "", focus: "", skip: 0, limit: 20,
      },
    })
    expect(external.find("#filter-q").element.value).toBe("外部链接")
  })
})

describe("页内视图控件", () => {
  it("次级对象工具返回 canonical 资料库总览", async () => {
    const wrapper = shallowMount(WorldView, {
      props: {
        projectId: "p-obj",
        subView: "bible",
        bibleDeepLink: { openObjectTools: true },
      },
    })

    await wrapper.get(".view-header__actions > .btn-ghost").trigger("click")

    expect(localStorage.getItem("worldBible:p-obj:displayMode")).toBe("gallery")
    expect(navigateMock).toHaveBeenCalledWith("world", "bible")
  })

  it("默认使用表格，并以可访问状态分组浏览选项", async () => {
    const wrapper = shallowMount(WorldView, {
      props: { projectId: "p-obj", subView: "objects", discoveryMode: "hot" },
    })
    const options = wrapper.get(".world-view-options")
    const table = wrapper.get('[data-action="set-object-view"][data-view-mode="table"]')
    const card = wrapper.get('[data-action="set-object-view"][data-view-mode="card"]')

    expect(wrapper.findComponent(WorldObjectsTab).props("objectViewMode")).toBe("table")
    expect(table.attributes("aria-pressed")).toBe("true")
    expect(card.attributes("aria-pressed")).toBe("false")
    expect(wrapper.get('[data-action="set-discovery-mode"][data-mode="hot"]').attributes("aria-pressed")).toBe("true")
    expect(options.get('[role="group"][aria-label="人物与设定显示方式"]').exists()).toBe(true)
    expect(options.get('[role="group"][aria-label="资料范围"]').exists()).toBe(true)
    expect(options.find('[data-action="toggle-extract"]').exists()).toBe(false)
    expect(wrapper.get('[data-action="toggle-extract"]').text()).toBe("从正文整理资料")

    options.element.open = true
    await options.get('[data-action="close-view-options"]').trigger("click")
    expect(options.element.open).toBe(false)
  })

  it("需要决定是直达待处理对象的顶层当前页按钮", async () => {
    const wrapper = shallowMount(WorldView, {
      props: {
        projectId: "p-obj",
        subView: "review-objects",
        reviewSubView: "review-objects",
        reviewCounts: { objects: 2, aliases: 3, relations: 1 },
      },
    })
    const review = wrapper.get('[data-action="nav-review"]')
    const library = wrapper.get('[data-action="nav-bible"]')

    expect(review.element.tagName).toBe("BUTTON")
    expect(review.attributes("type")).toBe("button")
    expect(review.attributes("aria-current")).toBe("page")
    expect(review.classes()).toContain("active")
    expect(review.get(".today-count").text()).toBe("6")
    expect(review.attributes("aria-label")).toBe("需要决定，6 项")
    expect(library.attributes("aria-current")).toBeUndefined()
    expect(library.classes()).not.toContain("active")
    expect(wrapper.find(".world-attention-menu").exists()).toBe(false)

    await review.trigger("click")
    expect(navigateMock).toHaveBeenCalledWith("world", "review", true, expect.any(URLSearchParams))
  })

  it("待决定计数收起零值并限制视觉宽度，别名深链保留当前页语义", async () => {
    const wrapper = shallowMount(WorldView, {
      props: {
        projectId: "p-obj",
        subView: "aliases",
        reviewCounts: { objects: 156, aliases: 82, relations: 78 },
      },
    })
    const review = wrapper.get('[data-action="nav-review"]')

    expect(review.get(".today-count").text()).toBe("99+")
    expect(review.attributes("aria-label")).toBe("需要决定，316 项")
    expect(wrapper.get('[data-action="nav-bible"]').attributes("aria-current")).toBe("page")

    await wrapper.setProps({ reviewCounts: { objects: 0, aliases: 0, relations: 0 } })

    expect(review.find(".today-count").exists()).toBe(false)
    expect(review.attributes("aria-label")).toBeUndefined()
  })

  it("卡片/表格只切本地呈现并同步 query，不重挂载", async () => {
    const commitCurrentQuery = vi.fn(() => true)
    setBridgeOverrides({
      state: { currentProjectId: "p-obj", currentView: "world" },
      router: { navigate: navigateMock, refresh: vi.fn(), commitCurrentQuery },
    })
    const wrapper = shallowMount(WorldView, {
      attachTo: document.body,
      props: {
        projectId: "p-obj",
        subView: "objects",
        objectFilters: { display_state: "active", skip: 0, limit: 20 },
        objectViewMode: "table",
        discoveryMode: "hot",
      },
    })
    const root = wrapper.element
    const card = wrapper.get('[data-action="set-object-view"][data-view-mode="card"]')
    card.element.focus()

    await card.trigger("click")

    expect(wrapper.element).toBe(root)
    expect(document.activeElement).toBe(card.element)
    expect(card.attributes("aria-pressed")).toBe("true")
    expect(wrapper.get('[data-action="set-object-view"][data-view-mode="table"]').attributes("aria-pressed")).toBe("false")
    expect(card.classes()).not.toContain("btn-primary")
    expect(wrapper.findComponent(WorldObjectsTab).props("objectViewMode")).toBe("card")
    expect(commitCurrentQuery).toHaveBeenCalledTimes(1)
    expect(commitCurrentQuery.mock.calls[0][0].get("view")).toBe("card")
    expect(navigateMock).not.toHaveBeenCalled()
  })
})

describe("热点概览", () => {
  it("facet 点击切换 focus 并 navigate", async () => {
    const wrapper = mountTab({
      rankingFacets: { important: 1, hot: 2, other: 3, by_type: [{ entity_type: "location", count: 2 }] },
      rankingContext: { status: "unavailable" },
    })
    const facet = wrapper.find('[data-action="set-hot-focus"][data-focus="hot"]')
    expect(facet.find("strong").text()).toBe("2")
    await facet.trigger("click")
    const [, , , query] = navigateMock.mock.calls[0]
    expect(query.get("focus")).toBe("hot")
  })

  it("已激活 facet 再点取消 focus", async () => {
    const wrapper = mountTab({ objectFilters: { entity_type: "", display_state: "active", q: "", source: "", workflow_id: "", needs_review: "", auto_ingested: "", focus: "hot", skip: 0, limit: 20 } })
    await wrapper.find('[data-action="set-hot-focus"][data-focus="hot"]').trigger("click")
    const [, , , query] = navigateMock.mock.calls[0]
    expect(query.get("focus")).toBeNull()
  })

  it("normal 模式不渲染热点概览", () => {
    const wrapper = mountTab({ discoveryMode: "normal" })
    expect(wrapper.find(".world-hot-overview").exists()).toBe(false)
  })
})

describe("自动提取抽屉", () => {
  it("默认收起；autoExtractOpen 时渲染面板并可提交", async () => {
    const startStage = vi.fn(async () => ({ task_id: "task-extract-1", status: "running" }))
    setBridgeOverrides({
      api: { imports: { startStage } },
      state: { currentProjectId: "p-obj", currentView: "world" },
      router: { navigate: navigateMock, refresh: vi.fn(async () => true) },
      toast: toastMock,
    })
    worldSession.autoExtractOpen = true
    const wrapper = mountTab()
    const panel = wrapper.find(".world-extract-panel")
    expect(panel.exists()).toBe(true)
    expect(wrapper.find("#w-extract-status").text()).toContain("就绪")
    await wrapper.find('[data-action="submit-extract"]').trigger("click")
    await vi.waitFor(() => expect(startStage).toHaveBeenCalledWith("world_objects", "p-obj", 1, 10, false, false, expect.anything()))
  })

  it("有 progress 时渲染进度卡而非状态行", () => {
    autoExtractManager.state.progress = {
      taskId: "task-1", label: "世界对象与别名/关系自动提取", statusLabel: "运行中",
      percent: 40, hasPercent: true,
    }
    worldSession.autoExtractOpen = true
    const wrapper = mountTab()
    expect(wrapper.find("details.workflow-progress").exists()).toBe(true)
    expect(wrapper.find("#w-extract-status").exists()).toBe(false)
  })
})

describe("批次分组（normal 模式）", () => {
  it("自动入库组与其他对象组拆分渲染", () => {
    const wrapper = mountTab({
      discoveryMode: "normal",
      batches: [{ batch_id: "b1", ingested_at: "2026-07-17T10:00:00Z", entities: [{ id: "e2" }] }],
    })
    const groups = wrapper.findAll(".world-batch-group")
    expect(groups).toHaveLength(2)
    expect(groups[0].text()).toContain("自动入库")
    expect(groups[0].find("tr[data-id='e2']").exists()).toBe(true)
    expect(groups[1].text()).toContain("其他对象")
    expect(groups[1].find("tr[data-id='e1']").exists()).toBe(true)
    expect(groups[0].find(".badge-new").exists()).toBe(true)
  })
})

describe("分页与批量", () => {
  it("total > limit 时渲染分页并 navigate", async () => {
    const wrapper = mountTab({ entitiesTotal: 50 })
    const next = wrapper.find('[data-action="next-page"]')
    expect(next.exists()).toBe(true)
    await next.trigger("click")
    const [, , , query] = navigateMock.mock.calls[0]
    expect(query.get("page")).toBe("2")
  })

  it("批量选择驱动工具条计数", async () => {
    const wrapper = mountTab()
    expect(wrapper.find(".bulk-toolbar__status strong").text()).toBe("0")
    await wrapper.find('input[data-action="bulk-toggle-one"][data-id="e1"]').setValue(true)
    expect(getBulkSelection("world-objects").has("e1")).toBe(true)
    expect(wrapper.find(".bulk-toolbar__status strong").text()).toBe("1")
  })
})

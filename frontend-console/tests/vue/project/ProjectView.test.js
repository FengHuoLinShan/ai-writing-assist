/**
 * ProjectView 组件测试 — 对应原 tests/projectView.test.js 的视图行为契约。
 * 状态经 setBridgeOverrides 注入（state + onStateChange）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import ProjectView from "../../../vue/views/project/ProjectView.vue"
import ImportDrawer from "../../../vue/views/project/components/ImportDrawer.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { PROJECT_CARDS_SCOPE, projectSession } from "../../../vue/views/project/projectSession.js"
import { getBulkSelection } from "../../../shared/bulkSelection.js"

// 测试间共享 projectSession：残留挂载实例的 watch 会污染选择集，逐测试卸载
enableAutoUnmount(afterEach)

function makeState({ projects = [], currentProjectId = null } = {}) {
  const listeners = []
  const state = {
    projects,
    currentProjectId,
    currentProject: null,
    currentView: "project",
    currentSubView: null,
    viewStates: {},
  }
  return {
    state,
    onStateChange: (listener) => {
      listeners.push(listener)
      return () => listeners.splice(listeners.indexOf(listener), 1)
    },
    set(key, value) {
      const old = state[key]
      state[key] = value
      listeners.forEach((listener) => listener(key, value, old))
    },
  }
}

function makeProject(id, overrides = {}) {
  return {
    id,
    title: `项目${id}`,
    status: "active",
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-02T00:00:00Z",
    ...overrides,
  }
}

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

function mountView({ projects = [], currentProjectId = null, loadError = null } = {}) {
  const harness = makeState({ projects, currentProjectId })
  setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
  const wrapper = mount(ProjectView, { props: { loadError } })
  return { wrapper, harness }
}

async function enterManageMode(wrapper) {
  await wrapper.find('[data-action="manage-projects"]').trigger("click")
  await wrapper.vm.$nextTick()
}

beforeEach(() => {
  vi.clearAllMocks()
  document.getElementById("modal-body")?.remove()
  projectSession.importSectionOpen = false
  projectSession.manageMode = false
  projectSession.searchQuery = ""
  projectSession.recycleBinSkip = 0
  getBulkSelection(projectSession, PROJECT_CARDS_SCOPE).clear()
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("渲染状态", () => {
  it("有项目时渲染 hero、搜索条、卡片，管理操作渐进展开", async () => {
    const { wrapper } = mountView({ projects: [makeProject("p1"), makeProject("p2")] })
    expect(wrapper.find("#project-catalog-title").exists()).toBe(true)
    expect(wrapper.find('[data-role="project-total-count"]').text()).toBe("2 部作品")
    expect(wrapper.find('[data-action="recycle-bin"]').exists()).toBe(true)
    expect(wrapper.findAll(".project-card[data-id]")).toHaveLength(2)
    expect(wrapper.find(".project-card-placeholder").exists()).toBe(true)
    expect(wrapper.find("#project-search-input").exists()).toBe(true)
    expect(wrapper.find('[data-action="select-visible-projects"]').exists()).toBe(false)
    await enterManageMode(wrapper)
    expect(wrapper.find('[data-action="select-visible-projects"]').text()).toBe("全选当前可见作品")
    expect(wrapper.find('[data-action="select-visible-projects"]').attributes("aria-label")).toBe("全选当前可见的 2 部作品")
  })

  it("管理模式在同页重挂载后保留", () => {
    projectSession.manageMode = true
    const { wrapper } = mountView({ projects: [makeProject("p1")] })

    expect(wrapper.find('[data-action="manage-projects"]').text()).toBe("完成管理")
    expect(wrapper.find('[data-action="select-visible-projects"]').exists()).toBe(true)
  })

  it("无项目无错误显示首开空态", () => {
    const { wrapper } = mountView()
    expect(wrapper.find(".project-catalog-state--first").exists()).toBe(true)
    expect(wrapper.text()).toContain("开始你的第一部小说")
    expect(wrapper.find('[data-action="new"]').text()).toBe("新建空白作品")
    expect(wrapper.find('[data-action="toggle-import"]').text()).toBe("导入已有作品")
  })

  it("加载失败且无项目显示连接错误态", () => {
    const { wrapper } = mountView({ loadError: "连接被拒绝" })
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    expect(wrapper.text()).toContain("作品列表暂时无法加载")
    expect(wrapper.text()).toContain("连接被拒绝")
  })

  it("加载失败但有项目显示警告条", () => {
    const { wrapper } = mountView({ projects: [makeProject("p1")], loadError: "超时" })
    expect(wrapper.find(".alert-warning").exists()).toBe(true)
    expect(wrapper.text()).toContain("作品列表刷新失败")
  })

  it("当前项目置顶并带 current 徽标", () => {
    const { wrapper } = mountView({
      projects: [makeProject("p1"), makeProject("p2")],
      currentProjectId: "p2",
    })
    const cards = wrapper.findAll(".project-card[data-id]")
    expect(cards[0].attributes("data-id")).toBe("p2")
    expect(cards[0].classes()).toContain("current")
    expect(wrapper.find(".project-current-badge").exists()).toBe(true)
    expect(wrapper.find(".project-archive-hero__current b").text()).toBe("项目p2")
  })

  it("导入抽屉将选中的同一 File 转交项目导入确认", async () => {
    const confirmAction = vi.fn()
    const { wrapper } = mountView({ projects: [makeProject("p1")] })
    setBridgeOverrides({ confirmAction })
    projectSession.importSectionOpen = true
    await wrapper.vm.$nextTick()
    const selectedFile = new File(["正文"], "抽屉转交.txt", { type: "text/plain" })
    const createSpy = vi.spyOn(document, "createElement")

    try {
      wrapper.findComponent(ImportDrawer).vm.$emit("import-new-project", selectedFile)
      await wrapper.vm.$nextTick()

      expect(confirmAction).toHaveBeenCalledWith(
        "将创建新作品「抽屉转交」并导入文件「抽屉转交.txt」。是否继续？",
        expect.any(Function),
        "创建并导入",
      )
      expect(createSpy).not.toHaveBeenCalled()
    } finally {
      createSpy.mockRestore()
    }
  })

  it("首开导入按钮明确走无参 chooser 路径，不把 click 事件当作 File", async () => {
    const { wrapper } = mountView()
    const createElement = document.createElement.bind(document)
    let chooser = null
    const createSpy = vi.spyOn(document, "createElement").mockImplementation((tagName, options) => {
      const element = createElement(tagName, options)
      if (String(tagName).toLowerCase() === "input") chooser = element
      return element
    })
    try {
      await wrapper.find('[data-action="toggle-import"]').trigger("click")

      expect(chooser?.type).toBe("file")
      expect(chooser?.accept).toBe(".txt,.epub,.html,.htm")
    } finally {
      createSpy.mockRestore()
    }
  })
})

describe("搜索过滤", () => {
  it("输入过滤列表与计数；无结果显示搜索空态", async () => {
    const { wrapper } = mountView({
      projects: [makeProject("p1", { title: "星际旅人" }), makeProject("p2", { title: "古城谜案" })],
    })
    await wrapper.find("#project-search-input").setValue("星际")
    expect(wrapper.findAll(".project-card[data-id]")).toHaveLength(1)
    expect(wrapper.find('[data-role="project-filter-count"]').text()).toContain("显示 1 / 共 2 部作品")

    await wrapper.find("#project-search-input").setValue("不存在")
    expect(wrapper.findAll(".project-card[data-id]")).toHaveLength(0)
    expect(wrapper.find('[data-role="project-search-empty"]').exists()).toBe(true)

    await wrapper.find('[data-role="project-search-empty"] [data-action="clear-project-search"]').trigger("click")
    expect(wrapper.findAll(".project-card[data-id]")).toHaveLength(2)
    expect(projectSession.searchQuery).toBe("")
  })

  it("搜索词跨重挂载保留（会话状态）", () => {
    projectSession.searchQuery = "星际"
    const { wrapper } = mountView({
      projects: [makeProject("p1", { title: "星际旅人" }), makeProject("p2", { title: "古城谜案" })],
    })
    expect(wrapper.findAll(".project-card[data-id]")).toHaveLength(1)
  })
})

describe("选择与批量操作", () => {
  it("卡片勾选更新计数，全选可见，清空复位", async () => {
    const { wrapper } = mountView({ projects: [makeProject("p1"), makeProject("p2")] })
    await enterManageMode(wrapper)
    const bulkBar = () => wrapper.find(".bulk-toolbar__status strong")
    expect(bulkBar().text()).toBe("0")

    await wrapper.find('.project-card[data-id="p1"] input[data-action="bulk-toggle-one"]').setValue(true)
    expect(bulkBar().text()).toBe("1")

    await wrapper.find('[data-action="select-visible-projects"]').trigger("click")
    expect(bulkBar().text()).toBe("2")

    await wrapper.find('[data-action="bulk-clear"]').trigger("click")
    expect(bulkBar().text()).toBe("0")
    expect(wrapper.find('[data-action="bulk-run"]').attributes("disabled")).toBeDefined()
  })

  it("搜索过滤后选择集剔除不可见项", async () => {
    const { wrapper } = mountView({
      projects: [makeProject("p1", { title: "星际旅人" }), makeProject("p2", { title: "古城谜案" })],
    })
    await enterManageMode(wrapper)
    await wrapper.find('[data-action="select-visible-projects"]').trigger("click")
    expect(getBulkSelection(projectSession, PROJECT_CARDS_SCOPE).size).toBe(2)
    await wrapper.find("#project-search-input").setValue("星际")
    expect(getBulkSelection(projectSession, PROJECT_CARDS_SCOPE).size).toBe(1)
  })

  it("搜索过滤后全选只选择当前可见项目", async () => {
    const { wrapper } = mountView({
      projects: [makeProject("p1", { title: "星际旅人" }), makeProject("p2", { title: "古城谜案" })],
    })
    await enterManageMode(wrapper)
    await wrapper.find("#project-search-input").setValue("星际")
    const selectVisible = wrapper.find('[data-action="select-visible-projects"]')
    expect(selectVisible.text()).toBe("全选当前可见作品")
    expect(selectVisible.attributes("aria-label")).toBe("全选当前可见的 1 部作品")

    await selectVisible.trigger("click")
    expect(getBulkSelection(projectSession, PROJECT_CARDS_SCOPE)).toEqual(new Set(["p1"]))
  })

  it("批量移入回收站需确认并刷新列表", async () => {
    const { harness } = mountView({ projects: [makeProject("p1")] })
    getBulkSelection(projectSession, PROJECT_CARDS_SCOPE).add("p1")
    globalThis.api.projects.remove = vi.fn(async () => ({}))
    globalThis.api.projects.list = vi.fn(async () => ({ items: [] }))
    setBridgeOverrides({
      confirmAction: (_msg, onConfirm) => onConfirm(),
      state: harness.state,
      onStateChange: harness.onStateChange,
    })
    const wrapper = mount(ProjectView, { props: {} })
    await enterManageMode(wrapper)
    await wrapper.find('[data-action="bulk-run"]').trigger("click")
    await vi.waitFor(() => {
      expect(globalThis.toast).toHaveBeenCalledWith(expect.stringContaining("批量移入回收站"), "success")
    })
    expect(globalThis.api.projects.remove).toHaveBeenCalledWith("p1")
    expect(globalThis.router.refresh).not.toHaveBeenCalled()
  })

  it("批量删除响应晚到且已离开项目页时不刷新或提示", async () => {
    const removal = deferred()
    const { wrapper, harness } = mountView({ projects: [makeProject("p1")] })
    globalThis.api.projects.remove.mockReturnValue(removal.promise)
    globalThis.api.projects.list = vi.fn(async () => ({ items: [] }))
    setBridgeOverrides({ confirmAction: (_msg, onConfirm) => onConfirm() })
    await enterManageMode(wrapper)
    getBulkSelection(projectSession, PROJECT_CARDS_SCOPE).add("p1")
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-action="bulk-run"]').trigger("click")
    await vi.waitFor(() => expect(globalThis.api.projects.remove).toHaveBeenCalledWith("p1"))
    harness.state.currentView = "today"
    removal.resolve({})
    await flushPromises()

    expect(globalThis.api.projects.list).not.toHaveBeenCalled()
    expect(globalThis.router.refresh).not.toHaveBeenCalled()
    expect(globalThis.toast).not.toHaveBeenCalled()
  })

  it("批量删除全部失败时保留选择与确认框供重试", async () => {
    let confirmDelete = null
    const { wrapper } = mountView({ projects: [makeProject("p1")] })
    globalThis.api.projects.remove.mockRejectedValue(new Error("delete failed"))
    setBridgeOverrides({ confirmAction: (_msg, onConfirm) => { confirmDelete = onConfirm } })
    await enterManageMode(wrapper)
    getBulkSelection(projectSession, PROJECT_CARDS_SCOPE).add("p1")
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-action="bulk-run"]').trigger("click")

    await expect(confirmDelete()).resolves.toBe(false)
    expect(getBulkSelection(projectSession, PROJECT_CARDS_SCOPE)).toEqual(new Set(["p1"]))
    expect(globalThis.api.projects.list).not.toHaveBeenCalled()
    expect(globalThis.router.refresh).not.toHaveBeenCalled()
    expect(globalThis.toast).toHaveBeenCalledWith(expect.stringContaining("失败 1"), "error")
  })

  it("批量删除响应晚到且同页已打开新弹窗时不刷新", async () => {
    const removal = deferred()
    let confirmDelete = null
    const { wrapper } = mountView({ projects: [makeProject("p1")] })
    globalThis.api.projects.remove.mockReturnValue(removal.promise)
    document.body.insertAdjacentHTML("beforeend", '<div id="modal-body"><p class="confirm-owner"></p></div>')
    setBridgeOverrides({ confirmAction: (_msg, onConfirm) => { confirmDelete = onConfirm } })
    await enterManageMode(wrapper)
    getBulkSelection(projectSession, PROJECT_CARDS_SCOPE).add("p1")
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-action="bulk-run"]').trigger("click")
    const pending = confirmDelete()
    document.getElementById("modal-body").innerHTML = '<div class="replacement-modal"></div>'
    removal.resolve({})

    await expect(pending).resolves.toBe(true)
    expect(globalThis.api.projects.list).not.toHaveBeenCalled()
    expect(globalThis.router.refresh).not.toHaveBeenCalled()
    expect(globalThis.toast).not.toHaveBeenCalled()
  })
})

describe("卡片操作", () => {
  it("创建占位卡保留鼠标入口并支持 Enter 与 Space", async () => {
    const showModalHtml = vi.fn()
    setBridgeOverrides({ showModalHtml })
    const { wrapper } = mountView({ projects: [makeProject("p1")] })
    const placeholder = wrapper.find(".project-card-placeholder")
    expect(placeholder.attributes("role")).toBe("button")
    expect(placeholder.attributes("tabindex")).toBe("0")
    expect(placeholder.attributes("aria-label")).toBe("创建新作品")

    await placeholder.trigger("click")
    expect(showModalHtml).toHaveBeenCalledTimes(1)
    expect(showModalHtml).toHaveBeenCalledWith("新建作品", expect.any(String), expect.any(Array))

    showModalHtml.mockClear()
    await placeholder.trigger("keydown", { key: "Enter" })
    expect(showModalHtml).toHaveBeenCalledTimes(1)

    showModalHtml.mockClear()
    await placeholder.trigger("keydown", { key: " " })
    expect(showModalHtml).toHaveBeenCalledTimes(1)
  })

  it("打开项目写入 state 并导航今日工作", async () => {
    const { wrapper, harness } = mountView({ projects: [makeProject("p1", { title: "星际旅人" })] })
    await wrapper.find('.project-card[data-id="p1"]').trigger("click")
    expect(harness.state.currentProjectId).toBe("p1")
    expect(harness.state.currentProject.title).toBe("星际旅人")
    expect(globalThis.toast).toHaveBeenCalledWith("已切换到作品：星际旅人", "success")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("today")
  })

  it.each(["Enter", " "])("作品卡支持 %s 键打开", async (key) => {
    const { wrapper, harness } = mountView({ projects: [makeProject("p1", { title: "星际旅人" })] })
    const card = wrapper.find('.project-card[data-id="p1"]')

    expect(card.attributes("role")).toBe("link")
    expect(card.attributes("tabindex")).toBe("0")
    expect(card.attributes("aria-label")).toBe("打开作品：星际旅人")
    await card.trigger("keydown", { key })

    expect(harness.state.currentProjectId).toBe("p1")
    expect(globalThis.router.navigate).toHaveBeenCalledWith("today")
  })

  it("编辑按钮打开编辑 modal（不冒泡打开项目）", async () => {
    const showModalHtml = vi.fn()
    setBridgeOverrides({ showModalHtml })
    const { wrapper, harness } = mountView({ projects: [makeProject("p1")] })
    await enterManageMode(wrapper)
    await wrapper.find('[data-action="edit-project"]').trigger("click")
    expect(showModalHtml).toHaveBeenCalledWith("编辑作品", expect.stringContaining("edit-title"), expect.any(Array))
    expect(harness.state.currentProjectId).toBeNull()
  })

  it("删除按钮走二次确认（不冒泡打开项目）", async () => {
    const confirmAction = vi.fn()
    setBridgeOverrides({ confirmAction })
    const { wrapper, harness } = mountView({ projects: [makeProject("p1", { title: "星际旅人" })] })
    await enterManageMode(wrapper)
    await wrapper.find('[data-action="delete-project"]').trigger("click")
    expect(confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("星际旅人"),
      expect.any(Function),
      "移至回收站",
    )
    expect(harness.state.currentProjectId).toBeNull()
  })
})

describe("导入抽屉", () => {
  it("切换导入抽屉开合", async () => {
    const { wrapper } = mountView({ projects: [makeProject("p1")] })
    expect(wrapper.find(".project-import-drawer").exists()).toBe(false)
    await wrapper.find('[data-action="toggle-import"]').trigger("click")
    expect(wrapper.find(".project-import-drawer").exists()).toBe(true)
    expect(wrapper.find("#pv-import-file").exists()).toBe(true)
    expect(wrapper.find('[data-action="toggle-import"]').text()).toBe("收起导入")
  })
})

describe("重试与回收站入口", () => {
  it("重试重新拉取列表并刷新", async () => {
    globalThis.api.projects.list = vi.fn(async () => ({ items: [makeProject("p9")] }))
    const { wrapper, harness } = mountView({ loadError: "超时" })
    await wrapper.find('[data-action="retry-projects"]').trigger("click")
    await vi.waitFor(() => {
      expect(globalThis.api.projects.list).toHaveBeenCalled()
    })
    expect(harness.state.projects.map((p) => p.id)).toEqual(["p9"])
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(globalThis.router.refresh).not.toHaveBeenCalled()
  })

  it("重试响应晚到且已离开项目页时不刷新", async () => {
    const load = deferred()
    globalThis.api.projects.list.mockReturnValue(load.promise)
    const { wrapper, harness } = mountView({ loadError: "超时" })

    await wrapper.find('[data-action="retry-projects"]').trigger("click")
    await vi.waitFor(() => expect(globalThis.api.projects.list).toHaveBeenCalled())
    harness.state.currentView = "today"
    load.resolve({ items: [makeProject("p9")] })
    await flushPromises()

    expect(globalThis.router.refresh).not.toHaveBeenCalled()
  })

  it("回收站按钮触发回收站加载", async () => {
    globalThis.api.projects.listDeleted = vi.fn(async () => ({ items: [], total: 0 }))
    const { wrapper } = mountView({ projects: [makeProject("p1")] })
    await wrapper.find('[data-action="recycle-bin"]').trigger("click")
    await vi.waitFor(() => {
      expect(globalThis.api.projects.listDeleted).toHaveBeenCalled()
    })
    expect(globalThis.showModalHtml).toHaveBeenCalledWith(
      "回收站",
      expect.stringContaining("回收站为空"),
      [],
      expect.objectContaining({ size: "large" }),
    )
  })
})

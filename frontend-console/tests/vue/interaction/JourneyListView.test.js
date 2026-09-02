import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import HomeChoiceView from "../../../vue/views/interaction/HomeChoiceView.vue"
import JourneyListView from "../../../vue/views/interaction/JourneyListView.vue"
import {
  resetBridgeOverrides,
  setBridgeOverrides,
} from "../../../vue/bridge/index.js"

function connections(connected = true) {
  return {
    active_provider_id: "deepseek",
    providers: [{
      provider_id: "deepseek",
      label: "DeepSeek",
      model: "deepseek-v4-flash",
      connected,
      active: true,
    }],
  }
}

function existingJourney() {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    title: "廷根雨夜",
    status: "active",
    opening_excerpt: "我来到廷根。",
    current_excerpt: "马车停在雨里。",
    attempt_status: "completed",
  }
}

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

let api
let router
let state
let toast

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  api = {
    projects: {
      get: vi.fn(),
    },
    interactions: {
      createJourney: vi.fn(),
      listJourneys: vi.fn(),
      archiveJourney: vi.fn(),
      restoreJourney: vi.fn(),
      deleteJourney: vi.fn(),
      acknowledgeSeeSeaNotice: vi.fn(async () => ({
        see_sea_notice_acknowledged: true,
      })),
    },
  }
  router = {
    navigate: vi.fn(),
    getCurrentQuery: vi.fn(() => new URLSearchParams()),
  }
  state = {
    currentProjectId: null,
    currentProject: null,
    currentView: "journeys",
    currentSubView: null,
  }
  toast = vi.fn()
  setBridgeOverrides({
    api,
    router,
    state,
    toast,
    confirm: vi.fn(() => true),
    prompt: vi.fn(() => existingJourney().title),
  })
})

afterEach(() => resetBridgeOverrides())

async function advanceToDirectOpening(wrapper) {
  await wrapper.get(".rp-source-next").trigger("click")
  await flushPromises()
}

describe("首页入口请求所有权", () => {
  it("公共认证页只回传选中的使用方式", async () => {
    const wrapper = mount(HomeChoiceView, { props: { selectionOnly: true } })

    await wrapper.get("[data-entry='author']").trigger("click")
    await wrapper.get("[data-entry='rp']").trigger("click")

    expect(wrapper.emitted("select")).toEqual([["author"], ["rp"]])
    expect(router.navigate).not.toHaveBeenCalled()
    expect(api.projects.get).not.toHaveBeenCalled()
  })

  it("点击 RP 后迟到的作者项目不再改全局状态或抢回路由", async () => {
    const request = deferred()
    const previousProject = { id: "author-project", title: "本地作品" }
    state.currentProjectId = previousProject.id
    state.currentProject = previousProject
    state.currentView = "home"
    api.projects.get.mockReturnValue(request.promise)
    const wrapper = mount(HomeChoiceView)

    void wrapper.get("[data-entry='author']").trigger("click")
    await Promise.resolve()
    await wrapper.get("[data-entry='rp']").trigger("click")
    request.resolve({ id: previousProject.id, title: "迟到的服务端作品" })
    await flushPromises()

    expect(state.currentProject).toBe(previousProject)
    expect(router.navigate).toHaveBeenCalledTimes(1)
    expect(router.navigate).toHaveBeenCalledWith("journeys")
    expect(toast).not.toHaveBeenCalled()
  })
})

describe("RP 旅程列表与开场", () => {
  it("已有旅程时只显示扁平列表和一个开始新旅程入口", async () => {
    sessionStorage.setItem(
      `novel_rp_scroll:${existingJourney().id}`,
      JSON.stringify({ anchorId: "old", scrollTop: 50, atBottom: false }),
    )
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: [existingJourney()],
        archivedJourneys: [],
        llmConnections: connections(),
      },
    })

    expect(wrapper.text()).toContain("廷根雨夜")
    expect(wrapper.find(".rp-opening-composer").exists()).toBe(false)
    expect(wrapper.findAll(".rp-new-journey-button")).toHaveLength(1)
    expect(wrapper.get(".rp-journey-catalog").attributes("aria-busy")).toBe("false")
    expect(wrapper.findAll(".rp-journey-card__actions button")
      .find((button) => button.text() === "归档")
      .attributes("aria-label")).toBe("归档旅程：廷根雨夜")
    expect(wrapper.find("input[aria-label='搜索旅程']").exists()).toBe(false)
    await wrapper.get(".rp-search-toggle").trigger("click")
    expect(wrapper.find("input[aria-label='搜索旅程']").exists()).toBe(true)
    await wrapper.get(".rp-new-journey-button").trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("journeys", "new")
    await wrapper.get(".rp-journey-card__main").trigger("click")
    expect(sessionStorage.getItem(`novel_rp_scroll:${existingJourney().id}`))
      .toBeNull()
  })

  it("进行中的旅程醒目标注正在生成而不是普通继续状态", () => {
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: [{
          ...existingJourney(),
          attempt_status: "running",
        }],
        archivedJourneys: [],
        llmConnections: connections(),
      },
    })

    expect(wrapper.get(".rp-journey-card").classes()).toContain("is-generating")
    expect(wrapper.get(".rp-generating-dot").attributes("aria-label")).toBe("正在生成")
    expect(wrapper.text()).toContain("正在生成故事")
  })

  it("空账户先选来源方式，再保留超长开场而不提交", async () => {
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: [],
        archivedJourneys: [],
        llmConnections: connections(),
      },
    })
    expect(wrapper.find("textarea[aria-label='旅程开场']").exists()).toBe(false)
    await advanceToDirectOpening(wrapper)
    const input = wrapper.get("textarea[aria-label='旅程开场']")
    const tooLong = "界".repeat(100_001)
    await input.setValue(tooLong)

    expect(wrapper.find(".rp-opening-page").exists()).toBe(true)
    expect(input.element.value).toHaveLength(100_001)
    expect(wrapper.text()).toContain("这次输入过长，请分几次发送")
    expect(wrapper.get(".rp-send-button").element.disabled).toBe(true)
    expect(localStorage.getItem("novel_rp_opening_draft")).toBe(tooLong)
  })

  it("为归档管理操作保留旅程名称，并在创建中公开忙碌状态", async () => {
    const creating = deferred()
    api.interactions.createJourney.mockReturnValue(creating.promise)
    const opening = mount(JourneyListView, {
      props: {
        activeJourneys: [],
        archivedJourneys: [],
        llmConnections: connections(),
      },
    })

    await advanceToDirectOpening(opening)
    await opening.get("textarea[aria-label='旅程开场']").setValue("我从旧城醒来。")
    void opening.get(".rp-send-button").trigger("click")
    await Promise.resolve()
    expect(opening.get(".rp-opening-page").attributes("aria-busy")).toBe("true")

    creating.resolve({ journey: existingJourney() })
    await flushPromises()
    expect(opening.get(".rp-opening-page").attributes("aria-busy")).toBe("false")
    opening.unmount()

    const archive = mount(JourneyListView, {
      props: {
        activeJourneys: [],
        archivedJourneys: [{
          ...existingJourney(),
          id: "archived-journey",
          title: "旧城余晖",
          status: "archived",
        }],
        llmConnections: connections(),
      },
    })

    await archive.findAll("[role='tab']")
      .find((button) => button.text() === "已归档")
      .trigger("click")
    const actions = archive.findAll(".rp-journey-card__actions button")
    expect(actions.find((button) => button.text() === "恢复").attributes("aria-label"))
      .toBe("恢复旅程：旧城余晖")
    expect(actions.find((button) => button.text() === "永久删除").attributes("aria-label"))
      .toBe("永久删除旅程：旧城余晖")
  })

  it("创建旅程的组件已卸载时，迟到成功只清本次已提交草稿且不跳转", async () => {
    const request = deferred()
    state.currentSubView = "new"
    api.interactions.createJourney.mockReturnValue(request.promise)
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: [],
        archivedJourneys: [],
        llmConnections: connections(),
        startNew: true,
      },
    })
    await advanceToDirectOpening(wrapper)
    await wrapper.get("textarea[aria-label='旅程开场']").setValue("我从雨夜醒来。")
    void wrapper.get(".rp-send-button").trigger("click")
    await Promise.resolve()
    wrapper.unmount()

    request.resolve({ journey: existingJourney() })
    await flushPromises()

    expect(api.interactions.createJourney).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem("novel_rp_opening_draft")).toBeNull()
    expect(router.navigate).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it.each([
    ["归档", "active", "archiveJourney"],
    ["恢复", "archived", "restoreJourney"],
    ["永久删除", "archived", "deleteJourney"],
  ])("%s 返回时已离开旅程列表，不再重载或提示", async (label, status, method) => {
    const request = deferred()
    const journey = { ...existingJourney(), status }
    api.interactions[method].mockReturnValue(request.promise)
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: status === "active" ? [journey] : [],
        activeTotal: status === "active" ? 1 : 0,
        archivedJourneys: status === "archived" ? [journey] : [],
        archivedTotal: status === "archived" ? 1 : 0,
        llmConnections: connections(),
      },
    })
    if (status === "archived") {
      await wrapper.findAll("[role='tab']")
        .find((button) => button.text() === "已归档")
        .trigger("click")
    }
    void wrapper.findAll(".rp-journey-card__actions button")
      .find((button) => button.text() === label)
      .trigger("click")
    await Promise.resolve()
    state.currentView = "home"

    request.resolve({})
    await flushPromises()

    expect(api.interactions[method]).toHaveBeenCalledTimes(1)
    expect(api.interactions.listJourneys).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("全新无 Key 账户进入时先去账户连接，已有旅程仍保持可读", async () => {
    const empty = mount(JourneyListView, {
      props: {
        activeJourneys: [],
        archivedJourneys: [],
        llmConnections: connections(false),
      },
    })
    await flushPromises()
    expect(router.navigate).toHaveBeenCalledWith(
      "settings",
      null,
      true,
      expect.any(URLSearchParams),
    )
    expect(router.navigate.mock.calls[0][3].get("return_to")).toBe("journeys:new")
    expect(empty.text()).toContain("使用你在账户中连接的 AI 服务")
    expect(empty.text()).toContain("请求经本站后端代发")
    expect(empty.text()).toContain("Key 不会进入浏览器或作品")
    empty.unmount()
    router.navigate.mockClear()

    const existing = mount(JourneyListView, {
      props: {
        activeJourneys: [existingJourney()],
        archivedJourneys: [],
        llmConnections: connections(false),
      },
    })
    expect(existing.text()).toContain("廷根雨夜")
    expect(existing.text()).toContain("现有旅程仍可阅读和管理")
    expect(router.navigate).not.toHaveBeenCalled()
  })

  it("看海首次费用提示由账户接口确认，开关不会在确认前开启", async () => {
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: [],
        archivedJourneys: [],
        llmConnections: connections(),
        preferences: { see_sea_notice_acknowledged: false },
      },
    })
    await advanceToDirectOpening(wrapper)
    const sea = wrapper.findAll(".rp-mode-toggle")
      .find((button) => button.text() === "故事自主发展")
    await sea.trigger("click")
    expect(sea.attributes("aria-pressed")).toBe("false")
    const confirmButton = [...document.querySelectorAll(".rp-sea-notice button")]
      .find((button) => button.textContent === "开始自主发展")
    confirmButton.click()
    confirmButton.click()
    await flushPromises()

    expect(api.interactions.acknowledgeSeeSeaNotice).toHaveBeenCalledTimes(1)
    expect(sea.attributes("aria-pressed")).toBe("true")
  })

  it("列表加载失败不会伪装成新账户开场", async () => {
    api.interactions.listJourneys
      .mockResolvedValueOnce({ items: [existingJourney()], total: 1 })
      .mockResolvedValueOnce({ items: [], total: 0 })
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: [],
        archivedJourneys: [],
        llmConnections: null,
        loadError: "网络暂时不可用",
      },
    })

    expect(wrapper.find(".rp-opening-composer").exists()).toBe(false)
    expect(wrapper.text()).toContain("旅程历史暂时无法加载")
    await wrapper.get(".rp-list-load-error button").trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("廷根雨夜")
  })

  it("列表重试失败时不向用户展示 API 路径或内部标识", async () => {
    api.interactions.listJourneys.mockRejectedValue(
      new Error("API /interactions/journeys?owner_id=private-uuid failed (500)"),
    )
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: [],
        archivedJourneys: [],
        llmConnections: null,
        loadError: "旅程列表暂时无法加载，请稍后重试。",
      },
    })

    await wrapper.get(".rp-list-load-error button").trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("旅程列表暂时无法加载，请稍后重试。")
    expect(wrapper.text()).not.toContain("private-uuid")
    expect(toast).toHaveBeenCalledWith(
      "旅程列表暂时无法加载，请稍后重试。",
      "error",
    )
  })

  it("搜索走服务端且可以继续加载第 51 条之后的旅程", async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) => ({
      ...existingJourney(),
      id: `journey-${index}`,
      title: `旅程 ${index + 1}`,
    }))
    api.interactions.listJourneys.mockImplementation(async (params) => {
      if (params.status === "archived") return { items: [], total: 0 }
      if (params.offset === 50) {
        return {
          items: [{ ...existingJourney(), id: "journey-51", title: "目标旅程" }],
          total: 51,
        }
      }
      return { items: firstPage, total: 51 }
    })
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: firstPage,
        activeTotal: 51,
        archivedJourneys: [],
        archivedTotal: 0,
        llmConnections: connections(),
      },
    })

    await wrapper.get(".rp-load-more").trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("目标旅程")

    await wrapper.get(".rp-search-toggle").trigger("click")
    await wrapper.get("input[aria-label='搜索旅程']").setValue("目标")
    await wrapper.findAll(".rp-catalog-actions button")
      .find((button) => button.text() === "查找")
      .trigger("click")
    await flushPromises()
    expect(api.interactions.listJourneys).toHaveBeenCalledWith(
      expect.objectContaining({ status: "active", search: "目标", limit: 50 }),
    )
  })

  it("快速重复加载更多只提交一页且不会重复追加", async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) => ({
      ...existingJourney(),
      id: `journey-${index}`,
      title: `旅程 ${index + 1}`,
    }))
    const nextPage = deferred()
    api.interactions.listJourneys.mockReturnValue(nextPage.promise)
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: firstPage,
        activeTotal: 51,
        archivedJourneys: [],
        archivedTotal: 0,
        llmConnections: connections(),
      },
    })
    const button = wrapper.get(".rp-load-more")
    void button.trigger("click")
    void button.trigger("click")
    await Promise.resolve()

    expect(api.interactions.listJourneys).toHaveBeenCalledTimes(1)
    expect(button.attributes("aria-busy")).toBe("true")
    expect(wrapper.get(".rp-journey-catalog").attributes("aria-busy")).toBe("true")
    nextPage.resolve({
      items: [{ ...existingJourney(), id: "journey-51", title: "唯一新页" }],
      total: 51,
    })
    await flushPromises()

    expect(wrapper.findAll(".rp-journey-card")).toHaveLength(51)
    expect(wrapper.text().match(/唯一新页/g)).toHaveLength(1)
  })

  it("搜索未完成时不会从旧列表加载更多", async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) => ({
      ...existingJourney(),
      id: `journey-${index}`,
      title: `旅程 ${index + 1}`,
    }))
    const pendingActive = deferred()
    const pendingArchived = deferred()
    api.interactions.listJourneys.mockImplementation(({ status }) => (
      status === "active" ? pendingActive.promise : pendingArchived.promise
    ))
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: firstPage,
        activeTotal: 51,
        archivedJourneys: [],
        archivedTotal: 0,
        llmConnections: connections(),
      },
    })

    await wrapper.get(".rp-search-toggle").trigger("click")
    await wrapper.get("input[aria-label='搜索旅程']").setValue("新查询")
    const searchButton = wrapper.findAll(".rp-catalog-actions button")
      .find((button) => button.text() === "查找")
    void searchButton.trigger("click")
    await Promise.resolve()

    const loadMoreButton = wrapper.get(".rp-load-more")
    expect(loadMoreButton.attributes("disabled")).toBeDefined()
    expect(loadMoreButton.text()).toBe("正在查找…")
    expect(wrapper.get(".rp-journey-catalog").attributes("aria-busy")).toBe("true")
    await loadMoreButton.trigger("click")
    expect(api.interactions.listJourneys).toHaveBeenCalledTimes(2)

    pendingActive.resolve({ items: [], total: 0 })
    pendingArchived.resolve({ items: [], total: 0 })
    await flushPromises()
    expect(api.interactions.listJourneys).toHaveBeenCalledTimes(2)
  })

  it("连续搜索时迟到旧响应不能覆盖较新的查询结果", async () => {
    const oldActive = deferred()
    const oldArchived = deferred()
    api.interactions.listJourneys.mockImplementation(({ status, search }) => {
      if (search === "旧查询") {
        return status === "active" ? oldActive.promise : oldArchived.promise
      }
      return Promise.resolve(
        status === "active"
          ? {
              items: [{
                ...existingJourney(),
                id: "new-result",
                title: "新查询结果",
              }],
              total: 1,
            }
          : { items: [], total: 0 },
      )
    })
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: [existingJourney()],
        activeTotal: 1,
        archivedJourneys: [],
        archivedTotal: 0,
        llmConnections: connections(),
      },
    })
    await wrapper.get(".rp-search-toggle").trigger("click")
    const input = wrapper.get("input[aria-label='搜索旅程']")
    await input.setValue("旧查询")
    await input.trigger("keydown", { key: "Enter" })
    await input.setValue("新查询")
    await input.trigger("keydown", { key: "Enter" })
    await flushPromises()

    expect(wrapper.text()).toContain("新查询结果")
    oldActive.resolve({
      items: [{
        ...existingJourney(),
        id: "old-result",
        title: "迟到旧结果",
      }],
      total: 1,
    })
    oldArchived.resolve({ items: [], total: 0 })
    await flushPromises()

    expect(wrapper.text()).toContain("新查询结果")
    expect(wrapper.text()).not.toContain("迟到旧结果")
  })

  it("搜索没有结果时保留列表与搜索框，不误跳到新旅程开场", async () => {
    api.interactions.listJourneys.mockResolvedValue({ items: [], total: 0 })
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: [existingJourney()],
        activeTotal: 1,
        archivedJourneys: [],
        archivedTotal: 0,
        llmConnections: connections(),
      },
    })

    await wrapper.get(".rp-search-toggle").trigger("click")
    const input = wrapper.get("input[aria-label='搜索旅程']")
    await input.setValue("不存在的旅程")
    await input.trigger("keydown", { key: "Enter" })
    await flushPromises()

    expect(wrapper.find(".rp-journey-catalog").exists()).toBe(true)
    expect(wrapper.find(".rp-opening-composer").exists()).toBe(false)
    expect(wrapper.find("input[aria-label='搜索旅程']").exists()).toBe(true)
    expect(wrapper.text()).toContain("没有找到匹配旅程")
    expect(wrapper.get(".rp-empty-list").attributes("role")).toBe("status")
  })

  it("归档失败时保留列表中的旅程并明确说明生成内容仍在", async () => {
    api.interactions.archiveJourney.mockRejectedValue(new Error("offline"))
    const wrapper = mount(JourneyListView, {
      props: {
        activeJourneys: [existingJourney()],
        activeTotal: 1,
        archivedJourneys: [],
        archivedTotal: 0,
        llmConnections: connections(),
      },
    })

    await wrapper.findAll(".rp-journey-card__actions button")
      .find((button) => button.text() === "归档")
      .trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("廷根雨夜")
    expect(api.interactions.listJourneys).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(
      "归档失败；旅程和正在生成的内容仍保留，请重试。",
      "error",
    )
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import { nextTick } from "vue"
import ShellApp from "../../../vue/shell/ShellApp.vue"
import { createShellTestServices } from "./helpers.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)

beforeEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute("data-theme")
  document.body.innerHTML = ""
})

afterEach(() => resetBridgeOverrides())

describe("ShellApp", () => {
  it("owns the static shell, escapes state text, and reacts through the state bridge", async () => {
    const services = createShellTestServices({ state: {
      currentProject: { id: "p1", title: '<img src=x onerror="boom">雾港' },
      currentView: "world", currentSubView: "objects",
    } })
    const wrapper = mount(ShellApp, { props: { services, healthIntervalMs: 60_000 }, attachTo: document.body })

    expect(wrapper.get("#topbar-project").text()).toContain("<img")
    expect(wrapper.find("#topbar-project img").exists()).toBe(false)
    expect(wrapper.get("#topbar-module").text()).toBe("世界对象")
    expect(wrapper.get("#topbar-submodule").text()).toContain("对象库")
    expect(wrapper.get('.nav-item[data-view="world"]').classes()).toContain("active")
    expect(wrapper.get("#workspace-content").attributes("data-imperative-route-host")).toBe("hash-router")

    services.updateState("currentView", "generate")
    services.updateState("currentSubView", null)
    await nextTick()
    expect(wrapper.get("#topbar-module").text()).toBe("生成中心")
    expect(wrapper.get('.nav-item[data-view="generate"]').classes()).toContain("active")
    expect(wrapper.get("#workspace-content").attributes("data-workspace-view")).toBe("generate")
    expect(wrapper.get("#topbar-view-note").text()).toContain("先自由聊")
  })

  it("navigates through the existing hash router and reports failures visibly", async () => {
    const services = createShellTestServices()
    services.router.getLastSubView.mockImplementation((view) => view === "world" ? "bible" : null)
    const wrapper = mount(ShellApp, { props: { services, healthIntervalMs: 60_000 } })
    await wrapper.get('.nav-item[data-view="world"]').trigger("click")
    expect(services.router.navigate).toHaveBeenCalledWith("world", "bible")

    services.router.navigate.mockRejectedValueOnce(new Error("route down"))
    await wrapper.get('.nav-item[data-view="settings"]').trigger("click")
    expect(services.toast).toHaveBeenCalledWith("导航失败：route down", "error")
  })

  it("keeps router-owned DOM alive across shell state updates and exposes wordcount", async () => {
    const services = createShellTestServices({ state: { currentView: "writing" } })
    const wrapper = mount(ShellApp, { props: { services, healthIntervalMs: 60_000 }, attachTo: document.body })
    const host = wrapper.get("#workspace-content").element
    const external = document.createElement("article")
    external.dataset.routerOwned = "yes"
    external.textContent = "hash router content"
    host.appendChild(external)

    window.dispatchEvent(new CustomEvent("writing:dashboard-update", { detail: { chapterIndex: 12, chapterWords: 3456, todayWords: 789, saveState: "unsaved" } }))
    services.updateState("backendConnected", true)
    await nextTick()

    expect(host.querySelector('[data-router-owned="yes"]')).toBe(external)
    expect(wrapper.get("#topbar-chapter").text()).toContain("12")
    expect(wrapper.get("#topbar-chapter-wc").text()).toBe("3,456")
    expect(wrapper.get("#topbar-save-state").classes()).toContain("unsaved")
    expect(wrapper.get("#topbar-status-dot").classes()).toContain("connected")
  })

  it("handles theme, help, command and workspace shortcuts with component lifecycle cleanup", async () => {
    const services = createShellTestServices()
    const action = vi.fn()
    const wrapper = mount(ShellApp, { props: { services, healthIntervalMs: 60_000 }, attachTo: document.body })
    const button = document.createElement("button")
    button.dataset.action = "generate"
    button.addEventListener("click", action)
    wrapper.get("#workspace-content").element.appendChild(button)

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "?", bubbles: true }))
    await nextTick()
    expect(wrapper.get("#help-overlay").classes()).not.toContain("hidden")
    expect(wrapper.get("#main-layout").attributes()).toHaveProperty("inert")
    await vi.waitFor(() => expect(document.activeElement).toBe(wrapper.get("#help-close").element))
    document.activeElement.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }))
    expect(document.activeElement).toBe(wrapper.get("#help-close").element)
    await wrapper.get("#help-close").trigger("click")
    await nextTick()
    expect(wrapper.get("#main-layout").attributes()).not.toHaveProperty("inert")

    document.dispatchEvent(new KeyboardEvent("keydown", { key: ":", bubbles: true }))
    await nextTick()
    expect(wrapper.get("#command-bar").classes()).toContain("active")
    expect(wrapper.get("#command-input").element.value).toBe(":")
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "g", bubbles: true }))
    expect(services.workspace.triggerAction).not.toHaveBeenCalled()
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "s", metaKey: true, bubbles: true }))
    expect(services.workspace.autosave).not.toHaveBeenCalled()
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
    await nextTick()
    expect(wrapper.get("#command-bar").classes()).not.toContain("active")
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "G", bubbles: true }))
    expect(services.workspace.triggerAction).toHaveBeenLastCalledWith("generate", wrapper.get("#workspace-content").element)
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "s", metaKey: true, bubbles: true }))
    expect(services.workspace.autosave).toHaveBeenCalledWith(wrapper.get("#workspace-content").element)

    services.updateState("currentView", "writing")
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "o", metaKey: true, shiftKey: true, bubbles: true }))
    expect(services.workspace.toggleOutlineFloat).toHaveBeenCalledWith(wrapper.get("#workspace-content").element)

    await wrapper.get("#theme-toggle").trigger("click")
    await wrapper.get('[data-theme-value="dark"]').trigger("click")
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark")
    expect(localStorage.getItem("novel_theme")).toBe("dark")
    expect(services.toast).toHaveBeenCalledWith("已切换至「午夜星河」主题", "success")

    wrapper.unmount()
    window.dispatchEvent(new CustomEvent("writing:dashboard-update", { detail: { chapterIndex: 99, chapterWords: 999 } }))
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "?", bubbles: true }))
    expect(document.getElementById("help-overlay")).toBeNull()
  })

  it("consumes handled single-key actions but leaves unavailable actions to the browser", () => {
    const services = createShellTestServices()
    const wrapper = mount(ShellApp, { props: { services, healthIntervalMs: 60_000 }, attachTo: document.body })
    const titleInput = document.createElement("input")
    const newButton = document.createElement("button")
    newButton.dataset.action = "new"
    newButton.addEventListener("click", () => titleInput.focus())
    wrapper.get("#workspace-content").element.append(newButton, titleInput)

    const handled = new KeyboardEvent("keydown", { key: "n", bubbles: true, cancelable: true })
    document.dispatchEvent(handled)
    expect(services.workspace.triggerAction).toHaveBeenCalledWith("new", wrapper.get("#workspace-content").element)
    expect(handled.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(titleInput)

    titleInput.blur()
    expect(document.activeElement).not.toBe(titleInput)
    const unavailable = new KeyboardEvent("keydown", { key: "e", bubbles: true, cancelable: true })
    document.dispatchEvent(unavailable)
    expect(services.workspace.triggerAction).toHaveBeenLastCalledWith("edit", wrapper.get("#workspace-content").element)
    expect(unavailable.defaultPrevented).toBe(false)
  })

  it("keeps shell shortcuts out of the theme toggle and menu", async () => {
    const services = createShellTestServices()
    const wrapper = mount(ShellApp, { props: { services, healthIntervalMs: 60_000 }, attachTo: document.body })
    const toggle = wrapper.get("#theme-toggle")
    const toggleEnter = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true })
    toggle.element.dispatchEvent(toggleEnter)
    expect(toggleEnter.defaultPrevented).toBe(false)
    expect(services.workspace.triggerAction).not.toHaveBeenCalled()

    await toggle.trigger("click")
    const menuItem = wrapper.get('[data-theme-value="minimal"]')
    for (const key of ["g", "Enter", "Escape"]) {
      menuItem.element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }))
    }
    expect(services.workspace.triggerAction).not.toHaveBeenCalled()
    expect(services.router.navigate).not.toHaveBeenCalled()
  })

  it("defers Enter to focused activation controls but keeps workspace selection elsewhere", async () => {
    const services = createShellTestServices()
    const wrapper = mount(ShellApp, { props: { services, healthIntervalMs: 60_000 }, attachTo: document.body })
    const host = wrapper.get("#workspace-content").element
    const nativeButton = document.createElement("button")
    host.appendChild(nativeButton)
    nativeButton.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
    expect(services.workspace.triggerAction).not.toHaveBeenCalled()

    const sidebarButton = wrapper.get('.nav-item[data-view="world"]')
    sidebarButton.element.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }))
    await nextTick()
    expect(services.router.navigate).toHaveBeenCalledTimes(1)
    expect(services.workspace.triggerAction).not.toHaveBeenCalled()

    const ariaButton = document.createElement("div")
    ariaButton.setAttribute("role", "button")
    const nested = document.createElement("span")
    ariaButton.appendChild(nested)
    host.appendChild(ariaButton)
    nested.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
    expect(services.workspace.triggerAction).not.toHaveBeenCalled()

    host.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
    expect(services.workspace.triggerAction).toHaveBeenCalledTimes(1)
    expect(services.workspace.triggerAction).toHaveBeenCalledWith("select", host)

    nativeButton.dispatchEvent(new KeyboardEvent("keydown", { key: "g", bubbles: true }))
    expect(services.workspace.triggerAction).toHaveBeenLastCalledWith("generate", host)
  })

  it("blocks background workspace shortcuts while a modal is open but keeps Escape", () => {
    const services = createShellTestServices()
    services.modal.isOpen.mockReturnValue(true)
    const wrapper = mount(ShellApp, { props: { services, healthIntervalMs: 60_000 }, attachTo: document.body })

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "g", bubbles: true }))
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "s", metaKey: true, bubbles: true }))
    expect(services.workspace.triggerAction).not.toHaveBeenCalled()
    expect(services.workspace.autosave).not.toHaveBeenCalled()

    const escape = new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
    document.dispatchEvent(escape)
    expect(services.modal.close).toHaveBeenCalledWith(escape)
    wrapper.unmount()
  })

  it("restores focus to the help trigger after closing the modal", async () => {
    const services = createShellTestServices()
    const wrapper = mount(ShellApp, { props: { services, healthIntervalMs: 60_000 }, attachTo: document.body })
    const trigger = wrapper.get(".nav-item.help")
    trigger.element.focus()
    await trigger.trigger("click")
    await vi.waitFor(() => expect(document.activeElement).toBe(wrapper.get("#help-close").element))

    await wrapper.get("#help-close").trigger("click")
    await nextTick()
    expect(document.activeElement).toBe(trigger.element)
  })

  it("keeps account-dialog keys inside the modal and restores the avatar after close", async () => {
    setBridgeOverrides({ api: { auth: { wechatStartUrl: () => "/api/auth/reauth/wechat/start" } } })
    const services = createShellTestServices()
    const wrapper = mount(ShellApp, { props: { services, healthIntervalMs: 60_000 }, attachTo: document.body })
    const avatar = wrapper.get('[aria-label="账户菜单"]')
    avatar.element.focus()
    await avatar.trigger("click")
    await nextTick()
    await nextTick()

    expect(wrapper.get("#topbar").attributes()).toHaveProperty("inert")
    expect(wrapper.get("#main-layout").attributes()).toHaveProperty("inert")
    expect(document.activeElement).toBe(wrapper.get(".account-close").element)
    wrapper.get(".account-overlay").element.dispatchEvent(new KeyboardEvent("keydown", { key: "g", bubbles: true, cancelable: true }))
    expect(services.workspace.triggerAction).not.toHaveBeenCalled()

    wrapper.get(".account-overlay").element.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    await nextTick()
    await nextTick()
    expect(wrapper.find(".account-dialog").exists()).toBe(false)
    expect(wrapper.get("#topbar").attributes()).not.toHaveProperty("inert")
    expect(wrapper.get("#main-layout").attributes()).not.toHaveProperty("inert")
    expect(document.activeElement).toBe(avatar.element)
  })

  it("rejects a late health result after shell unmount", async () => {
    let resolveHealth
    const services = createShellTestServices({ state: { backendConnected: false } })
    services.health.check.mockReturnValue(new Promise((resolve) => { resolveHealth = resolve }))
    const wrapper = mount(ShellApp, { props: { services, healthIntervalMs: 60_000 } })
    await vi.waitFor(() => expect(services.health.check).toHaveBeenCalledTimes(1))
    wrapper.unmount()
    resolveHealth(true)
    await Promise.resolve()
    expect(services.state.backendConnected).toBe(false)
  })

  it("只对合法 RP 返回目标隐藏作者壳", () => {
    const invalidServices = createShellTestServices({
      state: { currentView: "settings" },
    })
    invalidServices.router.getCurrentQuery = vi.fn(
      () => new URLSearchParams({ return_to: "interaction:bad" }),
    )
    const invalid = mount(ShellApp, {
      props: { services: invalidServices, healthIntervalMs: 60_000 },
    })
    expect(invalid.find("#topbar").exists()).toBe(true)
    expect(invalid.find("#sidebar").exists()).toBe(true)
    invalid.unmount()

    const validServices = createShellTestServices({
      state: { currentView: "settings" },
    })
    validServices.router.getCurrentQuery = vi.fn(
      () => new URLSearchParams({
        return_to: "interaction:11111111-1111-4111-8111-111111111111",
      }),
    )
    const valid = mount(ShellApp, {
      props: { services: validServices, healthIntervalMs: 60_000 },
    })
    expect(valid.find("#topbar").exists()).toBe(false)
    expect(valid.find("#sidebar").exists()).toBe(false)
  })
})

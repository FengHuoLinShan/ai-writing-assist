import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import { nextTick } from "vue"
import ActionMenu from "../../../vue/components/ActionMenu.vue"

enableAutoUnmount(afterEach)

const items = [
  { action: "edit", label: "编辑", data: { id: "item-1" } },
  { action: "delete", label: "删除", class: "danger", data: { id: "item-1", kind: "thread" } },
]

beforeEach(() => { document.body.innerHTML = "" })

function mountMenu(props = {}) {
  return mount(ActionMenu, {
    attachTo: document.body,
    props: { menuId: "test-menu", label: "测试剧情线的更多操作", items, ...props },
  })
}

async function sendKey(element, key, options = {}) {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...options })
  element.dispatchEvent(event)
  await nextTick()
  return event
}

describe("ActionMenu", () => {
  it("keeps the established DOM/data contract and exposes labelled menu semantics", () => {
    const wrapper = mountMenu()
    const menu = wrapper.get(".action-menu")
    const trigger = wrapper.get(".action-menu-btn")
    const list = wrapper.get(".action-menu-list")
    const danger = wrapper.get('[data-action="delete"]')

    expect(menu.attributes("data-menu-id")).toBe("test-menu")
    expect(trigger.attributes("aria-label")).toBe("测试剧情线的更多操作")
    expect(trigger.attributes("aria-haspopup")).toBe("menu")
    expect(trigger.attributes("aria-expanded")).toBe("false")
    expect(list.attributes("role")).toBe("menu")
    expect(list.attributes("aria-labelledby")).toBe(trigger.attributes("id"))
    expect(danger.classes()).toContain("danger")
    expect(danger.attributes("data-id")).toBe("item-1")
    expect(danger.attributes("data-kind")).toBe("thread")
    expect(danger.attributes("type")).toBe("button")
    expect(danger.attributes("role")).toBe("menuitem")
  })

  it("updates its contextual label when the row name changes", async () => {
    const wrapper = mountMenu()
    await wrapper.setProps({ label: "改名后的剧情线的更多操作" })
    expect(wrapper.get(".action-menu-btn").attributes("aria-label")).toBe("改名后的剧情线的更多操作")
  })

  it("可以使用可读文字触发器并原生禁用", async () => {
    const wrapper = mountMenu({ triggerText: "更多", disabled: true })
    const trigger = wrapper.get(".action-menu-btn")

    expect(trigger.text()).toBe("更多")
    expect(trigger.attributes("disabled")).toBeDefined()
    expect(trigger.attributes("title")).toBe("测试剧情线的更多操作")
    await trigger.trigger("click")
    expect(wrapper.classes()).not.toContain("open")
  })

  it("opens through click or native Enter/Space activation without a double toggle", async () => {
    const wrapper = mountMenu()
    const trigger = wrapper.get(".action-menu-btn")
    await sendKey(trigger.element, "Enter")
    await trigger.trigger("click")
    expect(wrapper.classes()).toContain("open")
    expect(document.activeElement).toBe(wrapper.get('[data-action="edit"]').element)

    await sendKey(wrapper.get('[data-action="edit"]').element, " ")
    await wrapper.get('[data-action="edit"]').trigger("click")
    expect(wrapper.emitted("select")).toHaveLength(1)
    expect(wrapper.emitted("select")[0]).toEqual([items[0]])
  })

  it("leaves ordinary keys on a closed trigger available to shell shortcuts", async () => {
    const wrapper = mountMenu()
    const documentKeys = vi.fn()
    document.addEventListener("keydown", documentKeys)
    const ordinary = await sendKey(wrapper.get(".action-menu-btn").element, "g")
    expect(ordinary.defaultPrevented).toBe(false)
    expect(documentKeys).toHaveBeenCalledOnce()
    document.removeEventListener("keydown", documentKeys)
  })

  it("uses roving focus for trigger arrows, item arrows, Home, End, and Escape", async () => {
    const wrapper = mountMenu()
    const trigger = wrapper.get(".action-menu-btn")
    const first = wrapper.get('[data-action="edit"]')
    const last = wrapper.get('[data-action="delete"]')

    const down = await sendKey(trigger.element, "ArrowDown")
    expect(down.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(first.element)
    await sendKey(first.element, "ArrowUp")
    expect(document.activeElement).toBe(last.element)
    await sendKey(last.element, "Home")
    expect(document.activeElement).toBe(first.element)
    await sendKey(first.element, "End")
    expect(document.activeElement).toBe(last.element)
    await sendKey(last.element, "Escape")
    expect(wrapper.classes()).not.toContain("open")
    expect(document.activeElement).toBe(trigger.element)

    await sendKey(trigger.element, "ArrowUp")
    expect(document.activeElement).toBe(last.element)
  })

  it("closes for Tab, outside click, and focus leave while containing ordinary keys", async () => {
    const wrapper = mountMenu()
    const trigger = wrapper.get(".action-menu-btn")
    const documentKeys = vi.fn()
    document.addEventListener("keydown", documentKeys)
    await trigger.trigger("click")
    const first = wrapper.get('[data-action="edit"]')
    const ordinary = await sendKey(first.element, "g")
    expect(ordinary.defaultPrevented).toBe(false)
    expect(documentKeys).not.toHaveBeenCalled()

    const tab = await sendKey(first.element, "Tab")
    expect(tab.defaultPrevented).toBe(false)
    expect(wrapper.classes()).not.toContain("open")
    await trigger.trigger("click")
    document.body.dispatchEvent(new MouseEvent("click", { bubbles: true }))
    await nextTick()
    expect(wrapper.classes()).not.toContain("open")

    await trigger.trigger("click")
    const outside = document.createElement("button")
    document.body.appendChild(outside)
    outside.focus()
    await Promise.resolve()
    expect(wrapper.classes()).not.toContain("open")
    document.removeEventListener("keydown", documentKeys)
  })

  it("recovers focus after a non-focusable outside click but preserves a real outside focus target", async () => {
    const wrapper = mountMenu()
    const trigger = wrapper.get(".action-menu-btn")
    await trigger.trigger("click")
    document.body.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
    await nextTick()
    expect(wrapper.classes()).not.toContain("open")
    expect(document.activeElement).toBe(trigger.element)

    await trigger.trigger("click")
    const outside = document.createElement("button")
    document.body.appendChild(outside)
    outside.focus()
    document.body.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
    await nextTick()
    expect(document.activeElement).toBe(outside)
  })

  it("stops trigger and item clicks from reaching document while selecting once with the unchanged payload", async () => {
    const wrapper = mountMenu()
    const documentClicks = vi.fn()
    document.addEventListener("click", documentClicks)
    await wrapper.get(".action-menu-btn").trigger("click")
    expect(documentClicks).not.toHaveBeenCalled()
    await wrapper.get('[data-action="delete"]').trigger("click")

    expect(document.activeElement).toBe(wrapper.get(".action-menu-btn").element)
    expect(wrapper.emitted("select")).toEqual([[items[1]]])
    expect(documentClicks).not.toHaveBeenCalled()
    document.removeEventListener("click", documentClicks)
  })

  it("synchronizes open state through the coordinator without focus transfer or click bubbling", async () => {
    const first = mountMenu({ menuId: "first" })
    const second = mountMenu({ menuId: "second" })
    await first.get(".action-menu-btn").trigger("click")
    expect(first.classes()).toContain("open")
    const secondTrigger = second.get(".action-menu-btn").element
    const openSecond = new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true })
    secondTrigger.dispatchEvent(openSecond)
    await nextTick()
    expect(first.classes()).not.toContain("open")
    expect(first.get(".action-menu-btn").attributes("aria-expanded")).toBe("false")
    expect(second.classes()).toContain("open")
    expect(second.get(".action-menu-btn").attributes("aria-expanded")).toBe("true")
    expect(document.activeElement).toBe(second.get('[data-action="edit"]').element)

    second.unmount()
    await first.get(".action-menu-btn").trigger("click")
    expect(first.classes()).toContain("open")
  })

  it("cancels a same-tick focus task after outside close and leaves another instance usable", async () => {
    const first = mountMenu({ menuId: "first" })
    const second = mountMenu({ menuId: "second" })
    const outside = document.createElement("button")
    document.body.appendChild(outside)
    first.get(".action-menu-btn").element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
    document.body.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
    outside.focus()
    await nextTick()
    expect(first.classes()).not.toContain("open")
    expect(document.activeElement).toBe(outside)

    await sendKey(second.get(".action-menu-btn").element, "ArrowDown")
    expect(second.classes()).toContain("open")
    expect(document.activeElement).toBe(second.get('[data-action="edit"]').element)
  })
})

import { afterEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import ThemePicker from "../../../vue/shell/components/ThemePicker.vue"

enableAutoUnmount(afterEach)

afterEach(() => {
  document.body.innerHTML = ""
})

function mountPicker(modelValue = "minimal") {
  return mount(ThemePicker, {
    attachTo: document.body,
    props: { modelValue },
  })
}

async function openMenu(wrapper) {
  await wrapper.get("#theme-toggle").trigger("click")
  await Promise.resolve()
}

function options(wrapper) {
  return wrapper.findAll("[role='menuitemradio']")
}

describe("ThemePicker", () => {
  it("names and associates the toggle, then focuses the checked item on open", async () => {
    const wrapper = mountPicker("warm")
    const toggle = wrapper.get("#theme-toggle")

    expect(toggle.attributes("aria-label")).toBe("切换主题")
    expect(toggle.attributes("aria-controls")).toBe("theme-menu")
    await openMenu(wrapper)

    const menuItems = options(wrapper)
    expect(toggle.attributes("aria-expanded")).toBe("true")
    expect(menuItems[1].attributes("aria-checked")).toBe("true")
    expect(menuItems[1].attributes("tabindex")).toBe("0")
    expect(document.activeElement).toBe(menuItems[1].element)

    await toggle.trigger("click")
    expect(toggle.attributes("aria-expanded")).toBe("false")
  })

  it("falls back to the first item for an unknown theme value", async () => {
    const wrapper = mountPicker("unknown")
    await openMenu(wrapper)

    const menuItems = options(wrapper)
    expect(menuItems[0].attributes("tabindex")).toBe("0")
    expect(document.activeElement).toBe(menuItems[0].element)
  })

  it("moves roving focus with wrapping and Home/End without selecting a theme", async () => {
    const wrapper = mountPicker("minimal")
    await openMenu(wrapper)
    const menuItems = options(wrapper)

    await menuItems[0].trigger("keydown", { key: "ArrowUp" })
    await Promise.resolve()
    expect(document.activeElement).toBe(menuItems[2].element)
    expect(menuItems[2].attributes("tabindex")).toBe("0")

    await menuItems[2].trigger("keydown", { key: "ArrowDown" })
    await Promise.resolve()
    expect(document.activeElement).toBe(menuItems[0].element)

    await menuItems[0].trigger("keydown", { key: "End" })
    await Promise.resolve()
    expect(document.activeElement).toBe(menuItems[2].element)

    await menuItems[2].trigger("keydown", { key: "Home" })
    await Promise.resolve()
    expect(document.activeElement).toBe(menuItems[0].element)
    expect(wrapper.emitted("update:modelValue")).toBeUndefined()
    expect(menuItems[0].attributes("aria-checked")).toBe("true")
  })

  it("keeps activation and menu keydowns out of document shortcuts without preventing native activation", async () => {
    const wrapper = mountPicker("minimal")
    const documentKeydown = vi.fn()
    document.addEventListener("keydown", documentKeydown)
    try {
      for (const key of ["Enter", " "]) {
        const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true })
        wrapper.get("#theme-toggle").element.dispatchEvent(event)
        expect(event.defaultPrevented).toBe(false)
      }
      expect(documentKeydown).not.toHaveBeenCalled()

      await openMenu(wrapper)
      const menuItems = options(wrapper)
      for (const [key, prevented] of [["Enter", false], [" ", false], ["Tab", false], ["g", false], ["Escape", true]]) {
        const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true })
        menuItems[1].element.dispatchEvent(event)
        expect(event.defaultPrevented).toBe(prevented)
      }
      expect(documentKeydown).not.toHaveBeenCalled()
    } finally {
      document.removeEventListener("keydown", documentKeydown)
    }
  })

  it("leaves native Enter and Space activation to one click selection and returns focus", async () => {
    const wrapper = mountPicker("minimal")
    await openMenu(wrapper)
    const menuItems = options(wrapper)
    for (const key of ["Enter", " "]) {
      const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true })
      menuItems[1].element.dispatchEvent(event)
      expect(event.defaultPrevented).toBe(false)
    }

    await menuItems[1].trigger("click")
    expect(wrapper.emitted("update:modelValue")).toEqual([["warm"]])
    expect(wrapper.get("#theme-toggle").attributes("aria-expanded")).toBe("false")
    await Promise.resolve()
    expect(document.activeElement).toBe(wrapper.get("#theme-toggle").element)
  })

  it("returns focus on Escape, lets Tab leave normally, and closes without leaving hidden focus", async () => {
    const wrapper = mountPicker("minimal")
    await openMenu(wrapper)
    const menuItems = options(wrapper)

    await menuItems[0].trigger("keydown", { key: "Escape" })
    await Promise.resolve()
    expect(wrapper.get("#theme-toggle").attributes("aria-expanded")).toBe("false")
    expect(document.activeElement).toBe(wrapper.get("#theme-toggle").element)

    await openMenu(wrapper)
    const tabEvent = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true })
    menuItems[0].element.dispatchEvent(tabEvent)
    expect(tabEvent.defaultPrevented).toBe(false)
    const outside = document.createElement("button")
    document.body.appendChild(outside)
    outside.focus()
    await Promise.resolve()
    expect(wrapper.get("#theme-toggle").attributes("aria-expanded")).toBe("false")

    await openMenu(wrapper)
    expect(document.activeElement).toBe(menuItems[0].element)
    wrapper.vm.close()
    await vi.waitFor(() => {
      expect(wrapper.get("#theme-toggle").attributes("aria-expanded")).toBe("false")
      expect(document.activeElement).toBe(wrapper.get("#theme-toggle").element)
    })

    await openMenu(wrapper)
    outside.focus()
    wrapper.vm.close()
    await vi.waitFor(() => expect(document.activeElement).toBe(outside))
  })
})

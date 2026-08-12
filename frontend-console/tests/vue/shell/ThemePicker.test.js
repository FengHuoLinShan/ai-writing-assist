import { afterEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import ThemePicker from "../../../vue/shell/components/ThemePicker.vue"
import { SHELL_THEMES } from "../../../vue/shell/composables/useTheme.js"

enableAutoUnmount(afterEach)

afterEach(() => {
  document.body.innerHTML = ""
})

function mountPicker(modelValue = "sticky") {
  return mount(ThemePicker, {
    attachTo: document.body,
    props: { modelValue },
  })
}

function dots(wrapper) {
  return wrapper.findAll(".theme-dot")
}

describe("ThemePicker", () => {
  it("renders one labelled radio dot per theme inside a radiogroup", () => {
    const wrapper = mountPicker("night")
    const group = wrapper.get(".topbar-theme")
    expect(group.attributes("role")).toBe("radiogroup")
    expect(group.attributes("aria-label")).toBe("主题")

    const items = dots(wrapper)
    expect(items).toHaveLength(SHELL_THEMES.length)
    items.forEach((item, index) => {
      const theme = SHELL_THEMES[index]
      expect(item.attributes("role")).toBe("radio")
      expect(item.attributes("data-theme-value")).toBe(theme.value)
      expect(item.attributes("title")).toBe(theme.label)
      expect(item.attributes("aria-label")).toBe(`切换到${theme.label}`)
      expect(item.attributes("type")).toBe("button")
    })
    expect(items[1].attributes("aria-checked")).toBe("true")
    expect(items[1].classes()).toContain("is-active")
    expect(items[0].attributes("aria-checked")).toBe("false")
    expect(items[0].classes()).not.toContain("is-active")
  })

  it("emits update:modelValue when a dot is clicked", async () => {
    const wrapper = mountPicker("sticky")
    await dots(wrapper)[2].trigger("click")
    expect(wrapper.emitted("update:modelValue")).toEqual([["ink"]])
  })

  it("moves selection and focus with arrow keys, wrapping at both ends", async () => {
    const wrapper = mountPicker("sticky")
    const items = dots(wrapper)

    await items[0].trigger("keydown", { key: "ArrowRight" })
    expect(wrapper.emitted("update:modelValue")).toEqual([["night"]])
    await Promise.resolve()
    expect(document.activeElement).toBe(items[1].element)

    await items[1].trigger("keydown", { key: "ArrowLeft" })
    expect(wrapper.emitted("update:modelValue")).toEqual([["night"], ["sticky"]])
    await Promise.resolve()
    expect(document.activeElement).toBe(items[0].element)

    await items[0].trigger("keydown", { key: "ArrowUp" })
    expect(wrapper.emitted("update:modelValue")).toEqual([["night"], ["sticky"], ["ink"]])
    await Promise.resolve()
    expect(document.activeElement).toBe(items[2].element)

    await items[2].trigger("keydown", { key: "ArrowDown" })
    expect(wrapper.emitted("update:modelValue")).toEqual([["night"], ["sticky"], ["ink"], ["sticky"]])
    await Promise.resolve()
    expect(document.activeElement).toBe(items[0].element)
  })

  it("keeps dot keydowns out of document shortcuts without preventing native activation", () => {
    const wrapper = mountPicker("sticky")
    const documentKeydown = vi.fn()
    document.addEventListener("keydown", documentKeydown)
    try {
      const items = dots(wrapper)
      for (const [key, prevented] of [["Enter", false], [" ", false], ["g", false], ["ArrowRight", true]]) {
        const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true })
        items[0].element.dispatchEvent(event)
        expect(event.defaultPrevented).toBe(prevented)
      }
      expect(documentKeydown).not.toHaveBeenCalled()
    } finally {
      document.removeEventListener("keydown", documentKeydown)
    }
  })
})

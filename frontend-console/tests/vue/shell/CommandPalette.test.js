import { afterEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import CommandPalette from "../../../vue/shell/components/CommandPalette.vue"
import { createShellTestServices } from "./helpers.js"

enableAutoUnmount(afterEach)

afterEach(() => {
  document.body.innerHTML = ""
})

function suggestions() {
  return [
    { name: ":help", help: "查看帮助" },
    { name: ":home", help: "回到首页" },
    { name: ":history", help: "打开历史" },
  ]
}

function mountPalette(services = createShellTestServices()) {
  return mount(CommandPalette, { props: { services }, attachTo: document.body })
}

async function openPalette(wrapper, prefix = ":h") {
  await wrapper.vm.open(prefix)
  await wrapper.vm.$nextTick()
}

describe("CommandPalette", () => {
  it("exposes a bounded, escaped combobox listbox relationship", async () => {
    const services = createShellTestServices()
    services.commands.getSuggestions.mockReturnValue([
      { name: ':open<img src=x onerror="boom">', help: '<script>alert(1)</script>' },
      ...Array.from({ length: 6 }, (_, index) => ({ name: `:extra-${index}`, help: `帮助 ${index}` })),
    ])
    const wrapper = mountPalette(services)
    await openPalette(wrapper, ":o")

    const input = wrapper.get("#command-input")
    const options = wrapper.findAll("[role='option']")
    expect(input.attributes("role")).toBe("combobox")
    expect(input.attributes("aria-controls")).toBe("command-suggestions")
    expect(input.attributes("aria-expanded")).toBe("true")
    expect(input.attributes("aria-autocomplete")).toBe("list")
    expect(input.attributes("aria-describedby")).toBe("command-hint")
    expect(wrapper.get("#command-suggestions").attributes("role")).toBe("listbox")
    expect(wrapper.get("#command-suggestions").attributes("aria-label")).toBe("命令建议")
    expect(options).toHaveLength(6)
    expect(options[0].attributes("id")).toBe("command-suggestion-0")
    expect(options[0].attributes("data-cmd")).toContain(":open<img")
    expect(options[0].attributes("aria-selected")).toBe("false")
    expect(options[0].attributes("tabindex")).toBe("-1")
    expect(wrapper.get("#command-suggestions").text()).toContain("<img")
    expect(wrapper.find("img").exists()).toBe(false)
    expect(wrapper.find("script").exists()).toBe(false)
  })

  it("wraps active suggestion browsing without mutating input or executing", async () => {
    const services = createShellTestServices()
    services.commands.getSuggestions.mockReturnValue(suggestions())
    const wrapper = mountPalette(services)
    await openPalette(wrapper)
    const input = wrapper.get("#command-input")

    await input.trigger("keydown", { key: "ArrowUp" })
    expect(input.element.value).toBe(":h")
    expect(input.attributes("aria-activedescendant")).toBe("command-suggestion-2")
    expect(wrapper.findAll("[role='option']")[2].classes()).toContain("active")
    expect(wrapper.findAll("[role='option']")[2].attributes("aria-selected")).toBe("true")

    await input.trigger("keydown", { key: "ArrowDown" })
    expect(input.attributes("aria-activedescendant")).toBe("command-suggestion-0")
    expect(document.activeElement).toBe(input.element)
    expect(services.commands.execute).not.toHaveBeenCalled()
  })

  it("resets active selection when typing and preserves default Enter input execution", async () => {
    const services = createShellTestServices()
    services.commands.getSuggestions.mockReturnValue(suggestions())
    const wrapper = mountPalette(services)
    await openPalette(wrapper)
    const input = wrapper.get("#command-input")

    await input.trigger("keydown", { key: "ArrowDown" })
    expect(input.attributes("aria-activedescendant")).toBe("command-suggestion-0")
    await input.setValue(":custom exact input")
    expect(input.attributes("aria-activedescendant")).toBeUndefined()
    expect(wrapper.findAll("[role='option']").every((option) => option.attributes("aria-selected") === "false")).toBe(true)

    await input.trigger("keydown", { key: "Enter" })
    expect(services.commands.execute).toHaveBeenCalledTimes(1)
    expect(services.commands.execute).toHaveBeenCalledWith(":custom exact input")
  })

  it("executes the explicit active suggestion once and keeps Tab completion on the first option", async () => {
    const services = createShellTestServices()
    services.commands.getSuggestions.mockReturnValue(suggestions())
    const wrapper = mountPalette(services)
    await openPalette(wrapper)
    const input = wrapper.get("#command-input")

    await input.trigger("keydown", { key: "ArrowDown" })
    await input.trigger("keydown", { key: "ArrowDown" })
    expect(input.attributes("aria-activedescendant")).toBe("command-suggestion-1")
    await input.trigger("keydown", { key: "Tab" })
    expect(input.element.value).toBe(":help ")
    expect(input.attributes("aria-activedescendant")).toBeUndefined()
    expect(services.commands.execute).not.toHaveBeenCalled()

    await openPalette(wrapper)
    await input.trigger("keydown", { key: "ArrowDown" })
    await input.trigger("keydown", { key: "ArrowDown" })
    await input.trigger("keydown", { key: "Enter" })
    expect(services.commands.execute).toHaveBeenCalledTimes(1)
    expect(services.commands.execute).toHaveBeenCalledWith(":home")
  })

  it("keeps slash execution and rejected-command feedback unchanged", async () => {
    const services = createShellTestServices()
    services.commands.execute.mockRejectedValueOnce(new Error("command down"))
    const wrapper = mountPalette(services)
    await openPalette(wrapper, "/")
    const input = wrapper.get("#command-input")
    await input.setValue("/旧王都")
    await input.trigger("keydown", { key: "Enter" })

    expect(services.commands.execute).toHaveBeenCalledWith("/旧王都")
    expect(services.toast).toHaveBeenCalledWith("命令执行失败：command down", "error")
  })

  it("restores the opening origin on Escape and lets programmatic close preserve outside focus", async () => {
    const services = createShellTestServices()
    services.commands.getSuggestions.mockReturnValue(suggestions())
    const wrapper = mountPalette(services)
    const trigger = document.createElement("button")
    const outside = document.createElement("button")
    document.body.append(trigger, outside)
    trigger.focus()
    await openPalette(wrapper)
    const input = wrapper.get("#command-input")

    await input.trigger("keydown", { key: "Escape" })
    await vi.waitFor(() => expect(document.activeElement).toBe(trigger))
    expect(wrapper.vm.isOpen()).toBe(false)

    trigger.focus()
    await openPalette(wrapper)
    outside.focus()
    wrapper.vm.close()
    await vi.waitFor(() => expect(document.activeElement).toBe(outside))
    expect(document.activeElement).not.toBe(input.element)
  })

  it("executes mouse selection from the suggestion button", async () => {
    const services = createShellTestServices()
    services.commands.getSuggestions.mockReturnValue(suggestions())
    const wrapper = mountPalette(services)
    await openPalette(wrapper)
    await wrapper.findAll("[role='option']")[1].trigger("mousedown")

    expect(services.commands.execute).toHaveBeenCalledTimes(1)
    expect(services.commands.execute).toHaveBeenCalledWith(":home")
  })
})

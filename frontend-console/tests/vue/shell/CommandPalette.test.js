import { afterEach, describe, expect, it } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import CommandPalette from "../../../vue/shell/components/CommandPalette.vue"
import { createShellTestServices } from "./helpers.js"

enableAutoUnmount(afterEach)

describe("CommandPalette", () => {
  it("renders command metadata as text, completes, and executes through the command service", async () => {
    const services = createShellTestServices()
    services.commands.getSuggestions.mockReturnValue([{ name: ':open<img src=x onerror="boom">', help: '<script>alert(1)</script>' }])
    const wrapper = mount(CommandPalette, { props: { services }, attachTo: document.body })
    await wrapper.vm.open(":o")
    await wrapper.vm.$nextTick()
    expect(wrapper.get("#command-suggestions").text()).toContain("<img")
    expect(wrapper.find("img").exists()).toBe(false)
    expect(wrapper.find("script").exists()).toBe(false)
    await wrapper.get("#command-input").trigger("keydown", { key: "Tab" })
    expect(wrapper.get("#command-input").element.value).toContain(":open<img")
    await wrapper.get("#command-input").trigger("keydown", { key: "Enter" })
    expect(services.commands.execute).toHaveBeenCalledWith(':open<img src=x onerror="boom">')
    expect(services.state.mode).toBe("NORMAL")
  })

  it("executes slash search unchanged and surfaces a rejected command", async () => {
    const services = createShellTestServices()
    services.commands.execute.mockRejectedValueOnce(new Error("command down"))
    const wrapper = mount(CommandPalette, { props: { services } })
    await wrapper.vm.open("/")
    await wrapper.get("#command-input").setValue("/旧王都")
    await wrapper.get("#command-input").trigger("keydown", { key: "Enter" })
    expect(services.commands.execute).toHaveBeenCalledWith("/旧王都")
    expect(services.toast).toHaveBeenCalledWith("命令执行失败：command down", "error")
  })
})

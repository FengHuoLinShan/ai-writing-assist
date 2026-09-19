import { afterEach, describe, expect, it } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import Topbar from "../../../vue/shell/components/Topbar.vue"

enableAutoUnmount(afterEach)

afterEach(() => {
  document.body.innerHTML = ""
})

function mountTopbar(props = {}) {
  return mount(Topbar, {
    attachTo: document.body,
    props: {
      theme: "light",
      wordcount: { chapterIndex: 1, chapterWords: 0, todayWords: 0, saveState: "saved" },
      ...props,
    },
  })
}

function workspaceList() {
  return document.getElementById("action-menu-list-topbar-workspaces")
}

function workspaceItemLabels() {
  return [...workspaceList().querySelectorAll(".action-menu-item")].map((button) => button.textContent)
}

describe("Topbar 工作区菜单", () => {
  it("以浮动态挂载到 body，并提供进入互动故事的入口", async () => {
    const wrapper = mountTopbar()

    await wrapper.get(".topbar-workspace-menu .action-menu-btn").trigger("click")

    const list = workspaceList()
    expect(list).toBeTruthy()
    // 浮动态经 Teleport 挂到 body，避免被壳层 overflow/层叠裁剪或遮挡
    expect(list.parentElement).toBe(document.body)
    expect(workspaceItemLabels().some((label) => label.includes("互动故事"))).toBe(true)

    const rpItem = [...list.querySelectorAll(".action-menu-item")]
      .find((button) => button.textContent.includes("互动故事"))
    rpItem.click()
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted("navigate")?.at(-1)).toEqual(["journeys"])
  })

  it("公开演示模式下不提供互动故事入口", async () => {
    const wrapper = mountTopbar({ publicDemo: true })

    await wrapper.get(".topbar-workspace-menu .action-menu-btn").trigger("click")

    expect(workspaceItemLabels().some((label) => label.includes("互动故事"))).toBe(false)
  })
})

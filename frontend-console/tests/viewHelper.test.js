import { beforeEach, describe, expect, it } from "vitest"

import { bindActionMenus, renderActionMenu } from "../shared/viewHelper.js"

describe("bindActionMenus", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="workspace-content">${renderActionMenu("item-actions", [
      { action: "delete-item", label: "删除" },
    ])}</div>`
  })

  it("重复绑定后一次点击仍只切换一次菜单", () => {
    const container = document.getElementById("workspace-content")
    const menu = container.querySelector(".action-menu")
    const button = container.querySelector(".action-menu-btn")

    bindActionMenus(container)
    bindActionMenus(container)
    button.click()

    expect(menu.classList.contains("open")).toBe(true)
  })
})

import { beforeEach, describe, expect, it } from "vitest"

import {
  bindActionMenus,
  renderActionMenu,
  renderLoadingSkeleton,
} from "../shared/viewHelper.js"

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

describe("renderLoadingSkeleton", () => {
  it("renders presentational skeleton bars with an escaped accessible label", () => {
    const html = renderLoadingSkeleton('章节 <script>alert("x")</script> 加载中')
    document.body.innerHTML = html

    const status = document.querySelector(".loading-skeleton")
    expect(status?.getAttribute("role")).toBe("status")
    expect(status?.getAttribute("aria-busy")).toBe("true")
    expect(status?.querySelector(".sr-only")?.textContent).toBe(
      '章节 <script>alert("x")</script> 加载中',
    )
    expect(status?.querySelector("script")).toBeNull()
    expect(status?.querySelectorAll(".skeleton")).toHaveLength(4)
    expect([...status.querySelectorAll(".skeleton")].every((node) => (
      node.getAttribute("aria-hidden") === "true"
    ))).toBe(true)
  })
})

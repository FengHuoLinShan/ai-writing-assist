import { beforeEach, describe, expect, it } from "vitest"
import { renderWorkspaceRail, workspaceRailKey } from "../shared/workspaceRail.js"

describe("workspaceRail", () => {
  beforeEach(() => {
    sessionStorage.clear()
    document.body.innerHTML = ""
  })

  it("renders a polished semantic rail and escapes its labels", () => {
    const html = renderWorkspaceRail({
      key: workspaceRailKey("writing", "p1", "chapters"),
      title: "<章节>",
      className: "writing-tree-rail",
      content: '<div id="safe-content">正文列表</div>',
    })

    expect(html).toContain("workspace-rail__summary")
    expect(html).toContain("workspace-rail__icon")
    expect(html).toContain("&lt;章节&gt;")
    expect(html).toContain("workspace-rail:p1:writing:chapters")
    expect(html).toContain(" open")
    expect(html).not.toContain("<章节>")
  })

  it("restores state and persists native toggle changes", () => {
    const key = workspaceRailKey("map", "p1", "summary")
    sessionStorage.setItem(key, "closed")
    document.body.innerHTML = renderWorkspaceRail({
      key,
      title: "动态摘要",
      content: "<p>摘要内容</p>",
    })
    const rail = document.querySelector(".workspace-rail")

    expect(rail.open).toBe(false)
    rail.open = true
    rail.dispatchEvent(new Event("toggle"))

    expect(sessionStorage.getItem(key)).toBe("open")
    expect(document.querySelector(".workspace-rail__state").textContent).toBe("收起")
    expect(document.querySelector(".workspace-rail__summary").getAttribute("aria-label")).toBe("收起动态摘要")
  })
})

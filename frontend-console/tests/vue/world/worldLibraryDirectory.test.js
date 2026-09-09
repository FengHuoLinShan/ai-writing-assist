import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"

import WorldLibraryDirectory from "../../../vue/views/world/library/WorldLibraryDirectory.vue"

describe("资料库主题目录", () => {
  it("手机使用抽屉而不是常驻侧栏，触控目标不小于 44px", () => {
    const source = readFileSync(
      resolve(import.meta.dirname, "../../../vue/views/world/library/WorldLibraryDirectory.vue"),
      "utf8",
    )
    expect(source).toContain("WorkspaceDrawer")
    expect(source).toMatch(/isMobile[\s\S]*matchMedia\("\(max-width: 760px\)"/)
    expect(source).toMatch(/@media \(max-width: 760px\)[\s\S]*min-height:\s*44px/s)
  })

  it("目录切换在选中项与筛选之间保持一致（全部/工作稿/收藏/未归类/主题/类型）", async () => {
    const { createApp, h } = await import("vue")
    const emits = []
    const container = document.createElement("div")
    document.body.appendChild(container)
    const app = createApp({
      render: () => h(WorldLibraryDirectory, {
        filters: { q: "", kind: "all", type: "", state: "", topicId: "", favorite: false, unclassified: false },
        topics: [{ id: "t1", name: "地理", status: "active", member_count: 2, children: [] }],
        totalCount: 9,
        workingCount: 3,
        unclassifiedCount: 4,
        favoriteCount: 1,
        types: [{ value: "location", label: "地点", count: 5 }],
        projectId: "p1",
        onSelect: (patch) => emits.push(patch),
      }),
    })
    app.mount(container)
    const buttons = Array.from(container.querySelectorAll("button"))
    const byLabel = (label) => buttons.find((button) => button.textContent.trim().startsWith(label))
    byLabel("全部资料").click()
    byLabel("工作稿").click()
    byLabel("收藏").click()
    byLabel("未归类").click()
    byLabel("地理").click()
    byLabel("地点").click()
    app.unmount()
    container.remove()

    expect(emits).toEqual([
      { state: "", type: "", kind: "all", topicId: "", favorite: false, unclassified: false },
      { state: "working", type: "", kind: "all", topicId: "", favorite: false, unclassified: false },
      { state: "", type: "", kind: "all", topicId: "", favorite: true, unclassified: false },
      { state: "", type: "", kind: "all", topicId: "", favorite: false, unclassified: true },
      { state: "", type: "", kind: "all", topicId: "t1", favorite: false, unclassified: false },
      { state: "", type: "location", kind: "all", topicId: "", favorite: false, unclassified: false },
    ])
  })
})

import { beforeEach, describe, expect, it } from "vitest"

import { renderSceneCockpitPanel, saveSceneCockpitOrder } from "../views/sceneCockpitPanel.js"
import { clearDocument, resetState } from "./helpers.js"

beforeEach(() => {
  resetState({ currentProjectId: "p1" })
  clearDocument()
  localStorage.clear()
})

describe("sceneCockpitPanel", () => {
  it("renders modules in persisted order and escapes dynamic text", () => {
    saveSceneCockpitOrder("p1", ["must_not_happen", "goal", "scene_header"])

    const html = renderSceneCockpitPanel({
      projectId: "p1",
      scene: {
        id: "s1",
        scene_index: 7,
        title: "<script>alert(1)</script>",
        goal: "拿到令牌",
        must_not_happen: "主角死亡",
      },
      mapSummaryHtml: "",
    })

    const firstMustNot = html.indexOf("禁止发生")
    const secondGoal = html.indexOf("目标")
    const thirdTitle = html.indexOf("&lt;script&gt;alert(1)&lt;/script&gt;")
    expect(firstMustNot).toBeGreaterThan(-1)
    expect(firstMustNot).toBeLessThan(secondGoal)
    expect(secondGoal).toBeLessThan(thirdTitle)
    expect(html).toContain("data-action=\"open-scene-workbench\"")
    expect(html).toContain("整理")
    expect(html).toContain("写作副驾驶")
    expect(html).toContain("data-action=\"switch-cockpit-tab\"")
    expect(html).not.toContain("<script>alert")
  })

  it("renders cockpit tabs with escaped people and place references", () => {
    const html = renderSceneCockpitPanel({
      projectId: "p1",
      scene: {
        id: "s1",
        title: "东门",
        scene_characters: [{ name: "<img src=x>", status: "受伤" }],
        primary_location: { name: "旧城门", description: "<b>危险</b>" },
      },
      mapSummaryHtml: "<div>地图摘要</div>",
    })

    expect(html).toContain("人物")
    expect(html).toContain("地点")
    expect(html).toContain("设定")
    expect(html).toContain("地图")
    expect(html).toContain("&lt;img src=x&gt;")
    expect(html).toContain("&lt;b&gt;危险&lt;/b&gt;")
    expect(html).not.toContain("<img src=x>")
  })

  it("renders explicit reference data when the Scene response has no reference fields", () => {
    const html = renderSceneCockpitPanel({
      projectId: "p1",
      scene: { id: "s1", title: "东门" },
      people: [{ id: "c1", name: "沈澜", summary: "巡夜人" }],
      location: { id: "l1", name: "北港", summary: "旧码头区" },
    })

    expect(html).toContain("沈澜")
    expect(html).toContain("巡夜人")
    expect(html).toContain("北港")
    expect(html).toContain("旧码头区")
    expect(html).not.toContain("暂无关联人物")
    expect(html).not.toContain("暂无地点信息")
  })

  it("shows Scene execution details by default", () => {
    document.body.innerHTML = renderSceneCockpitPanel({
      projectId: "p1",
      scene: {
        id: "s1",
        title: "东门交锋",
        goal: "拿到令牌",
      },
    })

    expect(document.querySelector('[data-tab="lore"]')?.classList.contains("active")).toBe(true)
    expect(document.querySelector('[data-panel="lore"]')?.classList.contains("hidden")).toBe(false)
    expect(document.querySelector('[data-panel="lore"]')?.textContent).toContain("拿到令牌")
    expect(document.querySelector('[data-panel="people"]')?.classList.contains("hidden")).toBe(true)
  })

  it("collapses tail modules when compact mode is requested", () => {
    const html = renderSceneCockpitPanel({
      projectId: "p1",
      scene: {
        id: "s1",
        title: "东门",
        goal: "目标",
        must_happen: "必须发生",
        must_not_happen: "禁止发生",
        core_conflict: "冲突",
        emotional_beat: "情绪",
      },
      mapSummaryHtml: "<div>地图摘要</div>",
      compact: true,
    })

    expect(html).toContain("scene-cockpit-module is-collapsed")
    expect(html).toContain("data-action=\"toggle-cockpit-module\"")
  })
})

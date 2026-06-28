import { describe, it, expect } from "vitest"
import { buildMapLayout, boxesOverlap } from "../views/mapLayoutEngine.js"

function item(overrides = {}) {
  return {
    item_id: overrides.item_id || `item-${Math.random()}`,
    item_kind: overrides.item_kind || "observation",
    title: overrides.title || "沈砚",
    object_type: overrides.object_type || "character",
    dynamic_type: overrides.dynamic_type || "location",
    time_label: overrides.time_label || "Scene 42",
    status_label: overrides.status_label || "待确认",
    source_summary: overrides.source_summary || "来源摘要",
    priority: overrides.priority ?? 50,
    risk_level: overrides.risk_level || "info",
    review_state: overrides.review_state || "candidate",
    ...overrides,
  }
}

describe("mapLayoutEngine", () => {
  it("places high priority labels without overlaps and degrades dense low priority items", () => {
    const queue = Array.from({ length: 18 }, (_, index) => item({
      item_id: `dense-${index}`,
      title: `洛阳外城风险${index}`,
      priority: 100 - index,
      risk_level: index < 2 ? "danger" : "info",
      anchor: { x: 180 + (index % 3) * 8, y: 140 + Math.floor(index / 3) * 7 },
    }))

    const layout = buildMapLayout({
      dashboard: { dynamic_queue: queue },
      viewport: { width: 360, height: 240 },
      viewMode: "dashboard",
    })

    for (let i = 0; i < layout.labels.length; i += 1) {
      for (let j = i + 1; j < layout.labels.length; j += 1) {
        expect(boxesOverlap(layout.labels[i].box, layout.labels[j].box)).toBe(false)
      }
    }
    expect(layout.labels.some((label) => label.displayLevel === "full")).toBe(true)
    expect(layout.clusters.length + layout.hiddenCount).toBeGreaterThan(0)
  })

  it("keeps semantic bubbles in the top band without overlap", () => {
    const queue = [
      item({ item_id: "secret-1", title: "东门密道", dynamic_type: "secret", priority: 90 }),
      item({ item_id: "rule-1", title: "禁术代价", dynamic_type: "rule", priority: 88 }),
      item({ item_id: "power-1", title: "灵脉限制", dynamic_type: "power_system", priority: 86 }),
      item({ item_id: "knowledge-1", title: "失传地图", dynamic_type: "knowledge", priority: 84 }),
    ]

    const layout = buildMapLayout({
      dashboard: { dynamic_queue: queue },
      viewport: { width: 420, height: 260 },
      viewMode: "dashboard",
    })

    expect(layout.semanticBubbles).toHaveLength(4)
    expect(layout.semanticBubbles.every((bubble) => bubble.box.y < 96)).toBe(true)
    for (let i = 0; i < layout.semanticBubbles.length; i += 1) {
      for (let j = i + 1; j < layout.semanticBubbles.length; j += 1) {
        expect(boxesOverlap(layout.semanticBubbles[i].box, layout.semanticBubbles[j].box)).toBe(false)
      }
    }
  })

  it("lens mode boosts focus-related objects and reports low motion", () => {
    const layout = buildMapLayout({
      dashboard: {
        dynamic_queue: [
          item({
            item_id: "focus-candidate",
            title: "沈砚抵达洛阳",
            target_entity_id: "char-1",
            priority: 30,
            anchor: { x: 140, y: 120 },
          }),
          item({
            item_id: "background",
            title: "远处势力换防",
            object_type: "faction",
            priority: 80,
            anchor: { x: 150, y: 122 },
          }),
        ],
      },
      viewport: { width: 320, height: 220 },
      viewMode: "lens",
      focusEntityId: "char-1",
      lowMotion: true,
    })

    expect(layout.viewMode).toBe("lens")
    expect(layout.motion).toBe("low")
    expect(layout.labels[0].itemId).toBe("focus-candidate")
    expect(layout.layoutHint).toContain("叙事透镜")
  })
})

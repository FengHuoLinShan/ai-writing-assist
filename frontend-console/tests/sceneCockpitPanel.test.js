import { beforeEach, describe, expect, it } from "vitest"
import { loadSceneCockpitOrder, saveSceneCockpitOrder } from "../views/sceneCockpitPanel.js"

beforeEach(() => localStorage.clear())

describe("sceneCockpitPanel order helper", () => {
  it("保留已知顺序并补齐新模块", () => {
    saveSceneCockpitOrder("p1", ["must_not_happen", "unknown", "goal"])
    const order = loadSceneCockpitOrder("p1")
    expect(order.slice(0, 2)).toEqual(["must_not_happen", "goal"])
    expect(order).toContain("scene_header")
  })

  it("返回独立的默认顺序", () => {
    loadSceneCockpitOrder("p1").reverse()
    expect(loadSceneCockpitOrder("p2")[0]).toBe("scene_header")
  })
})

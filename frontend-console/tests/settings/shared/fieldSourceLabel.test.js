import { describe, it, expect } from "vitest"
import { renderSourceLabel, resettableField } from "../../../views/settings/shared/fieldSourceLabel.js"

describe("fieldSourceLabel", () => {
  it("renders 已覆盖 for project", () => {
    expect(renderSourceLabel({ source: "project", value: "x" })).toContain("已覆盖")
  })
  it("renders 继承全局 for global", () => {
    expect(renderSourceLabel({ source: "global", value: "x" })).toContain("继承全局")
  })
  it("renders 系统默认 for system", () => {
    expect(renderSourceLabel({ source: "system", value: "x" })).toContain("系统默认")
  })
  it("renders 未配置 for unset", () => {
    expect(renderSourceLabel({ source: "unset", value: null })).toContain("未配置")
  })
  it("resettableField produces button HTML with field name", () => {
    expect(resettableField("daily_goal")).toContain('data-field="daily_goal"')
  })
})
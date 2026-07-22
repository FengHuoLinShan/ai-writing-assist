/**
 * outlineBulkSelection 测试 — outline 批量选择（reactive 版）。
 * 语义对齐 shared/bulkSelection.js，状态落 reactive outlineBulkSelections。
 */
import { describe, it, expect, beforeEach } from "vitest"
import {
  clearAllBulkSelections,
  clearBulkSelection,
  getBulkSelection,
  reconcileBulkSelection,
  scopeBulkSelectionsToProject,
  selectAllState,
  toggleAllBulkSelection,
  toggleBulkSelection,
} from "../../../vue/views/outline/logic/outlineBulkSelection.js"

beforeEach(() => {
  scopeBulkSelectionsToProject(null)
  clearAllBulkSelections()
})

describe("选择与清除", () => {
  it("toggle 单项：id 统一字符串化", () => {
    toggleBulkSelection("outline-threads", 42, true)
    expect(getBulkSelection("outline-threads").has("42")).toBe(true)
    toggleBulkSelection("outline-threads", 42, false)
    expect(getBulkSelection("outline-threads").size).toBe(0)
  })

  it("toggleAll 批量加减；空 id 跳过", () => {
    toggleAllBulkSelection("outline-arcs", ["a", null, "b"], true)
    expect(Array.from(getBulkSelection("outline-arcs"))).toEqual(["a", "b"])
    toggleAllBulkSelection("outline-arcs", ["a"], false)
    expect(getBulkSelection("outline-arcs").has("a")).toBe(false)
  })

  it("clearBulkSelection / clearAllBulkSelections", () => {
    toggleBulkSelection("s1", "x", true)
    toggleBulkSelection("s2", "y", true)
    clearBulkSelection("s1")
    expect(getBulkSelection("s1").size).toBe(0)
    expect(getBulkSelection("s2").size).toBe(1)
    clearAllBulkSelections()
    expect(getBulkSelection("s2").size).toBe(0)
  })

  it("相同项目保留选择，跨项目时清空全部 scope", () => {
    scopeBulkSelectionsToProject("p-one")
    toggleBulkSelection("outline-threads", "thread-1", true)
    expect(scopeBulkSelectionsToProject("p-one")).toBe(false)
    expect(getBulkSelection("outline-threads").has("thread-1")).toBe(true)

    expect(scopeBulkSelectionsToProject("p-two")).toBe(true)
    expect(getBulkSelection("outline-threads").size).toBe(0)
  })
})

describe("reconcileBulkSelection", () => {
  it("移除不可见的选中项", () => {
    toggleAllBulkSelection("outline-threads", ["a", "b", "c"], true)
    reconcileBulkSelection("outline-threads", ["a", "c"])
    expect(Array.from(getBulkSelection("outline-threads"))).toEqual(["a", "c"])
  })
})

describe("selectAllState（全选框状态）", () => {
  it("空列表 disabled 且不选", () => {
    expect(selectAllState("s", [])).toEqual({ checked: false, indeterminate: false, disabled: true })
  })
  it("部分选中 indeterminate；全选 checked；未选均否", () => {
    toggleBulkSelection("s", "a", true)
    expect(selectAllState("s", ["a", "b"])).toEqual({ checked: false, indeterminate: true, disabled: false })
    toggleBulkSelection("s", "b", true)
    expect(selectAllState("s", ["a", "b"])).toEqual({ checked: true, indeterminate: false, disabled: false })
    clearAllBulkSelections()
    expect(selectAllState("s", ["a", "b"])).toEqual({ checked: false, indeterminate: false, disabled: false })
  })
})

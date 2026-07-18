/**
 * worldBulkSelection 测试 — 语义对齐 shared/bulkSelection.js，状态落 worldSession。
 */
import { describe, it, expect, beforeEach } from "vitest"
import {
  clearAllBulkSelections,
  clearBulkSelection,
  getBulkSelection,
  reconcileBulkSelection,
  selectAllState,
  toggleAllBulkSelection,
  toggleBulkSelection,
} from "../../../vue/views/world/logic/worldBulkSelection.js"
import { resetWorldSession } from "../../../vue/views/world/worldSession.js"

beforeEach(() => {
  resetWorldSession()
})

describe("选择与清除", () => {
  it("toggle 单项：id 统一字符串化", () => {
    toggleBulkSelection("world-objects", 42, true)
    expect(getBulkSelection("world-objects").has("42")).toBe(true)
    toggleBulkSelection("world-objects", 42, false)
    expect(getBulkSelection("world-objects").size).toBe(0)
  })

  it("toggleAll 批量加减；空 id 跳过", () => {
    toggleAllBulkSelection("world-objects", ["a", null, "b"], true)
    expect(Array.from(getBulkSelection("world-objects"))).toEqual(["a", "b"])
    toggleAllBulkSelection("world-objects", ["a"], false)
    expect(getBulkSelection("world-objects").has("a")).toBe(false)
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
})

describe("reconcileBulkSelection", () => {
  it("移除不可见的选中项", () => {
    toggleAllBulkSelection("world-objects", ["a", "b", "c"], true)
    reconcileBulkSelection("world-objects", ["a", "c"])
    expect(Array.from(getBulkSelection("world-objects"))).toEqual(["a", "c"])
  })
})

describe("selectAllState（对应 shared renderSelectionHeader）", () => {
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

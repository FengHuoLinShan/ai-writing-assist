/**
 * worldBulkSelection 测试 — 语义对齐 shared/bulkSelection.js，状态落 worldSession。
 */
import { mount } from "@vue/test-utils"
import WorldBulkToolbar from "../../../vue/views/world/components/WorldBulkToolbar.vue"
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

describe("selectAllState", () => {
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


describe("批量选择组件", () => {
  it("转义文本并响应半选、全选、清空与空列表", async () => {
    const scope = 's<1"'
    const label = '全选 <img src=x onerror=alert(1)>'
    const wrapper = mount(WorldBulkToolbar, { props: {
      scope,
      noun: "对象",
      selectAllIds: ['id"1', "e2"],
      selectAllLabel: label,
      actions: [{ action: "delete", label: "删除 <对象>" }, { action: "locked", label: "锁定", disabled: true }],
    } })
    try {
      const input = wrapper.get('input[type="checkbox"]')
      const action = wrapper.get('[data-bulk-action="delete"]')
      expect(input.attributes("data-scope")).toBe(scope)
      expect(input.element.checked).toBe(false)
      expect(action.element.disabled).toBe(true)
      expect(wrapper.find("img").exists()).toBe(false)
      expect(wrapper.get("label").attributes("title")).toBe(label)
      expect(wrapper.text()).toContain(label)
      expect(action.text()).toBe("删除 <对象>")

      toggleBulkSelection(scope, 'id"1', true)
      await wrapper.vm.$nextTick()
      expect(input.element.indeterminate).toBe(true)
      expect(input.attributes("data-indeterminate")).toBe("true")
      expect(wrapper.get("strong").text()).toBe("1")
      expect(wrapper.text()).toContain("对象已选")
      expect(action.element.disabled).toBe(false)
      expect(wrapper.get('[data-bulk-action="locked"]').element.disabled).toBe(true)

      await input.setValue(true)
      expect(input.element.checked).toBe(true)
      expect(input.element.indeterminate).toBe(false)
      expect(Array.from(getBulkSelection(scope))).toEqual(['id"1', "e2"])
      await action.trigger("click")
      expect(wrapper.emitted("run")).toEqual([["delete"]])
      await wrapper.get('[data-action="bulk-clear"]').trigger("click")
      expect(input.element.checked).toBe(false)
      expect(action.element.disabled).toBe(true)
      expect(wrapper.get("strong").text()).toBe("0")
      await wrapper.setProps({ selectAllIds: [] })
      expect(input.element.disabled).toBe(true)
    } finally {
      wrapper.unmount()
    }
  })
})

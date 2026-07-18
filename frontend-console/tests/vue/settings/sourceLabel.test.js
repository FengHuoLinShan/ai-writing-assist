/**
 * 来源标签纯逻辑测试 — 对应原 tests/settings/shared/fieldSourceLabel.test.js。
 */
import { describe, it, expect } from "vitest"
import {
  SOURCE_LABELS,
  formatSourceValue,
  sourceLabelClass,
  sourceLabelText,
} from "../../../vue/views/settings/logic/sourceLabel.js"

describe("sourceLabelText / sourceLabelClass", () => {
  it("四种来源的文案与 class 契约", () => {
    expect(sourceLabelText("project")).toBe("已覆盖")
    expect(sourceLabelClass("project")).toBe("source-label source-project")
    expect(sourceLabelText("global")).toBe("继承全局")
    expect(sourceLabelClass("global")).toBe("source-label source-global")
    expect(sourceLabelText("system")).toBe("系统默认")
    expect(sourceLabelClass("system")).toBe("source-label source-system")
    expect(sourceLabelText("unset")).toBe("未配置")
    expect(sourceLabelClass("unset")).toBe("source-label source-unset")
  })

  it("未知来源显示未知并使用 system class", () => {
    expect(sourceLabelText("mystery")).toBe("未知")
    expect(sourceLabelClass("mystery")).toBe("source-label source-system")
  })
})

describe("formatSourceValue", () => {
  it("null/undefined 显示 —", () => {
    expect(formatSourceValue(null)).toBe("—")
    expect(formatSourceValue(undefined)).toBe("—")
  })

  it("对象 JSON 序列化，原始值字符串化", () => {
    expect(formatSourceValue({ a: 1 })).toBe('{"a":1}')
    expect(formatSourceValue(180)).toBe("180")
    expect(formatSourceValue("deepseek")).toBe("deepseek")
    expect(formatSourceValue(false)).toBe("false")
  })
})

describe("SOURCE_LABELS", () => {
  it("与后端 source 枚举对齐（D1）", () => {
    expect(SOURCE_LABELS).toEqual({
      project: "已覆盖",
      global: "继承全局",
      system: "系统默认",
      unset: "未配置",
    })
  })
})

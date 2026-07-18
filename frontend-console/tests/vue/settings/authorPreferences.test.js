/**
 * 作者偏好纯逻辑测试 — 对应原 tests/settings/shared/authorPreferencesForm.test.js。
 */
import { describe, it, expect } from "vitest"
import {
  EDITOR_FONT_OPTIONS,
  authorFormFromDefaults,
  authorFormFromEffective,
  buildAuthorPrefsPayload,
  isResettableSource,
  validateAuthorPreferences,
} from "../../../vue/views/settings/logic/authorPreferences.js"

describe("buildAuthorPrefsPayload", () => {
  it("日更目标字符串转数字，空串转 null", () => {
    expect(buildAuthorPrefsPayload({ daily_goal: "6000", editor_font: "serif", default_focus_mode: true }))
      .toEqual({ daily_goal: 6000, editor_font: "serif", default_focus_mode: true })
    expect(buildAuthorPrefsPayload({ daily_goal: "", editor_font: "system", default_focus_mode: false }).daily_goal)
      .toBeNull()
  })
})

describe("validateAuthorPreferences", () => {
  it("合法值通过（含 null）", () => {
    expect(validateAuthorPreferences({ daily_goal: null }).ok).toBe(true)
    expect(validateAuthorPreferences({ daily_goal: 0 }).ok).toBe(true)
    expect(validateAuthorPreferences({ daily_goal: 100000 }).ok).toBe(true)
  })

  it("非整数或越界拒绝", () => {
    expect(validateAuthorPreferences({ daily_goal: 1.5 }).ok).toBe(false)
    expect(validateAuthorPreferences({ daily_goal: -1 }).ok).toBe(false)
    expect(validateAuthorPreferences({ daily_goal: 100001 }).ok).toBe(false)
  })
})

describe("isResettableSource（原 renderResetFor 契约）", () => {
  it("project/unset 可重置，global/system/null 不可", () => {
    expect(isResettableSource({ source: "project", value: 1 })).toBe(true)
    expect(isResettableSource({ source: "unset", value: null })).toBe(true)
    expect(isResettableSource({ source: "global", value: 1 })).toBe(false)
    expect(isResettableSource({ source: "system", value: 1 })).toBe(false)
    expect(isResettableSource(null)).toBe(false)
    expect(isResettableSource(undefined)).toBe(false)
  })
})

describe("表单初值构造", () => {
  it("authorFormFromEffective：editor_font 回退首个选项（与原 DOM select 读取语义一致）", () => {
    const form = authorFormFromEffective({
      daily_goal: { value: 3000, source: "project" },
      editor_font: { value: null, source: "unset" },
      default_focus_mode: { value: true, source: "global" },
    })
    expect(form.daily_goal).toBe("3000")
    expect(form.editor_font).toBe(EDITOR_FONT_OPTIONS[0])
    expect(form.default_focus_mode).toBe(true)
  })

  it("authorFormFromDefaults：全局页无 source 场景", () => {
    expect(authorFormFromDefaults({ daily_goal: 800, editor_font: "mono", default_focus_mode: false }))
      .toEqual({ daily_goal: "800", editor_font: "mono", default_focus_mode: false })
    expect(authorFormFromDefaults({})).toEqual({ daily_goal: "", editor_font: "system", default_focus_mode: false })
  })
})

import { describe, it, expect } from "vitest"
import { validateAuthorPreferences } from "../../../views/settings/shared/authorPreferencesForm.js"

describe("validateAuthorPreferences", () => {
  it("accepts null daily_goal", () => {
    expect(validateAuthorPreferences({ daily_goal: null }).ok).toBe(true)
  })
  it("rejects negative daily_goal", () => {
    expect(validateAuthorPreferences({ daily_goal: -1 }).ok).toBe(false)
  })
  it("rejects huge daily_goal", () => {
    expect(validateAuthorPreferences({ daily_goal: 999999 }).ok).toBe(false)
  })
  it("accepts 6000 daily_goal", () => {
    expect(validateAuthorPreferences({ daily_goal: 6000 }).ok).toBe(true)
  })
})
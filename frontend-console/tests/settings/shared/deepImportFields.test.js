import { describe, it, expect } from "vitest"
import {
  DEEP_IMPORT_GROUPS,
  deepImportFieldId,
  readDeepImportFields,
} from "../../../views/settings/shared/deepImportFields.js"

describe("deepImportFields schema", () => {
  it("has all 6 groups", () => {
    expect(DEEP_IMPORT_GROUPS.map((g) => g.id)).toEqual([
      "global", "phase0", "phase1a", "phase1b", "phase2", "phase3",
    ])
  })
  it("phase2 contains boundary_supplement_enabled bool", () => {
    const p2 = DEEP_IMPORT_GROUPS.find((g) => g.id === "phase2")
    expect(p2.fields.find((f) => f.key === "boundary_supplement_enabled").type).toBe("bool")
  })
  it("id encoding swaps underscores to dashes", () => {
    expect(deepImportFieldId("phase2", "boundary_scenes")).toBe("deep-import-phase2-boundary-scenes")
  })
})

describe("readDeepImportFields validation", () => {
  it("rejects out-of-range phase0 target_input_chars", () => {
    document.body.innerHTML = `<input id="${deepImportFieldId("phase0", "target_input_chars")}" value="10" />`
    const out = readDeepImportFields()
    expect(out.ok).toBe(false)
  })
  it("accepts empty document as default fallback", () => {
    document.body.innerHTML = ""
    const out = readDeepImportFields()
    expect(out.ok).toBe(true)
  })
})
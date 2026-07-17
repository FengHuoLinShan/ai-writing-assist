import { describe, it, expect } from "vitest"
import {
  DEEP_IMPORT_GROUPS,
  deepImportFieldId,
  renderDeepImportFields,
  readDeepImportFields,
} from "../../../views/settings/shared/deepImportFields.js"

describe("deepImportFields schema", () => {
  it("has all 7 groups", () => {
    expect(DEEP_IMPORT_GROUPS.map((g) => g.id)).toEqual([
      "global", "phase0", "phase1a", "phase1b", "phase1c", "phase2", "phase3",
    ])
  })
  it("phase1c exposes the safe auto-merge defaults", () => {
    const p1c = DEEP_IMPORT_GROUPS.find((g) => g.id === "phase1c")
    expect(p1c.fields.find((f) => f.key === "auto_merge_confidence").value).toBe(0.92)
    expect(p1c.fields.find((f) => f.key === "boundary_context_chars").value).toBe(2000)
    expect(p1c.fields.find((f) => f.key === "concurrency").value).toBe(20)
    expect(p1c.fields.find((f) => f.key === "decision_max_tokens").value).toBe(null)
    expect(p1c.fields.find((f) => f.key === "timeout_seconds").value).toBe(1200)
  })
  it("phase2 contains boundary_supplement_enabled bool", () => {
    const p2 = DEEP_IMPORT_GROUPS.find((g) => g.id === "phase2")
    expect(p2.fields.find((f) => f.key === "boundary_supplement_enabled").type).toBe("bool")
  })
  it("phase2 world window concurrency defaults to 20", () => {
    const p2 = DEEP_IMPORT_GROUPS.find((g) => g.id === "phase2")
    expect(p2.fields.find((f) => f.key === "world_window_concurrency").value).toBe(20)
  })
  it("phase2 complex scene extraction uses bounded concurrency", () => {
    const p2 = DEEP_IMPORT_GROUPS.find((g) => g.id === "phase2")
    expect(p2.fields.find((f) => f.key === "parallel_scene_concurrency").value).toBe(25)
    expect(p2.fields.find((f) => f.key === "parallel_scene_max_tokens").value).toBe(32768)
    expect(p2.fields.find((f) => f.key === "parallel_provider_timeout_seconds").value).toBe(360)
    expect(p2.fields.find((f) => f.key === "parallel_llm_timeout_seconds").value).toBe(900)
  })
  it("DeepSeek token ratios use the calibrated 1.0 upper-bound default", () => {
    const p0 = DEEP_IMPORT_GROUPS.find((g) => g.id === "phase0")
    const p2 = DEEP_IMPORT_GROUPS.find((g) => g.id === "phase2")
    expect(p0.fields.find((f) => f.key === "max_tokens_per_input_char").value).toBe(1.0)
    expect(p2.fields.find((f) => f.key === "world_max_tokens_per_source_char").value).toBe(1.0)
  })
  it("generation-heavy Phase 1B, Phase 2, and Phase 3 defaults use the full upper bound", () => {
    const p1b = DEEP_IMPORT_GROUPS.find((g) => g.id === "phase1b")
    const p2 = DEEP_IMPORT_GROUPS.find((g) => g.id === "phase2")
    const p3 = DEEP_IMPORT_GROUPS.find((g) => g.id === "phase3")
    expect(p1b.fields.find((f) => f.key === "enrich_max_tokens").value).toBe(32768)
    expect(p2.fields.find((f) => f.key === "world_min_max_tokens").value).toBe(32768)
    expect(p2.fields.find((f) => f.key === "world_max_max_tokens").value).toBe(32768)
    expect(p3.fields.find((f) => f.key === "structure_max_tokens").value).toBe(32768)
  })
  it("id encoding swaps underscores to dashes", () => {
    expect(deepImportFieldId("phase2", "boundary_scenes")).toBe("deep-import-phase2-boundary-scenes")
  })
  it("renders schema defaults when the project has no deep-import override", () => {
    document.body.innerHTML = renderDeepImportFields({})

    expect(document.getElementById(deepImportFieldId("phase0", "target_input_chars")).value).toBe("72000")
    expect(document.getElementById(deepImportFieldId("phase1c", "timeout_seconds")).value).toBe("1200")
    expect(document.getElementById(deepImportFieldId("phase1c", "decision_max_tokens")).value).toBe("")
  })
  it("preserves explicit project values instead of replacing them with defaults", () => {
    document.body.innerHTML = renderDeepImportFields({
      phase0: { target_input_chars: 88000 },
      phase1c: { timeout_seconds: null },
    })

    expect(document.getElementById(deepImportFieldId("phase0", "target_input_chars")).value).toBe("88000")
    expect(document.getElementById(deepImportFieldId("phase1c", "timeout_seconds")).value).toBe("")
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

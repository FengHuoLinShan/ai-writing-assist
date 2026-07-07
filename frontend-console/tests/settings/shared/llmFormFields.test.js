import { describe, it, expect } from "vitest"
import {
  validateLLMPayload,
  detectCreativeModeExport,
  CREATIVE_PRESETS,
} from "../../../views/settings/shared/llmFormFields.js"

describe("validateLLMPayload", () => {
  it("accepts all-null (pure inherit)", () => {
    expect(
      validateLLMPayload({
        provider_id: null, label: null, base_url: null, model: null,
        timeout: null, max_tokens: null, temperature: null, top_p: null, extra: {},
      }).ok,
    ).toBe(true)
  })
  it("rejects undefined (out-of-range numeric)", () => {
    expect(
      validateLLMPayload({
        provider_id: null, label: null, base_url: null, model: null,
        timeout: undefined, max_tokens: null, temperature: null, top_p: null, extra: {},
      }).ok,
    ).toBe(false)
  })
})

describe("detectCreativeModeExport", () => {
  it("returns creative when matching preset", () => {
    expect(detectCreativeModeExport(CREATIVE_PRESETS.creative)).toBe("creative")
  })
  it("returns custom for empty", () => {
    expect(detectCreativeModeExport({})).toBe("custom")
  })
})
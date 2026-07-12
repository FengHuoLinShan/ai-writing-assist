import { describe, it, expect } from "vitest"
import {
  SYSTEM_LLM_DEFAULTS,
  bindLLMPresetEvents,
  validateLLMPayload,
  detectCreativeModeExport,
  CREATIVE_PRESETS,
  renderLLMFormFields,
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
    expect(detectCreativeModeExport({ ...CREATIVE_PRESETS.creative, max_tokens: 7777 })).toBe("creative")
  })
  it("returns custom for empty", () => {
    expect(detectCreativeModeExport({})).toBe("custom")
  })
})

describe("LLM defaults and presets", () => {
  it("uses 12000 as the displayed system default", () => {
    expect(SYSTEM_LLM_DEFAULTS.max_tokens).toBe(12000)
    const html = renderLLMFormFields({
      values: SYSTEM_LLM_DEFAULTS,
      sourceMap: { max_tokens: { value: 12000, source: "system" } },
    })
    expect(html).toContain("默认输出上限（tokens）")
    expect(html).toContain("深度导入以外的业务 LLM 调用继承此值")
    expect(html).toContain("系统默认")
  })

  it("preset changes sampling but preserves max tokens", () => {
    document.body.innerHTML = renderLLMFormFields({ values: SYSTEM_LLM_DEFAULTS })
    bindLLMPresetEvents()
    const maxTokens = document.getElementById("llm-max-tokens")
    document.querySelector('[data-preset-id="fast"]').click()
    expect(document.getElementById("llm-temperature").value).toBe("0.6")
    expect(document.getElementById("llm-top-p").value).toBe("0.9")
    expect(maxTokens.value).toBe("12000")

    document.querySelector('[data-preset-id="custom"]').click()
    expect(document.querySelector('[data-preset-id="custom"]').classList.contains("active")).toBe(true)
    expect(document.getElementById("llm-temperature").value).toBe("0.6")
    expect(document.getElementById("llm-top-p").value).toBe("0.9")
    expect(maxTokens.value).toBe("12000")
  })
})

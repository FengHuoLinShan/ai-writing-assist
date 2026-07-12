import { describe, it, expect } from "vitest"
import {
  SYSTEM_LLM_DEFAULTS,
  bindLLMPresetEvents,
  bindLLMProviderTemplateEvents,
  bindLLMApiKeyEvents,
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
  it("toggles the newly entered API key visibility without changing its value", () => {
    document.body.innerHTML = renderLLMFormFields({
      values: { ...SYSTEM_LLM_DEFAULTS, api_key_configured: false },
    })
    const input = document.getElementById("llm-api-key")
    const toggle = document.getElementById("llm-toggle-api-key")
    input.value = "test-key-not-real"
    bindLLMApiKeyEvents()

    toggle.click()
    expect(input.type).toBe("text")
    expect(input.value).toBe("test-key-not-real")
    expect(toggle.textContent).toBe("隐藏 Key")
    expect(toggle.getAttribute("aria-pressed")).toBe("true")

    toggle.click()
    expect(input.type).toBe("password")
    expect(input.value).toBe("test-key-not-real")
    expect(toggle.textContent).toBe("显示 Key")
  })

  it("switches every common field to the selected provider template", () => {
    const templates = [
      {
        id: "deepseek", name: "DeepSeek", base_url: "https://api.deepseek.com",
        default_model: "deepseek-v4-flash", models: ["deepseek-v4-flash"],
        default_parameters: {
          timeout: 180, max_tokens: 12000, temperature: 0.3, top_p: null, extra: {},
        },
      },
      {
        id: "kimi", name: "Kimi / Moonshot", base_url: "https://api.moonshot.cn/v1",
        default_model: "kimi-k2.6", models: ["kimi-k2.6", "kimi-k2.5"],
        default_parameters: {
          timeout: 240, max_tokens: 32000, temperature: 0.6, top_p: 0.9,
          extra: { reasoning: true },
        },
      },
    ]
    document.body.innerHTML = renderLLMFormFields({
      values: { ...SYSTEM_LLM_DEFAULTS, api_key_configured: true }, templates,
    })
    bindLLMProviderTemplateEvents(templates, ["deepseek"])
    const provider = document.getElementById("llm-provider")
    provider.value = "kimi"
    provider.dispatchEvent(new Event("change"))

    expect(document.getElementById("llm-base-url").value).toBe("https://api.moonshot.cn/v1")
    expect(document.getElementById("llm-model").value).toBe("kimi-k2.6")
    expect(document.getElementById("llm-label").value).toBe("Kimi / Moonshot")
    expect(document.getElementById("llm-timeout").value).toBe("240")
    expect(document.getElementById("llm-max-tokens").value).toBe("32000")
    expect(document.getElementById("llm-temperature").value).toBe("0.6")
    expect(document.getElementById("llm-top-p").value).toBe("0.9")
    expect(document.getElementById("llm-extra").value).toContain('"reasoning": true')
    expect(document.getElementById("llm-key-status").textContent).toBe("此模板未保存")
  })

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

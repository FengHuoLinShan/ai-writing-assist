/**
 * LLM 表单纯逻辑测试 — 对应原 tests/settings/shared/llmFormFields.test.js 的行为契约。
 */
import { describe, it, expect } from "vitest"
import {
  CREATIVE_PRESETS,
  SYSTEM_LLM_DEFAULTS,
  buildLlmPayload,
  detectCreativeMode,
  formatExtra,
  llmFormFromDefaults,
  llmFormFromEffective,
  modelsForProvider,
  providerTemplatePatch,
  validateLLMPayload,
  withSystemLLMDefaults,
} from "../../../vue/views/settings/logic/llmForm.js"

describe("validateLLMPayload", () => {
  it("接受全 null（纯继承）", () => {
    expect(
      validateLLMPayload({
        provider_id: null, label: null, base_url: null, model: null,
        timeout: null, max_tokens: null, temperature: null, top_p: null, extra: {},
      }).ok,
    ).toBe(true)
  })

  it("拒绝 undefined（数值越界/非法）", () => {
    const result = validateLLMPayload({
      provider_id: null, label: null, base_url: null, model: null,
      timeout: undefined, max_tokens: null, temperature: null, top_p: null, extra: {},
    })
    expect(result.ok).toBe(false)
    expect(result.message).toContain("timeout")
  })
})

describe("detectCreativeMode", () => {
  it("匹配预设返回预设 id", () => {
    expect(detectCreativeMode({ ...CREATIVE_PRESETS.creative, max_tokens: 7777 })).toBe("creative")
    expect(detectCreativeMode({ temperature: "0.25", top_p: "0.8" })).toBe("precise")
  })

  it("空值或不匹配返回 custom", () => {
    expect(detectCreativeMode({})).toBe("custom")
    expect(detectCreativeMode({ temperature: 0.3, top_p: null })).toBe("custom")
  })
})

describe("withSystemLLMDefaults", () => {
  it("空值回退系统默认，有效值保留", () => {
    const merged = withSystemLLMDefaults({ model: "custom-model", timeout: null, base_url: "" })
    expect(merged.model).toBe("custom-model")
    expect(merged.timeout).toBe(SYSTEM_LLM_DEFAULTS.timeout)
    expect(merged.base_url).toBe(SYSTEM_LLM_DEFAULTS.base_url)
  })
})

describe("buildLlmPayload", () => {
  const baseForm = {
    provider_id: "deepseek",
    label: "  DeepSeek  ",
    base_url: " https://api.deepseek.com ",
    model: "deepseek-v4-flash",
    timeout: "180",
    max_tokens: "12000",
    temperature: "0.3",
    top_p: "",
    extraJson: '{"reasoning_effort":"high"}',
    api_key: " sk-test ",
    clear_api_key: false,
  }

  it("裁剪字符串、解析数值、解析 extra JSON", () => {
    const { payload, api_key, clear_api_key } = buildLlmPayload(baseForm)
    expect(payload.label).toBe("DeepSeek")
    expect(payload.base_url).toBe("https://api.deepseek.com")
    expect(payload.timeout).toBe(180)
    expect(payload.max_tokens).toBe(12000)
    expect(payload.temperature).toBe(0.3)
    expect(payload.top_p).toBeNull()
    expect(payload.extra).toEqual({ reasoning_effort: "high" })
    expect(api_key).toBe("sk-test")
    expect(clear_api_key).toBe(false)
  })

  it("越界数值返回 undefined，extra 非法 JSON 返回 undefined", () => {
    const { payload } = buildLlmPayload({ ...baseForm, timeout: "99999", extraJson: "{bad" })
    expect(payload.timeout).toBeUndefined()
    expect(payload.extra).toBeUndefined()
    expect(validateLLMPayload(payload).ok).toBe(false)
  })

  it("extra 为数组或空字符串的语义与原实现一致", () => {
    expect(buildLlmPayload({ ...baseForm, extraJson: "[1,2]" }).payload.extra).toBeUndefined()
    expect(buildLlmPayload({ ...baseForm, extraJson: "" }).payload.extra).toEqual({})
  })
})

describe("providerTemplatePatch / modelsForProvider", () => {
  const templates = [
    {
      id: "deepseek",
      name: "DeepSeek",
      base_url: "https://api.deepseek.com",
      default_model: "deepseek-v4-flash",
      models: ["deepseek-v4-flash", "deepseek-v4-pro"],
      default_parameters: { timeout: 180, max_tokens: 12000, temperature: 0.3, top_p: null, extra: { reasoning_effort: "high" } },
    },
  ]

  it("返回模板联动字段，extra 序列化为多行 JSON", () => {
    const patch = providerTemplatePatch(templates, "deepseek")
    expect(patch.base_url).toBe("https://api.deepseek.com")
    expect(patch.model).toBe("deepseek-v4-flash")
    expect(patch.timeout).toBe("180")
    expect(patch.top_p).toBe("")
    expect(patch.extraJson).toBe(JSON.stringify({ reasoning_effort: "high" }, null, 2))
  })

  it("模板不存在时返回 null", () => {
    expect(providerTemplatePatch(templates, "missing")).toBeNull()
  })

  it("modelsForProvider 返回模型列表", () => {
    expect(modelsForProvider(templates, "deepseek")).toEqual(["deepseek-v4-flash", "deepseek-v4-pro"])
    expect(modelsForProvider(templates, "missing")).toEqual([])
  })
})

describe("表单初值构造", () => {
  it("llmFormFromEffective 提取 value 并字符串化", () => {
    const form = llmFormFromEffective({
      provider_id: { value: "deepseek", source: "global" },
      timeout: { value: 200, source: "project" },
      top_p: { value: null, source: "unset" },
      extra: { value: { a: 1 }, source: "project" },
    })
    expect(form.provider_id).toBe("deepseek")
    expect(form.timeout).toBe("200")
    expect(form.top_p).toBe("")
    expect(form.extraJson).toBe(JSON.stringify({ a: 1 }, null, 2))
    expect(form.api_key).toBe("")
    expect(form.clear_api_key).toBe(false)
  })

  it("llmFormFromDefaults 套用系统默认回退", () => {
    const form = llmFormFromDefaults({ model: "x" })
    expect(form.model).toBe("x")
    expect(form.base_url).toBe(SYSTEM_LLM_DEFAULTS.base_url)
    expect(form.timeout).toBe(String(SYSTEM_LLM_DEFAULTS.timeout))
  })

  it("formatExtra 空对象返回空串", () => {
    expect(formatExtra({})).toBe("")
    expect(formatExtra(null)).toBe("")
  })
})

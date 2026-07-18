/**
 * LLM 设置表单纯逻辑 — 从 views/settings/shared/llmFormFields.js 移植。
 * 与原实现的行为差异仅在于数据来源：原实现从 DOM 读取，这里从响应式表单
 * 对象读取；校验语义（null=留空继承，undefined=非法）保持不变。
 */

export const CREATIVE_PRESETS = {
  creative: { label: "灵感创作", temperature: 0.9, top_p: 0.95 },
  precise: { label: "精修校对", temperature: 0.25, top_p: 0.8 },
  fast: { label: "快速生成", temperature: 0.6, top_p: 0.9 },
  custom: { label: "自定义" },
}

export const SYSTEM_LLM_DEFAULTS = {
  provider_id: "deepseek",
  label: "DeepSeek",
  base_url: "https://api.deepseek.com",
  model: "deepseek-v4-flash",
  timeout: 180,
  max_tokens: 12000,
  temperature: 0.3,
  top_p: null,
  extra: {},
}

/** 与系统默认合并展示（null/undefined/空字符串回退到系统默认）。 */
export function withSystemLLMDefaults(values) {
  const merged = { ...SYSTEM_LLM_DEFAULTS }
  for (const [key, value] of Object.entries(values || {})) {
    if (value !== null && value !== undefined && value !== "") {
      merged[key] = value
    }
  }
  return merged
}

export function detectCreativeMode(values) {
  for (const [id, preset] of Object.entries(CREATIVE_PRESETS)) {
    if (id === "custom") continue
    if (Number(values?.temperature) === preset.temperature && Number(values?.top_p) === preset.top_p) {
      return id
    }
  }
  return "custom"
}

export function formatExtra(extra) {
  if (!extra || typeof extra !== "object" || Object.keys(extra).length === 0) return ""
  return JSON.stringify(extra, null, 2)
}

/**
 * 由 effective-llm-settings 响应构造表单初值（字符串形态，供 v-model）。
 * effective 每项为 { value, source }。
 */
export function llmFormFromEffective(effectiveData) {
  const eff = effectiveData || {}
  const raw = (field) => {
    const value = eff[field]?.value
    return value === null || value === undefined ? "" : String(value)
  }
  return {
    provider_id: eff.provider_id?.value || "",
    label: eff.label?.value || "",
    base_url: eff.base_url?.value || "",
    model: eff.model?.value || "",
    timeout: raw("timeout"),
    max_tokens: raw("max_tokens"),
    temperature: raw("temperature"),
    top_p: raw("top_p"),
    extraJson: formatExtra(eff.extra?.value || {}),
    api_key: "",
    clear_api_key: false,
  }
}

/** 由全局默认对象（withSystemLLMDefaults 合并后）构造表单初值。 */
export function llmFormFromDefaults(defaults) {
  const merged = withSystemLLMDefaults(defaults)
  return {
    provider_id: merged.provider_id || "",
    label: merged.label || "",
    base_url: merged.base_url || "",
    model: merged.model || "",
    timeout: merged.timeout === null || merged.timeout === undefined ? "" : String(merged.timeout),
    max_tokens: merged.max_tokens === null || merged.max_tokens === undefined ? "" : String(merged.max_tokens),
    temperature: merged.temperature === null || merged.temperature === undefined ? "" : String(merged.temperature),
    top_p: merged.top_p === null || merged.top_p === undefined ? "" : String(merged.top_p),
    extraJson: formatExtra(merged.extra),
    api_key: "",
    clear_api_key: false,
  }
}

function parseIntStrict(raw, min, max) {
  const text = String(raw ?? "").trim()
  if (!text) return null
  const value = Number(text)
  if (!Number.isInteger(value) || value < min || value > max) return undefined
  return value
}

function parseFloatStrict(raw, min, max) {
  const text = String(raw ?? "").trim()
  if (!text) return null
  const value = Number(text)
  if (!Number.isFinite(value) || value < min || value > max) return undefined
  return value
}

function parseExtraJson(raw) {
  const text = String(raw ?? "").trim()
  if (!text) return {}
  try {
    const parsed = JSON.parse(text)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") return undefined
    return parsed
  } catch {
    return undefined
  }
}

/** 对应原 readLLMFormFields：从响应式表单对象产出 payload 与 Key 操作。 */
export function buildLlmPayload(form) {
  const payload = {
    provider_id: form.provider_id || null,
    label: String(form.label ?? "").trim() || null,
    base_url: String(form.base_url ?? "").trim() || null,
    model: String(form.model ?? "").trim() || null,
    timeout: parseIntStrict(form.timeout, 1, 3600),
    max_tokens: parseIntStrict(form.max_tokens, 1, 200000),
    temperature: parseFloatStrict(form.temperature, 0, 2),
    top_p: parseFloatStrict(form.top_p, 0, 1),
    extra: parseExtraJson(form.extraJson),
  }
  return {
    payload,
    api_key: String(form.api_key ?? "").trim(),
    clear_api_key: Boolean(form.clear_api_key),
  }
}

export function validateLLMPayload(payload) {
  for (const [key, value] of Object.entries(payload)) {
    if (value === undefined) return { ok: false, message: `${key} 字段非法或超范围` }
  }
  return { ok: true }
}

/**
 * 供应商模板切换时的联动字段（对应原 bindLLMProviderTemplateEvents 的 change 分支）。
 * 返回表单补丁；调用方负责写入响应式表单并清空 api_key/clear_api_key。
 */
export function providerTemplatePatch(templates, providerId) {
  const template = (templates || []).find((item) => item.id === providerId)
  if (!template) return null
  const parameters = template.default_parameters || {}
  const asText = (value) => (value === null || value === undefined ? "" : String(value))
  return {
    base_url: template.base_url || "",
    model: template.default_model || "",
    label: template.name || "",
    timeout: asText(parameters.timeout),
    max_tokens: asText(parameters.max_tokens),
    temperature: asText(parameters.temperature),
    top_p: asText(parameters.top_p),
    extraJson: parameters.extra && Object.keys(parameters.extra).length
      ? JSON.stringify(parameters.extra, null, 2)
      : "",
  }
}

export function modelsForProvider(templates, providerId) {
  return (templates || []).find((item) => item.id === providerId)?.models || []
}

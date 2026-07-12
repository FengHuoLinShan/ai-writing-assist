import { renderSourceLabel } from "./fieldSourceLabel.js"

const CREATIVE_PRESETS = {
  creative: { label: "灵感创作", temperature: 0.9, top_p: 0.95 },
  precise: { label: "精修校对", temperature: 0.25, top_p: 0.8 },
  fast: { label: "快速生成", temperature: 0.6, top_p: 0.9 },
  custom: { label: "自定义" },
}

export { CREATIVE_PRESETS }

const SYSTEM_LLM_DEFAULTS = {
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

export { SYSTEM_LLM_DEFAULTS }

export function renderLLMFormFields({ values, templates, sourceMap = {}, withApiKey = true } = {}) {
  const v = values || {}
  const providerOptions = (templates || []).length
    ? (templates || []).map((t) => `<option value="${t.id}" ${t.id === (v.provider_id || "") ? "selected" : ""}>${t.name}</option>`).join("")
    : `<option value="deepseek" selected>DeepSeek</option>`
  const modelOptions = ((templates?.find((t) => t.id === (v.provider_id || ""))?.models) || []).map((m) => `<option value="${m}"></option>`).join("")
  const creativeMode = detectCreativeMode(v)
  return `
    <div class="llm-main-form">
      ${withApiKey ? "" : "<p class='llm-global-hint'>全局默认不存 API Key；Key 仅项目级。</p>"}
      <div class="form-row">
        <div class="form-group">
          <label for="llm-provider">供应商模板</label>
          <select class="form-input" id="llm-provider" ${(templates || []).length ? "" : "disabled"}>
            ${providerOptions}
          </select>
          ${sourceHtml(sourceMap.provider_id)}
        </div>
        ${withApiKey ? renderKeyBlock(v.api_key_configured, v) : ""}
      </div>
      <div class="form-group">
        <label for="llm-base-url">Base URL</label>
        <input class="form-input" id="llm-base-url" value="${v.base_url || ""}" placeholder="https://api.example.com/v1" />
        ${sourceHtml(sourceMap.base_url)}
      </div>
      <div class="form-row">
        <div class="form-group">
          <label for="llm-model">模型</label>
          <input class="form-input" id="llm-model" list="llm-model-options" value="${v.model || ""}" placeholder="输入或选择模型名" />
          <datalist id="llm-model-options">${modelOptions}</datalist>
          <small id="llm-model-cost-hint" class="settings-section-hint" ${v.model === "deepseek-v4-pro" ? "" : "hidden"}>deepseek-v4-pro 预计约为 Flash 的 8 倍耗时；高质量开关不会自动切换模型。</small>
          ${sourceHtml(sourceMap.model)}
        </div>
        <div class="form-group">
          <label for="llm-label">显示名称</label>
          <input class="form-input" id="llm-label" value="${v.label || ""}" placeholder="可选" />
          ${sourceHtml(sourceMap.label)}
        </div>
      </div>
      <div class="llm-advanced-panel">
        <div class="form-group">
          <label>创作模式</label>
          <div class="llm-preset-list">
            ${Object.entries(CREATIVE_PRESETS).map(([id, p]) => `
              <button class="llm-preset-item ${creativeMode === id ? "active" : ""}" type="button" data-preset-id="${id}">
                <span>${p.label}</span>
                <small>${id === "custom" ? "保留当前参数" : `T ${p.temperature} · P ${p.top_p}`}</small>
              </button>`).join("")}
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label for="llm-timeout">超时（秒）</label>
            <input class="form-input" id="llm-timeout" type="number" min="1" max="3600" value="${v.timeout ?? ""}" placeholder="180" />
            ${sourceHtml(sourceMap.timeout)}
          </div>
          <div class="form-group">
            <label for="llm-max-tokens">默认输出上限（tokens）</label>
            <input class="form-input" id="llm-max-tokens" type="number" min="1" max="200000" value="${v.max_tokens ?? ""}" placeholder="12000" />
            <small class="settings-section-hint">深度导入以外的业务 LLM 调用继承此值。</small>
            ${sourceHtml(sourceMap.max_tokens)}
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label for="llm-temperature">Temperature</label>
            <input class="form-input" id="llm-temperature" type="number" min="0" max="2" step="0.1" value="${v.temperature ?? ""}" placeholder="0.3" />
            ${sourceHtml(sourceMap.temperature)}
          </div>
          <div class="form-group">
            <label for="llm-top-p">Top P</label>
            <input class="form-input" id="llm-top-p" type="number" min="0" max="1" step="0.05" value="${v.top_p ?? ""}" placeholder="可选" />
            ${sourceHtml(sourceMap.top_p)}
          </div>
        </div>
        <div class="form-group">
          <label for="llm-extra">供应商扩展参数（JSON）</label>
          <textarea class="form-input llm-extra-json" id="llm-extra" rows="4" placeholder='{"reasoning_effort":"high"}'>${formatExtra(v.extra)}</textarea>
          ${sourceHtml(sourceMap.extra)}
        </div>
      </div>
    </div>
  `
}

function renderKeyBlock(configured, v) {
  return `
    <div class="form-group">
      <label>API Key</label>
      <div class="settings-key-row">
        <input class="form-input" id="llm-api-key" type="password" autocomplete="off" placeholder="留空保留已保存密钥" />
        <button class="btn btn-sm" id="llm-toggle-api-key" type="button">显示 Key</button>
        <label class="llm-clear-key">
          <input id="llm-clear-api-key" type="checkbox" />
          清除
        </label>
      </div>
      <div id="llm-key-status" class="settings-key-status ${configured ? "success" : "muted"}">${configured ? "已保存" : "未保存"}</div>
      ${configured && v && (v.provider_id_source === "global" || v.base_url_source === "global" || v.provider_id_source === "system" || v.base_url_source === "system") ? "<p class='settings-key-mismatch-warning'>当前供应商/BaseURL 来自全局或系统默认，请确认 Key 与该供应商匹配</p>" : ""}
    </div>
  `
}

function sourceHtml(src) {
  if (!src) return ""
  return `<div class="settings-field-source">${renderSourceLabel(src)}</div>`
}

function detectCreativeMode(values) {
  for (const [id, p] of Object.entries(CREATIVE_PRESETS)) {
    if (id === "custom") continue
    if (Number(values?.temperature) === p.temperature && Number(values?.top_p) === p.top_p) {
      return id
    }
  }
  return "custom"
}

export function detectCreativeModeExport(values) {
  return detectCreativeMode(values)
}

export function bindLLMPresetEvents() {
  document.querySelectorAll(".llm-preset-item[data-preset-id]").forEach((button) => {
    button.addEventListener("click", (event) => {
      const selected = event.currentTarget
      const preset = CREATIVE_PRESETS[selected.dataset.presetId]
      if (!preset) return
      if (selected.dataset.presetId !== "custom") {
        const temperature = document.getElementById("llm-temperature")
        const topP = document.getElementById("llm-top-p")
        if (temperature) temperature.value = String(preset.temperature)
        if (topP) topP.value = String(preset.top_p)
      }
      document.querySelectorAll(".llm-preset-item").forEach((item) => {
        item.classList.toggle("active", item === selected)
      })
    })
  })
}

export function bindLLMApiKeyEvents() {
  const input = document.getElementById("llm-api-key")
  const toggle = document.getElementById("llm-toggle-api-key")
  if (!input || !toggle) return
  toggle.addEventListener("click", () => {
    const showing = input.type === "text"
    input.type = showing ? "password" : "text"
    toggle.textContent = showing ? "显示 Key" : "隐藏 Key"
    toggle.setAttribute("aria-pressed", String(!showing))
  })
}

export function bindLLMProviderTemplateEvents(templates = [], configuredProviders = []) {
  const provider = document.getElementById("llm-provider")
  if (!provider) return
  const configured = new Set(configuredProviders || [])
  const modelInput = document.getElementById("llm-model")
  const updateModelHint = () => {
    const hint = document.getElementById("llm-model-cost-hint")
    if (hint) hint.hidden = modelInput?.value.trim() !== "deepseek-v4-pro"
  }
  modelInput?.addEventListener("input", updateModelHint)
  provider.addEventListener("change", () => {
    const template = templates.find((item) => item.id === provider.value)
    if (!template) return
    setFieldValue("llm-base-url", template.base_url || "")
    setFieldValue("llm-model", template.default_model || "")
    updateModelHint()
    setFieldValue("llm-label", template.name || "")
    const parameters = template.default_parameters || {}
    setFieldValue("llm-timeout", parameters.timeout)
    setFieldValue("llm-max-tokens", parameters.max_tokens)
    setFieldValue("llm-temperature", parameters.temperature)
    setFieldValue("llm-top-p", parameters.top_p)
    setFieldValue(
      "llm-extra",
      parameters.extra && Object.keys(parameters.extra).length
        ? JSON.stringify(parameters.extra, null, 2)
        : "",
    )
    setFieldValue("llm-api-key", "")
    const clearKey = document.getElementById("llm-clear-api-key")
    if (clearKey) clearKey.checked = false
    const hasKey = configured.has(template.id)
    const status = document.getElementById("llm-key-status")
    if (status) {
      status.textContent = hasKey ? "已保存到此模板" : "此模板未保存"
      status.classList.toggle("success", hasKey)
      status.classList.toggle("muted", !hasKey)
    }
    const datalist = document.getElementById("llm-model-options")
    if (datalist) {
      datalist.innerHTML = (template.models || [])
        .map((model) => `<option value="${model}"></option>`)
        .join("")
    }
  })
}

function setFieldValue(id, value) {
  const field = document.getElementById(id)
  if (field) field.value = value == null ? "" : String(value)
}

function formatExtra(extra) {
  if (!extra || typeof extra !== "object" || Object.keys(extra).length === 0) return ""
  return JSON.stringify(extra, null, 2)
}

export function readLLMFormFields() {
  const payload = {
    provider_id: document.getElementById("llm-provider")?.value || null,
    label: document.getElementById("llm-label")?.value.trim() || null,
    base_url: document.getElementById("llm-base-url")?.value.trim() || null,
    model: document.getElementById("llm-model")?.value.trim() || null,
    timeout: parseIntOptional("llm-timeout", 1, 3600),
    max_tokens: parseIntOptional("llm-max-tokens", 1, 200000),
    temperature: parseFloatOptional("llm-temperature", 0, 2),
    top_p: parseFloatOptional("llm-top-p", 0, 1),
    extra: readExtra(),
  }
  const apiKey = document.getElementById("llm-api-key")?.value.trim() || ""
  const clearKey = Boolean(document.getElementById("llm-clear-api-key")?.checked)
  return { payload, api_key: apiKey, clear_api_key: clearKey }
}

function parseIntOptional(id, min, max) {
  const raw = document.getElementById(id)?.value.trim() || ""
  if (!raw) return null
  const v = Number(raw)
  if (!Number.isInteger(v) || v < min || v > max) return undefined  // undefined 表非法
  return v
}

function parseFloatOptional(id, min, max) {
  const raw = document.getElementById(id)?.value.trim() || ""
  if (!raw) return null
  const v = Number(raw)
  if (!Number.isFinite(v) || v < min || v > max) return undefined
  return v
}

function readExtra() {
  const raw = document.getElementById("llm-extra")?.value.trim() || ""
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") return undefined
    return parsed
  } catch {
    return undefined
  }
}

export function validateLLMPayload(payload) {
  for (const [k, v] of Object.entries(payload)) {
    if (v === undefined) return { ok: false, message: `${k} 字段非法或超范围` }
  }
  return { ok: true }
}

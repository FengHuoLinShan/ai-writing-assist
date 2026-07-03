/**
 * Project-level LLM settings view.
 */

const llmSettingsView = {
  _templates: [],
  _settings: {},
  _authorPreferences: {},
  _creativeMode: "custom",

  _creativePresets: {
    creative: { label: "灵感创作", temperature: 0.9, top_p: 0.95, max_tokens: 8192 },
    precise: { label: "精修校对", temperature: 0.25, top_p: 0.8, max_tokens: 4096 },
    fast: { label: "快速草稿", temperature: 0.6, top_p: 0.9, max_tokens: 2048 },
    custom: { label: "自定义" },
  },

  async onEnter() {
    if (!state.currentProjectId) {
      this._templates = []
      this._settings = {}
      return
    }
    try {
      const [templateResp, settings] = await Promise.all([
        api.projects.listLlmProviderTemplates(),
        api.projects.getLlmSettings(state.currentProjectId),
      ])
      this._templates = templateResp.items || []
      this._settings = settings || {}
      this._authorPreferences = this._loadAuthorPreferences()
      this._creativeMode = this._detectCreativeMode(this._settings)
    } catch (err) {
      console.error("加载 LLM 配置失败:", err)
      this._templates = []
      this._settings = {}
      toast("加载 LLM 配置失败", "error")
    }
  },

  async render() {
    if (!state.currentProjectId) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#9881;</div>
          <p>请先选择项目</p>
        </div>
      `
    }

    const settings = this._settings || {}
    const providerId = settings.provider_id || this._templates[0]?.id || "openai-compatible"
    const selectedTemplate = this._findTemplate(providerId) || this._templates[0] || {}
    const modelOptions = this._renderModelOptions(selectedTemplate, settings.model)
    const parameters = this._effectiveParameters(settings, selectedTemplate)
    const preferences = this._loadAuthorPreferences()
    const creativeMode = this._creativeMode || this._detectCreativeMode(parameters)
    const statusText = settings.api_key_configured ? "已保存" : "未保存"
    const statusClass = settings.api_key_configured ? "success" : "muted"

    queueMicrotask(() => this.bindEvents())

    return `
      <div class="llm-settings-view">
        <div class="section-header">
          <div>
            <h2>LLM 设置</h2>
            <p class="section-subtitle">${esc(state.currentProject?.title || "当前项目")}</p>
          </div>
          <button class="btn btn-primary" id="llm-save-btn">保存配置</button>
        </div>

        <div class="settings-panel">
          <div class="form-row">
            <div class="form-group">
              <label for="llm-provider">供应商模板</label>
              <select class="form-input" id="llm-provider">
                ${this._templates.map((template) => `
                  <option value="${esc(template.id)}" ${template.id === providerId ? "selected" : ""}>
                    ${esc(template.name)}
                  </option>
                `).join("")}
              </select>
            </div>
            <div class="form-group">
              <label>API Key</label>
              <div class="llm-key-row">
                <input class="form-input" id="llm-api-key" type="password" autocomplete="off" placeholder="留空保留已保存密钥" />
                <button class="btn btn-sm" id="llm-toggle-api-key" type="button">显示 Key</button>
                <label class="llm-clear-key">
                  <input id="llm-clear-api-key" type="checkbox" />
                  清除
                </label>
              </div>
              <div class="llm-status ${esc(statusClass)}">${esc(statusText)}</div>
            </div>
          </div>

          <div class="form-group">
            <label for="llm-base-url">Base URL</label>
            <input class="form-input" id="llm-base-url" value="${esc(settings.base_url || selectedTemplate.base_url || "")}" placeholder="https://api.example.com/v1" />
          </div>

          <div class="form-row">
            <div class="form-group">
              <label for="llm-model">模型</label>
              <input class="form-input" id="llm-model" list="llm-model-options" value="${esc(settings.model || selectedTemplate.default_model || "")}" placeholder="输入或选择模型名" />
              <datalist id="llm-model-options">${modelOptions}</datalist>
            </div>
            <div class="form-group">
              <label for="llm-label">显示名称</label>
              <input class="form-input" id="llm-label" value="${esc(settings.label || selectedTemplate.name || "")}" placeholder="可选" />
            </div>
          </div>

          <div class="llm-advanced-panel">
            <div class="form-group">
              <label>创作模式</label>
              <div class="llm-preset-list">
                ${Object.entries(this._creativePresets).map(([id, preset]) => `
                  <button class="llm-preset-item ${creativeMode === id ? "active" : ""}" type="button" data-preset-id="${esc(id)}">
                    <span>${esc(preset.label)}</span>
                    <small>${id === "custom" ? "保留当前参数" : `T ${preset.temperature} · P ${preset.top_p} · ${preset.max_tokens} tokens`}</small>
                  </button>
                `).join("")}
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label for="llm-timeout">超时（秒）</label>
                <input class="form-input" id="llm-timeout" type="number" min="1" max="3600" value="${esc(this._formatOptionalNumber(parameters.timeout))}" placeholder="180" />
              </div>
              <div class="form-group">
                <label for="llm-max-tokens">Max tokens</label>
                <input class="form-input" id="llm-max-tokens" type="number" min="1" max="200000" value="${esc(this._formatOptionalNumber(parameters.max_tokens))}" placeholder="4096" />
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label for="llm-temperature">Temperature</label>
                <input class="form-input" id="llm-temperature" type="number" min="0" max="2" step="0.1" value="${esc(this._formatOptionalNumber(parameters.temperature))}" placeholder="0.3" />
              </div>
              <div class="form-group">
                <label for="llm-top-p">Top P</label>
                <input class="form-input" id="llm-top-p" type="number" min="0" max="1" step="0.05" value="${esc(this._formatOptionalNumber(parameters.top_p))}" placeholder="可选" />
              </div>
            </div>
            <div class="form-group">
              <label for="llm-extra">供应商扩展参数（JSON）</label>
              <textarea class="form-input llm-extra-json" id="llm-extra" rows="4" placeholder='{"reasoning_effort":"high"}'>${esc(this._formatExtraParameters(parameters.extra))}</textarea>
            </div>
          </div>

          <div class="llm-template-list">
            ${this._templates.map((template) => this._renderTemplateSummary(template, providerId)).join("")}
          </div>

          <div class="llm-author-preferences">
            <h3>作者偏好</h3>
            <div class="form-row">
              <div class="form-group">
                <label for="author-daily-goal">日更目标（字）</label>
                <input class="form-input" id="author-daily-goal" type="number" min="0" max="100000" value="${esc(preferences.dailyGoal || "")}" placeholder="6000" />
              </div>
              <div class="form-group">
                <label for="author-editor-font">编辑器字体</label>
                <select class="form-input" id="author-editor-font">
                  <option value="system" ${preferences.editorFont === "system" ? "selected" : ""}>系统默认</option>
                  <option value="serif" ${preferences.editorFont === "serif" ? "selected" : ""}>宋体/衬线</option>
                  <option value="sans" ${preferences.editorFont === "sans" ? "selected" : ""}>黑体/无衬线</option>
                  <option value="mono" ${preferences.editorFont === "mono" ? "selected" : ""}>等宽</option>
                </select>
              </div>
              <div class="form-group llm-focus-default">
                <label>
                  <input id="author-default-focus" type="checkbox" ${preferences.defaultFocusMode ? "checked" : ""} />
                  默认专注模式
                </label>
              </div>
            </div>
            <button class="btn btn-sm" id="author-preferences-save" type="button">保存作者偏好</button>
          </div>
        </div>
      </div>
    `
  },

  bindEvents() {
    document.getElementById("llm-provider")?.addEventListener("change", (event) => {
      this.applyTemplate(event.target.value)
    })
    document.getElementById("llm-save-btn")?.addEventListener("click", () => {
      this.save()
    })
    document.getElementById("llm-toggle-api-key")?.addEventListener("click", () => {
      this.toggleApiKeyVisibility()
    })
    document.querySelectorAll(".llm-preset-item[data-preset-id]").forEach((item) => {
      item.addEventListener("click", () => {
        this.applyCreativePreset(item.dataset.presetId)
      })
    })
    document.getElementById("author-preferences-save")?.addEventListener("click", () => {
      this.saveAuthorPreferences()
    })
    document.querySelectorAll(".llm-template-item[data-template-id]").forEach((item) => {
      item.addEventListener("click", () => {
        this.applyTemplate(item.dataset.templateId)
      })
    })
  },

  toggleApiKeyVisibility() {
    const input = document.getElementById("llm-api-key")
    const button = document.getElementById("llm-toggle-api-key")
    if (!input || !button) return
    const visible = input.type === "text"
    input.type = visible ? "password" : "text"
    button.textContent = visible ? "显示 Key" : "隐藏 Key"
  },

  applyTemplate(templateId) {
    const template = this._findTemplate(templateId)
    if (!template) return
    const baseUrl = document.getElementById("llm-base-url")
    const model = document.getElementById("llm-model")
    const label = document.getElementById("llm-label")
    const datalist = document.getElementById("llm-model-options")
    const provider = document.getElementById("llm-provider")
    const params = template.default_parameters || {}

    if (provider) provider.value = template.id
    if (baseUrl) baseUrl.value = template.base_url || ""
    if (model) model.value = template.default_model || ""
    if (label) label.value = template.name || ""
    this._setInputValue("llm-timeout", params.timeout)
    this._setInputValue("llm-max-tokens", params.max_tokens)
    this._setInputValue("llm-temperature", params.temperature)
    this._setInputValue("llm-top-p", params.top_p)
    this._setInputValue("llm-extra", this._formatExtraParameters(params.extra))
    this._creativeMode = this._detectCreativeMode(params)
    this._syncPresetActiveState()
    if (datalist) {
      datalist.innerHTML = (template.models || [])
        .map((item) => `<option value="${esc(item)}"></option>`)
        .join("")
    }
  },

  applyCreativePreset(presetId) {
    const preset = this._creativePresets[presetId]
    if (!preset) return
    this._creativeMode = presetId
    if (presetId !== "custom") {
      this._setInputValue("llm-temperature", preset.temperature)
      this._setInputValue("llm-top-p", preset.top_p)
      this._setInputValue("llm-max-tokens", preset.max_tokens)
    }
    this._syncPresetActiveState()
  },

  saveAuthorPreferences() {
    const dailyGoalRaw = document.getElementById("author-daily-goal")?.value.trim() || ""
    const dailyGoal = dailyGoalRaw ? Number(dailyGoalRaw) : null
    if (dailyGoalRaw && (!Number.isInteger(dailyGoal) || dailyGoal < 0 || dailyGoal > 100000)) {
      toast("日更目标必须是 0-100000 的整数", "warning")
      return
    }
    const preferences = {
      dailyGoal,
      editorFont: document.getElementById("author-editor-font")?.value || "system",
      defaultFocusMode: Boolean(document.getElementById("author-default-focus")?.checked),
    }
    this._authorPreferences = preferences
    localStorage.setItem(this._authorPreferencesKey(), JSON.stringify(preferences))
    if (dailyGoal != null) localStorage.setItem("novel_daily_goal", String(dailyGoal))
    localStorage.setItem("novel_focus_default", preferences.defaultFocusMode ? "1" : "0")
    localStorage.setItem("novel_editor_font", preferences.editorFont)
    toast("作者偏好已保存", "success")
  },

  _authorPreferencesKey() {
    return `novel_author_preferences:${state.currentProjectId || "global"}`
  },

  _loadAuthorPreferences() {
    try {
      const parsed = JSON.parse(localStorage.getItem(this._authorPreferencesKey()) || "{}")
      return {
        dailyGoal: parsed.dailyGoal ?? "",
        editorFont: parsed.editorFont || "system",
        defaultFocusMode: Boolean(parsed.defaultFocusMode),
      }
    } catch {
      return { dailyGoal: "", editorFont: "system", defaultFocusMode: false }
    }
  },

  _detectCreativeMode(parameters) {
    for (const [id, preset] of Object.entries(this._creativePresets)) {
      if (id === "custom") continue
      if (
        Number(parameters?.temperature) === preset.temperature
        && Number(parameters?.top_p) === preset.top_p
        && Number(parameters?.max_tokens) === preset.max_tokens
      ) {
        return id
      }
    }
    return "custom"
  },

  _syncPresetActiveState() {
    document.querySelectorAll(".llm-preset-item[data-preset-id]").forEach((item) => {
      item.classList.toggle("active", item.dataset.presetId === this._creativeMode)
    })
  },

  async save() {
    const projectId = state.currentProjectId
    if (!projectId) {
      toast("请先选择项目", "warning")
      return
    }

    const providerId = document.getElementById("llm-provider")?.value || "openai-compatible"
    const template = this._findTemplate(providerId)
    const timeout = this._readOptionalInt("llm-timeout", "超时", 1, 3600)
    if (!timeout.ok) return
    const maxTokens = this._readOptionalInt("llm-max-tokens", "Max tokens", 1, 200000)
    if (!maxTokens.ok) return
    const temperature = this._readOptionalFloat("llm-temperature", "Temperature", 0, 2)
    if (!temperature.ok) return
    const topP = this._readOptionalFloat("llm-top-p", "Top P", 0, 1)
    if (!topP.ok) return
    const extra = this._readExtraParameters()
    if (!extra.ok) return

    const payload = {
      provider_id: providerId,
      label: document.getElementById("llm-label")?.value.trim() || template?.name || "",
      base_url: document.getElementById("llm-base-url")?.value.trim() || "",
      model: document.getElementById("llm-model")?.value.trim() || "",
      timeout: timeout.value,
      max_tokens: maxTokens.value,
      temperature: temperature.value,
      top_p: topP.value,
      extra: extra.value,
      api_key: document.getElementById("llm-api-key")?.value.trim() || "",
      clear_api_key: Boolean(document.getElementById("llm-clear-api-key")?.checked),
    }

    if (!payload.base_url || !payload.model) {
      toast("请填写 Base URL 和模型名", "warning")
      return
    }

    try {
      this._settings = await api.projects.updateLlmSettings(projectId, payload)
      const apiKeyInput = document.getElementById("llm-api-key")
      const clearKeyInput = document.getElementById("llm-clear-api-key")
      if (apiKeyInput) apiKeyInput.value = ""
      if (clearKeyInput) clearKeyInput.checked = false
      toast("LLM 配置已保存", "success")
      await router.refresh()
    } catch (err) {
      console.error("保存 LLM 配置失败:", err)
      toast(err.message || "保存 LLM 配置失败", "error")
    }
  },

  _findTemplate(templateId) {
    return this._templates.find((template) => template.id === templateId)
  },

  _renderModelOptions(template, currentModel) {
    const models = new Set(template?.models || [])
    if (currentModel) models.add(currentModel)
    return [...models].map((model) => `<option value="${esc(model)}"></option>`).join("")
  },

  _effectiveParameters(settings, template) {
    const defaults = template?.default_parameters || {}
    return {
      timeout: this._settingOrDefault(settings, defaults, "timeout"),
      max_tokens: this._settingOrDefault(settings, defaults, "max_tokens"),
      temperature: this._settingOrDefault(settings, defaults, "temperature"),
      top_p: this._settingOrDefault(settings, defaults, "top_p"),
      extra: settings.extra || defaults.extra || {},
    }
  },

  _settingOrDefault(settings, defaults, key) {
    const value = settings?.[key]
    return value === undefined || value === null ? defaults?.[key] : value
  },

  _formatOptionalNumber(value) {
    return value === undefined || value === null ? "" : String(value)
  },

  _formatExtraParameters(value) {
    if (!value || typeof value !== "object" || Object.keys(value).length === 0) {
      return ""
    }
    return JSON.stringify(value, null, 2)
  },

  _setInputValue(id, value) {
    const input = document.getElementById(id)
    if (!input) return
    input.value = value === undefined || value === null ? "" : String(value)
  },

  _readOptionalInt(id, label, min, max) {
    const raw = document.getElementById(id)?.value.trim() || ""
    if (!raw) return { ok: true, value: null }
    const value = Number(raw)
    if (!Number.isInteger(value) || value < min || value > max) {
      toast(`${label} 必须是 ${min}-${max} 的整数`, "warning")
      return { ok: false, value: null }
    }
    return { ok: true, value }
  },

  _readOptionalFloat(id, label, min, max) {
    const raw = document.getElementById(id)?.value.trim() || ""
    if (!raw) return { ok: true, value: null }
    const value = Number(raw)
    if (!Number.isFinite(value) || value < min || value > max) {
      toast(`${label} 必须是 ${min}-${max} 的数字`, "warning")
      return { ok: false, value: null }
    }
    return { ok: true, value }
  },

  _readExtraParameters() {
    const raw = document.getElementById("llm-extra")?.value.trim() || ""
    if (!raw) return { ok: true, value: {} }
    try {
      const value = JSON.parse(raw)
      if (!value || Array.isArray(value) || typeof value !== "object") {
        toast("供应商扩展参数必须是 JSON object", "warning")
        return { ok: false, value: {} }
      }
      return { ok: true, value }
    } catch (_err) {
      toast("供应商扩展参数不是合法 JSON", "warning")
      return { ok: false, value: {} }
    }
  },

  _renderTemplateSummary(template, activeId) {
    const active = template.id === activeId ? " active" : ""
    const model = template.default_model || "自定义模型"
    const baseUrl = template.base_url || "手动填写"
    return `
      <button class="llm-template-item${active}" type="button" data-template-id="${esc(template.id)}">
        <span>${esc(template.name)}</span>
        <small>${esc(template.category)} · ${esc(model)} · ${esc(baseUrl)}</small>
      </button>
    `
  },
}

if (typeof router !== "undefined") {
  router.registerView("llm", llmSettingsView)
}

if (typeof window !== "undefined") {
  window.llmSettingsView = llmSettingsView
}

export default llmSettingsView

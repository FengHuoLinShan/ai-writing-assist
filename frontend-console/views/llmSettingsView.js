/**
 * Project-level LLM settings view.
 */

const llmSettingsView = {
  _templates: [],
  _settings: {},

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
          <button class="btn primary" id="llm-save-btn">保存配置</button>
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

          <div class="llm-template-list">
            ${this._templates.map((template) => this._renderTemplateSummary(template, providerId)).join("")}
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
    document.querySelectorAll(".llm-template-item[data-template-id]").forEach((item) => {
      item.addEventListener("click", () => {
        this.applyTemplate(item.dataset.templateId)
      })
    })
  },

  applyTemplate(templateId) {
    const template = this._findTemplate(templateId)
    if (!template) return
    const baseUrl = document.getElementById("llm-base-url")
    const model = document.getElementById("llm-model")
    const label = document.getElementById("llm-label")
    const datalist = document.getElementById("llm-model-options")

    if (baseUrl) baseUrl.value = template.base_url || ""
    if (model) model.value = template.default_model || ""
    if (label) label.value = template.name || ""
    if (datalist) {
      datalist.innerHTML = (template.models || [])
        .map((item) => `<option value="${esc(item)}"></option>`)
        .join("")
    }
  },

  async save() {
    const projectId = state.currentProjectId
    if (!projectId) {
      toast("请先选择项目", "warning")
      return
    }

    const providerId = document.getElementById("llm-provider")?.value || "openai-compatible"
    const template = this._findTemplate(providerId)
    const payload = {
      provider_id: providerId,
      label: document.getElementById("llm-label")?.value.trim() || template?.name || "",
      base_url: document.getElementById("llm-base-url")?.value.trim() || "",
      model: document.getElementById("llm-model")?.value.trim() || "",
      api_key: document.getElementById("llm-api-key")?.value.trim() || "",
      clear_api_key: Boolean(document.getElementById("llm-clear-api-key")?.checked),
    }

    if (!payload.base_url || !payload.model) {
      toast("请填写 Base URL 和模型名", "warning")
      return
    }

    try {
      this._settings = await api.projects.updateLlmSettings(projectId, payload)
      document.getElementById("llm-api-key").value = ""
      document.getElementById("llm-clear-api-key").checked = false
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

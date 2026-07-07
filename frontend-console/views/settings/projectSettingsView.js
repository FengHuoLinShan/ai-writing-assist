/**
 * 项目设置页 — #/workbench/<pid>/project-settings 入口。
 *
 * 编排三个 Tab：主配置、深度导入、作者偏好。
 * 读取 state.currentProjectId 决定渲染项目设置还是空态。
 * 依赖全局：api、state、router、toast、esc。
 */
import llmMainTab from "./tabs/llmMainTab.js"
import deepImportTab from "./tabs/deepImportTab.js"
import authorPreferencesTab from "./tabs/authorPreferencesTab.js"

const projectSettingsView = {
  _projectId: null,
  _effectiveLLM: null,
  _effectivePrefs: null,
  _templates: [],
  _tab: "main",

  async onEnter() {
    this._projectId = state.currentProjectId
    if (!this._projectId) {
      this._effectiveLLM = null
      this._effectivePrefs = null
      return
    }
    try {
      if (typeof tryMigrateLocalAuthorPreferences !== "undefined") {
        try {
          await tryMigrateLocalAuthorPreferences(this._projectId)
        } catch (err) {
          console.warn("本地偏好迁移失败:", err)
        }
      }
      const [llm, prefs, templates] = await Promise.all([
        api.settings.getEffectiveLLMSettings(this._projectId),
        api.settings.getEffectiveAuthorPrefs(this._projectId),
        api.projects.listLlmProviderTemplates(),
      ])
      this._effectiveLLM = llm
      this._effectivePrefs = prefs
      // listLlmProviderTemplates 返回 { items: [...] }，归一化为数组供 llmFormFields 使用
      this._templates = Array.isArray(templates) ? templates : (templates?.items || [])
      if (!this._tab) this._tab = "main"
    } catch (err) {
      console.error("加载项目设置失败:", err)
      toast("加载项目设置失败", "error")
      this._effectiveLLM = null
      this._effectivePrefs = null
      this._templates = []
    }
  },

  async render() {
    setTimeout(() => this.bindEvents(), 0)
    if (!this._projectId) {
      return `
        <div class="project-settings-view empty-state">
          <p class="empty-hint">请先进入项目</p>
          <button class="btn btn-link" id="project-settings-goto-global">返回全局设置</button>
        </div>
      `
    }
    const title = state.currentProject?.title || this._projectId
    const tabs = [
      { key: "main", label: "主配置" },
      { key: "deep", label: "深度导入" },
      { key: "author", label: "作者偏好" },
    ]
      .map(
        (t) =>
          `<button class="tab-btn${this._tab === t.key ? " active" : ""}" data-tab="${t.key}">${t.label}</button>`
      )
      .join("")
    return `
      <div class="project-settings-view">
        <div class="section-header">
          <div>
            <h2>项目设置</h2>
            <p class="section-subtitle">${esc(title)}</p>
          </div>
          <div class="llm-global-actions">
            <button class="btn btn-link" id="project-settings-goto-global">全局设置 →</button>
          </div>
        </div>
        <nav class="settings-tab-nav">${tabs}</nav>
        <div class="settings-tab-content">${this._renderCurrentTab()}</div>
      </div>
    `
  },

  _renderCurrentTab() {
    if (!this._effectiveLLM || !this._effectivePrefs) return "加载中…"
    if (this._tab === "deep") {
      return deepImportTab.render({ effectiveData: this._effectiveLLM })
    }
    if (this._tab === "author") {
      return authorPreferencesTab.render({
        effectiveData: this._effectivePrefs,
        mode: "project",
      })
    }
    return llmMainTab.render({
      effectiveData: this._effectiveLLM,
      templates: this._templates,
    })
  },

  bindEvents() {
    document.querySelectorAll(".settings-tab-nav .tab-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        this._tab = e.currentTarget.dataset.tab
        router.refresh()
      })
    })
    document
      .getElementById("project-settings-goto-global")
      ?.addEventListener("click", () => router.navigate("settings"))

    if (!this._projectId || !this._effectiveLLM || !this._effectivePrefs) return
    if (this._tab === "deep") {
      deepImportTab.bindEvents({
        onSave: (deepImport) => this.saveDeepImport(deepImport),
        onResetAll: () => this.resetDeepImport(),
      })
    } else if (this._tab === "author") {
      authorPreferencesTab.bindEvents({
        onSave: (prefs) => this.saveAuthorPrefs(prefs),
        onResetField: (field) => this.resetAuthorPrefsField(field),
      })
    } else {
      llmMainTab.bindEvents({
        onSave: ({ payload, api_key, clear_api_key }) =>
          this.saveLLM(payload, api_key, clear_api_key),
        onResetAll: () => this.resetAllLLMFields(),
        onResetField: (field) => this.resetLLMField(field),
      })
    }
  },

  async saveLLM(payload, apiKey, clearApiKey) {
    try {
      await api.projects.updateLlmSettings(this._projectId, {
        ...payload,
        api_key: apiKey,
        clear_api_key: clearApiKey,
      })
      // D17: Key 未配置时给提示但仍报告其他字段已保存
      const eff = this._effectiveLLM
      const keyConfigured = eff?.api_key_configured?.value === true
      const willHaveKey = Boolean(apiKey) || (keyConfigured && !clearApiKey)
      if (willHaveKey) {
        toast("LLM 配置已保存", "success")
      } else {
        toast("Key 未配置，已保存其他字段", "warning")
      }
      await this._refreshEffective()
    } catch (err) {
      toast(err.message || "保存失败", "error")
    }
  },

  async saveDeepImport(deepImport) {
    try {
      const eff = await api.settings.getEffectiveLLMSettings(this._projectId)
      const pickProject = (field) =>
        eff[field]?.source === "project" ? eff[field].value : null
      const payload = {
        provider_id: pickProject("provider_id"),
        label: pickProject("label"),
        base_url: pickProject("base_url"),
        model: pickProject("model"),
        timeout: pickProject("timeout"),
        max_tokens: pickProject("max_tokens"),
        temperature: pickProject("temperature"),
        top_p: pickProject("top_p"),
        extra: pickProject("extra") || {},
        deep_import: deepImport,
      }
      await api.projects.updateLlmSettings(this._projectId, payload)
      toast("深度导入参数已保存", "success")
      await this._refreshEffective()
    } catch (err) {
      toast(err.message || "保存失败", "error")
    }
  },

  async saveAuthorPrefs(prefs) {
    try {
      await api.settings.updateProjectAuthorPrefs(this._projectId, prefs)
      toast("作者偏好已保存", "success")
      await this._refreshEffective()
    } catch (err) {
      toast(err.message || "保存失败", "error")
    }
  },

  async resetLLMField(field) {
    try {
      await api.settings.resetLLMSettingsField(this._projectId, field)
      toast(`${field} 已恢复到全局默认`, "success")
      await this._refreshEffective()
    } catch (err) {
      toast(err.message || "重置失败", "error")
    }
  },

  async resetAllLLMFields() {
    try {
      await api.projects.updateLlmSettings(this._projectId, {
        provider_id: null,
        label: null,
        base_url: null,
        model: null,
        timeout: null,
        max_tokens: null,
        temperature: null,
        top_p: null,
        extra: {},
        deep_import: {},
        api_key: "",
        clear_api_key: true,
      })
      toast("已恢复所有 LLM 字段到全局默认", "success")
      await this._refreshEffective()
    } catch (err) {
      toast(err.message || "重置失败", "error")
    }
  },

  resetDeepImport() {
    return this.resetLLMField("deep_import")
  },

  async resetAuthorPrefsField(field) {
    try {
      await api.settings.resetProjectAuthorPrefsField(this._projectId, field)
      toast(`${field} 已恢复到全局默认`, "success")
      await this._refreshEffective()
    } catch (err) {
      toast(err.message || "重置失败", "error")
    }
  },

  async _refreshEffective() {
    const [llm, prefs] = await Promise.all([
      api.settings.getEffectiveLLMSettings(this._projectId),
      api.settings.getEffectiveAuthorPrefs(this._projectId),
    ])
    this._effectiveLLM = llm
    this._effectivePrefs = prefs
    await router.refresh()
  },
}

if (typeof router !== "undefined") {
  router.registerView("project-settings", projectSettingsView)

  // #/llm 向后兼容别名（D15）
  router.registerView("llm", {
    async onEnter() {
      if (state.currentProjectId) {
        router.navigate("project-settings")
      } else {
        router.navigate("settings")
        if (typeof toast !== "undefined") toast("请先选择项目", "warning")
      }
    },
    async render() {
      return ""
    },
  })
}

export default projectSettingsView
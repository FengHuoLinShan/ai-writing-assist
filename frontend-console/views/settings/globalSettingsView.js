/**
 * 全局设置页 — #/settings 入口（无需选项目）。
 *
 * 渲染：owner 占位头部 + 全局 LLM 默认 + 全局作者偏好 + 引用此默认的项目（只读）+ 本地迁移。
 * 不渲染深度导入（D9）。
 *
 * 依赖全局：api、state、router、toast、esc。
 */
import {
  SYSTEM_LLM_DEFAULTS,
  bindLLMPresetEvents,
  renderLLMFormFields,
  readLLMFormFields,
  validateLLMPayload,
} from "./shared/llmFormFields.js"
import {
  renderAuthorPreferencesForm,
  readAuthorPreferencesForm,
  validateAuthorPreferences,
} from "./shared/authorPreferencesForm.js"

function setSettingsButtonLoading(btn, loading) {
  if (!btn) return
  btn.classList.toggle("settings-btn-loading", loading)
  btn.disabled = loading
}

function setSettingsButtonError(btn) {
  if (!btn) return
  btn.classList.add("settings-btn-error")
  setTimeout(() => btn.classList.remove("settings-btn-error"), 500)
}

const globalSettingsView = {
  _llmDefaults: null,
  _authorPrefs: null,
  _templates: [],
  _projectsUsingDefaults: { items: [], total: 0, truncated: false },

  async onEnter() {
    try {
      const [llm, prefs, projects, templates] = await Promise.all([
        api.settings.listGlobalLLMDefaults(),
        api.settings.listGlobalAuthorPrefs(),
        api.settings.listProjectsUsingDefaults({ limit: 50 }),
        api.projects.listLlmProviderTemplates(),
      ])
      this._llmDefaults = this._withSystemLLMDefaults(llm)
      this._authorPrefs = prefs || {}
      this._templates = Array.isArray(templates) ? templates : (templates?.items || [])
      this._projectsUsingDefaults = projects || { items: [], total: 0, truncated: false }
    } catch (err) {
      console.error("加载全局设置失败:", err)
      toast("加载全局设置失败", "error")
      this._llmDefaults = this._withSystemLLMDefaults(null)
      this._authorPrefs = {}
      this._templates = []
      this._projectsUsingDefaults = { items: [], total: 0, truncated: false }
    }
  },

  async render() {
    setTimeout(() => this.bindEvents(), 0)
    const hasProject = !!state.currentProjectId
    return `
      <div class="global-settings-view">
        <div class="view-header section-header">
          <h2 class="view-header__title">
            全局设置
            <span class="view-header__project">owner: local（demo 占位）</span>
          </h2>
          <div class="view-header__actions llm-global-actions">
            <button class="btn btn-sm btn-link" id="goto-recent-project-btn" ${hasProject ? "" : "disabled"}>进入当前项目 →</button>
          </div>
        </div>

        <section class="settings-section">
          <h3>LLM 全局默认</h3>
          <p class="settings-section-hint">不存 API Key；项目级才配置 Key。</p>
          ${renderLLMFormFields({ values: this._withSystemLLMDefaults(this._llmDefaults), templates: this._templates, withApiKey: false })}
          <div class="settings-actions">
            <button class="btn btn-primary" id="global-llm-save">保存 LLM 全局默认</button>
          </div>
        </section>

        <section class="settings-section">
          <h3>作者偏好全局默认</h3>
          ${renderAuthorPreferencesForm({
            dailyGoal: this._authorPrefs.daily_goal,
            editorFont: this._authorPrefs.editor_font,
            defaultFocusMode: this._authorPrefs.default_focus_mode,
          })}
          <div class="settings-actions">
            <button class="btn btn-primary" id="global-author-save">保存作者偏好</button>
          </div>
        </section>

        <section class="settings-section">
          <h3>引用此默认的项目（只读）</h3>
          ${this._renderProjectsUsingDefaults()}
        </section>

        <section class="settings-section">
          <h3>本地迁移</h3>
          <p class="settings-section-hint">将浏览器 localStorage 中的旧作者偏好一次性迁入后端。</p>
          <div class="settings-actions">
            <button class="btn btn-secondary" id="manual-migrate-btn">手动迁移所有项目本地偏好</button>
          </div>
        </section>
      </div>
    `
  },

  _withSystemLLMDefaults(values) {
    const merged = { ...SYSTEM_LLM_DEFAULTS }
    for (const [key, value] of Object.entries(values || {})) {
      if (value !== null && value !== undefined && value !== "") {
        merged[key] = value
      }
    }
    return merged
  },

  _renderProjectsUsingDefaults() {
    if (!this._projectsUsingDefaults?.items?.length) {
      return `<p class="empty-hint">没有项目继承全局默认</p>`
    }
    const items = this._projectsUsingDefaults.items.map((it) => `
      <li>${esc(it.title || "")} (${esc(it.project_id || "")})</li>
    `).join("")
    const tail = this._projectsUsingDefaults.truncated
      ? `<p class="settings-section-hint">还有更多项目省略…</p>`
      : ""
    return `<ul class="projects-using-list">${items}</ul>${tail}`
  },

  bindEvents() {
    bindLLMPresetEvents()
    document.getElementById("global-llm-save")?.addEventListener("click", () => this.saveLLM())
    document.getElementById("global-author-save")?.addEventListener("click", () => this.saveAuthor())
    document.getElementById("goto-recent-project-btn")?.addEventListener("click", () => {
      if (state.currentProjectId) router.navigate("project-settings")
    })
    document.getElementById("manual-migrate-btn")?.addEventListener("click", () => this.runManualMigration())
  },

  async saveLLM() {
    const btn = document.getElementById("global-llm-save")
    const { payload } = readLLMFormFields()
    const v = validateLLMPayload(payload)
    if (!v.ok) return toast(v.message, "warning")
    setSettingsButtonLoading(btn, true)
    try {
      const clean = { ...payload }
      delete clean.api_key
      delete clean.clear_api_key
      this._llmDefaults = await api.settings.updateGlobalLLMDefaults(clean)
      toast("LLM 全局默认已保存", "success")
    } catch (err) {
      toast(err.message || "保存失败", "error")
      setSettingsButtonError(btn)
    } finally {
      setSettingsButtonLoading(btn, false)
    }
  },

  async saveAuthor() {
    const btn = document.getElementById("global-author-save")
    const prefs = readAuthorPreferencesForm()
    const v = validateAuthorPreferences(prefs)
    if (!v.ok) return toast(v.message, "warning")
    setSettingsButtonLoading(btn, true)
    try {
      this._authorPrefs = await api.settings.updateGlobalAuthorPrefs(prefs)
      toast("作者偏好已保存", "success")
    } catch (err) {
      toast(err.message || "保存失败", "error")
      setSettingsButtonError(btn)
    } finally {
      setSettingsButtonLoading(btn, false)
    }
  },

  async runManualMigration() {
    toast("迁移中…", "info")
    const keys = Object.keys(localStorage).filter((k) => k.startsWith("novel_author_preferences:"))
    let migrated = 0
    for (const key of keys) {
      const projectId = key.split(":")[1]
      if (!projectId || projectId === "global") continue
      let parsed
      try {
        parsed = JSON.parse(localStorage.getItem(key) || "{}")
      } catch {
        continue
      }
      try {
        const existing = await api.settings.getProjectAuthorPrefs(projectId)
        if (existing &&
          (existing.daily_goal !== null || existing.editor_font !== null || existing.default_focus_mode !== null)) {
          localStorage.removeItem(key)
          continue
        }
      } catch {
        continue
      }
      const payload = {
        daily_goal: parsed.dailyGoal ?? null,
        editor_font: parsed.editorFont ?? null,
        default_focus_mode: Boolean(parsed.defaultFocusMode ?? false),
      }
      try {
        await api.settings.updateProjectAuthorPrefs(projectId, payload)
        localStorage.removeItem(key)
        migrated += 1
      } catch (err) {
        console.error(`迁移 ${projectId} 失败:`, err)
      }
    }
    toast(`已迁移 ${migrated} 个项目，余 ${keys.length - migrated} 个`, migrated ? "success" : "info")
  },
}

if (typeof router !== "undefined") {
  router.registerView("settings", globalSettingsView)
}

export default globalSettingsView

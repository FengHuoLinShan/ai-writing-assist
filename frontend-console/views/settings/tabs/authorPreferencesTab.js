/**
 * 作者偏好 Tab — 项目级作者偏好覆盖（日更/字体/专注）。
 *
 * 纯渲染 + 读取组件。mode ∈ {"project","global"}；当前仅 "project"（全局页直接用
 * renderAuthorPreferencesForm 不走 Tab 包裹）。保留 mode 参数供未来灵活性。
 * 依赖全局：document、toast。
 */
import {
  renderAuthorPreferencesForm,
  readAuthorPreferencesForm,
  validateAuthorPreferences,
} from "../shared/authorPreferencesForm.js"

const authorPreferencesTab = {
  render({ effectiveData, mode }) {
    const values = {
      dailyGoal: effectiveData.daily_goal?.value,
      editorFont: effectiveData.editor_font?.value,
      defaultFocusMode: effectiveData.default_focus_mode?.value,
    }
    const source = {
      daily_goal: effectiveData.daily_goal,
      editor_font: effectiveData.editor_font,
      default_focus_mode: effectiveData.default_focus_mode,
    }
    return `
      <div class="author-prefs-tab" data-mode="${mode || "project"}">
        ${renderAuthorPreferencesForm({
          ...values,
          source,
        })}
        <div class="settings-actions">
          <button class="btn btn-primary" id="author-prefs-tab-save">保存作者偏好</button>
        </div>
      </div>
    `
  },

  bindEvents({ onSave, onResetField }) {
    document.getElementById("author-prefs-tab-save")?.addEventListener("click", () => {
      const prefs = readAuthorPreferencesForm()
      const v = validateAuthorPreferences(prefs)
      if (!v.ok) return toast(v.message, "warning")
      onSave?.(prefs)
    })
    document.querySelectorAll(".field-reset[data-field]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        onResetField?.(e.currentTarget.dataset.field)
      })
    })
  },
}

export default authorPreferencesTab

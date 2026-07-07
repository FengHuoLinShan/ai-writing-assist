import { EDITOR_FONT_OPTIONS } from "./constants.js"

export function renderAuthorPreferencesForm({
  dailyGoal,
  editorFont,
  defaultFocusMode,
  source = {},
} = {}) {
  return `
    <div class="author-preferences-form">
      ${source.daily_goal ? `<div class="field-source">${sourceLabelHtml(source.daily_goal)}</div>` : ""}
      <div class="form-row">
        <div class="form-group">
          <label for="author-daily-goal">日更目标（字）</label>
          <input class="form-input" id="author-daily-goal" type="number" min="0" max="100000"
            value="${dailyGoal ?? ""}" placeholder="6000" />
          ${renderResetFor(source.daily_goal, "daily_goal")}
        </div>
        <div class="form-group">
          <label for="author-editor-font">编辑器字体</label>
          <select class="form-input" id="author-editor-font">
            ${EDITOR_FONT_OPTIONS.map((v) => `<option value="${v}" ${editorFont === v ? "selected" : ""}>${v}</option>`).join("")}
          </select>
          ${renderResetFor(source.editor_font, "editor_font")}
        </div>
        <div class="form-group">
          <label>
            <input id="author-default-focus" type="checkbox" ${defaultFocusMode ? "checked" : ""} />
            默认专注模式
          </label>
          ${renderResetFor(source.default_focus_mode, "default_focus_mode")}
        </div>
      </div>
    </div>
  `
}

function renderResetFor(srcObj, fieldName) {
  if (!srcObj || srcObj.source === "global" || srcObj.source === "system") return ""
  return `<button class="btn btn-sm btn-link field-reset" data-field="${fieldName}" type="button">恢复到全局默认</button>`
}

function sourceLabelHtml(srcObj) {
  return `<small class="source-tag">${srcObj.source}</small>`
}

export function readAuthorPreferencesForm() {
  const dailyGoalRaw = document.getElementById("author-daily-goal")?.value.trim() || ""
  return {
    daily_goal: dailyGoalRaw ? Number(dailyGoalRaw) : null,
    editor_font: document.getElementById("author-editor-font")?.value || null,
    default_focus_mode: Boolean(document.getElementById("author-default-focus")?.checked),
  }
}

export function validateAuthorPreferences(prefs) {
  if (
    prefs.daily_goal != null &&
    (!Number.isInteger(prefs.daily_goal) ||
      prefs.daily_goal < 0 ||
      prefs.daily_goal > 100000)
  ) {
    return { ok: false, message: "日更目标必须是 0-100000 的整数" }
  }
  return { ok: true }
}
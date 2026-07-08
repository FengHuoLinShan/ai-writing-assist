/**
 * 主配置 Tab — 项目级 LLM 主配置（供应商/Key/BaseURL/模型/参数/预设）。
 *
 * 纯渲染 + 读取组件，不含路由与数据来源逻辑；由 projectSettingsView 编排。
 * 依赖全局：document、toast、confirm。
 */
import {
  renderLLMFormFields,
  readLLMFormFields,
  validateLLMPayload,
} from "../shared/llmFormFields.js"

const llmMainTab = {
  render({ effectiveData, templates }) {
    const values = {
      provider_id: effectiveData.provider_id?.value || "",
      label: effectiveData.label?.value || "",
      base_url: effectiveData.base_url?.value || "",
      model: effectiveData.model?.value || "",
      timeout: effectiveData.timeout?.value ?? null,
      max_tokens: effectiveData.max_tokens?.value ?? null,
      temperature: effectiveData.temperature?.value ?? null,
      top_p: effectiveData.top_p?.value ?? null,
      extra: effectiveData.extra?.value || {},
      api_key_configured: effectiveData.api_key_configured?.value || false,
      provider_id_source: effectiveData.provider_id?.source,
      base_url_source: effectiveData.base_url?.source,
    }
    const sourceMap = {
      provider_id: effectiveData.provider_id,
      label: effectiveData.label,
      base_url: effectiveData.base_url,
      model: effectiveData.model,
      timeout: effectiveData.timeout,
      max_tokens: effectiveData.max_tokens,
      temperature: effectiveData.temperature,
      top_p: effectiveData.top_p,
      extra: effectiveData.extra,
    }
    return `
      <div class="llm-main-tab">
        ${renderLLMFormFields({ values, templates, sourceMap, withApiKey: true })}
        <div class="settings-actions">
          <button class="btn btn-primary" id="llm-tab-save">保存项目 LLM 配置</button>
          <button class="btn btn-link" id="llm-tab-reset-all">恢复所有字段到全局默认</button>
        </div>
        <ul class="llm-source-legend">
          <li><span class="source-label source-project">已覆盖</span>：项目自填值</li>
          <li><span class="source-label source-global">继承全局</span>：项目未设</li>
          <li><span class="source-label source-system">系统默认</span>：全局也无</li>
          <li><span class="source-label source-unset">未配置</span>：必须填</li>
        </ul>
      </div>
    `
  },

  bindEvents({ onSave, onResetAll, onResetField }) {
    document.getElementById("llm-tab-save")?.addEventListener("click", () => {
      const { payload, api_key, clear_api_key } = readLLMFormFields()
      const v = validateLLMPayload(payload)
      if (!v.ok) return toast(v.message, "warning")
      onSave?.({ payload, api_key, clear_api_key })
    })
    document.getElementById("llm-tab-reset-all")?.addEventListener("click", () => {
      if (!confirm("将清除项目所有 LLM 覆盖，回退到全局默认。继续？")) return
      onResetAll?.()
    })
    document.querySelectorAll(".field-reset[data-field]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const field = e.currentTarget.dataset.field
        onResetField?.(field)
      })
    })
  },
}

export default llmMainTab

/**
 * 深度导入 Tab — 40+ 字段（Phase 0/1A/1B/2/3）项目覆盖值。
 *
 * 纯渲染 + 读取组件。deep_import 整体覆盖语义（D6）：source=project 时展开字段；
 * source=global/system 时不展开字段值，UI 仅显示来源标签。重置按钮只在 source=project 时显示。
 * 依赖全局：document、toast、confirm。
 */
import { renderDeepImportFields, readDeepImportFields } from "../shared/deepImportFields.js"
import { renderSourceLabel } from "../shared/fieldSourceLabel.js"

const deepImportTab = {
  render({ effectiveData }) {
    const di = effectiveData.deep_import
    const settings = di?.source === "project" ? di.value || {} : {}
    return `
      <div class="deep-import-tab">
        <p class="deep-import-source-hint">
          深度导入参数 <small>${renderSourceLabel(di || { source: "system", value: null })}</small>
        </p>
        ${renderDeepImportFields(settings)}
        <div class="deep-import-actions">
          <button class="btn btn-primary" id="deep-import-tab-save">保存深度导入参数</button>
          ${di?.source === "project"
            ? `<button class="btn btn-link" id="deep-import-tab-reset-all">恢复到全局/系统默认</button>`
            : ""}
        </div>
      </div>
    `
  },

  bindEvents({ onSave, onResetAll }) {
    document.getElementById("deep-import-tab-save")?.addEventListener("click", () => {
      const out = readDeepImportFields()
      if (!out.ok) return toast(out.error, "warning")
      onSave?.(out.value)
    })
    document.getElementById("deep-import-tab-reset-all")?.addEventListener("click", () => {
      if (!confirm("将清除项目深度导入覆盖，整体回退。继续？")) return
      onResetAll?.()
    })
  },
}

export default deepImportTab

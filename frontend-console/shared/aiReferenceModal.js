import { renderContextSummary } from "./contextSummaryRenderer.js"
import { contextContentModeLabel } from "./assetDisplayState.js"

export function confirmAiReference(options) {
  return new Promise((resolve, reject) => {
    const overlay = document.getElementById("modal-overlay")
    const titleEl = document.getElementById("modal-title")
    const bodyEl = document.getElementById("modal-body")
    const footerEl = document.getElementById("modal-footer")
    if (!overlay || !titleEl || !bodyEl || !footerEl) {
      reject(new Error("AI 参考资料确认弹窗不可用"))
      return
    }

    let currentConfirmation = null
    const excludedSectionKeys = new Set(options.excluded_asset_ids?.context_sections || [])
    titleEl.textContent = "AI 参考资料"
    bodyEl.innerHTML = renderBody(options)
    loadActivationProfiles(options)
    footerEl.innerHTML = ""
    document.getElementById("ai-ref-scope")?.addEventListener("change", (event) => {
      event.currentTarget.dataset.userChanged = "1"
    })

    const close = () => overlay.classList.add("hidden")
    const refreshBtn = createButton("重新整理", "btn")
    const confirmBtn = createButton("确认使用", "btn btn-primary")
    const cancelBtn = createButton("取消", "btn btn-ghost")

    const renderCurrentSummary = () => {
      renderSummary(currentConfirmation, async (sectionKey) => {
        excludedSectionKeys.add(sectionKey)
        try {
          setBusy(refreshBtn, true)
          currentConfirmation = await createConfirmation(options, excludedSectionKeys)
          renderCurrentSummary()
          toast("AI 参考资料已重新整理", "success")
        } catch (err) {
          showError(err)
        } finally {
          setBusy(refreshBtn, false)
        }
      })
    }

    refreshBtn.addEventListener("click", async () => {
      try {
        setBusy(refreshBtn, true)
        currentConfirmation = await createConfirmation(options, excludedSectionKeys)
        renderCurrentSummary()
        toast("AI 参考资料已整理", "success")
      } catch (err) {
        showError(err)
      } finally {
        setBusy(refreshBtn, false)
      }
    })

    confirmBtn.addEventListener("click", async () => {
      try {
        setBusy(confirmBtn, true)
        if (!currentConfirmation) {
          currentConfirmation = await createConfirmation(options, excludedSectionKeys)
          renderCurrentSummary()
        }
        close()
        resolve(currentConfirmation)
      } catch (err) {
        showError(err)
      } finally {
        setBusy(confirmBtn, false)
      }
    })

    cancelBtn.addEventListener("click", () => {
      close()
      reject(new Error("已取消 AI 参考资料确认"))
    })

    footerEl.append(refreshBtn, confirmBtn, cancelBtn)
    overlay.classList.remove("hidden")
  })
}

function renderBody(options) {
  const chapterValue = options.chapter_index || options.start_chapter || ""
  const scope = options.scope || (chapterValue ? "chapter" : "project")
  const contextMode = options.context_mode || "canonical"
  return `
    <div class="ai-ref-modal">
      <div class="ai-ref-section">
        <div class="ai-ref-section-title">选择规则</div>
        <div class="ai-ref-form-grid">
          <label>范围
            <select id="ai-ref-scope" class="form-select">
              ${option("project", "项目", scope)}
              ${option("chapter", "章节", scope)}
              ${option("arc", "篇章", scope)}
              ${option("full", "全部", scope)}
            </select>
          </label>
          <label>章节
            <input id="ai-ref-chapter" class="form-input" type="number" min="1" value="${esc(chapterValue)}" />
          </label>
          <label>模式
            <select id="ai-ref-context-mode" class="form-select">
              ${option("canonical", contextContentModeLabel("canonical"), contextMode)}
              ${option("working", contextContentModeLabel("working"), contextMode)}
            </select>
          </label>
          <label class="ai-ref-checkbox">
            <input id="ai-ref-include-pending" type="checkbox" ${options.include_pending_objects ? "checked" : ""} />
            <span>包含待处理内容</span>
          </label>
        </div>
        <label>排除资产 ID
          <input id="ai-ref-excluded" class="form-input" placeholder="逗号分隔，可留空" />
        </label>
        <label>已发布 AI 参考规则（显式启用）
          <select id="ai-ref-activation-profile" class="form-select">
            <option value="">不启用</option>
          </select>
        </label>
      </div>
      <div class="ai-ref-section">
        <label>本次 AI 额外注意事项
          <textarea id="ai-ref-user-note" class="form-textarea" rows="3" placeholder="例如：避免剧透、只补抽长期资产">${esc(options.user_note || "")}</textarea>
        </label>
      </div>
      <div id="ai-ref-error" class="ai-ref-error" style="display:none;"></div>
      <div id="ai-ref-summary">${renderContextSummary({})}</div>
    </div>
  `
}

function option(value, label, selected) {
  return `<option value="${esc(value)}" ${selected === value ? "selected" : ""}>${esc(label)}</option>`
}

async function createConfirmation(options, excludedSectionKeys = new Set()) {
  const payload = buildPayload(options, excludedSectionKeys)
  return api.context.confirm(payload)
}

function buildPayload(options, excludedSectionKeys = new Set()) {
  const fallbackScope = options.scope || (options.chapter_index || options.start_chapter ? "chapter" : "project")
  const scopeEl = document.getElementById("ai-ref-scope")
  const scope = scopeEl?.dataset.userChanged === "1" ? scopeEl.value : fallbackScope
  const chapterRaw = document.getElementById("ai-ref-chapter")?.value
  const chapter = chapterRaw ? parseInt(chapterRaw, 10) : options.chapter_index
  const excludedRaw = document.getElementById("ai-ref-excluded")?.value || ""
  const excludedIds = excludedRaw.split(",").map((s) => s.trim()).filter(Boolean)
  const payload = {
    novel_id: options.novel_id,
    action: options.action,
    task: options.task,
    scope,
    reveal_mode: options.reveal_mode || "author_safe",
    context_mode: document.getElementById("ai-ref-context-mode")?.value || options.context_mode || "canonical",
    include_pending_objects: Boolean(document.getElementById("ai-ref-include-pending")?.checked),
    user_note: document.getElementById("ai-ref-user-note")?.value || undefined,
  }
  if (chapter) payload.chapter_index = chapter
  if (options.scene_id) payload.scene_id = options.scene_id
  if (options.arc_id) payload.arc_id = options.arc_id
  if (options.entity_ids) payload.entity_ids = options.entity_ids
  if (options.character_ids) payload.character_ids = options.character_ids
  if (options.viewpoint_character_id) payload.viewpoint_character_id = options.viewpoint_character_id
  if (options.location_ids) payload.location_ids = options.location_ids
  const activationProfileId = document.getElementById("ai-ref-activation-profile")?.value
    || options.activation_profile_id
  if (activationProfileId) payload.activation_profile_id = activationProfileId
  const excludedContextSections = Array.from(excludedSectionKeys)
  const optionExcluded = options.excluded_asset_ids || {}
  const hasOptionExcluded = Object.keys(optionExcluded).length > 0
  if (hasOptionExcluded || excludedIds.length || excludedContextSections.length) {
    payload.excluded_asset_ids = { ...optionExcluded }
    if (excludedIds.length) payload.excluded_asset_ids.manual = excludedIds
    if (excludedContextSections.length) payload.excluded_asset_ids.context_sections = excludedContextSections
  }
  return payload
}

async function loadActivationProfiles(options) {
  const select = document.getElementById("ai-ref-activation-profile")
  if (!select || !api.context.listActivationProfiles || !options.novel_id) return
  try {
    const result = await api.context.listActivationProfiles(options.novel_id)
    const profiles = (result?.items || []).filter((item) => item.status === "published")
    for (const profile of profiles) {
      const node = document.createElement("option")
      node.value = profile.id
      node.textContent = `${profile.name} · v${profile.version_number}`
      node.selected = profile.id === options.activation_profile_id
      select.append(node)
    }
  } catch {
    select.title = "AI 参考规则加载失败；本次仍可不启用规则继续。"
  }
}

function renderSummary(confirmation, onExcludeSection) {
  const el = document.getElementById("ai-ref-summary")
  if (!el) return
  el.innerHTML = renderContextSummary(confirmation)
  if (!onExcludeSection) return
  el.querySelectorAll("[data-ai-ref-exclude-section]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sectionKey = btn.getAttribute("data-ai-ref-exclude-section")
      if (sectionKey) onExcludeSection(sectionKey)
    })
  })
}

function showError(err) {
  const el = document.getElementById("ai-ref-error")
  if (!el) return
  const message = err?.message || "AI 参考资料整理失败"
  el.textContent = message.includes("请求超时")
    ? "AI 参考资料整理超时，请缩小范围或稍后重试。后端仍可继续处理其他操作。"
    : message
  el.style.display = ""
}

function createButton(text, className) {
  const btn = document.createElement("button")
  btn.className = className
  btn.textContent = text
  return btn
}

function setBusy(btn, busy) {
  btn.disabled = busy
}

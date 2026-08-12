import { renderContextSummary } from "./contextSummaryRenderer.js"
import { contextContentModeLabel } from "./assetDisplayState.js"
import { buildMapUrl } from "../views/mapRouteContext.js"

const CANCELLED = "已取消 AI 参考资料确认"
let sessionNumber = 0

export function confirmAiReference(options) {
  return new Promise((resolve, reject) => {
    const overlay = document.getElementById("modal-overlay")
    const bodyEl = document.getElementById("modal-body")
    const footerEl = document.getElementById("modal-footer")
    if (!overlay || !bodyEl || !footerEl || typeof globalThis.showModalHtml !== "function" || typeof globalThis.closeModal !== "function") {
      reject(new Error("AI 参考资料确认弹窗不可用"))
      return
    }

    const sessionId = `ai-reference-${++sessionNumber}`
    const excludedSectionKeys = new Set(options.excluded_asset_ids?.context_sections || [])
    let root = null
    let settled = false
    let requestGeneration = 0
    let currentConfirmation = null
    let observer = null
    let refreshBtn = null
    let confirmBtn = null
    let cancelBtn = null
    const busyLeases = new Map()

    const active = () => Boolean(
      !settled
      && root?.isConnected
      && bodyEl.contains(root)
      && !overlay.classList.contains("hidden"),
    )
    const cleanup = () => {
      requestGeneration += 1
      observer?.disconnect()
      observer = null
    }
    const settle = (value, error) => {
      if (settled) return false
      settled = true
      cleanup()
      if (error) reject(error)
      else resolve(value)
      return true
    }
    const cancel = () => settle(null, new Error(CANCELLED))
    const owns = (token) => active() && token === requestGeneration
    const acquireBusy = (button, label) => {
      if (!button) return () => {}
      const lease = busyLeases.get(button) || { count: 0, label: button.textContent }
      lease.count += 1
      busyLeases.set(button, lease)
      if (button.isConnected) {
        button.disabled = true
        if (label) button.textContent = label
      }
      return () => {
        const current = busyLeases.get(button)
        if (!current) return
        current.count -= 1
        if (current.count > 0) return
        busyLeases.delete(button)
        if (active() && button.isConnected) {
          button.disabled = false
          button.textContent = current.label
        }
      }
    }

    const showCurrentSummary = (confirmation) => {
      if (!active()) return
      currentConfirmation = confirmation
      renderSummary(root, confirmation, async (sectionKey) => {
        if (!active()) return
        excludedSectionKeys.add(sectionKey)
        const token = ++requestGeneration
        const releaseBusy = acquireBusy(refreshBtn, "正在重新整理…")
        try {
          const next = await createConfirmation(options, excludedSectionKeys, root)
          if (!owns(token)) return
          showCurrentSummary(next)
          toast("AI 参考资料已重新整理", "success")
        } catch (err) {
          if (owns(token)) showError(root, err)
        } finally {
          releaseBusy()
        }
      }, options)
    }

    const refresh = async () => {
      if (!active()) return false
      const token = ++requestGeneration
      const releaseBusy = acquireBusy(refreshBtn, "正在整理…")
      try {
        const confirmation = await createConfirmation(options, excludedSectionKeys, root)
        if (!owns(token)) return false
        showCurrentSummary(confirmation)
        toast("AI 参考资料已整理", "success")
      } catch (err) {
        if (owns(token)) showError(root, err)
      } finally {
        releaseBusy()
      }
      return false
    }

    const confirm = async () => {
      if (!active()) return false
      const token = ++requestGeneration
      const releaseBusy = acquireBusy(confirmBtn, "正在确认…")
      try {
        const confirmation = currentConfirmation || await createConfirmation(options, excludedSectionKeys, root)
        if (!owns(token)) return false
        showCurrentSummary(confirmation)
        if (!globalThis.closeModal({ force: true })) return false
        settle(confirmation)
      } catch (err) {
        if (owns(token)) showError(root, err)
      } finally {
        releaseBusy()
      }
      return false
    }

    try {
      globalThis.showModalHtml("AI 参考资料", renderBody(options, sessionId), [
        { text: "重新整理", class: "btn", handler: refresh },
        { text: "确认使用", class: "btn btn-primary", handler: confirm },
        {
          text: "取消",
          class: "btn btn-ghost",
          handler: () => {
            const ownsVisibleModal = active()
            cancel()
            if (ownsVisibleModal) globalThis.closeModal({ force: true })
            return false
          },
        },
      ], { protectUnsaved: false })
    } catch {
      root = bodyEl.querySelector(`[data-ai-reference-session="${sessionId}"]`)
      const ownsPartialModal = Boolean(root && bodyEl.contains(root) && !overlay.classList.contains("hidden"))
      settle(null, new Error("AI 参考资料确认弹窗不可用"))
      if (ownsPartialModal) globalThis.closeModal({ force: true })
      return
    }

    root = bodyEl.querySelector(`[data-ai-reference-session="${sessionId}"]`)
    if (!root) {
      settle(null, new Error("AI 参考资料确认弹窗不可用"))
      return
    }
    const buttons = Array.from(footerEl.querySelectorAll("button"))
    refreshBtn = buttons.find((button) => button.textContent === "重新整理") || null
    confirmBtn = buttons.find((button) => button.textContent === "确认使用") || null
    cancelBtn = buttons.find((button) => button.textContent === "取消") || null
    if (!refreshBtn || !confirmBtn || !cancelBtn) {
      settle(null, new Error("AI 参考资料确认弹窗不可用"))
      if (bodyEl.contains(root) && !overlay.classList.contains("hidden")) globalThis.closeModal({ force: true })
      return
    }
    root.querySelector("#ai-ref-scope")?.addEventListener("change", (event) => {
      event.currentTarget.dataset.userChanged = "1"
    })

    observer = new MutationObserver(() => {
      if (!active()) cancel()
    })
    observer.observe(overlay, { attributes: true, attributeFilter: ["class"] })
    observer.observe(bodyEl, { childList: true })
    loadActivationProfiles(options, root, active)
  })
}

function renderBody(options, sessionId) {
  const chapterValue = options.chapter_index || options.start_chapter || ""
  const scope = options.scope || (chapterValue ? "chapter" : "project")
  const contextMode = options.context_mode || "canonical"
  return `
    <div class="ai-ref-modal" data-ai-reference-session="${esc(sessionId)}">
      <div class="ai-ref-section">
        <div class="ai-ref-section-title">选择规则</div>
        <div class="ai-ref-form-grid">
          <label>范围
            <select id="ai-ref-scope" class="form-select" ${options.lock_scope ? "disabled" : ""}>
              ${option("project", "项目", scope)}
              ${option("chapter", "章节", scope)}
              ${option("arc", "篇章", scope)}
              ${option("full", "全部", scope)}
            </select>
          </label>
          <label>${options.visible_until_chapter ? "起始章节" : "章节"}
            <input id="ai-ref-chapter" class="form-input" type="number" min="1" value="${esc(chapterValue)}" ${options.lock_chapter ? "readonly" : ""} />
          </label>
          ${options.visible_until_chapter ? `<label>结束章节
            <input class="form-input" type="number" value="${esc(options.visible_until_chapter)}" readonly />
          </label>` : ""}
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
        <label>已发布 AI 参考规则（显式启用）
          <select id="ai-ref-activation-profile" class="form-select"><option value="">不启用</option></select>
        </label>
      </div>
      <div class="ai-ref-section"><label>本次 AI 额外注意事项
        <textarea id="ai-ref-user-note" class="form-textarea" rows="3" placeholder="例如：避免剧透、只补抽长期资产">${esc(options.user_note || "")}</textarea>
      </label></div>
      <div id="ai-ref-error" class="ai-ref-error" style="display:none;"></div>
      <div id="ai-ref-summary">${renderContextSummary({})}</div>
    </div>
  `
}

function option(value, label, selected) {
  return `<option value="${esc(value)}" ${selected === value ? "selected" : ""}>${esc(label)}</option>`
}

async function createConfirmation(options, excludedSectionKeys, root) {
  return api.context.confirm(buildPayload(options, excludedSectionKeys, root))
}

function buildPayload(options, excludedSectionKeys, root) {
  const fallbackScope = options.scope || (options.chapter_index || options.start_chapter ? "chapter" : "project")
  const scopeEl = root?.querySelector("#ai-ref-scope")
  const scope = scopeEl?.dataset.userChanged === "1" ? scopeEl.value : fallbackScope
  const chapterRaw = root?.querySelector("#ai-ref-chapter")?.value
  const chapter = chapterRaw ? parseInt(chapterRaw, 10) : options.chapter_index
  const payload = {
    novel_id: options.novel_id,
    action: options.action,
    task: options.task,
    scope,
    reveal_mode: options.reveal_mode || "author_safe",
    context_mode: root?.querySelector("#ai-ref-context-mode")?.value || options.context_mode || "canonical",
    include_pending_objects: Boolean(root?.querySelector("#ai-ref-include-pending")?.checked),
    user_note: root?.querySelector("#ai-ref-user-note")?.value || undefined,
  }
  if (chapter) payload.chapter_index = chapter
  if (options.visible_until_chapter) payload.visible_until_chapter = options.visible_until_chapter
  if (options.budget_tokens != null) payload.budget_tokens = options.budget_tokens
  if (options.scene_id) payload.scene_id = options.scene_id
  if (options.arc_id) payload.arc_id = options.arc_id
  if (options.entity_ids) payload.entity_ids = options.entity_ids
  if (options.character_ids) payload.character_ids = options.character_ids
  if (options.thread_ids) payload.thread_ids = options.thread_ids
  if (options.viewpoint_character_id) payload.viewpoint_character_id = options.viewpoint_character_id
  if (options.location_ids) payload.location_ids = options.location_ids
  const activationProfileId = root?.querySelector("#ai-ref-activation-profile")?.value || options.activation_profile_id
  if (activationProfileId) payload.activation_profile_id = activationProfileId
  const sections = Array.from(excludedSectionKeys)
  const optionExcluded = options.excluded_asset_ids || {}
  if (Object.keys(optionExcluded).length || sections.length) {
    payload.excluded_asset_ids = { ...optionExcluded }
    if (sections.length) payload.excluded_asset_ids.context_sections = sections
  }
  return payload
}

async function loadActivationProfiles(options, root, active) {
  const select = root?.querySelector("#ai-ref-activation-profile")
  if (!select || !api.context.listActivationProfiles || !options.novel_id) return
  try {
    const result = await api.context.listActivationProfiles(options.novel_id)
    if (!active()) return
    for (const profile of (result?.items || []).filter((item) => item.status === "published")) {
      const node = document.createElement("option")
      node.value = profile.id
      node.textContent = `${profile.name} · v${profile.version_number}`
      node.selected = profile.id === options.activation_profile_id
      select.append(node)
    }
  } catch {
    if (active()) select.title = "AI 参考规则加载失败；本次仍可不启用规则继续。"
  }
}

function renderSummary(root, confirmation, onExcludeSection, options = {}) {
  const el = root?.querySelector("#ai-ref-summary")
  if (!el) return
  const knowledgeRepairHref = options.viewpoint_character_id && options.novel_id
    ? `#workbench/${encodeURIComponent(options.novel_id)}/world/objects?knowledge_character_id=${encodeURIComponent(options.viewpoint_character_id)}`
    : ""
  const sceneStateRepairHref = options.scene_id && options.novel_id
    ? buildMapUrl({ projectId: options.novel_id, sceneId: options.scene_id, mode: "live" })
    : ""
  el.innerHTML = renderContextSummary(confirmation, { knowledgeRepairHref, sceneStateRepairHref })
  if (!onExcludeSection) return
  el.querySelectorAll("[data-ai-ref-exclude-section]").forEach((button) => {
    button.addEventListener("click", () => {
      const sectionKey = button.getAttribute("data-ai-ref-exclude-section")
      if (sectionKey) onExcludeSection(sectionKey)
    })
  })
}

function showError(root, err) {
  const el = root?.querySelector("#ai-ref-error")
  if (!el) return
  const message = err?.message || "AI 参考资料整理失败"
  el.textContent = message.includes("请求超时")
    ? "AI 参考资料整理超时，请缩小范围或稍后重试。后端仍可继续处理其他操作。"
    : message
  el.style.display = ""
}

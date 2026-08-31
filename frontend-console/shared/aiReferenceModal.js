import { contextContentModeLabel } from "./assetDisplayState.js"
import { renderContextSummary } from "./contextSummaryRenderer.js"

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
    const pinnedRefs = refMap(options.pinned_refs)
    const excludedRefs = refMap(options.excluded_refs)
    let root = null
    let settled = false
    let previewGeneration = 0
    let proposalGeneration = 0
    let searchGeneration = 0
    let currentPreview = null
    let pendingProposal = null
    let dirty = true
    let confirming = false
    let observer = null
    let refreshBtn = null
    let confirmBtn = null
    let cancelBtn = null
    const busyLeases = new Map()
    const confirmingControlStates = new Map()

    const active = () => Boolean(!settled && root?.isConnected && bodyEl.contains(root) && !overlay.classList.contains("hidden"))
    const cleanup = () => {
      previewGeneration += 1
      proposalGeneration += 1
      searchGeneration += 1
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
          syncConfirmState()
        }
      }
    }
    const syncConfirmState = () => {
      if (!confirmBtn?.isConnected) return
      confirmBtn.disabled = dirty
        || confirming
        || !currentPreview?.context_fingerprint
        || Boolean(currentPreview?.blockers?.length)
        || Boolean(pendingProposal)
        || busyLeases.has(confirmBtn)
    }
    const setStatus = (message, tone = "") => {
      const el = root?.querySelector("#ai-ref-status")
      if (!el) return
      el.textContent = message
      el.dataset.tone = tone
    }
    const markDirty = () => {
      if (confirming) return
      dirty = true
      currentPreview = null
      pendingProposal = null
      renderProposal(root, null)
      setStatus("资料选择已变化，请重新整理后再开始任务", "warning")
      syncConfirmState()
    }
    const setConfirming = (value) => {
      confirming = value
      const controls = [refreshBtn, ...(root?.querySelectorAll("button, input, select, textarea") || [])].filter(Boolean)
      if (value) {
        for (const control of controls) {
          if (!confirmingControlStates.has(control)) confirmingControlStates.set(control, control.disabled)
          control.disabled = true
        }
        setStatus("正在确认这份资料；完成前不会接受新的调整…")
      } else {
        for (const [control, wasDisabled] of confirmingControlStates) {
          if (control.isConnected) control.disabled = wasDisabled
        }
        confirmingControlStates.clear()
      }
      syncConfirmState()
    }

    const showCurrentPreview = (preview) => {
      if (!active()) return
      currentPreview = preview
      dirty = false
      pendingProposal = null
      renderProposal(root, null)
      renderSummary(root, preview, {
        onExcludeSection: async (sectionKey) => {
          excludedSectionKeys.add(sectionKey)
          await refresh()
        },
        onExcludeItem: async (itemKey) => {
          const item = findContextItem(currentPreview, itemKey)
          if (!item?.selection_ref) return
          const key = stableRefKey(item.selection_ref)
          pinnedRefs.delete(key)
          excludedRefs.set(key, item.selection_ref)
          await refresh()
        },
        onRestoreItem: async (itemKey) => {
          const item = findContextItem(currentPreview, itemKey)
          if (!item?.selection_ref) return
          const key = stableRefKey(item.selection_ref)
          excludedRefs.delete(key)
          if (item.selection_state === "omitted") pinnedRefs.set(key, item.selection_ref)
          await refresh()
        },
      }, options)
      const blocked = preview?.blockers?.length
      setStatus(blocked ? "这份资料还不能开始任务，请先处理提示" : "资料已整理，可以继续调整或开始任务", blocked ? "error" : "success")
      syncConfirmState()
    }

    const refresh = async () => {
      if (!active() || confirming) return false
      const token = ++previewGeneration
      dirty = true
      currentPreview = null
      pendingProposal = null
      renderProposal(root, null)
      syncConfirmState()
      setStatus("正在整理本次会交给 AI 的资料…")
      const releaseBusy = acquireBusy(refreshBtn, "正在整理…")
      try {
        const preview = await api.context.compile(buildPayload(options, excludedSectionKeys, pinnedRefs, excludedRefs, root))
        if (!active() || token !== previewGeneration) return false
        if (!preview?.context_fingerprint) throw new Error("未能取得可确认的 AI 参考资料")
        clearError(root)
        showCurrentPreview(preview)
      } catch (err) {
        if (active() && token === previewGeneration) {
          showError(root, err)
          setStatus("资料整理失败，当前调整仍保留", "error")
        }
      } finally {
        releaseBusy()
      }
      return false
    }

    const confirm = async () => {
      if (!active() || confirming || dirty || !currentPreview?.context_fingerprint || currentPreview.blockers?.length || pendingProposal) return false
      const reviewedFingerprint = currentPreview.context_fingerprint
      const token = ++previewGeneration
      const releaseBusy = acquireBusy(confirmBtn, "正在确认…")
      let refreshAfterConflict = false
      setConfirming(true)
      try {
        const payload = buildPayload(options, excludedSectionKeys, pinnedRefs, excludedRefs, root)
        payload.expected_context_fingerprint = reviewedFingerprint
        const confirmation = await api.context.confirm(payload)
        if (!active() || token !== previewGeneration || dirty || currentPreview?.context_fingerprint !== reviewedFingerprint) return false
        if (!globalThis.closeModal({ force: true })) return false
        settle(confirmation)
      } catch (err) {
        if (active() && token === previewGeneration) {
          showError(root, err)
          refreshAfterConflict = Number(err?.status) === 409 || String(err?.message || "").includes("已变化")
          setStatus(
            refreshAfterConflict ? "资料已变化，正在重新整理…" : "确认失败，当前资料仍保留",
            refreshAfterConflict ? "warning" : "error",
          )
        }
      } finally {
        releaseBusy()
        setConfirming(false)
      }
      if (refreshAfterConflict) await refresh()
      return false
    }

    const proposeSelection = async () => {
      if (confirming) return false
      const input = root?.querySelector("#ai-ref-selection-command")
      const instruction = String(input?.value || "").trim()
      if (!instruction) {
        showInlineError(input, "请先说明想加入或移除哪些资料")
        return false
      }
      if (dirty || !currentPreview?.context_fingerprint) {
        showError(root, new Error("请先重新整理当前资料，再让 AI 帮你调整"))
        return false
      }
      clearInlineError(input)
      const button = root.querySelector("#ai-ref-selection-submit")
      const releaseBusy = acquireBusy(button, "正在分析…")
      const token = ++proposalGeneration
      setStatus("正在请当前项目模型分析资料调整；不会自动应用…")
      try {
        const payload = buildPayload(options, excludedSectionKeys, pinnedRefs, excludedRefs, root)
        payload.instruction = instruction
        payload.current_context_fingerprint = currentPreview.context_fingerprint
        const proposal = await api.context.proposeSelection(payload)
        if (!active() || token !== proposalGeneration) return false
        pendingProposal = proposal
        renderProposal(root, proposal)
        setStatus(proposal.operations?.length ? "AI 已提出调整，请审查后应用或放弃" : "AI 没有找到可明确执行的资料调整", proposal.operations?.length ? "warning" : "")
        syncConfirmState()
      } catch (err) {
        if (active() && token === proposalGeneration) {
          showError(root, err)
          setStatus("AI 调整暂不可用，你仍可手动增减资料", "error")
        }
      } finally {
        releaseBusy()
      }
      return false
    }

    const applyProposal = async () => {
      if (confirming || !pendingProposal) return false
      for (const operation of pendingProposal.operations || []) {
        const ref = operation.selection_ref
        const key = stableRefKey(ref)
        if (!key) continue
        if (operation.operation === "include") {
          excludedRefs.delete(key)
          pinnedRefs.set(key, ref)
        } else {
          pinnedRefs.delete(key)
          excludedRefs.set(key, ref)
        }
      }
      pendingProposal = null
      renderProposal(root, null)
      await refresh()
      return false
    }
    const dismissProposal = () => {
      if (confirming) return false
      pendingProposal = null
      renderProposal(root, null)
      setStatus("已放弃 AI 提议；当前资料没有变化")
      syncConfirmState()
      return false
    }

    const searchMore = async () => {
      if (confirming) return false
      const input = root?.querySelector("#ai-ref-search-input")
      const query = String(input?.value || "").trim()
      if (!query) {
        showInlineError(input, "请输入人物、设定、场景或正文线索")
        return false
      }
      clearInlineError(input)
      const button = root.querySelector("#ai-ref-search-submit")
      const releaseBusy = acquireBusy(button, "正在搜索…")
      const token = ++searchGeneration
      try {
        const result = await api.context.searchEvidence(buildSearchPayload(options, root, query))
        if (!active() || token !== searchGeneration) return false
        renderSearchResults(root, result.hits || [])
      } catch (err) {
        if (active() && token === searchGeneration) showError(root, err)
      } finally {
        releaseBusy()
      }
      return false
    }
    const addSearchResult = async (index) => {
      if (confirming) return false
      const hit = (root?._aiReferenceSearchResults || [])[index]
      if (!hit) return false
      const ref = hit.source_ref
        ? { kind: "source_range", source_ref: hit.source_ref }
        : hit.target_ref ? { kind: "target", target_ref: hit.target_ref } : null
      const key = stableRefKey(ref)
      if (!key) return false
      excludedRefs.delete(key)
      pinnedRefs.set(key, ref)
      await refresh()
      return false
    }

    try {
      globalThis.showModalHtml("确认 AI 参考资料", renderBody(options, sessionId), [
        { text: "重新整理", class: "btn", handler: refresh },
        { text: "按这份资料开始", class: "btn btn-primary", handler: confirm },
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
      ], { protectUnsaved: false, size: "large" })
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
    const scopeSelect = root.querySelector("#ai-ref-scope")
    if (scopeSelect && Array.from(scopeSelect.options).some((item) => item.value === (options.scope || ""))) {
      scopeSelect.value = options.scope
    }
    const buttons = Array.from(footerEl.querySelectorAll("button"))
    refreshBtn = buttons.find((button) => button.textContent === "重新整理") || null
    confirmBtn = buttons.find((button) => button.textContent === "按这份资料开始") || null
    cancelBtn = buttons.find((button) => button.textContent === "取消") || null
    if (!refreshBtn || !confirmBtn || !cancelBtn) {
      settle(null, new Error("AI 参考资料确认弹窗不可用"))
      if (bodyEl.contains(root) && !overlay.classList.contains("hidden")) globalThis.closeModal({ force: true })
      return
    }
    confirmBtn.disabled = true
    root.querySelector("#ai-ref-scope")?.addEventListener("change", (event) => {
      event.currentTarget.dataset.userChanged = "1"
    })
    root.querySelectorAll("[data-ai-ref-selection-input]").forEach((control) => {
      control.addEventListener(control.tagName === "SELECT" || control.type === "checkbox" ? "change" : "input", markDirty)
    })
    root.querySelector("#ai-ref-selection-submit")?.addEventListener("click", proposeSelection)
    root.querySelector("#ai-ref-proposal")?.addEventListener("click", (event) => {
      if (event.target.closest("[data-ai-ref-apply-proposal]")) applyProposal()
      if (event.target.closest("[data-ai-ref-dismiss-proposal]")) dismissProposal()
    })
    root.querySelector("#ai-ref-search-submit")?.addEventListener("click", searchMore)
    root.querySelector("#ai-ref-search-results")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-ai-ref-add-result]")
      if (button) addSearchResult(Number(button.dataset.aiRefAddResult))
    })

    observer = new MutationObserver(() => {
      if (!active()) cancel()
    })
    observer.observe(overlay, { attributes: true, attributeFilter: ["class"] })
    observer.observe(bodyEl, { childList: true })
    loadActivationProfiles(options, root, active).finally(() => {
      if (active()) refresh()
    })
  })
}

function renderBody(options, sessionId) {
  const chapterValue = options.chapter_index || options.start_chapter || ""
  const scope = options.scope || (chapterValue ? "chapter" : "project")
  const contextMode = options.context_mode || "canonical"
  return `
    <div class="ai-ref-modal" data-ai-reference-session="${escAttr(sessionId)}">
      <p class="ai-ref-intro">任务开始前，先确认 AI 会看到哪些资料。你可以手动调整，也可以让当前项目模型提出调整建议。</p>
      <div class="ai-ref-section ai-ref-task-note"><label for="ai-ref-user-note">本次补充要求</label>
        <textarea id="ai-ref-user-note" data-ai-ref-selection-input class="form-textarea" rows="3" placeholder="例如：重点检查第 8 章后人物动机变化，不引用后续 Scene">${esc(options.user_note || "")}</textarea>
        <div class="ai-ref-help">这段要求会参与资料检索，并随本次任务一起确认。</div>
      </div>
      <details class="ai-ref-section ai-ref-advanced">
        <summary>调整范围与来源</summary>
        <div class="ai-ref-form-grid">
          <label>范围<select id="ai-ref-scope" data-ai-ref-selection-input class="form-select" ${options.lock_scope ? "disabled" : ""}>${option("project", "项目", scope)}${option("world", "世界资料", scope)}${option("world_character", "人物与世界", scope)}${option("generation_center", "生成中心", scope)}${option("arc", "篇章", scope)}${option("chapter", "章节", scope)}${option("scene", "当前 Scene", scope)}${option("full", "全部", scope)}</select></label>
          <label>${options.visible_until_chapter ? "起始章节" : "章节"}<input id="ai-ref-chapter" data-ai-ref-selection-input class="form-input" type="number" min="1" value="${escAttr(chapterValue)}" ${options.lock_chapter ? "readonly" : ""} /></label>
          ${options.visible_until_chapter ? `<label>结束章节<input class="form-input" type="number" value="${escAttr(options.visible_until_chapter)}" readonly /></label>` : ""}
          <label>内容版本<select id="ai-ref-context-mode" data-ai-ref-selection-input class="form-select">${option("canonical", contextContentModeLabel("canonical"), contextMode)}${option("working", contextContentModeLabel("working"), contextMode)}</select></label>
          <label class="ai-ref-checkbox"><input id="ai-ref-include-pending" data-ai-ref-selection-input type="checkbox" ${options.include_pending_objects ? "checked" : ""} /><span>包含待处理内容</span></label>
        </div>
        <label>已发布 AI 参考规则<select id="ai-ref-activation-profile" data-ai-ref-selection-input class="form-select"><option value="">不启用</option></select></label>
      </details>
      <div class="ai-ref-tools">
        <section class="ai-ref-section">
          <label for="ai-ref-selection-command">让 AI 帮我调整资料</label>
          <div class="ai-ref-inline-form"><input id="ai-ref-selection-command" class="form-input" maxlength="1000" placeholder="例如：加入沈岚的人物资料，去掉地图相关内容" /><button id="ai-ref-selection-submit" type="button" class="btn">提出调整</button></div>
          <div class="ai-ref-help">会调用当前项目模型，只提出增减建议；不会自动应用，也不会开始任务。</div>
          <div class="ai-ref-field-error" data-for="ai-ref-selection-command"></div><div id="ai-ref-proposal"></div>
        </section>
        <details class="ai-ref-section"><summary>手动添加更多资料</summary>
          <div class="ai-ref-inline-form"><input id="ai-ref-search-input" class="form-input" placeholder="搜索人物、设定、Scene 或正文线索" /><button id="ai-ref-search-submit" type="button" class="btn">搜索</button></div>
          <div class="ai-ref-field-error" data-for="ai-ref-search-input"></div><div id="ai-ref-search-results" class="ai-ref-search-results"></div>
        </details>
      </div>
      <div id="ai-ref-error" class="ai-ref-error" role="alert" tabindex="-1" hidden></div>
      <div id="ai-ref-status" class="ai-ref-status" role="status" aria-live="polite">正在准备资料…</div>
      <div id="ai-ref-summary" tabindex="-1">${renderContextSummary({})}</div>
    </div>`
}

function option(value, label, selected) {
  return `<option value="${escAttr(value)}" ${selected === value ? "selected" : ""}>${esc(label)}</option>`
}

function buildPayload(options, excludedSectionKeys, pinnedRefs, excludedRefs, root) {
  const fallbackScope = options.scope || (options.chapter_index || options.start_chapter ? "chapter" : "project")
  const scopeEl = root?.querySelector("#ai-ref-scope")
  const scope = scopeEl?.dataset.userChanged === "1" ? scopeEl.value : fallbackScope
  const chapterRaw = root?.querySelector("#ai-ref-chapter")?.value
  const chapter = chapterRaw ? parseInt(chapterRaw, 10) : options.chapter_index
  const contentMode = root?.querySelector("#ai-ref-context-mode")?.value || options.context_mode || options.content_mode || "canonical"
  const payload = {
    novel_id: options.novel_id,
    action: options.action,
    task: options.task,
    scope,
    reveal_mode: options.reveal_mode || "author_safe",
    context_mode: contentMode,
    content_mode: contentMode,
    include_pending_objects: Boolean(root?.querySelector("#ai-ref-include-pending")?.checked),
    user_note: root?.querySelector("#ai-ref-user-note")?.value || undefined,
    pinned_refs: Array.from(pinnedRefs.values()),
    excluded_refs: Array.from(excludedRefs.values()),
  }
  if (chapter) payload.chapter_index = chapter
  for (const key of ["visible_until_chapter", "visible_until_scene_id", "visible_until_offset", "budget_tokens", "scene_id", "arc_id", "entity_ids", "character_ids", "thread_ids", "viewpoint_character_id", "location_ids", "selected_world_bible_draft_ids"]) {
    if (options[key] != null) payload[key] = options[key]
  }
  if (options.include_world_synopsis) payload.include_world_synopsis = true
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

function buildSearchPayload(options, root, query) {
  const chapterRaw = root?.querySelector("#ai-ref-chapter")?.value
  const chapter = chapterRaw ? parseInt(chapterRaw, 10) : options.chapter_index
  const revealMode = options.reveal_mode || "author_safe"
  return {
    novel_id: options.novel_id,
    query,
    content_mode: root?.querySelector("#ai-ref-context-mode")?.value || options.content_mode || "canonical",
    visibility: {
      mode: ["reader", "character"].includes(revealMode) ? revealMode : "author",
      cutoff_chapter: options.visible_until_chapter || chapter || undefined,
      cutoff_scene_id: options.visible_until_scene_id || (revealMode === "author_safe" ? options.scene_id : undefined),
      character_id: options.viewpoint_character_id || undefined,
    },
    scopes: ["manuscript", "world", "outline"],
    include_pending_objects: Boolean(root?.querySelector("#ai-ref-include-pending")?.checked),
    top_k: 20,
    context_scene_id: options.scene_id || undefined,
  }
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

function renderSummary(root, preview, handlers, options = {}) {
  const el = root?.querySelector("#ai-ref-summary")
  if (!el) return
  const knowledgeRepairHref = options.viewpoint_character_id && options.novel_id
    ? `#workbench/${encodeURIComponent(options.novel_id)}/world/objects?knowledge_character_id=${encodeURIComponent(options.viewpoint_character_id)}`
    : ""
  el.innerHTML = renderContextSummary(preview, { knowledgeRepairHref })
  el.querySelectorAll("[data-ai-ref-exclude-section]").forEach((button) => button.addEventListener("click", () => handlers.onExcludeSection(button.dataset.aiRefExcludeSection)))
  el.querySelectorAll("[data-ai-ref-exclude-item]").forEach((button) => button.addEventListener("click", () => handlers.onExcludeItem(button.dataset.aiRefExcludeItem)))
  el.querySelectorAll("[data-ai-ref-restore-item]").forEach((button) => button.addEventListener("click", () => handlers.onRestoreItem(button.dataset.aiRefRestoreItem)))
}

function renderProposal(root, proposal) {
  const el = root?.querySelector("#ai-ref-proposal")
  if (!el) return
  if (!proposal) return el.replaceChildren()
  const operations = proposal.operations || []
  el.innerHTML = `<div class="ai-ref-proposal-card"><strong>${esc(proposal.summary || "AI 资料调整建议")}</strong>${operations.length ? `<ul>${operations.map((item) => `<li><span>${item.operation === "include" ? "加入" : "移除"}</span><strong>${esc(item.label)}</strong><small>${esc(item.reason)}</small></li>`).join("")}</ul>` : '<p class="ai-ref-muted">没有可明确执行的调整。</p>'}${(proposal.unresolved || []).length ? `<p class="ai-ref-warning-note">仍不明确：${esc(proposal.unresolved.join("；"))}</p>` : ""}<div class="ai-ref-proposal-actions">${operations.length ? '<button type="button" class="btn btn-primary" data-ai-ref-apply-proposal>应用调整</button>' : ""}<button type="button" class="btn btn-ghost" data-ai-ref-dismiss-proposal>放弃</button></div></div>`
}

function renderSearchResults(root, hits) {
  const el = root?.querySelector("#ai-ref-search-results")
  if (!el) return
  root._aiReferenceSearchResults = hits
  if (!hits.length) {
    el.innerHTML = '<div class="ai-ref-muted">没有找到可加入的资料，请换一个具体说法。</div>'
    return
  }
  el.innerHTML = hits.map((hit, index) => `<article class="ai-ref-search-card"><div><strong>${esc(hit.title || "项目资料")}</strong><p>${esc(hit.snippet || "暂无摘要")}</p></div><button type="button" class="btn btn-ghost btn-xs" data-ai-ref-add-result="${index}">加入本次资料</button></article>`).join("")
}

function findContextItem(preview, key) {
  const included = (preview?.sections || []).flatMap((section) => section.items || [])
  const excluded = preview?.selection_state?.excluded_items || []
  const omitted = preview?.selection_state?.omitted_items || []
  return [...included, ...excluded, ...omitted].find((item) => item.key === key)
}

function refMap(values = []) {
  return new Map((values || []).map((value) => [stableRefKey(value), value]).filter(([key]) => key))
}

function stableRefKey(value) {
  if (!value) return ""
  if (Array.isArray(value)) return `[${value.map(stableRefKey).join(",")}]`
  if (typeof value === "object") return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableRefKey(value[key])}`).join(",")}}`
  return JSON.stringify(value)
}

function showError(root, err) {
  const el = root?.querySelector("#ai-ref-error")
  if (!el) return
  const message = err?.message || "AI 参考资料整理失败"
  el.textContent = message.includes("请求超时") ? "AI 参考资料整理超时，请缩小范围或稍后重试。当前调整仍保留。" : message
  el.hidden = false
  el.focus({ preventScroll: true })
}

function clearError(root) {
  const el = root?.querySelector("#ai-ref-error")
  if (!el) return
  el.textContent = ""
  el.hidden = true
}

function showInlineError(input, message) {
  if (!input) return
  const el = input.closest(".ai-ref-section")?.querySelector(`[data-for="${input.id}"]`)
  if (el) el.textContent = message
  input.setAttribute("aria-invalid", "true")
  input.focus()
}

function clearInlineError(input) {
  if (!input) return
  const el = input.closest(".ai-ref-section")?.querySelector(`[data-for="${input.id}"]`)
  if (el) el.textContent = ""
  input.removeAttribute("aria-invalid")
}

function esc(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;")
}

function escAttr(value) {
  return esc(value)
}

import { confirmAiReference } from "../shared/aiReferenceModal.js"

const severityLabels = {
  high: "高",
  medium: "中",
  low: "低",
  info: "提示",
}

const statusLabels = {
  open: "未处理",
  resolved: "已处理",
  ignored: "忽略",
  later: "稍后",
}

export function showWritingConflictModal({
  check,
  novelId,
  onStatusChanged = null,
  onAiReviewComplete = null,
  onSuggestionComplete = null,
  onLocate = null,
  onOpenSource = null,
} = {}) {
  const items = Array.isArray(check?.items) ? check.items : []
  const ruleItems = items.filter((item) => !item.is_ai_judgment)
  const aiItems = items.filter((item) => item.is_ai_judgment)
  const body = `
    <div class="writing-conflict-modal" data-conflict-check-id="${esc(check?.id || "")}">
      <div class="writing-conflict-modal__meta">
        <span>检查范围：第 ${esc(check?.chapter_index || "-")} 章</span>
        <span>问题 ${items.length} 条</span>
        ${check?.include_candidates ? "<span>包含待确认对象</span>" : ""}
      </div>
      <div class="writing-conflict-list">
        ${renderConflictGroup("规则命中", ruleItems)}
        ${renderAiReviewGroup(check, aiItems)}
      </div>
    </div>
  `

  showModal("剧情设定冲突检查", body, [{ text: "关闭", class: "btn-ghost", handler: closeModal }])
  bindConflictModalEvents({
    check,
    novelId,
    onStatusChanged,
    onAiReviewComplete,
    onSuggestionComplete,
    onLocate,
    onOpenSource,
  })
}

function renderConflictGroup(title, items) {
  return `
    <section class="writing-conflict-group">
      <div class="writing-conflict-group__head">
        <strong>${esc(title)}</strong>
        <span>${items.length} 条</span>
      </div>
      ${items.length ? items.map(renderConflictItem).join("") : `
        <div class="writing-conflict-empty">暂无${esc(title)}</div>
      `}
    </section>
  `
}

function renderAiReviewGroup(check, items) {
  const status = check?.ai_review_status || "not_requested"
  const pendingCopy = check?.include_candidates
    ? '<span class="pill pill-warning">包含待确认对象，结果需复核</span>'
    : ""
  return `
    <section class="writing-conflict-group writing-conflict-group--ai">
      <div class="writing-conflict-group__head">
        <strong>AI 判断</strong>
        <span>${items.length} 条</span>
      </div>
      <div class="writing-conflict-ai-toolbar">
        <button class="btn btn-sm btn-primary" data-conflict-ai-review="${esc(check?.id || "")}">补充 AI 软冲突判断</button>
        <span class="pill">状态：${esc(aiReviewStatusLabel(status))}</span>
        ${pendingCopy}
      </div>
      ${items.length ? items.map(renderConflictItem).join("") : `
        <div class="writing-conflict-empty">暂无 AI 判断</div>
      `}
    </section>
  `
}

function renderConflictItem(item) {
  const needsReview = item.needs_review
    ? '<span class="pill pill-warning">需复核</span>'
    : ""
  const aiBadge = item.is_ai_judgment ? '<span class="pill">AI 判断</span>' : ""
  const confidence = typeof item.confidence === "number"
    ? `<span class="pill">置信度 ${esc(Math.round(item.confidence * 100))}%</span>`
    : ""
  return `
    <div class="writing-conflict-item" data-conflict-item-id="${esc(item.id)}">
      <div class="writing-conflict-item__head">
        <span class="badge badge-conflicted">${esc(severityLabels[item.severity] || item.severity || "-")}</span>
        <strong>${esc(kindLabel(item.kind))}</strong>
        <span class="pill">${esc(item.source_module || "-")}</span>
        ${aiBadge}
        ${needsReview}
        ${confidence}
        <span class="writing-conflict-status">${esc(statusLabels[item.status] || item.status || "未处理")}</span>
      </div>
      <p class="writing-conflict-evidence">${esc(item.evidence_summary || "")}</p>
      ${item.llm_rationale ? `<p class="writing-conflict-rationale">${esc(item.llm_rationale)}</p>` : ""}
      <div class="writing-conflict-actions">
        <button class="btn btn-sm" data-conflict-locate="${esc(item.id)}">定位</button>
        <button class="btn btn-sm" data-conflict-open-source="${esc(item.id)}">来源</button>
        <button class="btn btn-sm" data-conflict-status="resolved" data-conflict-item="${esc(item.id)}">已处理</button>
        <button class="btn btn-sm" data-conflict-status="ignored" data-conflict-item="${esc(item.id)}">忽略</button>
        <button class="btn btn-sm" data-conflict-status="later" data-conflict-item="${esc(item.id)}">稍后</button>
        <button class="btn btn-sm" data-conflict-ai-suggestion="${esc(item.id)}">生成 AI 修复建议</button>
      </div>
      ${renderSuggestion(item)}
    </div>
  `
}

function kindLabel(kind) {
  return {
    forbidden_present: "禁止项出现在正文",
    required_missing: "必须发生项缺失",
    map_risk: "地图/世界状态风险",
    continuity_location_mismatch: "前后连续性风险",
    motivation_gap: "动机衔接风险",
    emotion_jump: "情绪跳变",
    foreshadowing_misfire: "伏笔承接风险",
    premature_reveal: "过早揭示",
    implicit_lore_conflict: "隐含设定风险",
    voice_or_pov_drift: "声音/视角漂移",
    scene_goal_drift: "Scene 目标漂移",
    continuity_soft_risk: "软连续性风险",
  }[kind] || kind || "问题"
}

function aiReviewStatusLabel(status) {
  return {
    not_requested: "未生成",
    running: "生成中",
    done: "已生成",
    partial: "部分生成",
    failed: "失败",
  }[status] || status || "未生成"
}

function renderSuggestion(item) {
  if (item.suggestion_status === "failed") {
    return `<div class="writing-conflict-suggestion is-error">AI 修复建议失败：${esc(item.suggestion_error || "未知错误")}</div>`
  }
  if (!item.ai_suggestion) return ""
  const suggestion = parseSuggestion(item.ai_suggestion)
  return `
    <div class="writing-conflict-suggestion">
      <div class="writing-conflict-suggestion__head">
        <strong>${esc(suggestion.strategy || "AI 修复建议")}</strong>
        <button class="btn btn-sm" data-conflict-copy-suggestion="${esc(item.id)}">复制</button>
      </div>
      <p>${esc(suggestion.suggested_text || item.ai_suggestion)}</p>
      ${suggestion.rationale ? `<small>${esc(suggestion.rationale)}</small>` : ""}
      ${renderSuggestionList("约束", suggestion.constraints)}
      ${renderSuggestionList("注意", suggestion.risk_notes)}
    </div>
  `
}

function renderSuggestionList(label, values) {
  if (!Array.isArray(values) || !values.length) return ""
  return `<small>${esc(label)}：${values.map((value) => esc(value)).join("；")}</small>`
}

function parseSuggestion(value) {
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === "object" ? parsed : { suggested_text: value }
  } catch {
    return { suggested_text: value }
  }
}

function bindConflictModalEvents({
  check,
  novelId,
  onStatusChanged,
  onAiReviewComplete,
  onSuggestionComplete,
  onLocate,
  onOpenSource,
}) {
  const handler = async (event) => {
    const target = event.target
    if (!(target instanceof HTMLElement)) return

    const status = target.getAttribute("data-conflict-status")
    const statusItemId = target.getAttribute("data-conflict-item")
    if (status && statusItemId) {
      try {
        const updated = await api.writing.updateConflictItem(statusItemId, novelId, { status })
        updateConflictItemStatus(statusItemId, updated?.status || status)
        if (typeof onStatusChanged === "function") onStatusChanged(updated)
        toast("问题状态已更新", "success")
      } catch (err) {
        toast(err.message || "状态更新失败", "error")
      }
      return
    }

    const aiReviewCheckId = target.getAttribute("data-conflict-ai-review")
    if (aiReviewCheckId) {
      try {
        const confirmation = await confirmAiReference({
          novel_id: novelId,
          action: "writing.conflict_check.ai_review",
          task: "writing conflict AI review",
          scope: "chapter",
          chapter_index: check?.chapter_index,
          scene_id: check?.scene_id,
          context_mode: "canonical",
          include_pending_objects: Boolean(check?.include_candidates),
        })
        const updated = await api.writing.runConflictAiReview(aiReviewCheckId, {
          novel_id: novelId,
          context_confirmation_id: confirmation.id,
        })
        if (typeof onAiReviewComplete === "function") onAiReviewComplete(updated)
        if (updated?.ai_review_status === "failed") {
          toast(updated.ai_review_error || "AI 软冲突判断失败", "error")
        } else if (updated?.ai_review_status === "partial") {
          toast("AI 软冲突判断部分生成，部分结果需复核", "warning")
        } else {
          toast("AI 软冲突判断已生成", "success")
        }
      } catch (err) {
        toast(err.message || "AI 软冲突判断失败", "error")
      }
      return
    }

    const suggestionItemId = target.getAttribute("data-conflict-ai-suggestion")
    if (suggestionItemId) {
      try {
        const confirmation = await confirmAiReference({
          novel_id: novelId,
          action: "writing.conflict_check.ai_suggestion",
          task: "writing conflict AI suggestion",
          scope: "chapter",
          chapter_index: check?.chapter_index,
          scene_id: check?.scene_id,
          context_mode: "canonical",
          include_pending_objects: Boolean(check?.include_candidates),
        })
        const updated = await api.writing.requestConflictAiSuggestion(suggestionItemId, {
          novel_id: novelId,
          context_confirmation_id: confirmation.id,
        })
        updateConflictItemSuggestion(suggestionItemId, updated)
        if (typeof onSuggestionComplete === "function") onSuggestionComplete(updated)
        if (updated?.suggestion_status === "failed") {
          toast(updated.suggestion_error || "AI 建议生成失败", "error")
        } else {
          toast("AI 修复建议已生成", "success")
        }
      } catch (err) {
        toast(err.message || "AI 建议生成失败", "error")
      }
      return
    }

    const copyItemId = target.getAttribute("data-conflict-copy-suggestion")
    if (copyItemId) {
      const row = findConflictItemRow(copyItemId)
      const text = row?.querySelector(".writing-conflict-suggestion p")?.textContent || ""
      if (navigator.clipboard && text) await navigator.clipboard.writeText(text)
      toast("已复制 AI 修复建议", "success")
      return
    }

    const locateItemId = target.getAttribute("data-conflict-locate")
    if (locateItemId && typeof onLocate === "function") {
      onLocate(locateItemId)
      return
    }

    const sourceItemId = target.getAttribute("data-conflict-open-source")
    if (sourceItemId && typeof onOpenSource === "function") {
      onOpenSource(sourceItemId)
    }
  }
  document.removeEventListener("click", window.__writingConflictModalClick)
  window.__writingConflictModalClick = handler
  document.addEventListener("click", handler)
}

function updateConflictItemStatus(itemId, status) {
  const row = findConflictItemRow(itemId)
  const statusNode = row?.querySelector(".writing-conflict-status")
  if (statusNode) {
    statusNode.textContent = statusLabels[status] || status || "未处理"
  }
}

function updateConflictItemSuggestion(itemId, item) {
  const row = findConflictItemRow(itemId)
  if (!row) return
  row.querySelector(".writing-conflict-suggestion")?.remove()
  row.insertAdjacentHTML("beforeend", renderSuggestion(item))
}

function findConflictItemRow(itemId) {
  const rows = Array.from(document.querySelectorAll(".writing-conflict-item"))
  return rows.find((candidate) => candidate.getAttribute("data-conflict-item-id") === itemId)
}

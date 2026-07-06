/**
 * Smart Dedup 业务管理器
 *
 * 负责智能去重扫描的启动、轮询、建议展示与应用。
 * 从 app.js 下沉，便于独立测试与复用。
 */
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "./workflowProgress.js"
import { renderWorkflowCard } from "./progressRenderer.js"

const PAGE_SIZE = 6

export function createSmartDedupManager({
  api,
  router,
  toast,
  modal,
  esc,
  onRenderActions,
  getCurrentProjectId,
}) {
  const modalApi = modal || {
    showModalHtml: globalThis.showModalHtml,
    closeModal: globalThis.closeModal,
  }

  const manager = {
    _taskId: null,
    _progress: null,
    _poller: null,
    _suggestionPage: 0,
    _suggestionDraft: {},
    _currentProjectId() {
      return typeof getCurrentProjectId === "function" ? getCurrentProjectId() : null
    },

    getState() {
      return {
        taskId: this._taskId,
        progress: this._progress,
        suggestionPage: this._suggestionPage,
        suggestionDraft: { ...this._suggestionDraft },
      }
    },

    _showModalHtml(title, body, buttons = []) {
      const fn = modalApi.showModalHtml || modalApi.showHtml
      if (typeof fn === "function") fn(title, body, buttons)
    },

    _closeModal() {
      const fn = modalApi.closeModal || modalApi.close
      if (typeof fn === "function") fn()
    },

    recoverWorkflow(projectId) {
      if (!projectId) return
      const workflow = recoverActiveWorkflows(projectId)
        .find((item) => item.workflowType === "smart_dedup_scan")
      if (!workflow?.taskId) return
      this._taskId = workflow.taskId
      this._progress = normalizeTaskProgress({
        task_id: workflow.taskId,
        task_type: "smart_dedup_scan",
        status: "running",
        meta: workflow.meta || {},
      }, "smart_dedup_scan")
      this._startPolling(workflow.taskId)
    },

    async startScan() {
      const projectId = this._currentProjectId()
      if (!projectId) {
        toast("请先选择项目", "warning")
        return
      }
      if (this._progress && !this._progress.terminal) {
        this.showProgress()
        return
      }
      try {
        this._suggestionPage = 0
        this._suggestionDraft = {}
        const result = await api.projects.startSmartDedupScan(projectId, {})
        this._taskId = result.task_id
        this._progress = normalizeTaskProgress({
          ...result,
          task_type: "smart_dedup_scan",
        }, "smart_dedup_scan")
        persistActiveWorkflow({
          taskId: result.task_id,
          workflowType: "smart_dedup_scan",
          label: "智能去重扫描",
          projectId,
        })
        toast("智能去重扫描已提交", "success")
        this._startPolling(result.task_id)
        this._notifyRender()
      } catch (err) {
        toast(`智能去重启动失败：${err.message}`, "error")
      }
    },

    showProgress() {
      const progress = this._progress
      if (!progress) {
        this.startScan()
        return
      }
      if (progress.done) {
        this._showSuggestions()
        return
      }
      this._showModalHtml("智能去重", renderWorkflowCard(progress, {
        title: "智能去重扫描",
        destinationLabel: "完成后可选择合并或软废弃重复资产",
        detailLevel: "detailed",
      }), [])
    },

    handleAction(action) {
      if (action === "start-smart-dedup") {
        this.startScan()
      } else if (action === "show-smart-dedup-progress") {
        this.showProgress()
      }
    },

    renderActionButton(progressState = null) {
      const progress = progressState !== null ? progressState : this._progress
      const running = progress && !progress.terminal
      const done = progress?.done
      const label = running ? "查看智能去重" : done ? "查看去重建议" : "智能去重"
      const action = running || done ? "show-smart-dedup-progress" : "start-smart-dedup"
      return `
        <button class="btn btn-sm ${running ? "btn-primary" : ""}" data-action="${action}">
          ${esc(label)}
        </button>
      `
    },

    dispose() {
      this._stopPolling()
    },

    // ============================================================
    // 内部方法
    // ============================================================

    _notifyRender() {
      if (typeof onRenderActions === "function") onRenderActions()
    },

    _startPolling(taskId) {
      this._stopPolling()
      const capturedProjectId = this._currentProjectId()
      this._poller = pollTaskProgress({
        taskId,
        workflowType: "smart_dedup_scan",
        apiClient: api,
        onUpdate: (progress) => {
          if (this._currentProjectId() !== capturedProjectId) {
            this._stopPolling()
            this._taskId = null
            return
          }
          this._progress = progress
          this._notifyRender()
        },
        onDone: (progress) => {
          if (this._currentProjectId() !== capturedProjectId) {
            this._stopPolling()
            this._taskId = null
            return
          }
          clearActiveWorkflow(progress.taskId || taskId)
          this._taskId = null
          this._progress = progress
          toast("智能去重扫描完成", "success")
          this._notifyRender()
          this._showSuggestions()
        },
        onFailed: (progress) => {
          if (this._currentProjectId() !== capturedProjectId) {
            this._stopPolling()
            this._taskId = null
            return
          }
          clearActiveWorkflow(progress.taskId || taskId)
          this._taskId = null
          this._progress = progress
          toast(`智能去重扫描失败：${progress.errorMessage || "未知错误"}`, "error")
          this._notifyRender()
        },
      })
    },

    _stopPolling() {
      if (this._poller?.stop) this._poller.stop()
      this._poller = null
    },

    _resetResult() {
      const taskId = this._taskId
        || this._progress?.taskId
        || this._progress?.id
        || this._progress?.raw?.result?.task_id
      this._stopPolling()
      if (taskId) clearActiveWorkflow(taskId)
      this._taskId = null
      this._progress = null
      this._suggestionPage = 0
      this._suggestionDraft = {}
      this._notifyRender()
    },

    _showSuggestions(page = this._suggestionPage || 0) {
      const result = this._progress?.raw?.result || {}
      const suggestions = this._suggestions(result)
      if (!suggestions.length) {
        this._resetResult()
        this._showModalHtml("智能去重", "<p>没有发现可处理的重复资产。</p>", [{
          text: "重新扫描",
          class: "btn-primary",
          handler: async () => this.startScan(),
        }])
        return
      }
      const totalPages = Math.max(1, Math.ceil(suggestions.length / PAGE_SIZE))
      this._suggestionPage = Math.max(0, Math.min(Number(page) || 0, totalPages - 1))
      const body = this._renderSuggestionsBody(
        result,
        suggestions,
        this._suggestionPage,
      )
      this._showModalHtml("智能去重建议", body, [{
        text: "应用选中建议",
        class: "btn-primary",
        handler: async () => this._applySuggestions(suggestions),
      }])
      this._bindSuggestionControls(suggestions)
    },

    _suggestions(result) {
      if (!result || typeof result !== "object") return []
      const raw = Array.isArray(result.suggestions) ? result.suggestions : []
      return raw
        .map((item) => this._normalizeSuggestion(item))
        .filter(Boolean)
    },

    _normalizeSuggestion(item) {
      if (!item || typeof item !== "object") return null
      const sourceId = item.source_asset_id || item.source_entity_id
      const targetId = item.target_asset_id || item.target_entity_id
      if (!sourceId || !targetId || sourceId === targetId) return null
      const evidence = Array.isArray(item.evidence_anchors)
        ? item.evidence_anchors.filter((anchor) => anchor && typeof anchor === "object")
        : []
      const normalized = {
        ...item,
        asset_type: item.asset_type || "world_entity",
        action: item.action || "needs_review",
        source_asset_id: String(sourceId),
        source_title: item.source_title || item.source_entity_name || String(sourceId),
        target_asset_id: String(targetId),
        target_title: item.target_title || item.target_entity_name || String(targetId),
        recommended_primary_asset_id: item.recommended_primary_asset_id
          || item.recommended_primary_entity_id
          || item.target_asset_id
          || item.target_entity_id,
        recommended_primary_title: item.recommended_primary_title
          || item.recommended_primary_entity_name
          || item.target_title
          || item.target_entity_name,
        evidence_anchors: evidence,
        requires_canonical_confirmation: Boolean(item.requires_canonical_confirmation),
        requires_manual_confirmation: Boolean(item.requires_manual_confirmation),
        risk_level: item.risk_level || null,
      }
      if (this._isHighRiskSuggestion(normalized)) {
        normalized.requires_manual_confirmation = true
        normalized.risk_level = normalized.risk_level || "high"
      }
      return normalized
    },

    _isHighRiskSuggestion(item) {
      if (!item || typeof item !== "object") return false
      if (item.risk_level === "high" || item.requires_manual_confirmation) return true
      const method = String(item.match_method || "").toLowerCase()
      const action = String(item.action || "")
      const sourceTitle = normalizeTitle(item.source_title)
      const targetTitle = normalizeTitle(item.target_title)
      return method.includes("alias")
        && ["merge", "alias_only"].includes(action)
        && sourceTitle
        && targetTitle
        && sourceTitle !== targetTitle
    },

    _renderSuggestionsBody(result, suggestions, page = 0) {
      const totalPages = Math.max(1, Math.ceil(suggestions.length / PAGE_SIZE))
      const currentPage = Math.max(0, Math.min(Number(page) || 0, totalPages - 1))
      const start = currentPage * PAGE_SIZE
      const visible = suggestions.slice(start, start + PAGE_SIZE)
      const rows = visible
        .map((item, offset) => this._renderSuggestion(item, start + offset))
        .join("")
      return `
        <div style="margin-bottom:12px;color:var(--text-dim);font-size:13px;">
          扫描 ${esc(result.total_assets_scanned || 0)} 个资产，
          发现 ${esc(result.suggestion_count || suggestions.length)} 条建议。
          第 ${esc(currentPage + 1)} / ${esc(totalPages)} 页。
        </div>
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px;">
          <span style="font-size:12px;color:var(--text-muted);">
            本页 ${esc(start + 1)}-${esc(Math.min(start + visible.length, suggestions.length))} / ${esc(suggestions.length)}
          </span>
          <span style="display:flex;gap:6px;">
            <button type="button" class="btn btn-sm" data-smart-dedup-page="prev" ${currentPage <= 0 ? "disabled" : ""}>上一页</button>
            <button type="button" class="btn btn-sm" data-smart-dedup-page="next" ${currentPage >= totalPages - 1 ? "disabled" : ""}>下一页</button>
          </span>
        </div>
        ${rows}
      `
    },

    _bindSuggestionControls(suggestions) {
      document.querySelectorAll("[data-smart-dedup-page]").forEach((button) => {
        button.addEventListener("click", () => {
          if (button.disabled) return
          this._captureDraft()
          const delta = button.getAttribute("data-smart-dedup-page") === "next" ? 1 : -1
          this._showSuggestions(this._suggestionPage + delta)
        })
      })
      const bindings = [
        ["[data-smart-dedup-primary-mode]", "change"],
        ["[data-smart-dedup-manual-primary]", "input"],
        ["[data-smart-dedup-index], [data-smart-dedup-canonical]", "change"],
      ]
      bindings.forEach(([selector, eventName]) => {
        document.querySelectorAll(selector).forEach((input) => {
          input.addEventListener(eventName, () => this._captureDraft())
        })
      })
    },

    _renderSuggestion(item, index) {
      const actionLabel = {
        merge: "合并",
        alias_only: "登记别名",
        deprecate_duplicate: "废弃重复项",
        needs_review: "复核",
      }[item.action] || item.action || "复核"
      const assetLabel = {
        world_entity: "世界对象",
        plot_thread: "剧情线",
        outline_arc: "篇章纲",
        scene: "Scene",
        foreshadowing_plan: "伏笔",
        reveal_plan: "揭示",
      }[item.asset_type] || item.asset_type || "资产"
      const evidence = (item.evidence_anchors || [])
        .map((anchor) => anchor.snippet || anchor.reason || anchor.source_type || "")
        .filter(Boolean)
        .join(" / ")
      const draft = this._draftFor(index, item)
      const selected = draft.selected ? "checked" : ""
      const sourceTitle = item.source_title || item.source_asset_id || "左侧对象"
      const targetTitle = item.target_title || item.target_asset_id || "右侧对象"
      const recommended = this._recommendedPrimary(item)
      const primary = this._resolvePrimaryChoice(item, draft)
      const sourcePrimary = draft.primaryMode === "source" ? "checked" : ""
      const targetPrimary = draft.primaryMode === "target" ? "checked" : ""
      const manualPrimary = draft.primaryMode === "manual" ? "checked" : ""
      const operationText = {
        merge: `保留「${primary.primaryTitle}」，合并「${primary.duplicateTitle}」`,
        alias_only: `登记为别名：将「${primary.duplicateTitle}」登记到「${primary.primaryTitle}」`,
        deprecate_duplicate: `废弃「${primary.duplicateTitle}」，关联到「${primary.primaryTitle}」`,
        needs_review: "仅复核，不会直接应用",
      }[item.action] || "需要复核后处理"
      const riskNotice = this._isHighRiskSuggestion(item) ? `
        <div style="margin-top:8px;padding:8px;border:1px solid var(--warning);border-radius:var(--radius-md);color:var(--warning);font-size:12px;">
          高风险别名命中：默认不选中。确认这确实是同一对象后再手动勾选应用。
        </div>
      ` : ""
      const canonical = item.requires_canonical_confirmation ? `
        <label style="display:block;margin-top:6px;color:var(--warning);font-size:12px;">
          <input type="checkbox" data-smart-dedup-canonical="${esc(index)}" ${draft.allowCanonicalMerge ? "checked" : ""} />
          确认合并两个正史对象
        </label>
      ` : ""
      return `
        <article style="border:1px solid var(--border);border-radius:var(--radius-md);padding:10px;margin-bottom:10px;" data-smart-dedup-card="${esc(index)}">
          <label style="display:flex;gap:8px;align-items:flex-start;">
            <input type="checkbox" data-smart-dedup-index="${esc(index)}" ${selected} />
            <span>
              <strong>${esc(assetLabel)} · ${esc(actionLabel)}：</strong>
              ${esc(item.source_title || item.source_asset_id)} → ${esc(item.target_title || item.target_asset_id)}
            </span>
          </label>
          <div style="color:var(--text-dim);font-size:12px;margin-top:4px;">
            置信度 ${esc(item.confidence ?? "-")} · ${esc(item.match_method || "-")}
          </div>
          <p style="margin:6px 0 0;">${esc(item.reason || "无说明")}</p>
          <div style="margin-top:8px;padding:8px;border:1px solid var(--border-light);border-radius:var(--radius-md);background:var(--bg-alt);">
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:6px;">
              操作路径：${esc(operationText)}
            </div>
            <div style="font-size:12px;font-weight:600;margin-bottom:6px;">
              主体对象 <span style="font-weight:400;color:var(--accent);">推荐主体：${esc(recommended.title || recommended.id || "-")}</span>
            </div>
            <label style="display:block;font-size:12px;margin-bottom:4px;">
              <input type="radio" name="smart-dedup-primary-${esc(index)}" data-smart-dedup-primary-mode="${esc(index)}" value="target" ${targetPrimary} />
              保留右侧：${esc(targetTitle)} <span style="color:var(--text-dim);">(${esc(item.target_asset_id || "-")})</span>
            </label>
            <label style="display:block;font-size:12px;margin-bottom:4px;">
              <input type="radio" name="smart-dedup-primary-${esc(index)}" data-smart-dedup-primary-mode="${esc(index)}" value="source" ${sourcePrimary} />
              保留左侧：${esc(sourceTitle)} <span style="color:var(--text-dim);">(${esc(item.source_asset_id || "-")})</span>
            </label>
            <label style="display:block;font-size:12px;">
              <input type="radio" name="smart-dedup-primary-${esc(index)}" data-smart-dedup-primary-mode="${esc(index)}" value="manual" ${manualPrimary} />
              手动主体 ID
              <input class="form-input" data-smart-dedup-manual-primary="${esc(index)}" value="${esc(draft.manualPrimaryId || "")}" placeholder="输入要保留/登记到的对象 ID" style="margin-top:4px;" />
            </label>
          </div>
          ${riskNotice}
          ${canonical}
          <details style="margin-top:6px;"><summary>证据</summary><p>${esc(evidence || "无")}</p></details>
        </article>
      `
    },

    _draftFor(index, item) {
      const existing = this._suggestionDraft[index] || {}
      const recommended = this._recommendedPrimary(item)
      let primaryMode = existing.primaryMode
      let manualPrimaryId = existing.manualPrimaryId || ""
      if (!primaryMode) {
        if (recommended.id && recommended.id === item.source_asset_id) {
          primaryMode = "source"
        } else if (recommended.id && recommended.id !== item.target_asset_id) {
          primaryMode = "manual"
          manualPrimaryId = recommended.id
        } else {
          primaryMode = "target"
        }
      }
      return {
        selected: existing.selected ?? (
          item.action !== "needs_review"
          && !this._isHighRiskSuggestion(item)
        ),
        primaryMode,
        manualPrimaryId,
        allowCanonicalMerge: Boolean(existing.allowCanonicalMerge),
      }
    },

    _recommendedPrimary(item) {
      const id = item.recommended_primary_asset_id
        || item.recommended_target_asset_id
        || item.primary_asset_id
        || item.target_asset_id
      const title = item.recommended_primary_title
        || item.recommended_target_title
        || item.primary_title
        || (id === item.source_asset_id ? item.source_title : item.target_title)
      return { id, title }
    },

    _resolvePrimaryChoice(item, draft) {
      const source = {
        id: item.source_asset_id,
        title: item.source_title || item.source_asset_id,
      }
      const target = {
        id: item.target_asset_id,
        title: item.target_title || item.target_asset_id,
      }
      const [primary, duplicate] = draft.primaryMode === "source"
        ? [source, target]
        : [target, source]
      if (draft.primaryMode === "manual" && draft.manualPrimaryId) {
        primary.id = draft.manualPrimaryId
        primary.title = draft.manualPrimaryId
      }
      return {
        primaryId: primary.id,
        primaryTitle: primary.title,
        duplicateId: duplicate.id,
        duplicateTitle: duplicate.title,
      }
    },

    _captureDraft() {
      if (typeof document === "undefined") return
      document.querySelectorAll("[data-smart-dedup-index]").forEach((input) => {
        const index = Number(input.getAttribute("data-smart-dedup-index"))
        if (!Number.isFinite(index)) return
        const primary = document.querySelector(`input[name="smart-dedup-primary-${index}"]:checked`)
        const manual = document.querySelector(`[data-smart-dedup-manual-primary="${index}"]`)
        const canonical = document.querySelector(`[data-smart-dedup-canonical="${index}"]`)
        this._suggestionDraft[index] = {
          ...(this._suggestionDraft[index] || {}),
          selected: Boolean(input.checked),
          primaryMode: primary?.value || this._suggestionDraft[index]?.primaryMode,
          manualPrimaryId: manual?.value?.trim() || "",
          allowCanonicalMerge: Boolean(canonical?.checked),
        }
      })
    },

    _buildApplyItem(item, draft) {
      const primary = this._resolvePrimaryChoice(item, draft)
      if (!primary.primaryId || !primary.duplicateId) return null
      return {
        asset_type: item.asset_type,
        action: item.action,
        source_asset_id: primary.duplicateId,
        target_asset_id: primary.primaryId,
        alias: item.alias || primary.duplicateTitle,
        allow_canonical_merge: Boolean(draft.allowCanonicalMerge),
      }
    },

    async _applySuggestions(suggestions) {
      this._captureDraft()
      const selected = suggestions
        .map((item, index) => ({
          index,
          item,
          draft: this._draftFor(index, item),
        }))
        .filter((entry) => entry.item)
        .filter((entry) => entry.draft.selected)
        .filter((entry) => ["merge", "alias_only", "deprecate_duplicate"].includes(entry.item.action))
      if (!selected.length) {
        toast("请选择可应用的建议", "warning")
        return
      }
      const payload = selected
        .map(({ item, draft }) => this._buildApplyItem(item, draft))
        .filter(Boolean)
      try {
        const applied = await api.projects.applySmartDedup(this._currentProjectId(), {
          confirmed: true,
          suggestions: payload,
        })
        this._closeModal()
        toast(`已应用 ${applied.applied || 0} 条智能去重建议`, "success")
        this._resetResult()
        api.clearCache()
        router.refresh()
      } catch (err) {
        toast(err.message || "应用失败", "error")
      }
    },
  }

  return manager
}

function normalizeTitle(value) {
  return String(value || "").trim().toLowerCase()
}
